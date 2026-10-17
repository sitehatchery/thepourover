"""The admin console at /app/admin (SQLAdmin), built on the same SQLAlchemy models as the API.

- Only users with is_admin can sign in. The session cookie is scoped to /app/admin, SameSite=Strict, and
  expires after ADMIN_SESSION_HOURS; every request re-checks that the user still exists and is an admin.
- Emails typed into the admin go through rules.normalize_email, like every other way in.
- Imported subscribers, app users, segments and sources can be added and corrected. Events are facts from
  the CSVs and the webhook, so they can be viewed and deleted but not edited.
- API keys are created, rotated and revoked here. A new key is shown once and only its hash is stored.
  The users and refresh-token tables are read-only or hidden; passwords and tokens never appear.
"""

import hashlib
import hmac
import logging
import time
from typing import Any

from fastapi import FastAPI
from sqladmin import Admin, ModelView, action
from sqladmin.audit import AuditBackend, AuditEntry
from sqladmin.authentication import AuthenticationBackend, get_current_user_id
from sqladmin.filters import AllUniqueStringValuesFilter, BooleanFilter, StaticValuesFilter
from sqladmin.secret import Secret
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.auth.api_keys import KEY_PREFIX, hash_key, new_key, revoke_api_key, rotate_api_key
from app.auth.passwords import verify_password
from app.config import get_settings
from app.db import get_engine, open_session
from app.models import (
    AcquisitionSource,
    ApiClient,
    AppEvent,
    AppUser,
    ImportRun,
    Segment,
    SourceAlias,
    Subscriber,
    User,
    WebEvent,
    WebhookCall,
)
from app.ratelimit import RateLimiter, client_ip
from app.rules import normalize_email, utcnow
from app.segments.engine import SegmentDefinition

BASE_URL = "/app/admin"
ADMIN_SESSION_HOURS = 8
PAGE_SIZE = 50

log = logging.getLogger("cdp.admin")
admin_login_limiter = RateLimiter(get_settings().login_attempts_per_minute)


# ---- sign-in -------------------------------------------------------------------------------------


def _session_secret() -> str:
    # Derived from the JWT secret so there's no extra secret to manage, but distinct from it.
    return hmac.new(get_settings().jwt_secret.encode(), b"cdp-admin-session", hashlib.sha256).hexdigest()


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        admin_login_limiter.check(client_ip(request))
        form = await request.form()
        username, password = str(form.get("username", "")), str(form.get("password", ""))
        with open_session() as session:
            user = session.query(User).filter_by(username=username).one_or_none()
            # Verify even for unknown users so response time doesn't reveal which usernames exist.
            valid = verify_password(password, user.password_hash if user else None)
            if not (valid and user and user.is_admin):
                return False
            request.session.clear()
            request.session.update({"user_id": user.user_id, "signed_in_at": int(time.time())})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        user_id = request.session.get("user_id")
        signed_in_at = request.session.get("signed_in_at", 0)
        if not user_id or time.time() - signed_in_at > ADMIN_SESSION_HOURS * 3600:
            request.session.clear()
            return False
        with open_session() as session:
            user = session.get(User, user_id)
            return bool(user and user.is_admin)


class AdminAuditLog(AuditBackend):
    """Logs who changed what, by id. Field values are left out: they can contain emails."""

    async def log(self, entry: AuditEntry, request: Request) -> None:
        log.info("admin %s %s pk=%s by user %s", entry.action, entry.identity, entry.pk, get_current_user_id(request))


class _CurrentEngineSessions:
    """A session factory that follows app.db's engine, so tests that swap the database also swap the admin's."""

    class_ = Session

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    def configure(self, **options: Any) -> None:
        self.options = {k: v for k, v in options.items() if k != "autocommit"}

    def __call__(self, **options: Any) -> Session:
        return Session(get_engine(), **{**self.options, **options})


# ---- views ---------------------------------------------------------------------------------------


def _normalize_email_field(data: dict, required: bool) -> None:
    raw = data.get("email")
    if not raw and not required:
        data["email"] = None
        return
    email = normalize_email(raw)
    if email is None:
        raise ValueError(f"'{raw}' is not a valid email address")
    data["email"] = email


class SubscriberAdmin(ModelView, model=Subscriber):
    name_plural = "Subscribers"
    icon = "fa-solid fa-envelope"
    category = "Data"
    page_size = PAGE_SIZE
    column_list = [
        Subscriber.subscriber_id,
        Subscriber.email,
        Subscriber.signup_date,
        Subscriber.status,
        Subscriber.acquisition_source_id,
        Subscriber.last_open_date,
    ]
    column_labels = {Subscriber.acquisition_source_id: "Acquisition source id"}
    column_formatters = {Subscriber.status: lambda m, a: "active" if m.status == 1 else "unsubscribed"}
    column_searchable_list = [Subscriber.email]
    column_sortable_list = [Subscriber.subscriber_id, Subscriber.email, Subscriber.signup_date, Subscriber.last_open_date]
    column_default_sort = [(Subscriber.signup_date, True)]
    column_filters = [StaticValuesFilter(Subscriber.status, [("1", "Active"), ("0", "Unsubscribed")])]
    form_args = {"status": {"description": "1 = active, 0 = unsubscribed"}}

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        _normalize_email_field(data, required=True)


