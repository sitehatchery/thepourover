"""Tools the assistant's model can call. Every result is aggregate or categorical: counts, percentages,
sources, pages, event types and opaque result ids. No tool returns an email or a person's identifier."""

import secrets
import threading
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from pydantic import ValidationError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SEGMENT_GROUP_SUBSCRIBER, AppEvent, Segment, Subscriber, WebEvent
from app.segments.engine import FIELDS, SegmentDefinition, condition, describe, schema
from app.segments.people import build_people
from app.segments.service import definition_of, get_segment, unique_slug

RANKABLE = ["last_seen", "last_open_date", "web_event_count", "web_active_days", "app_event_count", "signup_date"]
MAX_RESULT_SETS = 200


class ToolError(Exception):
    """A tool call the model got wrong; the message goes back to the model so it can correct itself."""


# ---- result sets: the model gets an id, the browser gets the rows -------------------------------------


class ResultStore:
    """People lists the assistant has produced, kept in memory by id. The model only ever sees the id and
    the count; the UI fetches rows for an id straight from the API (behind login)."""

    def __init__(self, limit: int = MAX_RESULT_SETS):
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._limit = limit

    def put(self, definition: SegmentDefinition, rank_by: str | None, title: str) -> str:
        result_id = "r" + secrets.token_hex(6)
        with self._lock:
            self._items[result_id] = {"definition": definition, "rank_by": rank_by, "title": title}
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
        return result_id

    def get(self, result_id: str) -> dict | None:
        with self._lock:
            return self._items.get(result_id)


results = ResultStore()


# ---- helpers --------------------------------------------------------------------------------------------


def _definition(raw: Any) -> SegmentDefinition:
    try:
        return SegmentDefinition.model_validate(raw or {"match": "all", "filters": []})
    except ValidationError as exc:
        problems = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
        raise ToolError(f"Invalid segment definition: {problems}. Call get_schema to see valid fields.") from exc


def _count(session: Session, definition: SegmentDefinition) -> int:
    people = build_people()
    return session.scalar(select(func.count()).select_from(people).where(condition(definition, people)))


def _day(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"{name} must be a date as YYYY-MM-DD") from exc


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


# ---- tools ----------------------------------------------------------------------------------------------


def get_schema(session: Session) -> dict:
    data = schema(session)
    return {
        "today": data["today"],
        "fields": {
            name: {k: v for k, v in spec.items() if k in ("type", "label", "description", "operators", "values")}
            for name, spec in data["fields"].items()
        },
        "rank_by": RANKABLE,
        "saved_segments": [
            {"slug": s.slug, "name": s.name, "description": s.description}
            for s in session.scalars(select(Segment).order_by(Segment.name))
        ],
    }


def count_people(session: Session, definition: dict | None = None, segment: str | None = None) -> dict:
    parsed = _resolve(session, definition, segment)
    total = _count(session, SegmentDefinition())
    count = _count(session, parsed)
    return {"count": count, "percent_of_everyone": _pct(count, total), "rules": describe(parsed)}


def list_people(
    session: Session, definition: dict | None = None, segment: str | None = None, rank_by: str | None = None, title: str = ""
) -> dict:
    parsed = _resolve(session, definition, segment)
    if rank_by and rank_by not in RANKABLE:
        raise ToolError(f"rank_by must be one of {', '.join(RANKABLE)}")
    result_id = results.put(parsed, rank_by, title or describe(parsed))
    return {
        "result_id": result_id,
        "count": _count(session, parsed),
        "rules": describe(parsed),
        "note": "The list is shown to the user in a table. You can't see its rows; don't describe individuals.",
    }


def create_segment(session: Session, name: str, definition: dict, description: str = "") -> dict:
    parsed = _definition(definition)
    if not name.strip():
        raise ToolError("A segment needs a name")
    segment = Segment(
        slug=unique_slug(session, name),
        name=name.strip()[:64],
        description=description.strip()[:500],
        group=SEGMENT_GROUP_SUBSCRIBER,
        definition=parsed.model_dump(exclude_none=True),
    )
    session.add(segment)
    session.commit()
    return {"slug": segment.slug, "name": segment.name, "count": _count(session, parsed), "rules": describe(parsed)}


