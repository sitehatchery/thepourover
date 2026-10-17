"""Idempotent seed data for reference tables. Imports never reset these tables."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AcquisitionSource, SourceAlias

ACQUISITION_SOURCES = ["Instagram", "Facebook", "Referral", "Google", "Direct", "Podcast", "X"]

# Lowercase spellings seen in source data, mapped to the canonical source name.
SOURCE_ALIASES = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "referral": "Referral",
    "google": "Google",
    "direct": "Direct",
    "podcast": "Podcast",
    "x": "X",
    "twitter": "X",
}


def seed_reference_data(session: Session) -> None:
    existing = {s.source: s for s in session.scalars(select(AcquisitionSource))}
    for name in ACQUISITION_SOURCES:
        if name not in existing:
            existing[name] = AcquisitionSource(source=name)
            session.add(existing[name])
    session.flush()

    aliases = {a.alias for a in session.scalars(select(SourceAlias))}
    for alias, name in SOURCE_ALIASES.items():
        if alias not in aliases:
            session.add(SourceAlias(alias=alias, acquisition_source_id=existing[name].acquisition_source_id))
    session.commit()
