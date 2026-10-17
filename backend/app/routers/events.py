"""Read APIs for app events and web events: whole-table lists (with filters, sorting, paging and CSV)
and per-profile lists for the subscriber activity view."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, false, func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_auth
from app.db import get_session
from app.models import AppEvent, AppUser, Subscriber, WebEvent
from app.queries.listing import ListParams, apply_sort, csv_response, date_range_filter, iso, join_pipe, list_params, paginate
from app.queries.profiles import profile_id_for, resolve_profile
from app.rules import normalize_search

router = APIRouter(prefix="/app", tags=["events"], dependencies=[Depends(require_auth)])

EventType = Literal["app_open", "read_story", "link_click", "login"]

# ---- app events ------------------------------------------------------------------------------------

APP_EVENT_EMAIL = func.coalesce(Subscriber.email, AppUser.email).label("email")
APP_EVENT_COLUMNS = ["event_id", "event", "email", "user_id", "device_id", "timestamp", "properties", "profile_id"]


def _app_events_base() -> Select:
    return (
        select(AppEvent, APP_EVENT_EMAIL, AppUser.subscriber_id)
        .outerjoin(AppUser, AppUser.app_user_id == AppEvent.app_user_id)
        .outerjoin(Subscriber, Subscriber.subscriber_id == AppUser.subscriber_id)
    )


def _app_event_row(row) -> dict:
    event, email, subscriber_id = row
    return {
        "event_id": event.event_id,
        "event": event.event,
        "email": email,
        "user_id": event.app_user_id,
        "device_id": event.device_id,
        "timestamp": iso(event.timestamp),
        "received_at": iso(event.received_at),
        "properties": join_pipe(f"{k} : {v}" for k, v in (event.properties or {}).items()),
        "profile_id": profile_id_for(subscriber_id, event.app_user_id),
    }


def _app_events_response(session: Session, stmt: Select, params: ListParams):
    stmt = apply_sort(
        stmt,
        params,
        {"timestamp": AppEvent.timestamp, "event": AppEvent.event, "email": APP_EVENT_EMAIL, "user_id": AppEvent.app_user_id},
        default="timestamp",
        tiebreak=AppEvent.event_id,
    )
    if params.format == "csv":
        return csv_response(stmt, APP_EVENT_COLUMNS, _app_event_row, "app_events")
    return paginate(session, stmt, params, _app_event_row)


@router.get("/app_events")
def list_app_events(
    params: ListParams = Depends(list_params),
    date_from: date | None = None,
    date_to: date | None = None,
    today: bool = False,
    event: EventType | None = None,
    user_id: str | None = Query(None, max_length=32),
    anonymous: bool = Query(False, description="Only events with no user (device not logged in)"),
    email: str | None = Query(None, max_length=64, description="Part of an email address"),
    device_id: str | None = Query(None, max_length=64),
    session: Session = Depends(get_session),
):
    """All app events, newest first by default. Sortable by timestamp, event, email, user_id."""
    stmt = _app_events_base().where(*date_range_filter(AppEvent.timestamp, date_from, date_to, today))
    if event:
        stmt = stmt.where(AppEvent.event == event)
    if anonymous:
        stmt = stmt.where(AppEvent.app_user_id.is_(None))
    elif user_id:
        stmt = stmt.where(AppEvent.app_user_id == user_id.strip())
    if term := normalize_search(email):
        stmt = stmt.where(APP_EVENT_EMAIL.contains(term, autoescape=True))
    if device_id:
        stmt = stmt.where(AppEvent.device_id == device_id.strip())
    return _app_events_response(session, stmt, params)


@router.get("/profiles/{profile_id}/app_events")
def profile_app_events(profile_id: str, params: ListParams = Depends(list_params), session: Session = Depends(get_session)):
    """One person's app events, including anonymous events stitched to them at login."""
    profile = resolve_profile(session, profile_id)
    user_ids = profile.app_user_ids
    stmt = _app_events_base().where(AppEvent.app_user_id.in_(user_ids) if user_ids else false())
    return _app_events_response(session, stmt, params)


# ---- web events ------------------------------------------------------------------------------------

WEB_EVENT_COLUMNS = ["email", "visitor_id", "page", "timestamp", "utm_source", "email_backfilled", "profile_id"]


def _web_event_row(row) -> dict:
    (event,) = row
    return {
        "web_event_id": event.web_event_id,
        "email": event.email,
        "email_backfilled": event.email_backfilled,
        "visitor_id": event.visitor_id,
        "page": event.page,
        "timestamp": iso(event.timestamp),
        "utm_source": event.utm_source,
        "profile_id": profile_id_for(event.subscriber_id, None),
    }


def _web_events_response(session: Session, stmt: Select, params: ListParams):
    stmt = apply_sort(
        stmt,
        params,
        {"timestamp": WebEvent.timestamp, "page": WebEvent.page, "utm_source": WebEvent.utm_source, "email": WebEvent.email},
        default="timestamp",
        tiebreak=WebEvent.web_event_id,
    )
    if params.format == "csv":
        return csv_response(stmt, WEB_EVENT_COLUMNS, _web_event_row, "web_events")
    return paginate(session, stmt, params, _web_event_row)


@router.get("/web_events")
def list_web_events(
    params: ListParams = Depends(list_params),
    date_from: date | None = None,
    date_to: date | None = None,
    today: bool = False,
    utm_source: str | None = Query(None, max_length=32),
    email: str | None = Query(None, max_length=64, description="Part of an email address"),
    page_path: str | None = Query(None, alias="page_path", max_length=255, description="Exact page path, e.g. /subscribe"),
    session: Session = Depends(get_session),
):
    """All web events, newest first by default. Sortable by timestamp, page, utm_source, email."""
    stmt = select(WebEvent).where(*date_range_filter(WebEvent.timestamp, date_from, date_to, today))
    if utm_source:
        stmt = stmt.where(WebEvent.utm_source == utm_source.strip().lower())
    if term := normalize_search(email):
        stmt = stmt.where(WebEvent.email.contains(term, autoescape=True))
    if page_path:
        stmt = stmt.where(WebEvent.page == page_path.strip())
    return _web_events_response(session, stmt, params)


@router.get("/profiles/{profile_id}/web_events")
def profile_web_events(profile_id: str, params: ListParams = Depends(list_params), session: Session = Depends(get_session)):
    """One person's site visits: events captured with their email or backfilled from the same visitor."""
    profile = resolve_profile(session, profile_id)
    if profile.subscriber:
        condition = WebEvent.subscriber_id == profile.subscriber.subscriber_id
    else:
        condition = WebEvent.email.in_(profile.emails) if profile.emails else false()
    return _web_events_response(session, select(WebEvent).where(condition), params)
