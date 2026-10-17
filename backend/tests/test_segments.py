import csv
import io

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.importer.service import run_import
from app.importer.sources import LocalFolderSource
from app.segments.engine import SegmentDefinition, describe
from app.segments.service import members

# Expected sizes on the sample data, cross-checked with hand-written SQL.
SEEDED_COUNTS = {
    "instagram_not_opened_30_days": 229,
    "repeat_website_visitors": 1063,
    "recent_website_visitors": 1017,
    "app_users_not_subscribed": 30,
    "unsubscribed": 290,
    "subscribers_without_app": 2000,
    "multi_channel_readers": 431,
    "disengaged": 196,
}


@pytest.fixture
def imported(session, settings):
    run_import(session, LocalFolderSource(settings.import_source_dir), settings)


def count(session, definition: dict) -> int:
    _people, stmt = members(SegmentDefinition.model_validate(definition))
    return session.scalar(select(func.count()).select_from(stmt.subquery()))


# ---- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_filter",
    [
        {"field": "email", "operator": "equals", "value": "a@b.com"},  # not a segment field (PII)
        {"field": "acquisition_source", "operator": "gte", "value": "Instagram"},
        {"field": "web_event_count", "operator": "gte", "value": "lots"},
        {"field": "web_event_count", "operator": "gte", "value": -1},
        {"field": "signup_date", "operator": "before", "value": "last tuesday"},
        {"field": "last_open_date", "operator": "within_last_days", "value": 0},
        {"field": "has_app_account", "operator": "equals", "value": "yes"},
        {"field": "status", "operator": "equals", "value": "paused"},
        {"field": "app_event_type", "operator": "includes", "value": "purchase"},
        {"field": "has_app_account", "operator": "is_empty"},
        {"field": "signup_date", "operator": "on", "value": "2026-09-01", "within_last_days": 5},
        {"field": "status", "operator": "equals", "value": "active", "sql": "1=1"},
    ],
)
def test_invalid_definitions_are_rejected(bad_filter):
    with pytest.raises(ValidationError):
        SegmentDefinition(filters=[bad_filter])


def test_describe_reads_like_english():
    definition = SegmentDefinition(
        filters=[
            {"field": "acquisition_source", "operator": "equals", "value": "Instagram"},
            {"field": "last_open_date", "operator": "not_within_last_days", "value": 30},
        ]
    )
    assert describe(definition) == "Acquisition source is Instagram AND Last email open not in the last 30 days"


# ---- evaluation ---------------------------------------------------------------------------------


def test_brief_example_segment(session, imported):
    assert count(
        session,
        {
            "filters": [
                {"field": "acquisition_source", "operator": "equals", "value": "Instagram"},
                {"field": "last_open_date", "operator": "not_within_last_days", "value": 30},
            ]
        },
    ) == 229


def test_match_any_and_empty_definition(session, imported):
    assert count(session, {"filters": []}) == 2930  # 2,900 subscribers + 30 app-only users
    either = count(
        session,
        {
            "match": "any",
            "filters": [
                {"field": "acquisition_source", "operator": "equals", "value": "X"},
                {"field": "acquisition_source", "operator": "equals", "value": "Podcast"},
            ],
        },
    )
    assert either == count(session, {"filters": [{"field": "acquisition_source", "operator": "in", "value": ["X", "Podcast"]}]})


def test_date_operators(session, imported):
    on_day = count(session, {"filters": [{"field": "signup_date", "operator": "on", "value": "2026-09-28"}]})
    before = count(session, {"filters": [{"field": "signup_date", "operator": "before", "value": "2026-09-28"}]})
    assert on_day > 0
    assert on_day + before == 2900
    assert count(session, {"filters": [{"field": "signup_date", "operator": "after", "value": "2026-09-28"}]}) == 0
    never_opened = count(session, {"filters": [{"field": "is_subscriber", "operator": "equals", "value": True}, {"field": "last_open_date", "operator": "is_empty"}]})
    assert never_opened == 470  # SELECT count(*) FROM subscribers WHERE last_open_date IS NULL


