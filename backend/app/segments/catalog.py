"""The built-in segment catalog. Relative dates count back from the configured today (2026-09-28).

Seeding only adds segments whose slug is missing, so edits made in the app are never overwritten.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SEGMENT_GROUP_APP_USERS, SEGMENT_GROUP_SUBSCRIBER, SEGMENT_GROUP_WEB_EVENTS, Segment
from app.seeds import ACQUISITION_SOURCES
from app.segments.engine import SegmentDefinition


def _f(field: str, operator: str, value=None, within_last_days: int | None = None) -> dict:
    item = {"field": field, "operator": operator}
    if value is not None:
        item["value"] = value
    if within_last_days is not None:
        item["within_last_days"] = within_last_days
    return item


CATALOG: list[dict] = [
    {
        "slug": "instagram_not_opened_30_days",
        "name": "Instagram signups not opened in 30 days",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Signed up from Instagram and haven't opened a newsletter in the last 30 days (including never). The example from the brief.",
        "filters": [_f("acquisition_source", "equals", "Instagram"), _f("last_open_date", "not_within_last_days", 30)],
    },
    {
        "slug": "gone_cold",
        "name": "Gone cold",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Active subscribers who signed up more than 30 days ago and haven't opened in the last 30 days.",
        "filters": [
            _f("status", "equals", "active"),
            _f("signup_date", "not_within_last_days", 30),
            _f("last_open_date", "not_within_last_days", 30),
        ],
    },
    {
        "slug": "engaged_readers",
        "name": "Engaged readers",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Opened a newsletter in the last 14 days and visited the site or app in the last 30 days.",
        "filters": [_f("last_open_date", "within_last_days", 14), _f("last_seen", "within_last_days", 30)],
    },
    {
        "slug": "not_opened_30_days",
        "name": "Not opened in 30 days",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Subscribers with no newsletter open in the last 30 days, including those who never opened.",
        "filters": [_f("is_subscriber", "equals", True), _f("last_open_date", "not_within_last_days", 30)],
    },
    {
        "slug": "recently_engaged",
        "name": "Recently engaged",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Opened a newsletter in the last 30 days.",
        "filters": [_f("last_open_date", "within_last_days", 30)],
    },
    {
        "slug": "disengaged",
        "name": "Disengaged",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Signed up more than 60 days ago and no newsletter open in the last 60 days.",
        "filters": [
            _f("is_subscriber", "equals", True),
            _f("signup_date", "not_within_last_days", 60),
            _f("last_open_date", "not_within_last_days", 60),
        ],
    },
    {
        "slug": "new_subscribers",
        "name": "New subscribers",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Signed up in the last 30 days.",
        "filters": [_f("signup_date", "within_last_days", 30)],
    },
    {
        "slug": "unsubscribed",
        "name": "Unsubscribed",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Subscribers who have unsubscribed.",
        "filters": [_f("status", "equals", "unsubscribed")],
    },
    {
        "slug": "subscribers_without_app",
        "name": "Subscribers without the app",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Newsletter subscribers with no app account.",
        "filters": [_f("is_subscriber", "equals", True), _f("has_app_account", "equals", False)],
    },
    {
        "slug": "multi_channel_readers",
        "name": "Multi-channel readers",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": "Subscribed, have an app account and have visited the website.",
        "filters": [
            _f("is_subscriber", "equals", True),
            _f("has_app_account", "equals", True),
            _f("web_event_count", "gte", 1),
        ],
    },
    {
        "slug": "app_users_not_subscribed",
        "name": "App users who haven't subscribed",
        "group": SEGMENT_GROUP_APP_USERS,
        "description": "Have an app account but aren't newsletter subscribers.",
        "filters": [_f("has_app_account", "equals", True), _f("is_subscriber", "equals", False)],
    },
    {
        "slug": "new_app_users",
        "name": "New app users",
        "group": SEGMENT_GROUP_APP_USERS,
        "description": "App account created in the last 30 days.",
        "filters": [_f("app_created_at", "within_last_days", 30)],
    },
    {
        "slug": "active_app_readers",
        "name": "Active app readers",
        "group": SEGMENT_GROUP_APP_USERS,
        "description": "Read a story in the app in the last 30 days.",
        "filters": [_f("app_event_type", "includes", "read_story", within_last_days=30)],
    },
    {
        "slug": "recent_website_visitors",
        "name": "Recent website visitors",
        "group": SEGMENT_GROUP_WEB_EVENTS,
        "description": "At least one linked website visit in the last 30 days.",
        "filters": [_f("last_web_visit", "within_last_days", 30)],
    },
    {
        "slug": "repeat_website_visitors",
        "name": "Repeat website visitors",
        "group": SEGMENT_GROUP_WEB_EVENTS,
        "description": "Linked website activity on two or more different days.",
        "filters": [_f("web_active_days", "gte", 2)],
    },
] + [
    {
        "slug": f"source_{source.lower()}",
        "name": f"Signed up from {source}",
        "group": SEGMENT_GROUP_SUBSCRIBER,
        "description": f"Subscribers whose acquisition source is {source}.",
        "filters": [_f("acquisition_source", "equals", source)],
    }
    for source in ACQUISITION_SOURCES
]


def seed_segments(session: Session) -> int:
    """Add catalog segments that don't exist yet. Returns how many were added."""
    existing = set(session.scalars(select(Segment.slug)))
    added = 0
    for item in CATALOG:
        if item["slug"] in existing:
            continue
        definition = SegmentDefinition(match="all", filters=item["filters"])  # validates the catalog entry
        session.add(
            Segment(
                slug=item["slug"],
                name=item["name"],
                group=item["group"],
                description=item["description"],
                definition=definition.model_dump(exclude_none=True),
            )
        )
        added += 1
    session.commit()
    return added
