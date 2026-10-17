"""Loading segments and turning them into filters for the people, app event and web event queries."""

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement, Subquery

from app.models import AppEvent, AppUser, Segment, WebEvent
from app.segments.engine import SegmentDefinition, condition
from app.segments.people import build_people


def get_segment(session: Session, id_or_slug: str) -> Segment:
    segment = (
        session.get(Segment, int(id_or_slug))
        if id_or_slug.isdigit()
        else session.scalar(select(Segment).where(Segment.slug == id_or_slug))
    )
    if segment is None:
        raise HTTPException(404, detail=f"Segment '{id_or_slug}' not found")
    return segment


def definition_of(segment: Segment) -> SegmentDefinition:
    try:
        return SegmentDefinition.model_validate(segment.definition)
    except ValidationError as exc:  # a stored definition that no longer fits the schema
        raise HTTPException(500, detail=f"Segment '{segment.slug}' has an invalid definition") from exc


def segments_condition(session: Session, segment_ids: list[str], people: Subquery) -> ColumnElement[bool]:
    """People in every one of the given segments."""
    return and_(*(condition(definition_of(get_segment(session, s)), people) for s in segment_ids))


def members(definition: SegmentDefinition) -> tuple[Subquery, Select]:
    people = build_people()
    return people, select(people).where(condition(definition, people))


def member_keys(session: Session, segment_ids: list[str]) -> Subquery:
    """subscriber_id / app_user_id / email of the people in all the given segments."""
    people = build_people()
    return (
        select(people.c.subscriber_id, people.c.app_user_id, people.c.email)
        .where(segments_condition(session, segment_ids, people))
        .subquery()
    )


def app_events_in_segments(session: Session, segment_ids: list[str]) -> ColumnElement[bool]:
    keys = member_keys(session, segment_ids)
    return or_(
        AppEvent.app_user_id.in_(
            select(AppUser.app_user_id).where(AppUser.subscriber_id.in_(select(keys.c.subscriber_id).where(keys.c.subscriber_id.is_not(None))))
        ),
        AppEvent.app_user_id.in_(select(keys.c.app_user_id).where(keys.c.subscriber_id.is_(None))),
    )


def web_events_in_segments(session: Session, segment_ids: list[str]) -> ColumnElement[bool]:
    keys = member_keys(session, segment_ids)
    return or_(
        WebEvent.subscriber_id.in_(select(keys.c.subscriber_id).where(keys.c.subscriber_id.is_not(None))),
        and_(
            WebEvent.subscriber_id.is_(None),
            WebEvent.email.in_(select(keys.c.email).where(keys.c.subscriber_id.is_(None), keys.c.email.is_not(None))),
        ),
    )
