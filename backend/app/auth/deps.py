"""Request authentication: every protected endpoint accepts a UI access token or an API key."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.api_keys import KEY_PREFIX, find_active_client
from app.auth.tokens import TokenError, decode_access_token
from app.config import get_settings
from app.db import get_session
from app.rules import utcnow

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    kind: str  # "user" or "api_client"
    id: int
    name: str
    is_admin: bool = False


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> Principal:
    if credentials is None:
        raise _unauthorized("Sign in or send an API key")
    token = credentials.credentials

    if token.startswith(KEY_PREFIX):
        client = find_active_client(session, token)
        if client is None:
            raise _unauthorized("Invalid, expired or revoked API key")
        client.last_used_at = utcnow()
        session.commit()
        return Principal("api_client", client.api_client_id, client.name)

    try:
        claims = decode_access_token(token, get_settings())
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc
    return Principal("user", int(claims["sub"]), claims.get("name", ""), bool(claims.get("admin")))
