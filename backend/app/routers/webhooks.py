"""The app events webhook.

Primary path: POST /app/webhooks/app. The brief's path, POST /webhooks/app, is an alias for the same handler.
The App Events page sends through POST /app/app_events/send, which signs on the server and then goes
through exactly the same verification and processing as an external call.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.auth.deps import require_auth
from app.config import get_settings
from app.db import get_session
from app.ratelimit import RateLimiter, client_ip
from app.webhook.events import AppEventIn, EventResult, process_event
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


def handle_signed_request(session: Session, body: bytes, timestamp: str | None, signature: str | None) -> WebhookOut:
    """Verify, validate and store one event. Shared by the external webhook and the in-app sender."""
    settings = get_settings()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large")
    try:
        verify(body, timestamp, signature, settings.webhook_secret_list, settings.webhook_tolerance_seconds)
    except SignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    try:
        payload = AppEventIn.model_validate_json(body)
    except ValidationError as exc:
        errors = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"message": "Invalid event", "errors": errors}) from exc

    result = process_event(session, payload, steps=["Received", "Signature verified", "Payload valid"])
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
    return handle_signed_request(session, body, headers[TIMESTAMP_HEADER], headers[SIGNATURE_HEADER])
