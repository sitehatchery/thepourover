"""Readable notes for the top of CSV exports: what was exported, with which filters, sorted how."""

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Segment
from app.queries.profiles import resolve_profile
from app.rules import utcnow

FILTER_LABELS = {
    "email": "Email contains",
    "app_user_id": "App user ID",
    "status": "Status",
    "acquisition_source": "Source",
    "signup_from": "Signed up from",
    "signup_to": "Signed up to",
    "date_from": "From",
    "date_to": "To",
    "event": "Event",
    "user_id": "User ID",
    "device_id": "Device ID",
    "utm_source": "UTM source",
    "page_path": "Page",
}
NOT_FILTERS = {"format", "page", "page_size", "sort", "order"}


def export_notes(request: Request, session: Session, title: str, extra: list[str] | None = None) -> list[str]:
    params = request.query_params
    filters: list[str] = []
    for key in params:
        if key in NOT_FILTERS or key in ("segment_id", "profile_id", "today", "anonymous"):
            continue
        if value := params.get(key, "").strip():
            filters.append(f"{FILTER_LABELS.get(key, key)}: {value}")
    if params.get("today") == "true":
        filters.append(f"Today only ({get_settings().today.isoformat()})")
    if params.get("anonymous") == "true":
        filters.append("Anonymous events only")
    for segment_id in params.getlist("segment_id"):
        filters.append(f"Segment: {_segment_name(session, segment_id)}")
    if profile_id := params.get("profile_id"):
        try:
            profile = resolve_profile(session, profile_id)
            filters.append(f"Person: {profile.emails[0] if profile.emails else profile_id}")
        except Exception:
            filters.append(f"Person: {profile_id}")

    notes = [f"The Pour Over Mini CDP: {title}", f"Exported {utcnow():%Y-%m-%d %H:%M} UTC"]
    notes += extra or []
    notes.append("Filters: " + ("; ".join(filters) if filters else "none (everything)"))
    if sort := params.get("sort"):
        notes.append(f"Sorted by: {sort.replace('_', ' ')} ({'oldest/lowest' if params.get('order') == 'asc' else 'newest/highest'} first)")
    return notes


def _segment_name(session: Session, id_or_slug: str) -> str:
    query = session.query(Segment)
    segment = query.get(int(id_or_slug)) if id_or_slug.isdigit() else query.filter(Segment.slug == id_or_slug).first()
    return segment.name if segment else id_or_slug
