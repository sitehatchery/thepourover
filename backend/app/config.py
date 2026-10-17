"""Application settings, loaded from environment variables or backend/.env."""

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="CDP_", extra="ignore")

    # The brief fixes "today" for every time-based rule; read it from here, never hard-code it.
    today: date = date(2026, 9, 28)

    data_dir: Path = REPO_DIR / "var"
    database_url: str = ""
    import_source_dir: Path = REPO_DIR / "data" / "sample"
    import_batch_size: int = 10

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'cdp.sqlite3').as_posix()}"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
