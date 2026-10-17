"""The PII boundary between the CDP and the language model.

Two layers:
1. Design: the model's tools only ever return counts, percentages, category values (sources, pages,
   event types) and opaque result ids. Rows with emails or ids are fetched by the browser directly.
2. Guard: every payload is scanned just before it leaves the server. Anything that looks like an email
   or one of our identifiers blocks the request, so a bug in layer 1 fails closed instead of leaking.
"""

import json
import re
from typing import Any

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# App user, visitor, device and event ids as they appear in the data and the webhook.
IDENTIFIER = re.compile(r"\b(?:u|v|d|evt)_[A-Za-z0-9]{4,}\b")
# Profile ids (s_123 / u_...) as used by the API.
PROFILE_ID = re.compile(r"\bs_\d+\b")

REDACTED_EMAIL = "[email removed]"
REDACTED_ID = "[id removed]"


class PIIBlocked(Exception):
    """Raised when a payload bound for the model contains something that looks like personal data."""


def redact(text: str) -> tuple[str, bool]:
    """Strip emails and identifiers from user-typed text before it can reach the model."""
    cleaned = EMAIL.sub(REDACTED_EMAIL, text)
    cleaned = IDENTIFIER.sub(REDACTED_ID, cleaned)
    cleaned = PROFILE_ID.sub(REDACTED_ID, cleaned)
    return cleaned, cleaned != text


def find_pii(payload: Any) -> list[str]:
    """What in `payload` looks like personal data (kinds only, never the values themselves)."""
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    found = []
    if EMAIL.search(text):
        found.append("email address")
    if IDENTIFIER.search(text) or PROFILE_ID.search(text):
        found.append("person identifier")
    return found


def assert_no_pii(payload: Any, where: str) -> None:
    found = find_pii(payload)
    if found:
        raise PIIBlocked(f"Blocked {where}: it contained what looks like a {' and '.join(found)}")
