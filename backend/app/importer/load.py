"""load(): replace imported data in one transaction and link records by email.

Subscribers and web events exist only in the CSVs, so each import replaces them. App events exist only
because the webhook delivered them, so an import never touches them. App users sit in between: the CSV is
the source of truth for the accounts it lists, but a user the webhook introduced (a placeholder) or one
with webhook events must survive. So app users are merged:

- a user in the file is inserted, or updated in place, which completes a placeholder;
- a user missing from the file is deleted if nothing refers to it, and otherwise kept as a placeholder.
"""

from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.orm import Session

from app.importer.prepare import PreparedImport
from app.models import AcquisitionSource, AppEvent, AppUser, Subscriber, WebEvent


def load(session: Session, prepared: PreparedImport) -> None:
    """Runs inside the caller's transaction; any error rolls everything back."""
    # App users point at subscribers, so detach them before the subscribers are replaced.
    session.execute(update(AppUser).values(subscriber_id=None))
    session.execute(delete(WebEvent))
    session.execute(delete(Subscriber))

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
    _merge_app_users(session, prepared.app_users, subscriber_ids)

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


def _merge_app_users(session: Session, rows: list[dict], subscriber_ids: dict[str, int]) -> None:
    existing = set(session.scalars(select(AppUser.app_user_id)))
    in_file = {row["app_user_id"] for row in rows}

    new_rows = [row for row in rows if row["app_user_id"] not in existing]
    if new_rows:
        session.execute(
            insert(AppUser),
            [{**row, "subscriber_id": subscriber_ids.get(row["email"]), "is_placeholder": False} for row in new_rows],
        )
    for row in rows:
        if row["app_user_id"] in existing:  # an earlier import's user, or a webhook placeholder being completed
            session.execute(
                update(AppUser)
                .where(AppUser.app_user_id == row["app_user_id"])
                .values(
                    email=row["email"],
                    created_at=row["created_at"],
                    subscriber_id=subscriber_ids.get(row["email"]),
                    is_placeholder=False,
                )
            )

    gone = existing - in_file
    if gone:
        has_events = exists().where(AppEvent.app_user_id == AppUser.app_user_id)
        session.execute(delete(AppUser).where(AppUser.app_user_id.in_(gone), ~has_events))
        # Users with webhook events stay, as placeholders, so their activity isn't lost.
        session.execute(
            update(AppUser)
            .where(AppUser.app_user_id.in_(gone))
            .values(is_placeholder=True)
            .execution_options(synchronize_session=False)
        )
        for user in session.scalars(select(AppUser).where(AppUser.app_user_id.in_(gone), AppUser.email.is_not(None))):
            user.subscriber_id = subscriber_ids.get(user.email)


def _source_ids(session: Session, names: set[str | None]) -> dict[str, int]:
    """Map source names to ids, adding any subscriber source we haven't seen before."""
    known = {s.source: s.acquisition_source_id for s in session.scalars(select(AcquisitionSource))}
    for name in sorted(n for n in names if n and n not in known):
        source = AcquisitionSource(source=name[:24])
        session.add(source)
        session.flush()
        known[name] = source.acquisition_source_id
    return known
