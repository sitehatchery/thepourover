import json
import time
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import AppEvent, AppUser, Subscriber
from app.webhook.signing import sign
from tests.conftest import WEBHOOK_SECRET


def event(event_id: str, user_id: str | None = None, device_id: str = "d_1", ts: str = "2026-09-28T14:00:00Z", kind="app_open"):
    return {
        "event_id": event_id,
        "event": kind,
        "user_id": user_id,
        "device_id": device_id,
        "timestamp": ts,
        "properties": {"story": "supreme-court-ruling-explained"},
    }


def user_of(session, event_id: str) -> str | None:
    session.expire_all()
    return session.get(AppEvent, event_id).app_user_id


# ---- authentication -----------------------------------------------------------------------------


def test_signed_event_is_stored(send_webhook, session):
    response = send_webhook(event("evt_1", "u_new"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "stored"
    assert body["steps"][:3] == ["Received", "Signature verified", "Payload valid"]
    assert session.get(AppEvent, "evt_1").properties == {"story": "supreme-court-ruling-explained"}


def test_brief_path_is_an_alias(send_webhook):
    assert send_webhook(event("evt_1"), path="/webhooks/app").json()["status"] == "stored"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-CDP-Timestamp": str(int(time.time())), "X-CDP-Signature": "sha256=deadbeef"},
        sign(b"different body", WEBHOOK_SECRET),
        sign(json.dumps(event("evt_1")).encode(), "wrong_secret"),
        sign(json.dumps(event("evt_1")).encode(), WEBHOOK_SECRET, timestamp=int(time.time()) - 3600),
    ],
    ids=["missing", "garbage", "other-body", "wrong-secret", "replayed-hour-old"],
)
def test_bad_signatures_are_rejected(client, session, headers):
    body = json.dumps(event("evt_1")).encode()
    response = client.post("/app/webhooks/app", content=body, headers={"Content-Type": "application/json", **headers})

    assert response.status_code == 401
    assert session.get(AppEvent, "evt_1") is None


def test_rotated_secrets_both_verify(client, monkeypatch, settings):
    monkeypatch.setenv("CDP_WEBHOOK_SECRETS", f"whsec_new,{WEBHOOK_SECRET}")
    from app.config import get_settings

    get_settings.cache_clear()
    for i, secret in enumerate(["whsec_new", WEBHOOK_SECRET]):
        body = json.dumps(event(f"evt_{i}")).encode()
        response = client.post("/app/webhooks/app", content=body, headers=sign(body, secret))
        assert response.status_code == 200


# ---- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"event": "purchase"},
        {"event_id": "evt 1; DROP TABLE app_events"},
        {"device_id": ""},
        {"timestamp": "yesterday"},
        {"unexpected": "field"},
        {"properties": {"story": "x" * 300}},
    ],
)
def test_invalid_payloads_are_rejected(send_webhook, session, change):
    response = send_webhook({**event("evt_1"), **change})

    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "Invalid event"
    assert session.scalar(select(func.count()).select_from(AppEvent)) == 0


# ---- the brief's rules --------------------------------------------------------------------------


def test_duplicate_delivery_changes_nothing(send_webhook, session):
    send_webhook(event("evt_1", "u_1"))
    second = send_webhook(event("evt_1", "u_1", ts="2026-09-28T15:00:00Z"))

    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert session.scalar(select(func.count()).select_from(AppEvent)) == 1


def test_unknown_user_gets_a_placeholder_profile(send_webhook, session):
    body = send_webhook(event("evt_1", "u_unknown")).json()

    assert body["placeholder_created"] is True
    assert session.get(AppUser, "u_unknown").is_placeholder is True
    # A second event for the same user reuses the placeholder.
    assert send_webhook(event("evt_2", "u_unknown")).json()["placeholder_created"] is False


def test_known_user_is_resolved_to_their_subscriber(send_webhook, session):
    subscriber = Subscriber(email="ana@example.com", signup_date=date(2026, 9, 1))
    session.add(subscriber)
    session.flush()
    session.add(AppUser(app_user_id="u_ana", email="ana@example.com", subscriber_id=subscriber.subscriber_id))
    session.commit()

    body = send_webhook(event("evt_1", "u_ana")).json()
    assert "User u_ana resolved to a subscriber" in body["steps"]


