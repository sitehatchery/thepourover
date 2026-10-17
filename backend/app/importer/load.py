"""load(): replace imported data in one transaction and link records by email."""

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.importer.prepare import PreparedImport
from app.models import AcquisitionSource, AppEvent, AppUser, Subscriber, WebEvent

# Reset on every import. segments, acquisition_sources, source_aliases, auth tables and
# import_runs are deliberately not in this list. Order respects foreign keys.
RESET_TABLES = (WebEvent, AppEvent, AppUser, Subscriber)


def load(session: Session, prepared: PreparedImport) -> None:
    """Runs inside the caller's transaction; any error rolls everything back."""
    for model in RESET_TABLES:
        session.execute(delete(model))

    source_ids = _source_ids(session, {s["acquisition_source"] for s in prepared.subscribers})

    if prepared.subscribers:
        session.execute(
            insert(Subscriber),
            [
                {
                    "email": s["email"],
                    "signup_date": s["signup_date"],
                    "status": s["status"],
                    "acquisition_source_id": source_ids.get(s["acquisition_source"]),
                    "last_open_date": s["last_open_date"],
                }
                for s in prepared.subscribers
            ],
        )
    subscriber_ids = {email: sid for email, sid in session.execute(select(Subscriber.email, Subscriber.subscriber_id))}

    # Linking rule: app users and web events join to subscribers on normalized email.
    if prepared.app_users:
        session.execute(
            insert(AppUser),
            [{**u, "subscriber_id": subscriber_ids.get(u["email"]), "is_placeholder": False} for u in prepared.app_users],
        )

    if prepared.web_events:
        session.execute(
            insert(WebEvent),
            [
                {
                    "visitor_id": e["visitor_id"],
                    "page": e["page"],
                    "timestamp": e["timestamp"],
                    "utm_source": e["utm_source"],
                    "acquisition_source_id": source_ids.get(e["acquisition_source"]),
                    "email": e["email"],
                    "email_backfilled": e["email_backfilled"],
                    "subscriber_id": subscriber_ids.get(e["email"]),
                }
                for e in prepared.web_events
            ],
        )


def _source_ids(session: Session, names: set[str | None]) -> dict[str, int]:
    """Map source names to ids, adding any subscriber source we haven't seen before."""
    known = {s.source: s.acquisition_source_id for s in session.scalars(select(AcquisitionSource))}
    for name in sorted(n for n in names if n and n not in known):
        source = AcquisitionSource(source=name[:24])
        session.add(source)
        session.flush()
        known[name] = source.acquisition_source_id
    return known
