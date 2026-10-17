from datetime import timedelta

import jwt
from sqlalchemy import select

from app.auth.api_keys import rotate_api_key
from app.models import ApiClient
from app.rules import utcnow
from tests.conftest import TEST_PASSWORD


def login(client, password=TEST_PASSWORD, username="growth"):
    return client.post("/app/auth/login", json={"username": username, "password": password})


def test_login_returns_tokens_and_sets_refresh_cookie(client, user):
    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    cookie = response.headers["set-cookie"]
    assert "cdp_refresh=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie

    me = client.get("/app/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json() == {"kind": "user", "id": user.user_id, "name": "growth", "is_admin": False}


def test_wrong_password_and_unknown_user_get_the_same_answer(client, user):
    wrong = login(client, password="nope")
    unknown = login(client, username="nobody")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Incorrect username or password"}


def test_login_is_rate_limited(client, user, settings):
    for _ in range(settings.login_attempts_per_minute):
        login(client, password="nope")
    assert login(client).status_code == 429


def test_protected_endpoint_rejects_missing_bad_and_expired_tokens(client, user, settings):
    assert client.get("/app/auth/me").status_code == 401
    assert client.get("/app/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401

    expired = jwt.encode(
        {"sub": str(user.user_id), "type": "access", "exp": utcnow() - timedelta(minutes=1)}, settings.jwt_secret, "HS256"
    )
    assert client.get("/app/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_refresh_rotates_and_reuse_revokes_the_family(client, user):
    first = login(client).json()["refresh_token"]

    second = client.post("/app/auth/refresh", json={"refresh_token": first})
    assert second.status_code == 200
    second_token = second.json()["refresh_token"]
    assert second_token != first

    # Reusing the first token looks like theft: it fails, and so does the token rotated from it.
    assert client.post("/app/auth/refresh", json={"refresh_token": first}).status_code == 401
    assert client.post("/app/auth/refresh", json={"refresh_token": second_token}).status_code == 401


def test_refresh_works_from_the_cookie(client, user):
    login(client)  # TestClient keeps the cookie
    assert client.post("/app/auth/refresh").status_code == 200


def test_logout_revokes_the_refresh_token(client, user):
    token = login(client).json()["refresh_token"]
    assert client.post("/app/auth/logout", json={"refresh_token": token}).status_code == 204
    assert client.post("/app/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_api_key_rotation_keeps_the_old_key_for_a_grace_period(client, session, api_key):
    client_id = session.scalar(select(ApiClient.api_client_id))
    new_key = rotate_api_key(session, client_id)

    for key in (api_key, new_key):
        assert client.get("/app/auth/me", headers={"Authorization": f"Bearer {key}"}).status_code == 200

    old = session.get(ApiClient, client_id)
    old.expires_at = utcnow() - timedelta(seconds=1)  # grace period over
    session.commit()
    assert client.get("/app/auth/me", headers={"Authorization": f"Bearer {api_key}"}).status_code == 401
    assert client.get("/app/auth/me", headers={"Authorization": f"Bearer {new_key}"}).status_code == 200
