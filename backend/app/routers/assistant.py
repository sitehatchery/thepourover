from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.agent import ChatModel, OpenAIChatModel, PIIBlocked, ask
from app.assistant.tools import create_segment, results
from app.auth.deps import require_auth
from app.config import get_settings
from app.db import get_session
from app.queries.listing import ListParams, csv_response, list_params, paginate
from app.queries.people_rows import PEOPLE_COLUMNS, person_row
from app.segments.engine import condition
from app.segments.people import build_people

router = APIRouter(prefix="/app/assistant", tags=["assistant"], dependencies=[Depends(require_auth)])


def get_model() -> ChatModel:
    """The language model. Tests override this dependency with a scripted fake."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="The assistant isn't configured: set OPENAI_API_KEY in backend/.env")
    return OpenAIChatModel(settings.openai_api_key, settings.openai_model)


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=40)


@router.get("/status")
def assistant_status() -> dict:
    settings = get_settings()
    return {"configured": bool(settings.openai_api_key), "model": settings.openai_model}


@router.post("/ask")
async def ask_assistant(body: AskIn, session: Session = Depends(get_session), model: ChatModel = Depends(get_model)) -> dict:
    """Answer a question. The response includes `audit`: every payload sent to the model, for inspection."""
    try:
        reply = await run_in_threadpool(ask, session, model, body.question, [t.model_dump() for t in body.history], get_settings())
    except PIIBlocked as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # model/network failures shouldn't look like a server crash to the user
        if exc.__class__.__module__.startswith("openai"):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"The AI service didn't respond: {exc.__class__.__name__}") from exc
        raise
    return {
        "answer": reply.answer,
        "attachments": reply.attachments,
        "audit": reply.audit,
        "redacted_question": reply.redacted_question,
    }


class SaveIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


@router.post("/results/{result_id}/segment", status_code=status.HTTP_201_CREATED)
def save_result_as_segment(result_id: str, body: SaveIn, session: Session = Depends(get_session)) -> dict:
    """Save the rules behind an assistant list as a reusable segment."""
    stored = results.get(result_id)
    if stored is None:
        raise HTTPException(404, detail="This list has expired; ask the assistant again")
    return create_segment(session, body.name, stored["definition"].model_dump(exclude_none=True), "Created from the assistant")


@router.get("/results/{result_id}")
def result_rows(result_id: str, params: ListParams = Depends(list_params), session: Session = Depends(get_session)):
    """The people behind a list the assistant produced. Fetched by the browser; never sent to the model."""
    stored = results.get(result_id)
    if stored is None:
        raise HTTPException(404, detail="This list has expired; ask the assistant again")
    people = build_people()
    stmt = select(people).where(condition(stored["definition"], people))
    rank = stored["rank_by"]
    stmt = stmt.order_by(people.c[rank].desc().nulls_last() if rank else people.c.profile_id, people.c.profile_id)
    if params.format == "csv":
        return csv_response(stmt, PEOPLE_COLUMNS, person_row, "assistant_list")
    return {**paginate(session, stmt, params, person_row), "title": stored["title"], "rank_by": rank}
