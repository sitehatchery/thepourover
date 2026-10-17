"""API keys for external callers. Keys are random, shown once, and stored only as SHA-256 hashes."""

import hashlib
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ApiClient
from app.rules import utcnow

KEY_PREFIX = "cdp_"
_bearer = HTTPBearer(auto_error=False)


def hash_key(key: str) -> str:
    # Keys carry 256 bits of randomness, so a fast hash is safe here (no password stretching needed).
    return hashlib.sha256(key.encode()).hexdigest()


def create_api_key(session: Session, name: str) -> str:
    """Create a key and return it. This is the only time the plain key is available."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    session.add(ApiClient(name=name, key_prefix=key[:12], key_hash=hash_key(key)))
    session.commit()
    return key


def find_active_client(session: Session, key: str) -> ApiClient | None:
    client = session.scalar(select(ApiClient).where(ApiClient.key_hash == hash_key(key)))
    if client is None or client.revoked_at is not None:
        return None
    if client.expires_at is not None and client.expires_at <= utcnow():
        return None
    return client


def require_api_client(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> ApiClient:
    """FastAPI dependency: the request must carry `Authorization: Bearer <api key>`."""
    client = find_active_client(session, credentials.credentials) if credentials else None
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    client.last_used_at = utcnow()
    session.commit()
    return client
