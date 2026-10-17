"""prepare(): identify, validate, clean and de-duplicate import files before anything touches the database."""

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.importer.sources import SourceFile
from app.rules import normalize_email, parse_date, parse_timestamp

SUBSCRIBERS = "subscribers"
APP_USERS = "app_users"
WEB_EVENTS = "web_events"

# Files are identified by their header row, not their file name.
FINGERPRINTS = {
    SUBSCRIBERS: {"email", "signup_date", "status", "acquisition_source", "last_open_date"},
    APP_USERS: {"user_id", "email", "created_at"},
    WEB_EVENTS: {"visitor_id", "page", "timestamp", "utm_source", "email"},
}
REQUIRED_ENTITIES = (SUBSCRIBERS, APP_USERS, WEB_EVENTS)
ACCEPTED_MIME_TYPES = {"text/csv", "text/plain", "application/csv", "application/vnd.ms-excel"}
STATUS_VALUES = {"active": 1, "unsubscribed": 0}


@dataclass
class Issue:
    file: str
    row: int | None
    field: str
    value: str
    reason: str
    severity: str = "error"  # "error" = row or file rejected; "warning" = fixed or flagged, row kept


@dataclass
class FileStats:
    entity: str
    read: int = 0
    fixed: int = 0
    rejected: int = 0
    duplicates_merged: int = 0

    @property
    def loaded(self) -> int:
        return self.read - self.rejected - self.duplicates_merged

    def as_dict(self) -> dict:
        return {
            "entity": self.entity,
            "read": self.read,
            "loaded": self.loaded,
            "fixed": self.fixed,
            "rejected": self.rejected,
            "duplicates_merged": self.duplicates_merged,
        }


@dataclass
class PreparedImport:
    subscribers: list[dict] = field(default_factory=list)
    app_users: list[dict] = field(default_factory=list)
    web_events: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    file_stats: dict[str, FileStats] = field(default_factory=dict)
    entities_found: set[str] = field(default_factory=set)

    @property
    def missing_entities(self) -> list[str]:
        return [e for e in REQUIRED_ENTITIES if e not in self.entities_found]


class _RowCheck:
    """Collects the problems found in one row so the row is rejected (and counted) once."""

    def __init__(self) -> None:
        self.errors: list[tuple[str, str, str]] = []
        self.warnings: list[tuple[str, str, str]] = []

    def date(self, name: str, raw: str, required: bool) -> date | None:
        try:
            value = parse_date(raw)
        except ValueError:
            self.errors.append((name, raw, "Invalid date"))
            return None
        if value is None and required:
            self.errors.append((name, raw, "Missing date"))
        return value