class AppUserAdmin(ModelView, model=AppUser):
    name = "App user"
    name_plural = "App users"
    icon = "fa-solid fa-mobile-screen"
    category = "Data"
    page_size = PAGE_SIZE
    column_list = [AppUser.app_user_id, AppUser.email, AppUser.subscriber_id, AppUser.created_at, AppUser.is_placeholder]
    column_labels = {AppUser.is_placeholder: "Placeholder (from webhook)"}
    column_searchable_list = [AppUser.app_user_id, AppUser.email]
    column_sortable_list = [AppUser.app_user_id, AppUser.created_at]
    column_filters = [BooleanFilter(AppUser.is_placeholder)]

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        _normalize_email_field(data, required=False)


class AppEventAdmin(ModelView, model=AppEvent):
    name = "App event"
    name_plural = "App events"
    icon = "fa-solid fa-bolt"
    category = "Data"
    page_size = PAGE_SIZE
    can_create = False
    can_edit = False
    column_list = [AppEvent.event_id, AppEvent.event, AppEvent.app_user_id, AppEvent.device_id, AppEvent.timestamp, AppEvent.received_at]
    column_searchable_list = [AppEvent.event_id, AppEvent.app_user_id, AppEvent.device_id]
    column_sortable_list = [AppEvent.timestamp, AppEvent.received_at, AppEvent.event]
    column_default_sort = [(AppEvent.timestamp, True)]
    column_filters = [AllUniqueStringValuesFilter(AppEvent.event)]


class WebEventAdmin(ModelView, model=WebEvent):
    name = "Web event"
    name_plural = "Web events"
    icon = "fa-solid fa-globe"
    category = "Data"
    page_size = PAGE_SIZE
    can_create = False
    can_edit = False
    column_list = [
        WebEvent.web_event_id,
        WebEvent.visitor_id,
        WebEvent.page,
        WebEvent.timestamp,
        WebEvent.utm_source,
        WebEvent.email,
        WebEvent.email_backfilled,
        WebEvent.subscriber_id,
    ]
    column_searchable_list = [WebEvent.visitor_id, WebEvent.email, WebEvent.page]
    column_sortable_list = [WebEvent.timestamp, WebEvent.page, WebEvent.visitor_id]
    column_default_sort = [(WebEvent.timestamp, True)]
    column_filters = [AllUniqueStringValuesFilter(WebEvent.utm_source), BooleanFilter(WebEvent.email_backfilled)]


class SegmentAdmin(ModelView, model=Segment):
    name_plural = "Segments"
    icon = "fa-solid fa-layer-group"
    category = "Data"
    column_list = [Segment.segment_id, Segment.slug, Segment.name, Segment.group, Segment.updated_at]
    column_formatters = {Segment.group: lambda m, a: ["Subscribers", "App users", "Web events"][m.group]}
    column_searchable_list = [Segment.name, Segment.slug]
    column_sortable_list = [Segment.name, Segment.updated_at]
    form_excluded_columns = [Segment.created_at, Segment.updated_at]
    form_args = {"group": {"description": "0 = subscribers, 1 = app users, 2 = web events"}}

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        # The same validation the segment builder runs, so the admin can't save a segment that won't compile.
        SegmentDefinition.model_validate(data.get("definition") or {})


class AcquisitionSourceAdmin(ModelView, model=AcquisitionSource):
    name = "Acquisition source"
    name_plural = "Acquisition sources"
    icon = "fa-solid fa-bullhorn"
    category = "Reference"
    column_list = [AcquisitionSource.acquisition_source_id, AcquisitionSource.source]


class SourceAliasAdmin(ModelView, model=SourceAlias):
    name = "Source alias"
    name_plural = "Source aliases"
    icon = "fa-solid fa-right-left"
    category = "Reference"
    column_list = [SourceAlias.alias, SourceAlias.acquisition_source_id]
    column_searchable_list = [SourceAlias.alias]

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        data["alias"] = (data.get("alias") or "").strip().lower()  # the importer looks aliases up in lowercase


class ImportRunAdmin(ModelView, model=ImportRun):
    name = "Import run"
    name_plural = "Import runs"
    icon = "fa-solid fa-file-import"
    category = "Activity"
    can_create = can_edit = can_delete = False
    column_list = [ImportRun.import_run_id, ImportRun.started_at, ImportRun.finished_at, ImportRun.source, ImportRun.status]
    column_details_exclude_list = [ImportRun.error_report_path]
    column_default_sort = [(ImportRun.import_run_id, True)]


