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

    # Auth. Secrets have no defaults: the app refuses to issue tokens or accept webhooks without them.
    jwt_secret: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = True
    login_attempts_per_minute: int = 10

    # Webhook signing. Comma-separated so a secret can be rotated: the first signs, all verify.
    webhook_secrets: str = ""
    webhook_tolerance_seconds: int = 300
    webhook_requests_per_minute: int = 600

    @property
    def webhook_secret_list(self) -> list[str]:
        return [s.strip() for s in self.webhook_secrets.split(",") if s.strip()]

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'cdp.sqlite3').as_posix()}"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