def run_report(session: Session, report: str, **params: Any) -> dict:
    handler = REPORTS.get(report)
    if handler is None:
        raise ToolError(f"Unknown report. Available: {', '.join(REPORTS)}")
    return handler(session, **params)


def _resolve(session: Session, definition: dict | None, segment: str | None) -> SegmentDefinition:
    if segment:
        try:
            return definition_of(get_segment(session, segment))
        except Exception as exc:
            raise ToolError(f"No saved segment '{segment}'") from exc
    return _definition(definition)


# ---- reports (aggregates only) ---------------------------------------------------------------------------


def _report_signups_by_source(session: Session, signup_from: str | None = None, signup_to: str | None = None, **_) -> dict:
    people = build_people()
    stmt = select(people.c.acquisition_source, func.count()).where(people.c.is_subscriber == 1)
    if start := _day(signup_from, "signup_from"):
        stmt = stmt.where(people.c.signup_date >= start)
    if end := _day(signup_to, "signup_to"):
        stmt = stmt.where(people.c.signup_date <= end)
    rows = session.execute(stmt.group_by(people.c.acquisition_source).order_by(func.count().desc())).all()
    total = sum(n for _, n in rows)
    return {
        "title": "Signups by acquisition source",
        "definition": "Newsletter subscribers counted by the source they signed up from.",
        "columns": ["source", "signups", "percent"],
        "rows": [[source or "(unknown)", n, _pct(n, total)] for source, n in rows],
        "total": total,
    }


def _report_cold_by_source(session: Session, days_without_open: int = 30, signup_from: str | None = None, signup_to: str | None = None, **_) -> dict:
    """Active subscribers with no open in N days (or never), per source, as a share of that source."""
    people = build_people()
    since = get_settings().today - timedelta(days=int(days_without_open))
    cold = (people.c.last_open_date.is_(None)) | (people.c.last_open_date < since)
    stmt = select(
        people.c.acquisition_source,
        func.count(),
        func.sum(case((cold, 1), else_=0)),
    ).where(people.c.is_subscriber == 1, people.c.status == 1)
    start, end = _day(signup_from, "signup_from"), _day(signup_to, "signup_to")
    if start:
        stmt = stmt.where(people.c.signup_date >= start)
    if end:
        stmt = stmt.where(people.c.signup_date <= end)
    if start or end:
        signup_rule = "who signed up in the period asked about"
    else:
        # Same rule as the "Gone cold" segment and the system prompt: too new to have gone cold doesn't count.
        stmt = stmt.where(people.c.signup_date < since)
        signup_rule = f"who signed up more than {days_without_open} days ago"
    rows = session.execute(stmt.group_by(people.c.acquisition_source)).all()
    out = sorted(([s or "(unknown)", total, int(c or 0), _pct(int(c or 0), total)] for s, total, c in rows), key=lambda r: -r[2])
    return {
        "title": f"Active subscribers with no open in {days_without_open} days, by source",
        "definition": (
            f"Gone cold = still subscribed, {signup_rule}, with no newsletter open in the last "
            f"{days_without_open} days (including never opened)."
        ),
        "columns": ["source", "active_subscribers", "gone_cold", "percent_cold"],
        "rows": out,
        "total": sum(r[2] for r in out),
    }