def test_login_attaches_earlier_anonymous_events(send_webhook, session):
    send_webhook(event("evt_a", None, ts="2026-09-28T10:00:00Z"))
    send_webhook(event("evt_b", None, ts="2026-09-28T10:05:00Z"))
    send_webhook(event("evt_other_device", None, device_id="d_2", ts="2026-09-28T10:06:00Z"))

    login = send_webhook(event("evt_login", "u_1", ts="2026-09-28T10:10:00Z", kind="login")).json()

    assert login["attached_events"] == 2
    assert user_of(session, "evt_a") == user_of(session, "evt_b") == "u_1"
    assert user_of(session, "evt_other_device") is None


def test_late_anonymous_event_attaches_to_the_later_login(send_webhook, session):
    send_webhook(event("evt_login", "u_1", ts="2026-09-28T10:10:00Z", kind="login"))
    late = send_webhook(event("evt_late", None, ts="2026-09-28T10:00:00Z")).json()

    assert late["app_user_id"] == "u_1"
    assert user_of(session, "evt_late") == "u_1"


def test_anonymous_event_after_login_stays_anonymous(send_webhook, session):
    """user_id is present on every event after login, so a later null means the device logged out."""
    send_webhook(event("evt_login", "u_1", ts="2026-09-28T10:00:00Z", kind="login"))
    send_webhook(event("evt_after", None, ts="2026-09-28T11:00:00Z"))

    assert user_of(session, "evt_after") is None


def test_shared_device_events_go_to_the_next_login_only(send_webhook, session):
    send_webhook(event("evt_1", None, ts="2026-09-28T09:00:00Z"))
    send_webhook(event("evt_login_a", "u_a", ts="2026-09-28T09:10:00Z", kind="login"))
    send_webhook(event("evt_2", None, ts="2026-09-28T12:00:00Z"))
    send_webhook(event("evt_login_b", "u_b", ts="2026-09-28T12:10:00Z", kind="login"))

    assert user_of(session, "evt_1") == "u_a"
    assert user_of(session, "evt_2") == "u_b"


# ---- in-app sender ------------------------------------------------------------------------------


def test_in_app_sender_requires_auth_and_uses_the_webhook(client, auth, session):
    assert client.post("/app/app_events/send", json=event("evt_1", "u_1")).status_code == 401

    response = client.post("/app/app_events/send", json=event("evt_1", "u_1"), headers=auth)
    assert response.status_code == 200
    assert "Signature verified" in response.json()["steps"]
    assert session.get(AppEvent, "evt_1") is not None


# ---- call log (live feed) -----------------------------------------------------------------------


def test_feed_logs_stored_duplicate_and_rejected_calls(client, auth, send_webhook):
    send_webhook(event("evt_1", "u_new"))
    send_webhook(event("evt_1", "u_new"))
    send_webhook({**event("evt_2"), "unexpected": "jane@example.com"})
    body = json.dumps(event("evt_3", "u_secret_user")).encode()
    client.post("/app/webhooks/app", content=body, headers=sign(body, "wrong_secret"))

    assert client.get("/app/webhook_calls").status_code == 401
    calls = client.get("/app/webhook_calls", headers=auth).json()

    assert [c["outcome"] for c in calls] == ["rejected", "rejected", "duplicate", "stored"]
    assert [c["http_status"] for c in calls] == [401, 400, 200, 200]
    stored = calls[-1]
    assert stored["event_id"] == "evt_1" and stored["app_user_id"] == "u_new" and stored["channel"] == "webhook"
    assert stored["steps"][0] == "Received" and stored["steps"][-1] == "Stored"


def test_rejected_calls_keep_the_reason_not_the_payload(client, auth, send_webhook):
    send_webhook({**event("evt_2"), "unexpected": "jane@example.com"})
    body = json.dumps(event("evt_3", "u_secret_user")).encode()
    client.post("/app/webhooks/app", content=body, headers=sign(body, "wrong_secret"))

    calls = client.get("/app/webhook_calls", headers=auth).json()
    text = json.dumps(calls)
    for leaked in ("jane@example.com", "unexpected\"", "evt_2", "evt_3", "u_secret_user", "d_1"):
        assert leaked not in text
    assert calls[0]["steps"][-1].startswith("Rejected: ")
    assert calls[1]["steps"][-1] == "Rejected: invalid unexpected field"


def test_feed_polls_for_newer_calls_and_the_app_channel(client, auth, send_webhook):
    send_webhook(event("evt_1"))
    newest = client.get("/app/webhook_calls", headers=auth).json()[0]["webhook_call_id"]
    assert client.get(f"/app/webhook_calls?after={newest}", headers=auth).json() == []

    client.post("/app/app_events/send", json=event("evt_2"), headers=auth)
    newer = client.get(f"/app/webhook_calls?after={newest}", headers=auth).json()
    assert [(c["event_id"], c["channel"]) for c in newer] == [("evt_2", "app")]


def test_call_log_keeps_the_most_recent_calls(session, monkeypatch):
    from app.models import WebhookCall
    from app.webhook import log

    monkeypatch.setattr(log, "KEEP_CALLS", 3)
    for _ in range(5):
        log.record_call(session, "webhook", 401, ["Received", "Rejected: bad"], 1)

    ids = session.scalars(select(WebhookCall.webhook_call_id).order_by(WebhookCall.webhook_call_id)).all()
    assert ids == [3, 4, 5]


# ---- re-importing the CSVs after webhook traffic ------------------------------------------------


def _import(session, settings, folder):
    from app.importer.service import run_import
    from app.importer.sources import LocalFolderSource

    run = run_import(session, LocalFolderSource(folder), settings)
    session.expire_all()
    return run


def _files(app_users: str) -> dict[str, str]:
    return {
        "subscribers.csv": "email,signup_date,status,acquisition_source,last_open_date\nana@example.com,2026-07-01,active,Instagram,2026-09-01",
        "app_users.csv": f"user_id,email,created_at\n{app_users}",
        "web_events.csv": "visitor_id,page,timestamp,utm_source,email\nv_1,/,2026-09-01T10:00:00Z,,",
    }


def test_reimport_keeps_webhook_events_and_links(send_webhook, session, settings):
    _import(session, settings, settings.import_source_dir)
    send_webhook(event("evt_known", "u_2b6447a3"))
    send_webhook(event("evt_new", "u_never_seen", device_id="d_2"))

    _import(session, settings, settings.import_source_dir)

    assert session.get(AppEvent, "evt_known").app_user_id == "u_2b6447a3"
    assert session.get(AppEvent, "evt_new").app_user_id == "u_never_seen"
    known = session.get(AppUser, "u_2b6447a3")
    assert known.subscriber_id is not None and not known.is_placeholder  # relinked to the new subscriber rows
    assert session.get(AppUser, "u_never_seen").is_placeholder  # still not in the file, still kept


def test_import_completes_a_placeholder(send_webhook, session, settings, csv_folder):
    send_webhook(event("evt_1", "u_new"))
    assert session.get(AppUser, "u_new").is_placeholder

    _import(session, settings, csv_folder(_files("u_new,Ana@Example.com,2026-08-01")))

    user = session.get(AppUser, "u_new")
    assert not user.is_placeholder and user.email == "ana@example.com" and user.created_at == date(2026, 8, 1)
    assert session.get(Subscriber, user.subscriber_id).email == "ana@example.com"
    assert session.get(AppEvent, "evt_1").app_user_id == "u_new"


def test_users_dropped_from_the_file_are_kept_only_if_they_have_events(send_webhook, session, settings, csv_folder):
    _import(session, settings, csv_folder(_files("u_active,ana@example.com,2026-08-01\nu_idle,ben@example.com,2026-08-01")))
    send_webhook(event("evt_1", "u_active"))

    _import(session, settings, csv_folder(_files("")))

    assert session.get(AppUser, "u_idle") is None
    kept = session.get(AppUser, "u_active")
    assert kept.is_placeholder and kept.subscriber_id is not None  # ana is still a subscriber, so still linked
    assert session.get(AppEvent, "evt_1").app_user_id == "u_active"


def test_simultaneous_first_events_for_a_new_user_dont_fail(session, monkeypatch):
    from app.webhook.events import EventResult, _resolve_user

    session.add(AppUser(app_user_id="u_race", is_placeholder=True))  # created by the other request...
    session.commit()
    monkeypatch.setattr(session, "get", lambda *a, **k: None)  # ...after this request looked and found nothing

    result = EventResult(status="stored", event_id="evt_1")
    _resolve_user(session, "u_race", result)

    assert not result.placeholder_created and "simultaneous" in result.steps[-1]
    session.commit()  # the outer transaction is still usable
