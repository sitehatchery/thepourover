from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_auth
from app.config import get_settings
from app.db import get_session
from app.importer.service import run_import
from app.importer.sources import LocalFolderSource
from app.models import ImportRun

router = APIRouter(prefix="/import", tags=["import"], dependencies=[Depends(require_auth)])


class ImportRunOut(BaseModel):
    import_run_id: int
    status: str
    source: str
    message: str
    file_stats: dict
    has_error_report: bool
    started_at: str
    finished_at: str | None

    @classmethod
    def of(cls, run: ImportRun) -> "ImportRunOut":
        return cls(
            import_run_id=run.import_run_id,
            status=run.status,
            source=run.source,
            message=run.message,
            file_stats=run.file_stats,
            has_error_report=bool(run.error_report_path and Path(run.error_report_path).exists()),
            started_at=run.started_at.isoformat(),
            finished_at=run.finished_at.isoformat() if run.finished_at else None,
        )


@router.post("", response_model=ImportRunOut)
def start_import(session: Session = Depends(get_session)) -> ImportRunOut:
    """Replace subscribers, app users, app events and web events with a fresh import.
    Segments, sources and credentials are kept."""
    settings = get_settings()
    run = run_import(session, LocalFolderSource(settings.import_source_dir), settings)
    return ImportRunOut.of(run)


@router.get("/runs", response_model=list[ImportRunOut])
def list_runs(limit: int = 10, session: Session = Depends(get_session)) -> list[ImportRunOut]:
    limit = max(1, min(limit, 50))
    runs = session.scalars(select(ImportRun).order_by(ImportRun.import_run_id.desc()).limit(limit))
    return [ImportRunOut.of(r) for r in runs]


@router.get("/report")
def download_report(session: Session = Depends(get_session)) -> FileResponse:
    """The error report from the latest import attempt."""
    latest = session.scalar(select(ImportRun).order_by(ImportRun.import_run_id.desc()).limit(1))
    if latest is None or not latest.error_report_path or not Path(latest.error_report_path).exists():
        raise HTTPException(status_code=404, detail="The latest import has no error report")
    return FileResponse(latest.error_report_path, media_type="text/csv", filename="import_errors.csv")
