from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.api_keys import create_api_key
from app.cli import init_db
from app.config import get_settings
from app.db import open_session, reset_engine
from app.main import app


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A fresh, migrated and seeded database in a temp folder for each test."""
    monkeypatch.setenv("CDP_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("CDP_DATABASE_URL", "")
    get_settings.cache_clear()
    reset_engine()
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
def csv_folder(tmp_path: Path):
    """Write small CSV files for an import. Pass {file name: text}."""

    def write(files: dict[str, str]) -> Path:
        folder = tmp_path / "drop"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            (folder / name).write_text(text.strip() + "\n", encoding="utf-8")
        return folder

    return write
