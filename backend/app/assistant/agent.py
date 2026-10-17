"""The assistant's conversation loop: the model picks tools, the server runs them, and every payload is
checked for personal data before it leaves the server. Each step is recorded so the UI can show exactly
what the model was sent."""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.assistant.pii import PIIBlocked, assert_no_pii, find_pii, redact
from app.assistant.tools import TOOL_SPECS, ToolError, call_tool
from app.config import Settings

MAX_HISTORY = 12


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, as the model produced it


@dataclass
class ModelReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply: ...


class OpenAIChatModel:
    """OpenAI Chat Completions with tool calling."""

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        response = self._client.chat.completions.create(model=self.model, messages=messages, tools=tools)
        message = response.choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}") for c in (message.tool_calls or [])]
        return ModelReply(message.content, calls)


@dataclass
class AssistantReply:
    answer: str
    attachments: list[dict]
    audit: list[dict]
    redacted_question: bool


def system_prompt(settings: Settings) -> str:
    today = settings.today
    last_month_end = today.replace(day=1) - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    return f"""You are the data assistant for The Pour Over's Growth team, inside their customer data platform.
You answer plain-English questions about newsletter subscribers, website visits and app activity.

Today is {today.isoformat()}. "Last month" means {last_month_start.isoformat()} to {last_month_end.isoformat()}.

How to work:
- Use the tools for every number. Never guess or invent figures.
- Call get_schema when you need field names, operators or allowed values (sources are case-sensitive, e.g. "Instagram").
- For "how many" questions use count_people (or run_report for breakdowns).
- For "build me a list" / "who are" questions use list_people; the user sees the table, you only get a count.
- Only call create_segment when the user asks to save or create a segment.
- Definitions: "went cold" = active subscriber with no newsletter open in the last 30 days (including never opened),
  who signed up more than 30 days ago unless the question limits signup dates. "Engaged" / "most engaged" = the saved
  segment engaged_readers, ranked by web_active_days unless the user says otherwise. "Signups from X last month" =
  acquisition_source X with signup_date in last month.

Privacy:
- You never see personal data and must not ask for it. If the user mentions an email or id it has been removed.
- Never describe or speculate about individual people.

Answer in two or three short sentences with the key numbers. Say which definition you used when it matters."""


def _clean_history(history: list[dict]) -> list[dict]:
    cleaned = []
    for item in history[-MAX_HISTORY:]:
        if item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
            text, _ = redact(item["content"][:2000])
            cleaned.append({"role": item["role"], "content": text})
    return cleaned


def _attachment(name: str, result: dict) -> dict | None:
    if "error" in result:
        return None
    if name == "list_people":
        return {"type": "people", "result_id": result["result_id"], "count": result["count"], "title": result["rules"]}
    if name == "run_report":
        return {"type": "table", **{k: result[k] for k in ("title", "columns", "rows", "total")}}
    if name == "create_segment":
        return {"type": "segment", **result}
    if name == "count_people":
        return {"type": "count", **result}
    return None


def ask(session: Session, model: ChatModel, question: str, history: list[dict], settings: Settings) -> AssistantReply:
    clean_question, was_redacted = redact(question.strip()[:2000])
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(settings)},
        *_clean_history(history),
        {"role": "user", "content": clean_question},
    ]
    tools = [{"type": "function", "function": spec} for spec in TOOL_SPECS]
    audit: list[dict] = []
    attachments: list[dict] = []
    if was_redacted:
        audit.append({"step": "redacted", "detail": "Emails or ids in the question were removed before anything was sent."})

    for _round in range(settings.assistant_max_tool_rounds):
        # The guard: nothing leaves the server if it looks like personal data.
        assert_no_pii({"messages": messages, "tools": tools}, "the request to the model")
        audit.append({"step": "sent_to_model", "messages": json.loads(json.dumps(messages, default=str))})

        reply = model.complete(messages, tools)
        if not reply.tool_calls:
            answer = reply.content or "I couldn't find an answer to that."
            audit.append({"step": "answer", "content": answer})
            return AssistantReply(answer, attachments, audit, was_redacted)

        messages.append(
            {
                "role": "assistant",
                "content": reply.content,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in reply.tool_calls
                ],
            }
        )
        for call in reply.tool_calls:
            result = _run_tool(session, call)
            audit.append({"step": "tool", "name": call.name, "arguments": call.arguments, "result": result})
            if (attachment := _attachment(call.name, result)) is not None:
                attachments.append(attachment)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})

    answer = "That needed more steps than I'm allowed. Try asking a narrower question."
    audit.append({"step": "answer", "content": answer})
    return AssistantReply(answer, attachments, audit, was_redacted)


def _run_tool(session: Session, call: ToolCall) -> dict:
    try:
        arguments = json.loads(call.arguments or "{}")
        if not isinstance(arguments, dict):
            raise ToolError("Arguments must be a JSON object")
        result = call_tool(session, call.name, arguments)
    except (ToolError, ValueError, TypeError) as exc:
        session.rollback()
        return {"error": str(exc)}
    # Defence in depth: a tool result that somehow contains personal data is withheld from the model.
    if find_pii(result):
        return {"error": "Result withheld: it would have exposed personal data."}
    return result


__all__ = ["AssistantReply", "ChatModel", "ModelReply", "OpenAIChatModel", "PIIBlocked", "ToolCall", "ask"]
