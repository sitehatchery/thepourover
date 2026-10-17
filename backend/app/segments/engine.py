"""Segment definitions: the field schema, validation, and translation to parameterized SQL.

A definition is {"match": "all" | "any", "filters": [{"field", "operator", "value", "within_last_days"?}]}.
The same schema drives the segment builder UI and the AI assistant, so both can only express what's here.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement, Subquery

from app.config import get_settings
from app.models import AcquisitionSource, AppEvent, WebEvent
from app.segments.people import has_app_event, has_web_event

STATUS_VALUES = {"active": 1, "unsubscribed": 0}
APP_EVENT_TYPES = ["app_open", "read_story", "link_click", "login"]
MAX_FILTERS = 20

OPERATORS = {
    "string": ["equals", "not_equals", "in", "not_in", "is_empty", "is_not_empty"],
    "number": ["equals", "gte", "lte"],
    "date": ["before", "after", "on", "within_last_days", "not_within_last_days", "is_empty", "is_not_empty"],
    "boolean": ["equals"],
    "activity": ["includes", "not_includes"],
}


@dataclass(frozen=True)
class FieldDef:
    name: str
    type: str  # string | number | date | boolean | activity
    label: str
    description: str
    category: str
    nullable: bool = False
    datetime_column: bool = False  # date fields stored as timestamps rather than dates
    values: tuple[str, ...] | None = None  # fixed choices; dynamic ones are filled in by schema()


FIELDS: dict[str, FieldDef] = {
    f.name: f
    for f in [
        FieldDef("is_subscriber", "boolean", "Is a newsletter subscriber", "False for app users who never subscribed.", "Subscriber"),
        FieldDef("status", "string", "Newsletter status", "active or unsubscribed.", "Subscriber", True, values=tuple(STATUS_VALUES)),
        FieldDef("acquisition_source", "string", "Acquisition source", "Where the subscriber signed up from.", "Subscriber", True),
        FieldDef("signup_date", "date", "Signup date", "Newsletter signup date.", "Subscriber", True),
        FieldDef("last_open_date", "date", "Last email open", "Most recent newsletter open; empty if never opened.", "Subscriber", True),
        FieldDef("has_app_account", "boolean", "Has an app account", "Has at least one app account.", "App"),
        FieldDef("app_created_at", "date", "App account created", "When the app account was created.", "App", True),
        FieldDef("app_event_count", "number", "App events", "Number of app events.", "App"),
        FieldDef("last_app_activity", "date", "Last app activity", "Most recent app event.", "App", True, True),
        FieldDef(
            "app_event_type", "activity", "Did in the app", "Has an app event of this type (optionally within N days).", "App",
            values=tuple(APP_EVENT_TYPES),
        ),
        FieldDef("web_event_count", "number", "Website visits", "Number of linked web events.", "Website"),
        FieldDef("web_active_days", "number", "Days active on the website", "Distinct days with a linked web event.", "Website"),
        FieldDef("last_web_visit", "date", "Last website visit", "Most recent linked web event.", "Website", True, True),
        FieldDef("first_utm_source", "string", "First web source", "UTM source of the oldest linked web event that has one.", "Website", True),
        FieldDef("page_visited", "activity", "Visited page", "Has a linked web event on this page (optionally within N days).", "Website"),
        FieldDef("last_seen", "date", "Last seen", "Most recent web or app activity.", "Overall", True, True),
    ]
}


def operators_for(spec: FieldDef) -> list[str]:
    ops = OPERATORS[spec.type]
    return ops if spec.nullable else [o for o in ops if o not in ("is_empty", "is_not_empty")]


class SegmentFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    operator: str
    value: Any = None
    within_last_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def _check(self) -> "SegmentFilter":
        spec = FIELDS.get(self.field)
        if spec is None:
            raise ValueError(f"unknown field '{self.field}'")
        allowed = operators_for(spec)
        if self.operator not in allowed:
            raise ValueError(f"'{self.field}' supports {', '.join(allowed)}, not '{self.operator}'")
        if self.within_last_days is not None and spec.type != "activity":
            raise ValueError("within_last_days only applies to activity fields")
        self.value = _check_value(spec, self.operator, self.value)
        return self


class SegmentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: Literal["all", "any"] = "all"
    filters: list[SegmentFilter] = Field(default_factory=list, max_length=MAX_FILTERS)


def _check_value(spec: FieldDef, operator: str, value: Any) -> Any:
    if operator in ("is_empty", "is_not_empty"):
        if not spec.nullable:
            raise ValueError(f"'{spec.name}' is never empty")
        return None
    if operator in ("within_last_days", "not_within_last_days"):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 3650:
            raise ValueError(f"'{spec.name}' {operator} needs a number of days between 1 and 3650")
        return value
    if spec.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"'{spec.name}' needs true or false")
        return value
    if spec.type == "number":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"'{spec.name}' needs a whole number of 0 or more")
        return value
    if spec.type == "date":
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValueError(f"'{spec.name}' needs a date as YYYY-MM-DD") from exc
    if operator in ("in", "not_in"):
        if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
            raise ValueError(f"'{spec.name}' {operator} needs a list of values")
        values = [v.strip() for v in value][:50]
        if spec.name == "status":
            values = [v.lower() for v in values]
            if any(v not in STATUS_VALUES for v in values):
                raise ValueError("status must be active or unsubscribed")
        return values
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError(f"'{spec.name}' needs a text value")
    value = value.strip()
    if spec.name == "status":
        value = value.lower()
        if value not in STATUS_VALUES:
            raise ValueError("status must be active or unsubscribed")
    if spec.name == "app_event_type" and value not in APP_EVENT_TYPES:
        raise ValueError(f"app_event_type must be one of {', '.join(APP_EVENT_TYPES)}")
    return value


# ---- SQL -----------------------------------------------------------------------------------------


def condition(definition: SegmentDefinition, people: Subquery) -> ColumnElement[bool]:
    """WHERE clause on the people view that selects the segment's members. Values are always bound
    parameters; field names only come from the FIELDS allow-list."""
    clauses = [_filter_clause(f, people) for f in definition.filters]
    if not clauses:
        return true()
    return and_(*clauses) if definition.match == "all" else or_(*clauses)


def _filter_clause(f: SegmentFilter, people: Subquery) -> ColumnElement[bool]:
    spec = FIELDS[f.field]
    if spec.type == "activity":
        return _activity_clause(f, people)

    column = people.c[spec.name]
    op, value = f.operator, f.value
    if op == "is_empty":
        return column.is_(None)
    if op == "is_not_empty":
        return column.is_not(None)

    if spec.type == "boolean":
        return column == (1 if value else 0)
    if spec.type == "number":
        return {"equals": column == value, "gte": column >= value, "lte": column <= value}[op]
    if spec.type == "date":
        return _date_clause(spec, column, op, value)

    if spec.name == "status":
        value = [STATUS_VALUES[v] for v in value] if isinstance(value, list) else STATUS_VALUES[value]
    if op == "equals":
        return column == value
    if op == "not_equals":
        return or_(column.is_(None), column != value)
    if op == "in":
        return column.in_(value)
    return or_(column.is_(None), column.not_in(value))


def _date_clause(spec: FieldDef, column, op: str, value) -> ColumnElement[bool]:
    today = get_settings().today

    def bound(day: date):
        # Compare like with like: SQLite stores dates and timestamps as text.
        return datetime.combine(day, time.min) if spec.datetime_column else day

    if op in ("within_last_days", "not_within_last_days"):
        since = today - timedelta(days=value)
        within = column >= bound(since)
        # "Not within" includes people with no date at all (e.g. never opened).
        return within if op == "within_last_days" else or_(column.is_(None), column < bound(since))

    day = date.fromisoformat(value)
    if op == "before":
        return column < bound(day)
    if op == "after":
        return column >= bound(day + timedelta(days=1)) if spec.datetime_column else column > day
    if spec.datetime_column:
        return and_(column >= bound(day), column < bound(day + timedelta(days=1)))
    return column == day


def _activity_clause(f: SegmentFilter, people: Subquery) -> ColumnElement[bool]:
    model, check = (AppEvent, has_app_event) if f.field == "app_event_type" else (WebEvent, has_web_event)
    conditions = [(model.event if model is AppEvent else model.page) == f.value]
    if f.within_last_days:
        since = get_settings().today - timedelta(days=f.within_last_days)
        conditions.append(model.timestamp >= datetime.combine(since, time.min))
    found = check(people, *conditions)
    return found if f.operator == "includes" else ~found


# ---- schema for the UI and the AI ----------------------------------------------------------------


def schema(session: Session) -> dict:
    """Fields, operators and allowed values. Category values come from the data, never personal data."""
    dynamic = {
        "acquisition_source": sorted(session.scalars(select(AcquisitionSource.source))),
        "first_utm_source": sorted(v for v in session.scalars(select(WebEvent.utm_source).distinct()) if v),
        "page_visited": sorted(session.scalars(select(WebEvent.page).distinct())),
    }
    return {
        "today": get_settings().today.isoformat(),
        "match": ["all", "any"],
        "operators": OPERATORS,
        "fields": {
            spec.name: {
                "type": spec.type,
                "label": spec.label,
                "description": spec.description,
                "category": spec.category,
                "operators": operators_for(spec),
                **({"values": list(spec.values or dynamic.get(spec.name, []))} if spec.values or spec.name in dynamic else {}),
                **({"supports_within_last_days": True} if spec.type == "activity" else {}),
            }
            for spec in FIELDS.values()
        },
    }


def describe(definition: SegmentDefinition) -> str:
    """Plain-English summary, e.g. 'Acquisition source is Instagram AND Last email open not in the last 30 days'."""
    words = {
        "equals": "is", "not_equals": "is not", "in": "is one of", "not_in": "is not one of",
        "is_empty": "is empty", "is_not_empty": "is not empty", "gte": "is at least", "lte": "is at most",
        "before": "is before", "after": "is after", "on": "is on", "within_last_days": "in the last",
        "not_within_last_days": "not in the last", "includes": "includes", "not_includes": "does not include",
    }
    parts = []
    for f in definition.filters:
        label = FIELDS[f.field].label
        if f.operator in ("is_empty", "is_not_empty"):
            parts.append(f"{label} {words[f.operator]}")
            continue
        value = ", ".join(f.value) if isinstance(f.value, list) else ("yes" if f.value is True else "no" if f.value is False else f.value)
        suffix = " days" if "within" in f.operator else ""
        window = f" in the last {f.within_last_days} days" if f.within_last_days else ""
        parts.append(f"{label} {words[f.operator]} {value}{suffix}{window}")
    if not parts:
        return "Everyone"
    return (" AND " if definition.match == "all" else " OR ").join(parts)
