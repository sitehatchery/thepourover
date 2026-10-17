"""Row formatting and sorting shared by the Subscribers table and segment member lists."""

from app.queries.listing import iso

STATUS_LABELS = {1: "active", 0: "unsubscribed"}

PEOPLE_COLUMNS = [
    "profile_id",
    "email",
    "signup_date",
    "status",
    "acquisition_source",
    "last_open_date",
    "app_user_id",
    "app_created_at",
    "app_event_count",
    "web_event_count",
    "last_seen",
    "first_utm_source",
]

SORTABLE = [
    "email",
    "signup_date",
    "status",
    "acquisition_source",
    "last_open_date",
    "app_user_id",
    "app_created_at",
    "app_event_count",
    "web_event_count",
    "last_seen",
    "first_utm_source",
]


def person_row(row) -> dict:
    data = row._mapping
    return {
        "profile_id": data["profile_id"],
        "email": data["email"],
        "signup_date": iso(data["signup_date"]),
        "status": STATUS_LABELS.get(data["status"]),
        "acquisition_source": data["acquisition_source"],
        "last_open_date": iso(data["last_open_date"]),
        "app_user_id": data["app_user_id"],
        "app_created_at": iso(data["app_created_at"]),
        "app_event_count": data["app_event_count"],
        "web_event_count": data["web_event_count"],
        "web_active_days": data["web_active_days"],
        "last_seen": iso(data["last_seen"]),
        "first_utm_source": data["first_utm_source"],
        "is_subscriber": bool(data["is_subscriber"]),
        "is_placeholder": bool(data["is_placeholder"]),
    }


def sort_columns(people) -> dict:
    return {name: people.c[name] for name in SORTABLE}
