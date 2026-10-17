"""run_import(): fetch -> prepare -> load, recorded in import_runs, with a downloadable error report."""

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.importer.load import load
from app.importer.prepare import Issue, PreparedImport, Preparer
from app.importer.sources import ImportSource, fetch
from app.models import AcquisitionSource, ImportRun, SourceAlias
from app.queries.listing import csv_safe
from app.rules import utcnow

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

ERROR_REPORT_NAME = "import_errors_latest.csv"


def run_import(session: Session, source: ImportSource, settings: Settings) -> ImportRun:
    report_path = settings.reports_dir / ERROR_REPORT_NAME
    report_path.unlink(missing_ok=True)  # the report only ever describes the latest attempt

    run = ImportRun(started_at=utcnow(), source=source.label, status=STATUS_RUNNING, file_stats={})
    session.add(run)
    session.commit()

    try:
        prepared = prepare(source, _source_aliases(session), settings.import_batch_size)
        run.file_stats = {name: stats.as_dict() for name, stats in prepared.file_stats.items()}

        if prepared.missing_entities:
            run.status = STATUS_FAILED
            run.message = "Import stopped before changing any data: no file found for " + ", ".join(prepared.missing_entities) + "."
        else:
            load(session, prepared)
            run.status = STATUS_SUCCEEDED
            run.message = _summary(prepared)

        if prepared.issues:
            _write_report(report_path, prepared.issues)
            run.error_report_path = str(report_path)
    except Exception as exc:  # report every failure on the run record, with nothing half-written
        session.rollback()
        run = session.get(ImportRun, run.import_run_id)
        run.status = STATUS_FAILED
        run.message = f"Import failed and was rolled back: {exc}"

    run.finished_at = utcnow()
    session.commit()
    return run


def prepare(source: ImportSource, source_aliases: dict[str, str], batch_size: int) -> PreparedImport:
    preparer = Preparer(source_aliases)
    for batch in fetch(source, batch_size):
        for file in batch:
            preparer.add_file(file)
    return preparer.finish()


def _source_aliases(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(SourceAlias.alias, AcquisitionSource.source).join(
            AcquisitionSource, AcquisitionSource.acquisition_source_id == SourceAlias.acquisition_source_id
        )
    )
    return {alias: source for alias, source in rows}


def _summary(prepared: PreparedImport) -> str:
    rejected = sum(s.rejected for s in prepared.file_stats.values())
    merged = sum(s.duplicates_merged for s in prepared.file_stats.values())
    return (
        f"Loaded {len(prepared.subscribers):,} subscribers, {len(prepared.app_users):,} app users and "
        f"{len(prepared.web_events):,} web events. {merged:,} duplicates merged, {rejected:,} rows rejected."
    )


def _write_report(path: Path, issues: list[Issue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["severity", "file", "row", "field", "value", "reason"])
        for issue in issues:
            writer.writerow([issue.severity, issue.file, issue.row or "", issue.field, csv_safe(issue.value), issue.reason])