def _report_first_pages(session: Session, signed_up_within_days: int = 30, limit: int = 10, **_) -> dict:
    """For subscribers who signed up recently, the page of their first linked web visit."""
    settings = get_settings()
    since = settings.today - timedelta(days=int(signed_up_within_days))
    first_visit = (
        select(
            WebEvent.subscriber_id,
            WebEvent.page,
            func.row_number().over(partition_by=WebEvent.subscriber_id, order_by=WebEvent.timestamp).label("n"),
        )
        .join(Subscriber, Subscriber.subscriber_id == WebEvent.subscriber_id)
        .where(Subscriber.signup_date >= since)
        .subquery()
    )
    rows = session.execute(
        select(first_visit.c.page, func.count())
        .where(first_visit.c.n == 1)
        .group_by(first_visit.c.page)
        .order_by(func.count().desc())
        .limit(max(1, min(int(limit), 25)))
    ).all()
    total = session.scalar(select(func.count()).select_from(first_visit).where(first_visit.c.n == 1)) or 0
    return {
        "title": f"First page visited by subscribers who signed up in the last {signed_up_within_days} days",
        "definition": "Each subscriber's earliest linked website visit (any time; usually the visit where they signed up). Only subscribers with at least one linked visit are counted.",
        "columns": ["page", "subscribers", "percent"],
        "rows": [[page, n, _pct(n, total)] for page, n in rows],
        "total": total,
    }


def _report_top_pages(session: Session, date_from: str | None = None, date_to: str | None = None, limit: int = 10, **_) -> dict:
    stmt = select(WebEvent.page, func.count(), func.count(func.distinct(WebEvent.visitor_id)))
    if start := _day(date_from, "date_from"):
        stmt = stmt.where(WebEvent.timestamp >= datetime.combine(start, time.min))
    if end := _day(date_to, "date_to"):
        stmt = stmt.where(WebEvent.timestamp < datetime.combine(end + timedelta(days=1), time.min))
    rows = session.execute(stmt.group_by(WebEvent.page).order_by(func.count().desc()).limit(max(1, min(int(limit), 25)))).all()
    return {
        "title": "Most visited pages",
        "definition": "All website visits, including anonymous ones, with distinct visitor ids per page.",
        "columns": ["page", "visits", "unique_visitors"],
        "rows": [list(r) for r in rows],
        "total": sum(r[1] for r in rows),
    }


def _report_engagement_overview(session: Session, **_) -> dict:
    people = build_people()
    today = get_settings().today
    subs = select(people).where(people.c.is_subscriber == 1).subquery()
    total = session.scalar(select(func.count()).select_from(subs))
    buckets = [
        ("Opened in the last 7 days", subs.c.last_open_date >= today - timedelta(days=7)),
        ("Opened 8-30 days ago", (subs.c.last_open_date < today - timedelta(days=7)) & (subs.c.last_open_date >= today - timedelta(days=30))),
        ("No open in 30+ days", subs.c.last_open_date < today - timedelta(days=30)),
        ("Never opened", subs.c.last_open_date.is_(None)),
    ]
    rows = [[label, session.scalar(select(func.count()).select_from(subs).where(cond))] for label, cond in buckets]
    extra = [
        ["Unsubscribed", session.scalar(select(func.count()).select_from(subs).where(subs.c.status == 0))],
        ["Have the app", session.scalar(select(func.count()).select_from(subs).where(subs.c.has_app_account == 1))],
        ["Visited the website", session.scalar(select(func.count()).select_from(subs).where(subs.c.web_event_count > 0))],
    ]
    return {
        "title": "Subscriber engagement overview",
        "definition": "Groups overlap except the four newsletter-open buckets, which add up to all subscribers.",
        "columns": ["group", "subscribers", "percent"],
        "rows": [[label, n, _pct(n, total)] for label, n in rows + extra],
        "total": total,
    }


def _report_app_activity(session: Session, date_from: str | None = None, date_to: str | None = None, **_) -> dict:
    stmt = select(AppEvent.event, func.count(), func.count(func.distinct(AppEvent.app_user_id)))
    if start := _day(date_from, "date_from"):
        stmt = stmt.where(AppEvent.timestamp >= datetime.combine(start, time.min))
    if end := _day(date_to, "date_to"):
        stmt = stmt.where(AppEvent.timestamp < datetime.combine(end + timedelta(days=1), time.min))
    rows = session.execute(stmt.group_by(AppEvent.event).order_by(func.count().desc())).all()
    return {
        "title": "App activity by event type",
        "definition": "App events received through the webhook, with distinct logged-in users per type.",
        "columns": ["event", "events", "users"],
        "rows": [list(r) for r in rows],
        "total": sum(r[1] for r in rows),
    }


