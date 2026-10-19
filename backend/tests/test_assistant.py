import json

import pytest
from sqlalchemy import select

from app.assistant import tools
from app.assistant.agent import ModelReply, ToolCall, ask
from app.assistant.pii import PIIBlocked, assert_no_pii, find_pii, redact
from app.importer.service import run_import
from app.importer.sources import LocalFolderSource
from app.main import app
from app.models import AppUser, Subscriber, WebEvent
from app.routers.assistant import get_model


class ScriptedModel:
    """Plays back a fixed list of replies and records every request it receives."""

    def __init__(self, replies: list[ModelReply]):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def complete(self, messages, tool_specs):
        self.requests.append(json.loads(json.dumps({"messages": messages, "tools": tool_specs}, default=str)))
        return self.replies.pop(0)


def call(name: str, arguments: dict, call_id: str = "c1") -> ModelReply:
    return ModelReply(None, [ToolCall(call_id, name, json.dumps(arguments))])


def answer(text: str) -> ModelReply:
    return ModelReply(text)


@pytest.fixture
def imported(session, settings):
    run_import(session, LocalFolderSource(settings.import_source_dir), settings)


@pytest.fixture
def every_identifier(session, imported) -> set[str]:
    """Every email and person id in the database: none of these may ever reach the model."""
    values = set(session.scalars(select(Subscriber.email)))
    values |= {v for v in session.scalars(select(AppUser.email)) if v}
    values |= set(session.scalars(select(AppUser.app_user_id)))
    values |= set(session.scalars(select(WebEvent.visitor_id).distinct()))
    return values


def assert_never_sent(model: ScriptedModel, forbidden: set[str]):
    sent = json.dumps(model.requests)
    leaked = [v for v in forbidden if v in sent]
    assert not leaked, f"{len(leaked)} identifiers reached the model, e.g. {leaked[:3]}"
    assert not find_pii(model.requests)


# ---- the guard ------------------------------------------------------------------------------------------


def test_redact_removes_emails_and_ids():
    text, changed = redact("Is Julia.Evans230@gmail.com (u_2b6447a3, visitor v_098d80a408, s_370) engaged?")
    assert changed
    assert "@" not in text and "u_2b6447a3" not in text and "v_098d80a408" not in text and "s_370" not in text


def test_guard_blocks_payloads_with_pii():
    with pytest.raises(PIIBlocked):
        assert_no_pii({"messages": [{"role": "tool", "content": "ana@example.com"}]}, "test")
    with pytest.raises(PIIBlocked):
        assert_no_pii("device d_4b21e8", "test")
    assert_no_pii({"field": "app_event_type", "values": ["read_story", "app_open"], "page": "/news/ai-regulation-bill"}, "test")


def test_every_tool_result_is_free_of_pii(session, imported):
    outputs = [
        tools.get_schema(session),
        tools.count_people(session, segment="engaged_readers"),
        tools.list_people(session, segment="engaged_readers", rank_by="web_active_days"),
        *(tools.run_report(session, name) for name in tools.REPORTS),
    ]
    for output in outputs:
        assert find_pii(output) == [], output
    for name in tools.REPORTS:
        assert tools.run_report(session, name)["definition"], f"{name} needs a definition the model can quote"


# ---- conversations --------------------------------------------------------------------------------------


def test_brief_question_instagram_signups_went_cold(session, settings, imported, every_identifier):
    definition = {
        "match": "all",
        "filters": [
            {"field": "acquisition_source", "operator": "equals", "value": "Instagram"},
            {"field": "signup_date", "operator": "after", "value": "2026-07-31"},
            {"field": "signup_date", "operator": "before", "value": "2026-09-01"},
            {"field": "status", "operator": "equals", "value": "active"},
            {"field": "last_open_date", "operator": "not_within_last_days", "value": 30},
        ],
    }
    model = ScriptedModel([call("count_people", {"definition": definition}), answer("42 went cold.")])

    reply = ask(session, model, "How many Instagram signups went cold last month?", [], settings)

    expected = tools.count_people(session, definition)["count"]
    assert reply.attachments[0]["type"] == "count" and reply.attachments[0]["count"] == expected
    assert "2026-08-01 to 2026-08-31" in model.requests[0]["messages"][0]["content"]  # "last month" is defined
    assert_never_sent(model, every_identifier)


def test_list_people_gives_the_model_a_handle_and_the_browser_the_rows(client, auth, session, settings, imported, every_identifier):
    model = ScriptedModel(
        [call("list_people", {"segment": "engaged_readers", "rank_by": "web_active_days"}), answer("Here are your most engaged readers.")]
    )
    reply = ask(session, model, "Build me a list of our most engaged readers", [], settings)

    people = reply.attachments[0]
    expected = tools.count_people(session, segment="engaged_readers")["count"]
    assert people["type"] == "people" and people["count"] == expected
    assert "result_id" in people and "@" not in json.dumps(people)
    assert_never_sent(model, every_identifier)

    rows = client.get(f"/app/assistant/results/{people['result_id']}?page_size=5", headers=auth).json()
    assert rows["total"] == expected and rows["rank_by"] == "web_active_days"
    assert "@" in rows["items"][0]["email"]  # the browser, behind login, does get the people

    saved = client.post(f"/app/assistant/results/{people['result_id']}/segment", json={"name": "AI engaged list"}, headers=auth)
    assert saved.status_code == 201 and saved.json()["count"] == expected


