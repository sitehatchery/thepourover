"""Shared data rules. Every module that touches emails or dates goes through these functions."""

import re
from datetime import date, datetime, timezone

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _canonical(raw: str) -> str:
    """The one definition of a normalized email: trimmed and lowercased."""
    return raw.strip().lower()


def normalize_email(raw: str | None) -> str | None:
    """Normalize a whole email. Returns None when the value is blank or not a valid address.

    Every email stored goes through this: the CSV importer (subscribers, app users, web events) and the
    admin console. The webhook carries no email; app events reach a person through user_id.
    """
    if raw is None:
        return None
    email = _canonical(raw)
    if not email or not _EMAIL_PATTERN.match(email):
        return None
    return email


def normalize_search(raw: str | None) -> str | None:
    """Normalize a partial search term (e.g. "GMAIL.com ") exactly like stored emails, without requiring a
    whole address. Used by profile search and every email filter."""
    value = _canonical(raw or "")
    return value or None


def parse_date(raw: str | None) -> date | None:
    """Parse an ISO date (YYYY-MM-DD). Returns None for blank values; raises ValueError for bad ones."""
    value = (raw or "").strip()
    if not value:
        return None
    return date.fromisoformat(value)


def utcnow() -> datetime:
    """Current UTC time as a naive datetime, matching how timestamps are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_timestamp(raw: str | None) -> datetime | None:
    """Parse an ISO timestamp as a naive UTC datetime. Accepts 'YYYY-MM-DD HH:MM:SS' and '...Z' forms."""
    value = (raw or "").strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed
