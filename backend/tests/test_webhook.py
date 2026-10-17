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
