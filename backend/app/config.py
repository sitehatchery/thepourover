"""Application settings, loaded from environment variables or backend/.env."""

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
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

    # AI assistant. The key is read from CDP_OPENAI_API_KEY or the usual OPENAI_API_KEY.
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("CDP_OPENAI_API_KEY", "OPENAI_API_KEY"))
    openai_model: str = "gpt-5-mini"
    # For reasoning models: low keeps answers quick; the tools do the heavy lifting. Empty = model default.
    openai_reasoning_effort: str = "low"
    assistant_max_tool_rounds: int = 6

    # Google Drive import. The OAuth client is a "Web application" client; Google only accepts
    # localhost (or a real public domain) as a redirect, so local dev redirects to the API directly.
    google_client_id: str = Field(default="", validation_alias=AliasChoices("CDP_GOOGLE_CLIENT_ID", "GOOGLE_OAUTH_CLIENT"))
    google_client_secret: str = Field(default="", validation_alias=AliasChoices("CDP_GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_SECRET"))
    google_redirect_uri: str = "http://localhost:8000/app/integrations/google/callback"
    google_drive_folder_id: str = "1teqRUXwm-ONYlw8KvgMBX0NHVflhkzHd"
    # Where the browser may be sent back to after connecting (comma-separated origins).
    app_origins: str = "https://cdp.local,http://localhost:5173"

    # Connect to other services over IPv4 (see app/net.py for why).
    outbound_ipv4_only: bool = True

    @property
    def app_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.app_origins.split(",") if o.strip()]

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