def test_which_pages_new_subscribers_hit_first(session, settings, imported, every_identifier):
    model = ScriptedModel([call("run_report", {"report": "first_pages_new_subscribers", "params": {"signed_up_within_days": 30}}), answer("Mostly /subscribe.")])
    reply = ask(session, model, "Which pages do new subscribers hit first?", [], settings)

    table = reply.attachments[0]
    assert table["type"] == "table" and table["columns"] == ["page", "subscribers", "percent"]
    assert sum(row[1] for row in table["rows"]) <= table["total"]
    assert_never_sent(model, every_identifier)


def test_emails_in_the_question_never_reach_the_model(session, settings, imported, every_identifier):
    model = ScriptedModel([answer("I can't look up individuals, but I can count groups.")])
    reply = ask(session, model, "What has julia.evans230@gmail.com done in the app?", [{"role": "user", "content": "earlier: u_2b6447a3"}], settings)

    assert reply.redacted_question
    assert_never_sent(model, every_identifier)
    assert reply.audit[0]["step"] == "redacted"


def test_tool_errors_go_back_to_the_model(session, settings, imported):
    model = ScriptedModel(
        [
            call("count_people", {"definition": {"filters": [{"field": "email", "operator": "equals", "value": "x"}]}}),
            call("count_people", {"segment": "unsubscribed"}, "c2"),
            answer("290 people unsubscribed."),
        ]
    )
    reply = ask(session, model, "How many unsubscribed?", [], settings)

    first_tool_result = json.loads(model.requests[1]["messages"][-1]["content"])
    assert "Invalid segment definition" in first_tool_result["error"]
    assert reply.attachments[-1]["count"] == 290


def test_a_tool_result_containing_pii_is_withheld(session, settings, imported, monkeypatch):
    monkeypatch.setattr("app.assistant.agent.call_tool", lambda *_: {"leak": "ana@example.com"})
    model = ScriptedModel([call("get_schema", {}), answer("ok")])
    ask(session, model, "anything", [], settings)

    assert "withheld" in model.requests[1]["messages"][-1]["content"]
    assert not find_pii(model.requests)


def test_the_models_own_output_is_checked_too(session, settings, imported):
    from app.models import Segment

    definition = {"filters": [{"field": "acquisition_source", "operator": "equals", "value": "Podcast"}]}
    model = ScriptedModel(
        [
            call("create_segment", {"name": "Follow up with ana@example.com", "definition": definition}),
            answer("Done. Email ana@example.com or check u_2b6447a3."),
        ]
    )
    reply = ask(session, model, "Save podcast signups", [], settings)

    tool_result = json.loads(model.requests[1]["messages"][-1]["content"])
    assert "Arguments rejected" in tool_result["error"]  # nothing was run with those arguments
    assert session.scalar(select(Segment).where(Segment.name.like("Follow up%"))) is None
    assert not find_pii(reply.answer) and "ana@example.com" not in reply.answer
    assert any(step["step"] == "redacted" for step in reply.audit)


def test_create_segment_tool_saves_a_segment(session, settings, imported):
    definition = {"filters": [{"field": "acquisition_source", "operator": "equals", "value": "Podcast"}]}
    model = ScriptedModel([call("create_segment", {"name": "Podcast people", "definition": definition}), answer("Saved.")])
    reply = ask(session, model, "Save podcast signups as a segment", [], settings)

    assert reply.attachments[0] == {"type": "segment", "slug": "podcast_people", "name": "Podcast people", "count": 226, "rules": "Acquisition source is Podcast"}


# ---- API ------------------------------------------------------------------------------------------------


def test_ask_endpoint_returns_answer_attachments_and_audit(client, auth, imported):
    model = ScriptedModel([call("run_report", {"report": "signups_by_source"}), answer("Instagram leads.")])
    app.dependency_overrides[get_model] = lambda: model
    try:
        body = client.post("/app/assistant/ask", json={"question": "Signups by source?"}, headers=auth).json()
    finally:
        app.dependency_overrides.clear()

    assert body["answer"] == "Instagram leads."
    assert body["attachments"][0]["total"] == 2900
    assert [step["step"] for step in body["audit"]] == ["sent_to_model", "tool", "sent_to_model", "answer"]


def test_ask_without_a_key_explains_how_to_configure(client, auth, monkeypatch):
    monkeypatch.setenv("CDP_OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    assert client.get("/app/assistant/status", headers=auth).json()["configured"] is False
    response = client.post("/app/assistant/ask", json={"question": "hi"}, headers=auth)
    assert response.status_code == 503 and "OPENAI_API_KEY" in response.json()["detail"]


def test_assistant_requires_auth(client):
    assert client.post("/app/assistant/ask", json={"question": "hi"}).status_code == 401
    assert client.get("/app/assistant/results/rabc").status_code == 401
