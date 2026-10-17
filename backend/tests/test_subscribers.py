import pytest
from sqlalchemy import select

from app.importer.service import run_import
from app.importer.sources import LocalFolderSource
from app.models import AppUser, Subscriber


@pytest.fixture
def imported(session, settings):
    run_import(session, LocalFolderSource(settings.import_source_dir), settings)


def test_subscribers_require_auth(client):
    assert client.get("/app/subscribers").status_code == 401
    assert client.get("/app/profiles/search?q=gmail").status_code == 401


def test_subscribers_default_listing(client, auth, imported):
    body = client.get("/app/subscribers", headers=auth).json()

    assert body["total"] == 2900 and len(body["items"]) == 40
    first = body["items"][0]
    assert set(first) >= {"profile_id", "email", "signup_date", "status", "acquisition_source", "app_user_id", "web_event_count", "last_seen", "first_utm_source"}
    signups = [i["signup_date"] for i in body["items"]]
    assert signups == sorted(signups, reverse=True)


def test_subscriber_filters(client, auth, imported):
    get = lambda q: client.get(f"/app/subscribers?{q}", headers=auth).json()["total"]

    assert get("status=unsubscribed") == 290
    assert get("acquisition_source=Instagram") == 899
    assert get("segment_id=source_instagram&status=unsubscribed") == get("acquisition_source=Instagram&status=unsubscribed")
    assert get("today=true") == get("signup_from=2026-09-28&signup_to=2026-09-28")
    assert get("email=JULIA.EVANS230") == 1
    assert get("app_user_id=u_2b6447a3") == 1


def test_subscriber_sorting(client, auth, imported):
    items = client.get("/app/subscribers?sort=web_event_count&order=desc", headers=auth).json()["items"]
    counts = [i["web_event_count"] for i in items]
    assert counts == sorted(counts, reverse=True) and counts[0] > 0
    assert client.get("/app/subscribers?sort=password", headers=auth).status_code == 400


def test_search_by_email_user_and_visitor(client, auth, session, imported):
    by_email = client.get("/app/profiles/search?q=julia.evans230", headers=auth).json()
    assert [p["email"] for p in by_email] == ["julia.evans230@gmail.com"]

    by_user = client.get("/app/profiles/search?q=u_2b6447a3", headers=auth).json()
    assert by_user[0]["profile_id"] == by_email[0]["profile_id"]

    by_visitor = client.get("/app/profiles/search?q=v_098d80a408", headers=auth).json()
    assert len(by_visitor) <= 1


def test_profile_detail_for_a_subscriber(client, auth, session, imported):
    user = session.get(AppUser, "u_2b6447a3")
    event = {"event_id": "evt_1", "event": "read_story", "user_id": "u_2b6447a3", "device_id": "d_phone", "timestamp": "2026-09-28T10:00:00Z", "properties": {}}
    client.post("/app/app_events/send", json=event, headers=auth)

    profile = client.get(f"/app/profiles/s_{user.subscriber_id}", headers=auth).json()

    assert profile["newsletter"]["email"] == "julia.evans230@gmail.com"
    assert profile["app_accounts"][0]["app_user_id"] == "u_2b6447a3"
    assert profile["device_ids"] == ["d_phone"]
    assert profile["app_event_count"] == 1
    assert profile["last_seen"].startswith("2026-09-28")
    assert {s["slug"] for s in profile["segments"]} >= {"multi_channel_readers"} or profile["web_event_count"] == 0


def test_profile_detail_for_app_only_and_placeholder(client, auth, session, imported):
    app_only = session.scalar(select(AppUser).where(AppUser.subscriber_id.is_(None)))
    profile = client.get(f"/app/profiles/u_{app_only.app_user_id}", headers=auth).json()
    assert profile["newsletter"] is None and profile["is_subscriber"] is False
    assert any(s["slug"] == "app_users_not_subscribed" for s in profile["segments"])

    event = {"event_id": "evt_p", "event": "app_open", "user_id": "u_mystery", "device_id": "d_x", "timestamp": "2026-09-28T10:00:00Z", "properties": {}}
    client.post("/app/app_events/send", json=event, headers=auth)
    placeholder = client.get("/app/profiles/u_u_mystery", headers=auth).json()
    assert placeholder["is_placeholder"] is True and placeholder["app_event_count"] == 1


def test_linked_app_user_profile_redirects_to_subscriber(client, auth, session, imported):
    user = session.get(AppUser, "u_2b6447a3")
    profile = client.get("/app/profiles/u_u_2b6447a3", headers=auth).json()
    assert profile["profile_id"] == f"s_{user.subscriber_id}"
    assert session.get(Subscriber, user.subscriber_id).email == profile["email"]