class Preparer:
    """Accumulates files (batch by batch), then de-duplicates and links rows in finish()."""

    def __init__(self, source_aliases: dict[str, str]):
        # lowercase spelling -> canonical source name, e.g. {"twitter": "X"}
        self.source_aliases = source_aliases
        self.result = PreparedImport()
        self._subscriber_rows: list[tuple[str, dict]] = []
        self._app_user_rows: list[tuple[str, dict]] = []

    def add_file(self, file: SourceFile) -> None:
        if file.mime_type not in ACCEPTED_MIME_TYPES:
            self._file_issue(file.name, "mime_type", file.mime_type, "Not a CSV file; skipped")
            return
        try:
            text = file.content.decode("utf-8-sig")
        except UnicodeDecodeError:
            self._file_issue(file.name, "encoding", "", "File is not UTF-8 text; skipped")
            return

        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = {h.strip() for h in (reader.fieldnames or [])}
        entity = next((name for name, cols in FINGERPRINTS.items() if cols <= headers), None)
        if entity is None:
            self._file_issue(file.name, "headers", ",".join(sorted(headers)), "Headers don't match a known file type; skipped")
            return

        self.result.entities_found.add(entity)
        stats = self.result.file_stats.setdefault(file.name, FileStats(entity=entity))
        parse_row = {SUBSCRIBERS: self._subscriber, APP_USERS: self._app_user, WEB_EVENTS: self._web_event}[entity]

        for row_number, raw in enumerate(reader, start=2):  # row 1 is the header
            stats.read += 1
            row = {k.strip(): (v or "") for k, v in raw.items() if k}
            check = _RowCheck()
            if not any(v.strip() for v in row.values()):
                check.errors.append(("*", "", "Blank row"))
                data, fixed = None, False
            else:
                data, fixed = parse_row(row, check)

            for name, value, reason in check.warnings:
                self.result.issues.append(Issue(file.name, row_number, name, value, reason, "warning"))
            if check.errors:
                stats.rejected += 1
                for name, value, reason in check.errors:
                    self.result.issues.append(Issue(file.name, row_number, name, value, reason))
                continue
            if fixed:
                stats.fixed += 1
            if entity == SUBSCRIBERS:
                self._subscriber_rows.append((file.name, data))
            elif entity == APP_USERS:
                self._app_user_rows.append((file.name, data))
            else:
                self.result.web_events.append(data)

    def finish(self) -> PreparedImport:
        self._dedupe_subscribers()
        self._dedupe_app_users()
        self._backfill_web_event_emails()
        return self.result

    # ---- row parsers: return (clean row, whether anything was fixed) -------------------------------

    def _subscriber(self, row: dict, check: _RowCheck) -> tuple[dict, bool]:
        email = normalize_email(row["email"])
        if email is None:
            check.errors.append(("email", row["email"], "Invalid email" if row["email"].strip() else "Missing email"))
        signup = check.date("signup_date", row["signup_date"], required=True)
        last_open = check.date("last_open_date", row["last_open_date"], required=False)
        status_raw = row["status"].strip().lower()
        if status_raw and status_raw not in STATUS_VALUES:
            check.errors.append(("status", row["status"], "Unknown status"))
        elif not status_raw:
            check.warnings.append(("status", "", "Blank status; defaulted to active"))
        if signup and last_open and last_open < signup:
            check.warnings.append(("last_open_date", row["last_open_date"], "Last open is before signup"))

        data = {
            "email": email,
            "signup_date": signup,
            "status": STATUS_VALUES.get(status_raw, 1),
            "acquisition_source": self._canonical_source(row["acquisition_source"]),
            "last_open_date": last_open,
        }
        return data, row["email"] != email

    def _app_user(self, row: dict, check: _RowCheck) -> tuple[dict, bool]:
        user_id = row["user_id"].strip()
        if not user_id:
            check.errors.append(("user_id", "", "Missing user_id"))
        created = check.date("created_at", row["created_at"], required=True)
        email = normalize_email(row["email"])
        if email is None:
            # Keep the account: it's still an app user, it just can't be linked to a subscriber.
            check.warnings.append(("email", row["email"], "Invalid or missing email; user kept unlinked"))
        data = {"app_user_id": user_id, "email": email, "created_at": created}
        return data, email is not None and row["email"] != email

    def _web_event(self, row: dict, check: _RowCheck) -> tuple[dict, bool]:
        visitor_id, page = row["visitor_id"].strip(), row["page"].strip()
        if not visitor_id:
            check.errors.append(("visitor_id", "", "Missing visitor_id"))
        if not page:
            check.errors.append(("page", "", "Missing page"))
        timestamp = None
        try:
            timestamp = parse_timestamp(row["timestamp"])
        except ValueError:
            check.errors.append(("timestamp", row["timestamp"], "Invalid timestamp"))
        else:
            if timestamp is None:
                check.errors.append(("timestamp", "", "Missing timestamp"))

        email = None
        if row["email"].strip():
            email = normalize_email(row["email"])
            if email is None:
                check.warnings.append(("email", row["email"], "Invalid email removed; event kept"))
        utm = row["utm_source"].strip().lower() or None
        data = {
            "visitor_id": visitor_id,
            "page": page,
            "timestamp": timestamp,
            "utm_source": utm,
            "acquisition_source": self.source_aliases.get(utm) if utm else None,
            "email": email,
            "email_backfilled": False,
        }
        return data, email is not None and row["email"] != email

    # ---- cross-row rules ----------------------------------------------------------------------

    def _dedupe_subscribers(self) -> None:
        """One row per normalized email. Winner: latest last_open_date, then latest signup_date, then
        the later row. Blank fields on the winner are filled from the other rows in the same order."""
        groups: dict[str, list[tuple[int, str, dict]]] = defaultdict(list)
        for order, (file, data) in enumerate(self._subscriber_rows):
            groups[data["email"]].append((order, file, data))

        def priority(item: tuple[int, str, dict]) -> tuple[date, date, int]:
            order, _file, data = item
            return (data["last_open_date"] or date.min, data["signup_date"], order)

        for rows in groups.values():
            ranked = sorted(rows, key=priority, reverse=True)
            merged = dict(ranked[0][2])
            for _order, file, other in ranked[1:]:
                self.result.file_stats[file].duplicates_merged += 1
                for key, value in other.items():
                    if merged.get(key) is None and value is not None:
                        merged[key] = value
            self.result.subscribers.append(merged)

    def _dedupe_app_users(self) -> None:
        """One row per user_id; the later row wins."""
        latest: dict[str, tuple[str, dict]] = {}
        for file, data in self._app_user_rows:
            previous = latest.get(data["app_user_id"])
            if previous:
                self.result.file_stats[previous[0]].duplicates_merged += 1
            latest[data["app_user_id"]] = (file, data)
        self.result.app_users = [data for _file, data in latest.values()]

    def _backfill_web_event_emails(self) -> None:
        """Events without an email inherit the email of an identified event from the same visitor_id.
        A visitor seen with more than one email is ambiguous, so it isn't backfilled."""
        emails_by_visitor: dict[str, set[str]] = defaultdict(set)
        for event in self.result.web_events:
            if event["email"]:
                emails_by_visitor[event["visitor_id"]].add(event["email"])
        for visitor_id, emails in emails_by_visitor.items():
            if len(emails) > 1:
                self.result.issues.append(
                    Issue(WEB_EVENTS, None, "visitor_id", visitor_id, "Visitor has several emails; not backfilled", "warning")
                )
        for event in self.result.web_events:
            emails = emails_by_visitor.get(event["visitor_id"])
            if not event["email"] and emails and len(emails) == 1:
                event["email"] = next(iter(emails))
                event["email_backfilled"] = True

    def _canonical_source(self, raw: str) -> str | None:
        value = raw.strip()
        if not value:
            return None
        return self.source_aliases.get(value.lower(), value)

    def _file_issue(self, file: str, name: str, value: str, reason: str) -> None:
        self.result.issues.append(Issue(file, None, name, value, reason))
