"""Profiles: one person as the CDP knows them.

profile_id is "s_<subscriber_id>" for a subscriber (with any linked app account and web visits) or
"u_<app_user_id>" for an app user with no subscription, including placeholders created by the webhook.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser, Subscriber


@dataclass
class ProfileRef:
    profile_id: str
    subscriber: Subscriber | None
    app_users: list[AppUser]

    @property
    def app_user_ids(self) -> list[str]:
        return [u.app_user_id for u in self.app_users]

    @property
    def emails(self) -> list[str]:
        if self.subscriber:
            return [self.subscriber.email]
        return [u.email for u in self.app_users if u.email]


def profile_id_for(subscriber_id: int | None, app_user_id: str | None) -> str | None:
    if subscriber_id is not None:
        return f"s_{subscriber_id}"
    if app_user_id is not None:
        return f"u_{app_user_id}"
    return None


def resolve_profile(session: Session, profile_id: str) -> ProfileRef:
    kind, _, key = profile_id.partition("_")
    if kind == "s" and key.isdigit():
        subscriber = session.get(Subscriber, int(key))
        if subscriber is not None:
            users = list(session.scalars(select(AppUser).where(AppUser.subscriber_id == subscriber.subscriber_id)))
            return ProfileRef(profile_id, subscriber, users)
    elif kind == "u" and key:
        user = session.get(AppUser, key)
        if user is not None:
            if user.subscriber_id is not None:
                # This app user belongs to a subscriber; use the subscriber's profile.
                return resolve_profile(session, f"s_{user.subscriber_id}")
            return ProfileRef(profile_id, None, [user])
    raise HTTPException(404, detail="Profile not found")
