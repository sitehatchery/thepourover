import csv
import io

import pytest
from sqlalchemy import select

from app.importer.service import run_import
from app.importer.sources import LocalFolderSource
from app.models import AppUser, Subscriber


@pytest.fixture
def imported(session, settings):
    run_import(session, LocalFolderSource(settings.import_source_dir), settings)


def test_event_lists_require_auth(client):
    for path in ("/app/app_events", "/app/web_events", "/app/profiles/s_1/web_events"):
        assert client.get(path).status_code == 401


# ---- web events ---------------------------------------------------------------------------------


def test_web_events_default_page(client, auth, imported):
    body = client.get("/app/web_events", headers=auth).json()

    assert body["total"] == 10000 and body["page_size"] == 40 and len(body["items"]) == 40
    timestamps = [i["timestamp"] for i in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_web_events_filters(client, auth, imported):
    today = client.get("/app/web_events?today=true&page_size=200", headers=auth).json()
    assert today["total"] > 0
    assert all(i["timestamp"].startswith("2026-09-28") for i in today["items"])

    twitter = client.get("/app/web_events?utm_source=Twitter", headers=auth).json()
    assert twitter["total"] == 50

    subscribe = client.get("/app/web_events?page_path=/subscribe", headers=auth).json()
    assert subscribe["total"] == 2433

    by_email = client.get("/app/web_events?email=GMAIL.COM", headers=auth).json()
    assert by_email["total"] > 0 and all("gmail.com" in i["email"] for i in by_email["items"])


def test_bad_sort_and_date_range_are_rejected(client, auth):
    assert client.get("/app/web_events?sort=visitor_id;drop", headers=auth).status_code == 400
    assert client.get("/app/web_events?date_from=2026-09-10&date_to=2026-09-01", headers=auth).status_code == 400


def test_web_events_sort_by_page_ascending(client, auth, imported):
    items = client.get("/app/web_events?sort=page&order=asc", headers=auth).json()["items"]
    assert [i["page"] for i in items] == sorted(i["page"] for i in items)


def test_web_events_csv_export_has_every_matching_row(client, auth, imported):
    response = client.get("/app/web_events?format=csv&page_path=/about", headers=auth)

    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="web_events_2026-09-28.csv"' in response.headers["content-disposition"]
    lines = response.text.splitlines()
    notes = [line for line in lines if line.startswith("#")]
    assert notes[0] == "# The Pour Over Mini CDP: Web events"
    assert "# Filters: Page: /about" in notes
    rows = list(csv.DictReader(line for line in lines if not line.startswith("#")))
    assert len(rows) == 537  # all of them, not one page


# ---- app events ---------------------------------------------------------------------------------


def _send(client, auth, event_id, user_id, device="d_1", ts="2026-09-28T10:00:00Z", kind="app_open"):
    payload = {"event_id": event_id, "event": kind, "user_id": user_id, "device_id": device, "timestamp": ts, "properties": {}}
    assert client.post("/app/app_events/send", json=payload, headers=auth).status_code == 200


def test_csv_notes_name_segments_people_and_sort(client, auth, imported):
    text = client.get("/app/subscribers?format=csv&segment_id=gone_cold&status=active&today=true&sort=email&order=asc", headers=auth).text
    notes = [line for line in text.splitlines() if line.startswith("#")]

    assert "# Filters: Status: active; Today only (2026-09-28); Segment: Gone cold" in notes
    assert "# Sorted by: email (oldest/lowest first)" in notes
    unfiltered = client.get("/app/subscribers?format=csv", headers=auth).text
    assert "# Filters: none (everything)" in unfiltered.splitlines()


def test_app_events_list_filters_and_email(client, auth, session, imported):
    user = session.scalar(select(AppUser).where(AppUser.subscriber_id.is_not(None)))
    _send(client, auth, "evt_anon", None, device="d_9", ts="2026-09-27T10:00:00Z")
    _send(client, auth, "evt_known", user.app_user_id, kind="read_story")

    everything = client.get("/app/app_events", headers=auth).json()
    assert everything["total"] == 2
    assert everything["items"][0]["event_id"] == "evt_known"  # newest first

    known = everything["items"][0]
    assert known["email"] == session.get(Subscriber, user.subscriber_id).email
    assert known["profile_id"] == f"s_{user.subscriber_id}"

    anonymous = client.get("/app/app_events?anonymous=true", headers=auth).json()
    assert [i["event_id"] for i in anonymous["items"]] == ["evt_anon"]
    assert client.get("/app/app_events?today=true", headers=auth).json()["total"] == 1
    assert client.get("/app/app_events?event=read_story", headers=auth).json()["total"] == 1
    assert client.get("/app/app_events?event=purchase", headers=auth).status_code == 422


# ---- profiles -----------------------------------------------------------------------------------


def test_subscriber_profile_events(client, auth, session, imported):
    user = session.scalar(select(AppUser).where(AppUser.subscriber_id.is_not(None)))
    _send(client, auth, "evt_1", user.app_user_id)
    subscriber_profile = f"s_{user.subscriber_id}"

    app_events = client.get(f"/app/profiles/{subscriber_profile}/app_events", headers=auth).json()
    assert [i["event_id"] for i in app_events["items"]] == ["evt_1"]

    # The u_ id of a linked app user resolves to the same subscriber profile.
    via_user = client.get(f"/app/profiles/u_{user.app_user_id}/app_events", headers=auth).json()
    assert via_user["total"] == 1

    web = client.get(f"/app/profiles/{subscriber_profile}/web_events", headers=auth).json()
    assert all(i["profile_id"] == subscriber_profile for i in web["items"])


def test_profile_filter_on_the_list_endpoints(client, auth, session, imported):
    subscriber_id = session.scalar(select(Subscriber.subscriber_id).where(Subscriber.email == "julia.evans230@gmail.com"))
    _send(client, auth, "evt_1", "u_2b6447a3")

    listed = client.get(f"/app/web_events?profile_id=s_{subscriber_id}", headers=auth).json()
    direct = client.get(f"/app/profiles/s_{subscriber_id}/web_events", headers=auth).json()
    assert listed["total"] == direct["total"]
    assert client.get(f"/app/app_events?profile_id=s_{subscriber_id}", headers=auth).json()["total"] == 1
    assert client.get("/app/app_events?profile_id=s_999999", headers=auth).status_code == 404


def test_id_suggestions(client, auth, imported):
    _send(client, auth, "evt_1", None, device="d_phone_1")

    users = client.get("/app/app_events/suggest?field=user_id&q=u_2b6", headers=auth).json()
    assert "u_2b6447a3" in users and all(u.startswith("u_2b6") for u in users)
    assert client.get("/app/app_events/suggest?field=device_id&q=d_ph", headers=auth).json() == ["d_phone_1"]
    assert client.get("/app/app_events/suggest?field=email", headers=auth).status_code == 422


def test_placeholder_profile_and_unknown_profile(client, auth, imported):
    _send(client, auth, "evt_1", "u_never_seen")

    assert client.get("/app/profiles/u_u_never_seen/app_events", headers=auth).json()["total"] == 1
    assert client.get("/app/profiles/u_u_never_seen/web_events", headers=auth).json()["total"] == 0
    assert client.get("/app/profiles/s_999999/app_events", headers=auth).status_code == 404
    assert client.get("/app/profiles/x_1/app_events", headers=auth).status_code == 404


def test_csv_export_escapes_formula_cells(client, auth):
    # "-" is a valid first character for a device id, and spreadsheet apps would read "-23" as a formula.
    _send(client, auth, "evt_formula", None, device="-23")

    text = client.get("/app/app_events?format=csv", headers=auth).text
    rows = list(csv.DictReader(line for line in text.splitlines() if not line.startswith("#")))
    assert rows[0]["device_id"] == "'-23"
    assert client.get("/app/app_events?format=csv").status_code == 401  # exports contain PII
