import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.api_keys import hash_key
from app.auth.passwords import hash_password
from app.main import app
from app.models import ApiClient, Subscriber, User
from tests.conftest import TEST_PASSWORD

ADMIN = "/app/admin"


@pytest.fixture
def admin_client(settings):
    # The admin cookie is Secure, so talk to it over https like a browser would.
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def make_user(session, username: str, is_admin: bool) -> User:
    user = User(username=username, password_hash=hash_password(TEST_PASSWORD), is_admin=is_admin)
    session.add(user)
    session.commit()
    return user


def sign_in(client, username: str) -> None:
    client.post(f"{ADMIN}/login", data={"username": username, "password": TEST_PASSWORD}, follow_redirects=False)


@pytest.fixture
def admin(admin_client, session):
    make_user(session, "boss", is_admin=True)
    sign_in(admin_client, "boss")
    return admin_client


def test_admin_requires_an_admin_sign_in(admin_client, session):
    make_user(session, "growth", is_admin=False)

    response = admin_client.get(f"{ADMIN}/subscriber/list", follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"].endswith("/app/admin/login")

    sign_in(admin_client, "growth")  # right password, but not an admin
    assert admin_client.get(f"{ADMIN}/subscriber/list", follow_redirects=False).status_code == 302

    make_user(session, "boss", is_admin=True)
    admin_client.post(f"{ADMIN}/login", data={"username": "boss", "password": "wrong"}, follow_redirects=False)
    assert admin_client.get(f"{ADMIN}/subscriber/list", follow_redirects=False).status_code == 302

    sign_in(admin_client, "boss")
    assert admin_client.get(f"{ADMIN}/subscriber/list").status_code == 200


def test_admin_cookie_is_scoped_and_strict(admin_client, session):
    make_user(session, "boss", is_admin=True)
    response = admin_client.post(f"{ADMIN}/login", data={"username": "boss", "password": TEST_PASSWORD}, follow_redirects=False)

    cookie = response.headers["set-cookie"].lower()
    assert "path=/app/admin" in cookie and "samesite=strict" in cookie and "secure" in cookie and "httponly" in cookie


def test_admin_emails_go_through_the_shared_normalization(admin, session):
    form = {"email": "  New.Reader@Example.COM ", "signup_date": "2026-09-01", "status": "1"}
    admin.post(f"{ADMIN}/subscriber/create", data=form)

    assert session.scalar(select(Subscriber.email).where(Subscriber.email.like("new.reader%"))) == "new.reader@example.com"

    response = admin.post(f"{ADMIN}/subscriber/create", data={**form, "email": "not-an-email"})
    assert "not a valid email address" in response.text
    assert session.scalar(select(Subscriber).where(Subscriber.email == "not-an-email")) is None


def test_invalid_segment_definitions_are_refused(admin, session):
    form = {"slug": "broken", "name": "Broken", "group": "0", "definition": '{"match": "all", "filters": [{"field": "nope"}]}', "description": ""}
    response = admin.post(f"{ADMIN}/segment/create", data=form)

    assert response.status_code == 400 or "error" in response.text.lower()
    from app.models import Segment

    assert session.scalar(select(Segment).where(Segment.slug == "broken")) is None


def _shown_key(html: str) -> str:
    match = re.search(r'value="(cdp_[A-Za-z0-9_\-]+)"', html)
    assert match, "the new key should be shown once"
    return match.group(1)


def test_api_key_is_shown_once_stored_hashed_and_works(admin, client, session):
    response = admin.post(f"{ADMIN}/api-client/create", data={"name": "Mobile backend"})
    key = _shown_key(response.text)
    assert response.headers["cache-control"].startswith("no-store")

    stored = session.scalar(select(ApiClient).where(ApiClient.name == "Mobile backend"))
    assert stored.key_hash == hash_key(key) and stored.key_prefix == key[:12]
    assert key not in admin.get(f"{ADMIN}/api-client/details/{stored.api_client_id}").text
    assert client.get("/app/subscribers", headers={"Authorization": f"Bearer {key}"}).status_code == 200


def test_api_key_rotate_and_revoke(admin, client, session):
    key = _shown_key(admin.post(f"{ADMIN}/api-client/create", data={"name": "Partner"}).text)
    old = session.scalar(select(ApiClient).where(ApiClient.key_hash == hash_key(key)))

    replacement = _shown_key(admin.get(f"{ADMIN}/api-client/action/rotate?pks={old.api_client_id}").text)
    assert replacement != key
    session.expire_all()
    assert session.get(ApiClient, old.api_client_id).expires_at is not None  # old key is in its grace period
    for k in (key, replacement):
        assert client.get("/app/subscribers", headers={"Authorization": f"Bearer {k}"}).status_code == 200

    admin.get(f"{ADMIN}/api-client/action/revoke?pks={old.api_client_id}")
    assert client.get("/app/subscribers", headers={"Authorization": f"Bearer {key}"}).status_code == 401
    assert client.get("/app/subscribers", headers={"Authorization": f"Bearer {replacement}"}).status_code == 200


def test_auth_tables_never_show_secrets(admin, session):
    page = admin.get(f"{ADMIN}/user/list").text + admin.get(f"{ADMIN}/user/details/1").text
    assert "$argon2" not in page and "password" not in page.lower()
    assert admin.get(f"{ADMIN}/user/create").status_code in (403, 404)
    assert admin.get(f"{ADMIN}/refresh-token/list").status_code == 404
