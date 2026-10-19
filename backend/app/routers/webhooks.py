"""The app events webhook.

Primary path: POST /app/webhooks/app. The brief's path, POST /webhooks/app, is an alias for the same handler.
The App Events page sends through POST /app/app_events/send, which signs on the server and then goes
through exactly the same verification and processing as an external call.
"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_auth
from app.config import get_settings
from app.db import get_session
from app.models import WebhookCall
from app.ratelimit import RateLimiter, client_ip
from app.webhook.events import AppEventIn, EventResult, process_event
from app.webhook.log import record_call
from app.webhook.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, SignatureError, sign, verify

MAX_BODY_BYTES = 16 * 1024

router = APIRouter(tags=["webhook"])
webhook_limiter = RateLimiter(get_settings().webhook_requests_per_minute)


class WebhookOut(BaseModel):
    status: str
    event_id: str
    app_user_id: str | None
    attached_events: int
    placeholder_created: bool
    steps: list[str]

    @classmethod
    def of(cls, result: EventResult) -> "WebhookOut":
        return cls(
            status=result.status,
            event_id=result.event_id,
            app_user_id=result.app_user_id,
            attached_events=result.attached_events,
            placeholder_created=result.placeholder_created,
            steps=result.steps,
        )


def handle_signed_request(
    session: Session, body: bytes, timestamp: str | None, signature: str | None, channel: str = "webhook"
) -> WebhookOut:
    """Verify, validate and store one event, and log the call for the live feed.

    Shared by the external webhook and the in-app sender."""
    started = time.monotonic()
    steps = ["Received"]

    def log(http_status: int, payload: AppEventIn | None = None, result: EventResult | None = None) -> None:
        record_call(session, channel, http_status, steps, int((time.monotonic() - started) * 1000), payload, result)

    def reject(http_status: int, step: str, detail: object) -> HTTPException:
        steps.append(step)
        log(http_status)
        return HTTPException(http_status, detail=detail)

    settings = get_settings()
    if len(body) > MAX_BODY_BYTES:
        raise reject(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Rejected: payload too large", "Payload too large")
    try:
        verify(body, timestamp, signature, settings.webhook_secret_list, settings.webhook_tolerance_seconds)
    except SignatureError as exc:
        raise reject(status.HTTP_401_UNAUTHORIZED, f"Rejected: {exc}", str(exc)) from exc
    steps.append("Signature verified")
    try:
        payload = AppEventIn.model_validate_json(body)
    except ValidationError as exc:
        errors = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        # Only known field names go in the log; an unexpected key could be anything the caller sent.
        names = {e["field"].split(".")[0] for e in errors}
        fields = sorted(name if name in AppEventIn.model_fields else "unexpected field" for name in names)
        detail = {"message": "Invalid event", "errors": errors}
        raise reject(status.HTTP_400_BAD_REQUEST, f"Rejected: invalid {', '.join(fields) or 'body'}", detail) from exc
    steps.append("Payload valid")

    result = process_event(session, payload, steps=steps)
    log(status.HTTP_200_OK, payload, result)
    return WebhookOut.of(result)


async def _receive(request: Request, session: Session) -> WebhookOut:
    webhook_limiter.check(client_ip(request))
    body = await request.body()
    return await run_in_threadpool(
        handle_signed_request, session, body, request.headers.get(TIMESTAMP_HEADER), request.headers.get(SIGNATURE_HEADER)
    )


@router.post("/app/webhooks/app", response_model=WebhookOut)
async def app_events_webhook(request: Request, session: Session = Depends(get_session)) -> WebhookOut:
    """Receive one app event. Requires `X-CDP-Timestamp` and `X-CDP-Signature: sha256=<hmac>` headers,
    where the HMAC-SHA256 covers `{timestamp}.{raw body}` with the shared webhook secret."""
    return await _receive(request, session)


@router.post("/webhooks/app", response_model=WebhookOut)
async def app_events_webhook_alias(request: Request, session: Session = Depends(get_session)) -> WebhookOut:
    """Alias of `POST /app/webhooks/app`, at the path given in the assessment brief."""
    return await _receive(request, session)


@router.post("/app/app_events/send", response_model=WebhookOut, dependencies=[Depends(require_auth)])
def send_app_event(payload: AppEventIn, session: Session = Depends(get_session)) -> WebhookOut:
    """Send an event from the App Events page. The server signs it and runs it through the webhook handler."""
    secrets = get_settings().webhook_secret_list
    if not secrets:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook secret is not configured")
    body = json.dumps(payload.model_dump(mode="json"), separators=(",", ":")).encode()
    headers = sign(body, secrets[0])
    return handle_signed_request(session, body, headers[TIMESTAMP_HEADER], headers[SIGNATURE_HEADER], channel="app")


class WebhookCallOut(BaseModel):
    webhook_call_id: int
    received_at: datetime
    channel: str
    outcome: str
    http_status: int
    event_id: str | None
    event: str | None
    app_user_id: str | None
    device_id: str | None
    steps: list[str]
    duration_ms: int

    model_config = {"from_attributes": True}


@router.get("/app/webhook_calls", response_model=list[WebhookCallOut], dependencies=[Depends(require_auth)])
def webhook_calls(
    after: int = Query(0, ge=0, description="Only calls newer than this webhook_call_id (for polling)."),
    limit: int = Query(25, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[WebhookCall]:
    """The live feed: the most recent webhook calls, newest first, with each call's outcome and steps."""
    stmt = select(WebhookCall).where(WebhookCall.webhook_call_id > after)
    return list(session.scalars(stmt.order_by(WebhookCall.webhook_call_id.desc()).limit(limit)))
