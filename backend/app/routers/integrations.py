from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import Principal, require_auth
from app.config import get_settings
from app.db import get_session
from app.integrations import google
from app.queries.listing import iso

router = APIRouter(prefix="/app/integrations/google", tags=["google drive"])


class StartIn(BaseModel):
    return_to: str = Field(max_length=200, description="Origin of the app page, e.g. https://cdp.local")


@router.get("/status", dependencies=[Depends(require_auth)])
def status(session: Session = Depends(get_session)) -> dict:
    """Whether Google Drive is connected, as whom, and the files waiting in the shared folder."""
    settings = get_settings()
    conn = google.connection(session)
    out = {
        "configured": google.configured(settings),
        "connected": conn is not None,
        "account_email": conn.account_email if conn else None,
        "connected_at": iso(conn.connected_at) if conn else None,
        "folder_id": settings.google_drive_folder_id,
        "folder_name": None,
        "files": [],
        "error": None,
    }
    if conn is None:
        return out
    try:
        out["folder_name"] = google.folder_name(session, settings)
        out["files"] = [
            {"name": f.name, "mime_type": f.mime_type, "size_bytes": f.size, "modified": f.modified}
            for f in google.list_folder(session, settings)
        ]
    except google.GoogleError as exc:
        out["error"] = str(exc)
    return out


@router.post("/start")
def start(body: StartIn, principal: Principal = Depends(require_auth)) -> dict:
    """Begin connecting: returns the Google sign-in URL for the browser to open."""
    try:
        user_id = principal.id if principal.kind == "user" else None
        return {"url": google.start(get_settings(), user_id, body.return_to)}
    except google.GoogleError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.get("/callback", include_in_schema=False)
def callback(state: str = "", code: str = "", error: str = "", session: Session = Depends(get_session)) -> RedirectResponse:
    """Google redirects the browser here. Not behind login: the single-use state proves who started it."""
    settings = get_settings()
    fallback = settings.app_origin_list[0]
    if error:
        message = "Google sign-in was canceled." if error == "access_denied" else f"Google sign-in failed ({error})."
        return RedirectResponse(f"{fallback}/setup?{urlencode({'google': 'error', 'message': message})}", status_code=303)
    try:
        return_to = google.finish(session, settings, code, state)
    except google.GoogleError as exc:
        return RedirectResponse(f"{fallback}/setup?{urlencode({'google': 'error', 'message': str(exc)})}", status_code=303)
    return RedirectResponse(f"{return_to}/setup?google=connected", status_code=303)


@router.post("/disconnect", status_code=204, dependencies=[Depends(require_auth)])
def disconnect(session: Session = Depends(get_session)) -> None:
    """Revoke the Google tokens and forget them."""
    google.disconnect(session, get_settings())
