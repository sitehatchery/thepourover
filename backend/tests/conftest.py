import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.admin import admin_login_limiter
from app.auth.api_keys import create_api_key
from app.auth.passwords import hash_password
from app.cli import init_db
from app.config import get_settings
from app.db import open_session, reset_engine
from app.main import app
from app.models import User
from app.routers.auth import login_limiter
from app.routers.webhooks import webhook_limiter
from app.webhook.signing import sign

WEBHOOK_SECRET = "whsec_test_secret"
TEST_PASSWORD = "correct horse battery staple"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A fresh, migrated and seeded database in a temp folder for each test, with test secrets."""
    monkeypatch.setenv("CDP_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("CDP_DATABASE_URL", "")
    monkeypatch.setenv("CDP_JWT_SECRET", "test-jwt-secret-that-is-long-enough-for-hs256")
    monkeypatch.setenv("CDP_WEBHOOK_SECRETS", WEBHOOK_SECRET)
    monkeypatch.setenv("CDP_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    reset_engine()
    login_limiter.reset()
    webhook_limiter.reset()
    admin_login_limiter.reset()
    init_db()
    yield get_settings()
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def session(settings):
    with open_session() as s:
        yield s


@pytest.fixture
def client(settings):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def api_key(session) -> str:
    return create_api_key(session, "tests")


@pytest.fixture
def auth(api_key) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture
def user(session) -> User:
    account = User(username="growth", password_hash=hash_password(TEST_PASSWORD))
    session.add(account)
    session.commit()
    return account


@pytest.fixture
def send_webhook(client):
    """POST a signed event to the webhook. Returns the response."""

    def send(event: dict, secret: str = WEBHOOK_SECRET, path: str = "/app/webhooks/app", timestamp: int | None = None):
        body = json.dumps(event).encode()
        headers = {"Content-Type": "application/json", **sign(body, secret, timestamp)}
        return client.post(path, content=body, headers=headers)

    return send


@pytest.fixture
def csv_folder(tmp_path: Path):
    """Write small CSV files for an import. Pass {file name: text}."""

    def write(files: dict[str, str]) -> Path:
        folder = tmp_path / "drop"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            (folder / name).write_text(text.strip() + "\n", encoding="utf-8")
        return folder

    return write
