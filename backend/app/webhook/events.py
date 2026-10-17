"""Taking in one app event: validation, duplicate handling, unknown users and anonymous-to-login stitching.

Stitching rule: an anonymous event (user_id null) belongs to the *next* identified event from the same
device. So when an identified event arrives, anonymous events from that device between the previous
identified event and this one are attached to its user; and when an anonymous event arrives late, it
takes the user of the device's next identified event, if there is one. Arrival order doesn't matter.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AppEvent, AppUser
from app.rules import utcnow

ID_PATTERN = r"^[A-Za-z0-9_\-]+$"
MAX_PROPERTIES = 20


class AppEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    event: Literal["app_open", "read_story", "link_click", "login"]
    user_id: str | None = Field(default=None, min_length=1, max_length=32, pattern=ID_PATTERN)
    device_id: str = Field(min_length=1, max_length=64, pattern=ID_PATTERN)
    timestamp: datetime
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("properties")
    @classmethod
    def _limit_properties(cls, value: dict) -> dict:
        if len(value) > MAX_PROPERTIES:
            raise ValueError(f"at most {MAX_PROPERTIES} properties")
        for key, item in value.items():
            if not key or len(key) > 48:
                raise ValueError("property names must be 1-48 characters")
            if isinstance(item, str) and len(item) > 256:
                raise ValueError(f"property '{key}' is longer than 256 characters")
        return value

    @property
    def timestamp_utc(self) -> datetime:
        if self.timestamp.tzinfo is None:
            return self.timestamp
        return self.timestamp.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class EventResult:
    status: str  # "stored" or "duplicate"
    event_id: str
    app_user_id: str | None = None
    steps: list[str] = field(default_factory=list)
    attached_events: int = 0
    placeholder_created: bool = False


def process_event(session: Session, payload: AppEventIn, steps: list[str]) -> EventResult:
    result = EventResult(status="stored", event_id=payload.event_id, steps=steps)

    if session.get(AppEvent, payload.event_id) is not None:
        return _duplicate(result)

    timestamp = payload.timestamp_utc
    user_id = payload.user_id
    if user_id:
        _resolve_user(session, user_id, result)
    else:
        user_id = _user_from_later_login(session, payload.device_id, timestamp)
        if user_id:
            result.steps.append(f"Arrived late: attached to {user_id}, who logged in on this device afterwards")
        else:
            result.steps.append("Anonymous event stored; it will attach to the user when this device logs in")

    session.add(
        AppEvent(
            event_id=payload.event_id,
            event=payload.event,
            app_user_id=user_id,
            device_id=payload.device_id,
            timestamp=timestamp,
            received_at=utcnow(),
            properties=payload.properties,
        )
    )
    try:
        session.flush()
    except IntegrityError:  # the same event delivered twice at the same moment
        session.rollback()
        return _duplicate(EventResult(status="stored", event_id=payload.event_id, steps=steps))

    if payload.user_id:
        result.attached_events = _attach_earlier_anonymous(session, payload.device_id, timestamp, payload.user_id)
        if result.attached_events:
            noun = "event" if result.attached_events == 1 else "events"
            result.steps.append(f"{result.attached_events} earlier anonymous {noun} from this device attached")

    session.commit()
    result.app_user_id = user_id
    result.steps.append("Stored")
    return result


def _duplicate(result: EventResult) -> EventResult:
    result.status = "duplicate"
    result.steps.append("Duplicate event_id: already stored, nothing changed")
    return result


def _resolve_user(session: Session, user_id: str, result: EventResult) -> None:
    user = session.get(AppUser, user_id)
    if user is None:
        # Never drop an unknown user: create a placeholder profile that a later import can complete.
        session.add(AppUser(app_user_id=user_id, is_placeholder=True))
        session.flush()
        result.placeholder_created = True
        result.steps.append(f"Unknown user {user_id}: placeholder profile created")
    elif user.subscriber_id is not None:
        result.steps.append(f"User {user_id} resolved to a subscriber")
    else:
        result.steps.append(f"User {user_id} found (not linked to a subscriber)")


def _user_from_later_login(session: Session, device_id: str, timestamp: datetime) -> str | None:
    """The user of the device's next identified event at or after `timestamp`."""
    return session.scalar(
        select(AppEvent.app_user_id)
        .where(AppEvent.device_id == device_id, AppEvent.app_user_id.is_not(None), AppEvent.timestamp >= timestamp)
        .order_by(AppEvent.timestamp)
        .limit(1)
    )


def _attach_earlier_anonymous(session: Session, device_id: str, timestamp: datetime, user_id: str) -> int:
    """Attach anonymous events from this device since its previous identified event."""
    previous_identified = session.scalar(
        select(AppEvent.timestamp)
        .where(AppEvent.device_id == device_id, AppEvent.app_user_id.is_not(None), AppEvent.timestamp < timestamp)
        .order_by(AppEvent.timestamp.desc())
        .limit(1)
    )
    conditions = [AppEvent.device_id == device_id, AppEvent.app_user_id.is_(None), AppEvent.timestamp <= timestamp]
    if previous_identified is not None:
        conditions.append(AppEvent.timestamp > previous_identified)
    return session.execute(update(AppEvent).where(*conditions).values(app_user_id=user_id)).rowcount
