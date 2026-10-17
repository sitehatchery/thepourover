"""Access tokens (short-lived JWTs) and refresh tokens (opaque, single-use, rotated on every refresh)."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import RefreshToken, User
from app.rules import utcnow

ALGORITHM = "HS256"


class TokenError(Exception):
    pass


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _secret(settings: Settings) -> str:
    if not settings.jwt_secret:
        raise RuntimeError("CDP_JWT_SECRET is not set; refusing to issue or accept tokens")
    return settings.jwt_secret


def create_access_token(user: User, settings: Settings) -> str:
    now = utcnow()
    claims = {
        "sub": str(user.user_id),
        "name": user.username,
        "admin": user.is_admin,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(claims, _secret(settings), algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict:
    try:
        claims = jwt.decode(token, _secret(settings), algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired access token") from exc
    if claims.get("type") != "access":
        raise TokenError("Not an access token")
    return claims


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_tokens(session: Session, user: User, settings: Settings, family_id: str | None = None) -> TokenPair:
    """Create an access token and a new refresh token. A login starts a new token family;
    refreshes continue the family so a stolen, reused token can revoke the whole chain."""
    refresh = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.user_id,
            token_hash=_hash(refresh),
            family_id=family_id or str(uuid.uuid4()),
            issued_at=utcnow(),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )
    session.commit()
    return TokenPair(create_access_token(user, settings), refresh, settings.access_token_minutes * 60)


def rotate_refresh_token(session: Session, refresh: str, settings: Settings) -> TokenPair:
    record = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(refresh)))
    if record is None:
        raise TokenError("Unknown refresh token")
    if record.revoked_at is not None:
        # A revoked token being used again means it leaked: end every session in its family.
        revoke_family(session, record.family_id)
        raise TokenError("Refresh token was already used; please sign in again")
    if record.expires_at <= utcnow():
        raise TokenError("Refresh token expired; please sign in again")

    record.revoked_at = utcnow()
    user = session.get(User, record.user_id)
    return issue_tokens(session, user, settings, family_id=record.family_id)


def revoke_refresh_token(session: Session, refresh: str) -> None:
    record = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(refresh)))
    if record is not None:
        revoke_family(session, record.family_id)


def revoke_family(session: Session, family_id: str) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    session.commit()
