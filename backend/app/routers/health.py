from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    """Confirms the API is running and the database answers. No authentication."""
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "today": get_settings().today.isoformat()}