REPORTS: dict[str, Callable[..., dict]] = {
    "signups_by_source": _report_signups_by_source,
    "cold_by_source": _report_cold_by_source,
    "first_pages_new_subscribers": _report_first_pages,
    "top_pages": _report_top_pages,
    "engagement_overview": _report_engagement_overview,
    "app_activity": _report_app_activity,
}

REPORT_DESCRIPTIONS = {
    "signups_by_source": "Subscriber signups per acquisition source. Params: signup_from, signup_to (YYYY-MM-DD, optional).",
    "cold_by_source": "Active subscribers with no email open in N days (or never), per source with percent cold. Params: days_without_open (default 30), signup_from, signup_to.",
    "first_pages_new_subscribers": "Which page recently signed-up subscribers hit first on the website. Params: signed_up_within_days (default 30), limit (default 10).",
    "top_pages": "Most visited pages with unique visitors. Params: date_from, date_to, limit.",
    "engagement_overview": "How many subscribers opened recently, went cold, never opened, unsubscribed, have the app, visited the site. No params.",
    "app_activity": "App events by type with distinct users. Params: date_from, date_to.",
}


# ---- tool definitions for the model ----------------------------------------------------------------------

DEFINITION_PARAM = {
    "type": "object",
    "description": "Segment definition: {match: 'all'|'any', filters: [{field, operator, value, within_last_days?}]}. "
    "Fields, operators and allowed values come from get_schema.",
    "properties": {
        "match": {"type": "string", "enum": ["all", "any"]},
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(FIELDS)},
                    "operator": {"type": "string"},
                    "value": {},
                    "within_last_days": {"type": "integer"},
                },
                "required": ["field", "operator"],
            },
        },
    },
}

TOOL_SPECS = [
    {
        "name": "get_schema",
        "description": "Fields and operators for segment definitions, allowed values (sources, pages, event types), "
        "today's date, ranking options and saved segments. Call this first if you are unsure.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "count_people",
        "description": "Count the people matching a definition or a saved segment, with their share of everyone.",
        "parameters": {
            "type": "object",
            "properties": {"definition": DEFINITION_PARAM, "segment": {"type": "string", "description": "Saved segment slug"}},
        },
    },
    {
        "name": "list_people",
        "description": "Show the user a table of the matching people (e.g. 'build me a list'). Returns a result id and "
        "count only; you never see the rows. Optionally rank by a metric (highest first).",
        "parameters": {
            "type": "object",
            "properties": {
                "definition": DEFINITION_PARAM,
                "segment": {"type": "string", "description": "Saved segment slug"},
                "rank_by": {"type": "string", "enum": RANKABLE},
                "title": {"type": "string", "description": "Short title for the table"},
            },
        },
    },
    {
        "name": "create_segment",
        "description": "Save a definition as a reusable segment. Only do this when the user asks to save or create a segment.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "definition": DEFINITION_PARAM,
            },
            "required": ["name", "definition"],
        },
    },
    {
        "name": "run_report",
        "description": "Aggregate reports. " + " ".join(f"{k}: {v}" for k, v in REPORT_DESCRIPTIONS.items()),
        "parameters": {
            "type": "object",
            "properties": {
                "report": {"type": "string", "enum": list(REPORTS)},
                "params": {"type": "object", "description": "Report parameters (see description)"},
            },
            "required": ["report"],
        },
    },
]


def call_tool(session: Session, name: str, arguments: dict) -> dict:
    if name == "get_schema":
        return get_schema(session)
    if name == "count_people":
        return count_people(session, arguments.get("definition"), arguments.get("segment"))
    if name == "list_people":
        return list_people(session, arguments.get("definition"), arguments.get("segment"), arguments.get("rank_by"), arguments.get("title", ""))
    if name == "create_segment":
        return create_segment(session, arguments.get("name", ""), arguments.get("definition") or {}, arguments.get("description", ""))
    if name == "run_report":
        params = arguments.get("params") or {}
        if not isinstance(params, dict):
            raise ToolError("params must be an object")
        return run_report(session, arguments.get("report", ""), **params)
    raise ToolError(f"Unknown tool '{name}'")
