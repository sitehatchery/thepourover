from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import require_auth
from app.db import get_session
from app.models import SEGMENT_GROUP_APP_USERS, SEGMENT_GROUP_SUBSCRIBER, SEGMENT_GROUP_WEB_EVENTS, Segment
from app.queries.export_notes import export_notes
from app.queries.listing import ListParams, apply_sort, csv_response, iso, list_params, paginate
from app.queries.people_rows import PEOPLE_COLUMNS, person_row, sort_columns
from app.segments.engine import SegmentDefinition, describe, schema
from app.segments.service import definition_of, get_segment, members, unique_slug

router = APIRouter(prefix="/app/segments", tags=["segments"], dependencies=[Depends(require_auth)])

GROUPS = {"subscriber": SEGMENT_GROUP_SUBSCRIBER, "app_users": SEGMENT_GROUP_APP_USERS, "web_events": SEGMENT_GROUP_WEB_EVENTS}
GROUP_NAMES = {v: k for k, v in GROUPS.items()}


class SegmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    group: str = Field(default="subscriber", pattern="^(subscriber|app_users|web_events)$")
    definition: SegmentDefinition


def _count(session: Session, definition: SegmentDefinition) -> int:
    _people, stmt = members(definition)
    return session.scalar(select(func.count()).select_from(stmt.subquery()))


def _out(session: Session, segment: Segment, with_count: bool = True) -> dict:
    definition = definition_of(segment)
    return {
        "segment_id": segment.segment_id,
        "slug": segment.slug,
        "name": segment.name,
        "group": GROUP_NAMES.get(segment.group, "subscriber"),
        "description": segment.description,
        "summary": describe(definition),
        "definition": definition.model_dump(exclude_none=True),
        "member_count": _count(session, definition) if with_count else None,
        "created_at": iso(segment.created_at),
        "updated_at": iso(segment.updated_at),
    }


@router.get("")
def list_segments(with_counts: bool = True, session: Session = Depends(get_session)) -> list[dict]:
    """Saved segments, grouped by group then name, with live member counts."""
    segments = session.scalars(select(Segment).order_by(Segment.group, Segment.name))
    return [_out(session, s, with_counts) for s in segments]


@router.get("/schema")
def get_schema(session: Session = Depends(get_session)) -> dict:
    """Fields, operators and allowed values for segment definitions (used by the builder and the AI)."""
    return schema(session)


@router.post("/preview")
def preview(definition: SegmentDefinition, session: Session = Depends(get_session)) -> dict:
    """Count and describe an unsaved definition."""
    return {"member_count": _count(session, definition), "summary": describe(definition)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_segment(body: SegmentIn, session: Session = Depends(get_session)) -> dict:
    segment = Segment(
        slug=unique_slug(session, body.name),
        name=body.name.strip(),
        description=body.description.strip(),
        group=GROUPS[body.group],
        definition=body.definition.model_dump(exclude_none=True),
    )
    session.add(segment)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, detail="A segment with that name already exists") from exc
    return _out(session, segment)


@router.get("/{id_or_slug}")
def read_segment(id_or_slug: str, session: Session = Depends(get_session)) -> dict:
    return _out(session, get_segment(session, id_or_slug))


@router.put("/{id_or_slug}")
def update_segment(id_or_slug: str, body: SegmentIn, session: Session = Depends(get_session)) -> dict:
    segment = get_segment(session, id_or_slug)
    segment.name = body.name.strip()
    segment.slug = unique_slug(session, body.name, segment.segment_id)
    segment.description = body.description.strip()
    segment.group = GROUPS[body.group]
    segment.definition = body.definition.model_dump(exclude_none=True)
    session.commit()
    return _out(session, segment)


@router.delete("/{id_or_slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_segment(id_or_slug: str, session: Session = Depends(get_session)) -> None:
    session.delete(get_segment(session, id_or_slug))
    session.commit()


@router.get("/{id_or_slug}/count")
def count_members(id_or_slug: str, session: Session = Depends(get_session)) -> dict:
    return {"member_count": _count(session, definition_of(get_segment(session, id_or_slug)))}


@router.get("/{id_or_slug}/members")
def list_members(id_or_slug: str, params: ListParams = Depends(list_params), session: Session = Depends(get_session)):
    """The people in the segment, with the same columns as the Subscribers table. `format=csv` exports all."""
    segment = get_segment(session, id_or_slug)
    people, stmt = members(definition_of(segment))
    stmt = apply_sort(stmt, params, sort_columns(people), default="last_seen", tiebreak=people.c.profile_id)
    if params.format == "csv":
        notes = export_notes(params.request, session, f"Segment {segment.name}", [f"Rules: {describe(definition_of(segment))}"])
        return csv_response(stmt, PEOPLE_COLUMNS, person_row, f"segment_{segment.slug}", notes)
    return paginate(session, stmt, params, person_row)
