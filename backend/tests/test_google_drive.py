from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.integrations import google
from app.models import GoogleConnection, Subscriber
from app.rules import utcnow

FOLDER = "1teqRUXwm-ONYlw8KvgMBX0NHVflhkzHd"
SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"


class FakeGoogle:
    """Serves Google's token, userinfo and Drive endpoints from memory, and records what it was sent."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.refresh_ok = True
        self.files = {
            "f1": ("subscribers.csv", "text/csv", (SAMPLE / "subscribers.csv").read_bytes()),
            "f2": ("app_users", google.GOOGLE_SHEET, (SAMPLE / "app_users.csv").read_bytes()),  # a Google Sheet
            "f3": ("web_events.csv", "text/csv", (SAMPLE / "web_events.csv").read_bytes()),
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(google.TOKEN_URL):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                if form["code"] != ["good-code"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600, "scope": google.SCOPES})
            if not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})
        if url.startswith(google.USERINFO_URL):
            return httpx.Response(200, json={"email": "jason@example.com"})
        if url.startswith(google.REVOKE_URL):
            return httpx.Response(200)
        path = request.url.path.removeprefix("/drive/v3")
        if path == f"/files/{FOLDER}":
            return httpx.Response(200, json={"name": "Full_Stack_Dev_Assessment_csvs"})
        if path == "/files":
            files = [{"id": k, "name": n, "mimeType": m, "size": str(len(b))} for k, (n, m, b) in self.files.items()]
            return httpx.Response(200, json={"files": files + [{"id": "sub", "name": "old", "mimeType": "application/vnd.google-apps.folder"}]})
        for file_id, (_name, _mime, body) in self.files.items():
            if path in (f"/files/{file_id}", f"/files/{file_id}/export"):
                return httpx.Response(200, content=body)
        return httpx.Response(404)


@pytest.fixture
def fake_google(monkeypatch, settings):
    fake = FakeGoogle()
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT", "client-123.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_SECRET", "secret-xyz")
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(google, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    return fake


def connect(client, auth) -> str:
    url = client.post("/app/integrations/google/start", json={"return_to": "https://cdp.local"}, headers=auth).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return client.get(f"/app/integrations/google/callback?state={state}&code=good-code", follow_redirects=False)


def test_start_builds_a_pkce_consent_url(client, auth, fake_google):
    url = client.post("/app/integrations/google/start", json={"return_to": "https://cdp.local"}, headers=auth).json()["url"]
    query = parse_qs(urlparse(url).query)

    assert url.startswith(google.AUTH_URL)
    assert query["redirect_uri"] == ["http://localhost:8000/app/integrations/google/callback"]
    assert query["code_challenge_method"] == ["S256"] and query["access_type"] == ["offline"]
    assert "drive.readonly" in query["scope"][0]


def test_start_rejects_unknown_return_addresses(client, auth, fake_google):
    response = client.post("/app/integrations/google/start", json={"return_to": "https://evil.example"}, headers=auth)
    assert response.status_code == 400


def test_connect_stores_encrypted_tokens_and_redirects_back(client, auth, session, fake_google):
    response = connect(client, auth)

    assert response.status_code == 303
    assert response.headers["location"] == "https://cdp.local/setup?google=connected"
    conn = session.scalar(select(GoogleConnection))
    assert conn.account_email == "jason@example.com"
    assert "rt-1" not in conn.refresh_token_encrypted and "at-1" not in (conn.access_token_encrypted or "")
    token_request = next(r for r in fake_google.requests if "grant_type=authorization_code" in r.content.decode())
    assert "code_verifier=" in token_request.content.decode()


def test_state_is_single_use(client, auth, fake_google):
    url = client.post("/app/integrations/google/start", json={"return_to": "https://cdp.local"}, headers=auth).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get(f"/app/integrations/google/callback?state={state}&code=good-code", follow_redirects=False)

    replay = client.get(f"/app/integrations/google/callback?state={state}&code=good-code", follow_redirects=False)
    assert "google=error" in replay.headers["location"]
    forged = client.get("/app/integrations/google/callback?state=made-up&code=good-code", follow_redirects=False)
    assert "google=error" in forged.headers["location"]


def test_canceled_consent_returns_to_setup_with_a_message(client, fake_google):
    response = client.get("/app/integrations/google/callback?error=access_denied", follow_redirects=False)
    assert "google=error" in response.headers["location"] and "canceled" in response.headers["location"]


def test_status_lists_the_folder(client, auth, fake_google):
    connect(client, auth)
    status = client.get("/app/integrations/google/status", headers=auth).json()

    assert status["connected"] and status["account_email"] == "jason@example.com"
    assert status["folder_name"] == "Full_Stack_Dev_Assessment_csvs"
    assert [f["name"] for f in status["files"]] == ["subscribers.csv", "app_users", "web_events.csv"]  # sub-folder skipped


def test_import_reads_from_drive_including_a_google_sheet(client, auth, session, fake_google):
    connect(client, auth)
    run = client.post("/app/import", headers=auth).json()  # auto picks Drive once connected

    assert run["status"] == "succeeded" and run["source"] == "google_drive"
    assert run["file_stats"]["app_users"]["entity"] == "app_users"
    assert session.query(Subscriber).count() == 2900
    assert any("/export" in str(r.url) for r in fake_google.requests)


def test_expired_access_token_is_refreshed(client, auth, session, fake_google):
    connect(client, auth)
    conn = session.scalar(select(GoogleConnection))
    conn.access_token_expires_at = utcnow() - timedelta(minutes=1)
    session.commit()

    client.get("/app/integrations/google/status", headers=auth)
    assert any("grant_type=refresh_token" in r.content.decode() for r in fake_google.requests)


def test_revoked_access_shows_a_reconnect_message(client, auth, session, fake_google):
    connect(client, auth)
    conn = session.scalar(select(GoogleConnection))
    conn.access_token_expires_at = utcnow() - timedelta(minutes=1)
    session.commit()
    fake_google.refresh_ok = False

    status = client.get("/app/integrations/google/status", headers=auth).json()
    assert "Reconnect" in status["error"]
    run = client.post("/app/import?source=google_drive", headers=auth).json()
    assert run["status"] == "failed" and "Reconnect" in run["message"]


def test_disconnect_revokes_and_forgets(client, auth, session, fake_google):
    connect(client, auth)
    assert client.post("/app/integrations/google/disconnect", headers=auth).status_code == 204

    assert session.scalar(select(GoogleConnection)) is None
    assert any(str(r.url).startswith(google.REVOKE_URL) for r in fake_google.requests)
    assert client.post("/app/import?source=google_drive", headers=auth).status_code == 400


def test_endpoints_require_auth_except_the_callback(client):
    assert client.get("/app/integrations/google/status").status_code == 401
    assert client.post("/app/integrations/google/start", json={"return_to": "https://cdp.local"}).status_code == 401
    assert client.post("/app/integrations/google/disconnect").status_code == 401