def test_activity_fields_react_to_new_webhook_events(client, auth, session, imported):
    readers = {"filters": [{"field": "app_event_type", "operator": "includes", "value": "read_story", "within_last_days": 30}]}
    assert count(session, readers) == 0

    event = {"event_id": "evt_1", "event": "read_story", "user_id": "u_2b6447a3", "device_id": "d_1", "timestamp": "2026-09-28T10:00:00Z", "properties": {}}
    client.post("/app/app_events/send", json=event, headers=auth)

    assert count(session, readers) == 1  # no restart, no cache


def test_page_visited(session, imported):
    visited = count(session, {"filters": [{"field": "page_visited", "operator": "includes", "value": "/about"}]})
    not_visited = count(session, {"filters": [{"field": "page_visited", "operator": "not_includes", "value": "/about"}]})
    assert visited > 0 and visited + not_visited == 2930


# ---- API ----------------------------------------------------------------------------------------


def test_seeded_catalog_counts(client, auth, imported):
    segments = {s["slug"]: s for s in client.get("/app/segments", headers=auth).json()}

    assert len(segments) == 22
    for slug, expected in SEEDED_COUNTS.items():
        assert segments[slug]["member_count"] == expected, slug
    source_total = sum(s["member_count"] for slug, s in segments.items() if slug.startswith("source_"))
    assert source_total == 2900


def test_schema_lists_fields_and_data_values(client, auth, imported):
    schema = client.get("/app/segments/schema", headers=auth).json()

    assert schema["today"] == "2026-09-28"
    assert "email" not in schema["fields"]
    assert schema["fields"]["acquisition_source"]["values"] == ["Direct", "Facebook", "Google", "Instagram", "Podcast", "Referral", "X"]
    assert "/subscribe" in schema["fields"]["page_visited"]["values"]
    assert "is_empty" not in schema["fields"]["has_app_account"]["operators"]


def test_create_preview_update_delete(client, auth, imported):
    definition = {"filters": [{"field": "acquisition_source", "operator": "equals", "value": "Podcast"}]}
    preview = client.post("/app/segments/preview", json=definition, headers=auth).json()
    assert preview == {"member_count": 226, "summary": "Acquisition source is Podcast"}

    created = client.post("/app/segments", json={"name": "Podcast fans!", "definition": definition}, headers=auth)
    assert created.status_code == 201
    segment = created.json()
    assert segment["slug"] == "podcast_fans" and segment["member_count"] == 226

    definition["filters"].append({"field": "status", "operator": "equals", "value": "active"})
    updated = client.put(f"/app/segments/{segment['slug']}", json={"name": "Podcast fans", "definition": definition}, headers=auth).json()
    assert updated["member_count"] < 226

    assert client.delete(f"/app/segments/{segment['segment_id']}", headers=auth).status_code == 204
    assert client.get(f"/app/segments/{segment['segment_id']}", headers=auth).status_code == 404


def test_invalid_definition_returns_422(client, auth):
    response = client.post("/app/segments/preview", json={"filters": [{"field": "email", "operator": "equals", "value": "x"}]}, headers=auth)
    assert response.status_code == 422


def test_members_and_csv(client, auth, imported):
    page = client.get("/app/segments/source_x/members?page_size=10", headers=auth).json()
    assert page["total"] == 114 and len(page["items"]) == 10
    assert all(i["acquisition_source"] == "X" for i in page["items"])

    exported = client.get("/app/segments/source_x/members?format=csv", headers=auth)
    assert len(list(csv.DictReader(io.StringIO(exported.text)))) == 114


def test_segment_filters_on_event_lists(client, auth, session, imported):
    web = client.get("/app/web_events?segment_id=repeat_website_visitors", headers=auth).json()
    everyone_linked = client.get("/app/web_events?page_size=1", headers=auth).json()
    assert 0 < web["total"] < everyone_linked["total"]

    both = client.get("/app/web_events?segment_id=repeat_website_visitors&segment_id=source_x", headers=auth).json()
    assert both["total"] < web["total"]

    assert client.get("/app/web_events?segment_id=nope", headers=auth).status_code == 404
