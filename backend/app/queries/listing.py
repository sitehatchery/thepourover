"""Shared helpers for list endpoints: paging, allow-listed sorting, date filters and CSV export."""

import csv
import io
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import open_session

DEFAULT_PAGE_SIZE = 40
MAX_PAGE_SIZE = 200


class ListParams(BaseModel):
    page: int
    page_size: int
    sort: str | None
    order: str
    format: str


def list_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    sort: str | None = Query(None, max_length=32),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> ListParams:
    return ListParams(page=page, page_size=page_size, sort=sort, order=order, format=format)


def apply_sort(stmt: Select, params: ListParams, columns: dict[str, Any], default: str, tiebreak: Any) -> Select:
    """Sort by an allow-listed column only; anything else is rejected rather than passed to SQL."""
    key = params.sort or default
    if key not in columns:
        raise HTTPException(400, detail=f"Can't sort by '{key}'. Allowed: {', '.join(sorted(columns))}")
    column = columns[key]
    direction = column.desc() if params.order == "desc" else column.asc()
    return stmt.order_by(direction.nulls_last(), tiebreak)


def date_range_filter(column: Any, date_from: date | None, date_to: date | None, today: bool) -> list:
    """Inclusive day range on a datetime column. `today` means the configured today (2026-09-28)."""
    if today:
        date_from = date_to = get_settings().today
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, detail="date_from must be on or before date_to")
    conditions = []
    if date_from:
        conditions.append(column >= datetime.combine(date_from, time.min))
    if date_to:
        conditions.append(column < datetime.combine(date_to + timedelta(days=1), time.min))
    return conditions


def paginate(session: Session, stmt: Select, params: ListParams, to_row: Callable[[Any], dict]) -> dict:
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = session.execute(stmt.limit(params.page_size).offset((params.page - 1) * params.page_size))
    return {
        "items": [to_row(r) for r in rows],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }


def csv_safe(value: Any) -> str:
    """Stop spreadsheet apps from running cell values as formulas."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def csv_response(stmt: Select, columns: list[str], to_row: Callable[[Any], dict], name: str) -> StreamingResponse:
    """Stream every matching row (not just one page) as CSV."""

    def generate() -> Iterator[str]:
        # The response streams after the endpoint returns, so it reads with its own session.
        with open_session() as session:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(columns)
            for row in session.execute(stmt.execution_options(yield_per=500)):
                data = to_row(row)
                writer.writerow([csv_safe(data[c]) for c in columns])
                if buffer.tell() > 64_000:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate()
            yield buffer.getvalue()

    filename = f"{name}_{get_settings().today.isoformat()}.csv"
    return StreamingResponse(
        generate(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def join_pipe(items: Iterable[str]) -> str:
    return " | ".join(items)
