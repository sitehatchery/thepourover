"""Subscribers table, profile lookup and the full profile used by the subscriber activity view."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.deps import require_auth
from app.config import get_settings
from app.db import get_session
from app.models import AppEvent, Segment, WebEvent
from app.queries.export_notes import export_notes
from app.queries.listing import ListParams, apply_sort, csv_response, iso, list_params, paginate
from app.queries.people_rows import PEOPLE_COLUMNS, STATUS_LABELS, person_row, sort_columns
from app.queries.profiles import resolve_profile
from app.rules import normalize_search
from app.segments.engine import condition
from app.segments.people import build_people
from app.segments.service import definition_of, segments_condition

router = APIRouter(prefix="/app", tags=["subscribers"], dependencies=[Depends(require_auth)])

STATUS_FILTER = {label: value for value, label in STATUS_LABELS.items()}


@router.get("/subscribers")
def list_subscribers(
    params: ListParams = Depends(list_params),
    email: str | None = Query(None, max_length=64, description="Part of an email address"),
    app_user_id: str | None = Query(None, max_length=32),
    status: str | None = Query(None, pattern="^(active|unsubscribed)$"),
    acquisition_source: str | None = Query(None, max_length=24),
    signup_from: date | None = None,
    signup_to: date | None = None,
    today: bool = Query(False, description="Only people who signed up on the configured today"),
    segment_id: list[str] = Query(default=[], max_length=10, description="Segment id or slug; repeat to require several"),
    session: Session = Depends(get_session),
):
    """Subscribers with their app account and web activity summary. Sortable by any column."""
    people = build_people()
    stmt = select(people).where(people.c.is_subscriber == 1)
    if term := normalize_search(email):
        stmt = stmt.where(people.c.email.contains(term, autoescape=True))
    if app_user_id:
        stmt = stmt.where(people.c.app_user_id == app_user_id.strip())
    if status:
        stmt = stmt.where(people.c.status == STATUS_FILTER[status])
    if acquisition_source:
        stmt = stmt.where(people.c.acquisition_source == acquisition_source.strip())
    if today:
        signup_from = signup_to = get_settings().today
    if signup_from:
        stmt = stmt.where(people.c.signup_date >= signup_from)
    if signup_to:
        stmt = stmt.where(people.c.signup_date <= signup_to)
    if segment_id:
        stmt = stmt.where(segments_condition(session, segment_id, people))

    stmt = apply_sort(stmt, params, sort_columns(people), default="signup_date", tiebreak=people.c.profile_id)
    if params.format == "csv":
        return csv_response(stmt, PEOPLE_COLUMNS, person_row, "subscribers", export_notes(params.request, session, "Subscribers"))
    return paginate(session, stmt, params, person_row)


@router.get("/profiles/search")
def search_profiles(q: str = Query(min_length=2, max_length=64), session: Session = Depends(get_session)) -> list[dict]:
    """Find people by part of an email, an app user id or a visitor id. Returns up to 10 matches."""
    term = q.strip()
    people = build_people()
    visitor_subscribers = select(WebEvent.subscriber_id).where(WebEvent.visitor_id == term, WebEvent.subscriber_id.is_not(None))
    stmt = (
        select(people)
        .where(
            or_(
                people.c.email.contains(normalize_search(term), autoescape=True),
                people.c.app_user_id == term,
                people.c.profile_id == term,
                people.c.subscriber_id.in_(visitor_subscribers),
            )
        )
        .order_by(people.c.email)
        .limit(10)
    )
    return [person_row(r) for r in session.execute(stmt)]


@router.get("/profiles/{profile_id}")
def read_profile(profile_id: str, session: Session = Depends(get_session)) -> dict:
    """Everything known about one person: newsletter info, app accounts, identifiers, summary and segments."""
    ref = resolve_profile(session, profile_id)
    people = build_people()
    person = session.execute(select(people).where(people.c.profile_id == ref.profile_id)).one()

    devices = (
        sorted(session.scalars(select(AppEvent.device_id).where(AppEvent.app_user_id.in_(ref.app_user_ids)).distinct()))
        if ref.app_user_ids
        else []
    )
    web_condition = (
        WebEvent.subscriber_id == ref.subscriber.subscriber_id
        if ref.subscriber
        else WebEvent.email.in_(ref.emails) if ref.emails else None
    )
    visitors = sorted(session.scalars(select(WebEvent.visitor_id).where(web_condition).distinct())) if web_condition is not None else []

    in_segments = []
    for segment in session.scalars(select(Segment).order_by(Segment.name)):
        is_member = select(people.c.profile_id).where(people.c.profile_id == ref.profile_id, condition(definition_of(segment), people))
        if session.scalar(is_member) is not None:
            in_segments.append({"segment_id": segment.segment_id, "slug": segment.slug, "name": segment.name})

    return {
        **person_row(person),
        "newsletter": {
            "email": ref.subscriber.email,
            "status": STATUS_LABELS.get(ref.subscriber.status),
            "signup_date": iso(ref.subscriber.signup_date),
            "acquisition_source": person._mapping["acquisition_source"],
            "last_open_date": iso(ref.subscriber.last_open_date),
        }
        if ref.subscriber
        else None,
        "app_accounts": [
            {"app_user_id": u.app_user_id, "created_at": iso(u.created_at), "is_placeholder": u.is_placeholder}
            for u in ref.app_users
        ],
        "device_ids": devices,
        "visitor_ids": visitors,
        "web_active_days": person._mapping["web_active_days"],
        "last_web_visit": iso(person._mapping["last_web_visit"]),
        "last_app_activity": iso(person._mapping["last_app_activity"]),
        "segments": in_segments,
    }
