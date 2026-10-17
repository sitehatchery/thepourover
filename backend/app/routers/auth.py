from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Principal, require_auth
from app.auth.passwords import verify_password
from app.auth.tokens import TokenError, TokenPair, issue_tokens, revoke_refresh_token, rotate_refresh_token
from app.config import get_settings
from app.db import get_session
from app.models import User
from app.ratelimit import RateLimiter, client_ip

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "cdp_refresh"
login_limiter = RateLimiter(get_settings().login_attempts_per_minute)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    # Also set as an httpOnly cookie for the browser; returned here for API clients and scripts.
    refresh_token: str


def _respond(response: Response, pair: TokenPair) -> TokenOut:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        pair.refresh_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/app/auth",
    )
    return TokenOut(access_token=pair.access_token, expires_in=pair.expires_in, refresh_token=pair.refresh_token)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)) -> TokenOut:
    """Check a username and password; return a short-lived access token and a refresh token."""
    login_limiter.check(client_ip(request))
    user = session.scalar(select(User).where(User.username == body.username))
    if not verify_password(body.password, user.password_hash if user else None):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    return _respond(response, issue_tokens(session, user, get_settings()))


@router.post("/refresh", response_model=TokenOut)
def refresh(
    response: Response,
    body: RefreshIn | None = None,
    cdp_refresh: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
) -> TokenOut:
    """Swap a refresh token for a new access token and a new refresh token. Each refresh token works once."""
    token = (body.refresh_token if body else None) or cdp_refresh
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    try:
        pair = rotate_refresh_token(session, token, get_settings())
    except TokenError as exc:
        response.delete_cookie(REFRESH_COOKIE, path="/app/auth")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _respond(response, pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    body: RefreshIn | None = None,
    cdp_refresh: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
) -> Response:
    """End the session: the refresh token (and every token rotated from it) stops working."""
    token = (body.refresh_token if body else None) or cdp_refresh
    if token:
        revoke_refresh_token(session, token)
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(REFRESH_COOKIE, path="/app/auth")
    return response


@router.get("/me")
def me(principal: Principal = Depends(require_auth)) -> dict:
    return {"kind": principal.kind, "id": principal.id, "name": principal.name, "is_admin": principal.is_admin}
