"""Google Drive connection: OAuth 2.0 (authorization code + PKCE), encrypted token storage, Drive calls.

Flow: a signed-in user calls start() and is sent to Google; Google redirects the browser to the API's
callback, which exchanges the code for tokens, stores them encrypted, and sends the browser back to the
Setup page. Tokens never reach the browser.
"""

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import GoogleConnection
from app.net import outbound_client
from app.rules import utcnow

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
DRIVE_URL = "https://www.googleapis.com/drive/v3"

# Read-only Drive access (to read files shared with the account), plus the email to show who's connected.
SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
STATE_TTL_SECONDS = 600


class GoogleError(Exception):
    pass


def http_client() -> httpx.Client:
    """Factory so tests can swap in a mock transport."""
    return outbound_client()


# ---- token encryption -------------------------------------------------------------------------------


def _fernet(settings: Settings) -> Fernet:
    if not settings.jwt_secret:
        raise GoogleError("CDP_JWT_SECRET must be set to store Google tokens")
    # A separate key derived from the app secret, so the stored tokens are useless without it.
    key = hashlib.sha256(b"cdp-google-token-key:" + settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(settings: Settings, value: str) -> str:
    return _fernet(settings).encrypt(value.encode()).decode()


def _decrypt(settings: Settings, value: str) -> str:
    try:
        return _fernet(settings).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise GoogleError("Stored Google tokens can't be read (was CDP_JWT_SECRET changed?). Reconnect Google Drive.") from exc


# ---- OAuth ------------------------------------------------------------------------------------------


@dataclass
class _Pending:
    verifier: str
    user_id: int | None
    return_to: str
    created: float


_pending: dict[str, _Pending] = {}
_pending_lock = threading.Lock()


def configured(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def start(settings: Settings, user_id: int | None, return_to: str) -> str:
    """URL to send the browser to. The state is single-use and tied to this request."""
    if not configured(settings):
        raise GoogleError("Google OAuth isn't configured: set GOOGLE_OAUTH_CLIENT and GOOGLE_OAUTH_SECRET in backend/.env")
    if return_to.rstrip("/") not in settings.app_origin_list:
        raise GoogleError("That return address isn't allowed")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with _pending_lock:
        now = time.monotonic()
        for key in [k for k, p in _pending.items() if now - p.created > STATE_TTL_SECONDS]:
            del _pending[key]
        _pending[state] = _Pending(verifier, user_id, return_to.rstrip("/"), now)
    query = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",  # always return a refresh token, also on Reconnect
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(query)}"


def finish(session: Session, settings: Settings, code: str, state: str) -> str:
    """Exchange the code for tokens and store them. Returns the origin to send the browser back to."""
    with _pending_lock:
        pending = _pending.pop(state, None)
    if pending is None or time.monotonic() - pending.created > STATE_TTL_SECONDS:
        raise GoogleError("This sign-in link expired or was already used. Start again from the Setup page.")

    with http_client() as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "code_verifier": pending.verifier,
                "grant_type": "authorization_code",
                "redirect_uri": settings.google_redirect_uri,
            },
        )
        if response.status_code != 200:
            raise GoogleError(f"Google didn't accept the sign-in ({response.json().get('error', response.status_code)})")
        tokens = response.json()
        if "refresh_token" not in tokens:
            raise GoogleError("Google didn't return a refresh token. Remove the app's access in your Google account and reconnect.")
        email = None
        userinfo = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        if userinfo.status_code == 200:
            email = userinfo.json().get("email")

    session.execute(delete(GoogleConnection))  # one connection at a time; Reconnect replaces it
    session.add(
        GoogleConnection(
            account_email=email,
            refresh_token_encrypted=_encrypt(settings, tokens["refresh_token"]),
            access_token_encrypted=_encrypt(settings, tokens["access_token"]),
            access_token_expires_at=utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)) - 60),
            scopes=tokens.get("scope", ""),
            connected_by_user_id=pending.user_id,
        )
    )
    session.commit()
    return pending.return_to


def connection(session: Session) -> GoogleConnection | None:
    return session.scalar(select(GoogleConnection))


def access_token(session: Session, settings: Settings) -> str:
    """A valid access token, refreshed with the stored refresh token when it has expired."""
    conn = connection(session)
    if conn is None:
        raise GoogleError("Google Drive isn't connected")
    if conn.access_token_encrypted and conn.access_token_expires_at and conn.access_token_expires_at > utcnow():
        return _decrypt(settings, conn.access_token_encrypted)

    with http_client() as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": _decrypt(settings, conn.refresh_token_encrypted),
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise GoogleError("Google Drive access was revoked or expired. Reconnect Google Drive.")
    tokens = response.json()
    conn.access_token_encrypted = _encrypt(settings, tokens["access_token"])
    conn.access_token_expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)) - 60)
    session.commit()
    return tokens["access_token"]


def disconnect(session: Session, settings: Settings) -> None:
    conn = connection(session)
    if conn is None:
        return
    try:
        with http_client() as client:
            client.post(REVOKE_URL, data={"token": _decrypt(settings, conn.refresh_token_encrypted)})
    except (httpx.HTTPError, GoogleError):
        pass  # forget the tokens locally even if Google can't be reached
    session.execute(delete(GoogleConnection))
    session.commit()


# ---- Drive ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None
    modified: str | None


def folder_name(session: Session, settings: Settings) -> str:
    data = _drive_get(session, settings, f"/files/{settings.google_drive_folder_id}", {"fields": "name", "supportsAllDrives": "true"})
    return data.json()["name"]


def list_folder(session: Session, settings: Settings) -> list[DriveFile]:
    files: list[DriveFile] = []
    page_token = None
    while True:
        params = {
            "q": f"'{settings.google_drive_folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime)",
            "orderBy": "name",
            "pageSize": "100",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        data = _drive_get(session, settings, "/files", params).json()
        for f in data.get("files", []):
            if f["mimeType"] != "application/vnd.google-apps.folder":
                size = f.get("size")
                files.append(DriveFile(f["id"], f["name"], f["mimeType"], int(size) if size else None, f.get("modifiedTime")))
        page_token = data.get("nextPageToken")
        if not page_token:
            return files


def download(session: Session, settings: Settings, file: DriveFile) -> tuple[bytes, str]:
    """File bytes and the mime type to treat them as. Google Sheets are exported as CSV."""
    if file.mime_type == GOOGLE_SHEET:
        return _drive_get(session, settings, f"/files/{file.id}/export", {"mimeType": "text/csv"}).content, "text/csv"
    return _drive_get(session, settings, f"/files/{file.id}", {"alt": "media", "supportsAllDrives": "true"}).content, file.mime_type


def _drive_get(session: Session, settings: Settings, path: str, params: dict) -> httpx.Response:
    token = access_token(session, settings)
    with http_client() as client:
        response = client.get(f"{DRIVE_URL}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
    if response.status_code == 404:
        raise GoogleError("The shared Drive folder can't be found with this Google account. Is it shared with you?")
    if response.status_code in (401, 403):
        raise GoogleError("Google Drive refused access. Reconnect, and check the folder is shared with this account.")
    if response.status_code != 200:
        raise GoogleError(f"Google Drive returned an error ({response.status_code})")
    return response
