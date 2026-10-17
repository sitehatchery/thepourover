"""The webhook call log behind the live feed on the App Events page.

Every call is recorded with its outcome and the steps it went through. Rejected calls keep only the reason:
their payload is never stored, because it failed verification or validation and can't be trusted.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import WebhookCall
from app.rules import utcnow
from app.webhook.events import AppEventIn, EventResult

KEEP_CALLS = 500


def record_call(
    session: Session,
    channel: str,
    http_status: int,
    steps: list[str],
    duration_ms: int,
    payload: AppEventIn | None = None,
    result: EventResult | None = None,
) -> None:
    call = WebhookCall(
        received_at=utcnow(),
        channel=channel,
        outcome=result.status if result else "rejected",
        http_status=http_status,
        steps=list(steps),
        duration_ms=duration_ms,
    )
    if payload is not None:
        call.event_id = payload.event_id
        call.event = payload.event
        call.device_id = payload.device_id
        call.app_user_id = (result.app_user_id if result else None) or payload.user_id
    session.add(call)
    session.flush()
    _prune(session)
    session.commit()


def _prune(session: Session) -> None:
    cutoff = session.scalar(
        select(WebhookCall.webhook_call_id).order_by(WebhookCall.webhook_call_id.desc()).offset(KEEP_CALLS).limit(1)
    )
    if cutoff is not None:
        session.execute(delete(WebhookCall).where(WebhookCall.webhook_call_id <= cutoff))
