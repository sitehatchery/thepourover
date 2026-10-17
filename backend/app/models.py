"""SQLAlchemy models: the single definition of every table (used by the API, migrations and admin)."""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

STATUS_ACTIVE = 1
STATUS_UNSUBSCRIBED = 0

SEGMENT_GROUP_SUBSCRIBER = 0
SEGMENT_GROUP_APP_USERS = 1
SEGMENT_GROUP_WEB_EVENTS = 2


class AcquisitionSource(Base):
    __tablename__ = "acquisition_sources"

    acquisition_source_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(24), unique=True)


class SourceAlias(Base):
    """Maps a lowercase source spelling (e.g. 'twitter') to an acquisition source (e.g. 'X')."""

    __tablename__ = "source_aliases"

    alias: Mapped[str] = mapped_column(String(24), primary_key=True)
    acquisition_source_id: Mapped[int] = mapped_column(ForeignKey("acquisition_sources.acquisition_source_id"))


class Subscriber(Base):
    __tablename__ = "subscribers"

    subscriber_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(64), unique=True)
    signup_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=STATUS_ACTIVE, server_default=str(STATUS_ACTIVE))
    acquisition_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("acquisition_sources.acquisition_source_id"), index=True
    )
    last_open_date: Mapped[date | None] = mapped_column(Date, index=True)


class AppUser(Base):
    __tablename__ = "app_users"

    app_user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(64), index=True)
    subscriber_id: Mapped[int | None] = mapped_column(ForeignKey("subscribers.subscriber_id"), index=True)
    created_at: Mapped[date | None] = mapped_column(Date, index=True)
    # Set when a webhook event names a user_id we have never seen; cleared when an import supplies the user.
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class AppEvent(Base):
    __tablename__ = "app_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event: Mapped[str] = mapped_column(String(24), index=True)
    # Null until the device logs in; earlier anonymous events are attached on login.
    app_user_id: Mapped[str | None] = mapped_column(ForeignKey("app_users.app_user_id"), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    properties: Mapped[dict] = mapped_column(JSON, default=dict)


class WebEvent(Base):
    __tablename__ = "web_events"

    web_event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(32), index=True)
    page: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    utm_source: Mapped[str | None] = mapped_column(String(32))
    acquisition_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("acquisition_sources.acquisition_source_id")
    )
    email: Mapped[str | None] = mapped_column(String(64), index=True)
    # True when the email was copied from the same visitor's identified event rather than captured on this row.
    email_backfilled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    subscriber_id: Mapped[int | None] = mapped_column(ForeignKey("subscribers.subscriber_id"), index=True)


class Segment(Base):
    __tablename__ = "segments"

    segment_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    group: Mapped[int] = mapped_column(SmallInteger, default=SEGMENT_GROUP_SUBSCRIBER)
    definition: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class User(Base):
    """People who can sign in to the UI."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class ApiClient(Base):
    """API keys for external callers. Only a SHA-256 hash of each key is stored."""

    __tablename__ = "api_clients"

    api_client_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    refresh_token_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class ImportRun(Base):
    __tablename__ = "import_runs"

    import_run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    # Per-file counts: {file name: {entity, read, loaded, fixed, rejected, duplicates_merged}}
    file_stats: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(Text, default="")
    error_report_path: Mapped[str | None] = mapped_column(String(255))
