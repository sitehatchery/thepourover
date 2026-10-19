"""API keys for external callers. Keys are random, shown once, and stored only as SHA-256 hashes."""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiClient
from app.rules import utcnow

KEY_PREFIX = "cdp_"
ROTATION_GRACE = timedelta(hours=24)


def hash_key(key: str) -> str:
    # Keys carry 256 bits of randomness, so a fast hash is safe here (no password stretching needed).
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def create_api_key(session: Session, name: str) -> str:
    """Create a key and return it. This is the only time the plain key is available."""
    key = new_key()
    session.add(ApiClient(name=name, key_prefix=key[:12], key_hash=hash_key(key)))
    session.commit()
    return key


def rotate_api_key(session: Session, api_client_id: int) -> str:
    """Issue a replacement key. The old key keeps working for ROTATION_GRACE so callers can switch over."""
    old = session.get(ApiClient, api_client_id)
    if old is None or old.revoked_at is not None:
        raise LookupError("No active API key with that id")
    grace_end = utcnow() + ROTATION_GRACE
    old.expires_at = min(old.expires_at, grace_end) if old.expires_at else grace_end
    session.commit()
    return create_api_key(session, old.name)


def revoke_api_key(session: Session, api_client_id: int) -> None:
    client = session.get(ApiClient, api_client_id)
    if client is None:
        raise LookupError("No API key with that id")
    client.revoked_at = client.revoked_at or utcnow()
    session.commit()


def find_active_client(session: Session, key: str) -> ApiClient | None:
    client = session.scalar(select(ApiClient).where(ApiClient.key_hash == hash_key(key)))
    if client is None or client.revoked_at is not None:
        return None
    if client.expires_at is not None and client.expires_at <= utcnow():
        return None
    return client