class WebhookCallAdmin(ModelView, model=WebhookCall):
    name = "Webhook call"
    name_plural = "Webhook calls"
    icon = "fa-solid fa-satellite-dish"
    category = "Activity"
    page_size = PAGE_SIZE
    can_create = can_edit = can_delete = False
    column_list = [
        WebhookCall.webhook_call_id,
        WebhookCall.received_at,
        WebhookCall.channel,
        WebhookCall.outcome,
        WebhookCall.http_status,
        WebhookCall.event_id,
        WebhookCall.duration_ms,
    ]
    column_default_sort = [(WebhookCall.webhook_call_id, True)]
    column_filters = [AllUniqueStringValuesFilter(WebhookCall.outcome)]


class UserAdmin(ModelView, model=User):
    name = "Sign-in user"
    name_plural = "Sign-in users"
    icon = "fa-solid fa-user-shield"
    category = "Access"
    can_create = can_edit = can_delete = False  # managed with `python -m app.cli create-user`
    column_list = [User.user_id, User.username, User.is_admin, User.created_at]
    column_details_list = [User.user_id, User.username, User.is_admin, User.created_at]


def _key_status(client: ApiClient) -> str:
    if client.revoked_at:
        return "revoked"
    if client.expires_at and client.expires_at <= utcnow():
        return "expired"
    if client.expires_at:
        return "rotating (old key, still valid until it expires)"
    return "active"


class ApiClientAdmin(ModelView, model=ApiClient):
    name = "API key"
    name_plural = "API keys"
    icon = "fa-solid fa-key"
    category = "Access"
    can_edit = False
    can_delete = False  # revoke instead, so there's a record of the key
    form_columns = [ApiClient.name]
    form_args = {"name": {"description": "Who or what will use this key, e.g. 'Mobile app backend'."}}
    column_list = [
        ApiClient.api_client_id,
        ApiClient.name,
        ApiClient.key_prefix,
        "status",
        ApiClient.created_at,
        ApiClient.expires_at,
        ApiClient.last_used_at,
    ]
    column_details_list = [*column_list[:4], ApiClient.created_at, ApiClient.expires_at, ApiClient.revoked_at, ApiClient.last_used_at]
    column_labels = {ApiClient.key_prefix: "Key starts with"}
    column_formatters = {"status": lambda m, a: _key_status(m)}
    column_formatters_detail = column_formatters
    column_default_sort = [(ApiClient.api_client_id, True)]

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        key = new_key()
        data["key_prefix"], data["key_hash"] = key[:12], hash_key(key)
        request.state.new_api_key = key

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        Secret.reveal_once(request, request.state.new_api_key, title="New API key", label=_KEY_LABEL)

    @action("rotate", "Rotate", "Issue a replacement key? The old key keeps working for 24 hours.", add_in_list=False)
    async def rotate(self, request: Request) -> Response:
        pk = request.query_params.get("pks", "").split(",")[0]
        with open_session() as session:
            try:
                key = rotate_api_key(session, int(pk))
            except (LookupError, ValueError):
                return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)
            new_client = session.query(ApiClient).filter_by(key_hash=hash_key(key)).one()
        Secret.reveal_once(request, key, title="Replacement API key", label=_KEY_LABEL)
        context = {
            "model_view": self,
            "model": new_client,
            "title": self.name,
            "secret_next_url": str(request.url_for("admin:details", identity=self.identity, pk=new_client.api_client_id)),
        }
        response = await self.templates.TemplateResponse(request, self.details_template, context)
        Secret.apply_no_store_headers(response)
        return response

    @action("revoke", "Revoke", "Revoke the selected keys? Callers using them are refused immediately.")
    async def revoke(self, request: Request) -> Response:
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]
        with open_session() as session:
            for pk in pks:
                try:
                    revoke_api_key(session, int(pk))
                except (LookupError, ValueError):
                    continue
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)


_KEY_LABEL = f"Copy it now: it won't be shown again. Send it as `Authorization: Bearer {KEY_PREFIX}…`."


VIEWS = [
    SubscriberAdmin,
    AppUserAdmin,
    AppEventAdmin,
    WebEventAdmin,
    SegmentAdmin,
    AcquisitionSourceAdmin,
    SourceAliasAdmin,
    ImportRunAdmin,
    WebhookCallAdmin,
    ApiClientAdmin,
    UserAdmin,
]


def mount_admin(app: FastAPI) -> Admin:
    settings = get_settings()
    auth = AdminAuth(
        secret_key=_session_secret(),
        session_cookie="cdp_admin",
        path=BASE_URL,
        max_age=ADMIN_SESSION_HOURS * 3600,
        same_site="strict",
        https_only=settings.cookie_secure,
    )
    admin = Admin(
        app,
        session_maker=_CurrentEngineSessions(),  # type: ignore[arg-type]
        base_url=BASE_URL,
        title="Mini CDP admin",
        logo_url="/tpo-logo.png",
        favicon_url="/tpo-logo.png",
        authentication_backend=auth,
        audit_backend=AdminAuditLog(),
    )
    for view in VIEWS:
        admin.add_view(view)
    return admin
