import csv
from datetime import date

from sqlalchemy import func, select

from app.importer.service import STATUS_FAILED, STATUS_SUCCEEDED, run_import
from app.importer.sources import LocalFolderSource
from app.models import AcquisitionSource, AppUser, Segment, Subscriber, WebEvent

SUBSCRIBER_HEADER = "email,signup_date,status,acquisition_source,last_open_date"
APP_USER_HEADER = "user_id,email,created_at"
WEB_HEADER = "visitor_id,page,timestamp,utm_source,email"


def count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where))


def import_folder(session, settings, folder):
    return run_import(session, LocalFolderSource(folder), settings)


def minimal_files(subscribers: str = "", app_users: str = "", web: str = "") -> dict[str, str]:
    return {
        "subscribers.csv": f"{SUBSCRIBER_HEADER}\n{subscribers}",
        "app_users.csv": f"{APP_USER_HEADER}\n{app_users}",
        "web_events.csv": f"{WEB_HEADER}\n{web}",
    }


# ---- the sample data from the brief ------------------------------------------------------------


def test_sample_data_import_counts(session, settings):
    run = import_folder(session, settings, settings.import_source_dir)

    assert run.status == STATUS_SUCCEEDED
    assert count(session, Subscriber) == 2900
    assert count(session, AppUser) == 930
    assert count(session, AppUser, AppUser.subscriber_id.is_not(None)) == 900
    assert count(session, WebEvent) == 10000
    assert count(session, WebEvent, WebEvent.email.is_not(None)) == 8441
    assert count(session, WebEvent, WebEvent.email_backfilled.is_(True)) == 7041
    assert count(session, WebEvent, WebEvent.subscriber_id.is_not(None)) == 8441

    stats = run.file_stats["subscribers.csv"]
    assert stats == {"entity": "subscribers", "read": 2995, "loaded": 2900, "fixed": 85, "rejected": 10, "duplicates_merged": 85}


def test_sample_data_error_report(session, settings):
    run = import_folder(session, settings, settings.import_source_dir)

    with open(run.error_report_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    reasons = sorted(r["reason"] for r in rows)
    assert reasons == ["Blank row"] * 8 + ["Invalid email"] * 2
    # A value starting with "@" is escaped so spreadsheet apps don't treat it as a formula.
    assert any(r["value"] == "'@gmail.com" for r in rows)


def test_reimport_replaces_data_and_keeps_segments(session, settings):
    session.add(Segment(slug="kept", name="Kept", definition={"match": "all", "filters": []}))
    session.commit()

    import_folder(session, settings, settings.import_source_dir)
    import_folder(session, settings, settings.import_source_dir)

    assert count(session, Subscriber) == 2900
    assert count(session, Segment) == 1


# ---- rules on small files -----------------------------------------------------------------------


def test_dedupe_keeps_most_recent_open_and_fills_blanks(session, settings, csv_folder):
    folder = csv_folder(
        minimal_files(
            subscribers="\n".join(
                [
                    "Ana@Example.com,2026-07-01,active,Instagram,2026-08-01",
                    " ana@example.com ,2026-07-01,unsubscribed,,2026-09-01",
                ]
            )
        )
    )
    run = import_folder(session, settings, folder)

    subscriber = session.scalar(select(Subscriber))
    assert run.file_stats["subscribers.csv"]["duplicates_merged"] == 1
    assert subscriber.email == "ana@example.com"
    assert subscriber.last_open_date == date(2026, 9, 1)  # the fresher row wins...
    assert subscriber.status == 0
    source = session.get(AcquisitionSource, subscriber.acquisition_source_id)
    assert source.source == "Instagram"  # ...and its blank source is filled from the other row


def test_web_events_backfill_by_visitor_and_link_by_email(session, settings, csv_folder):
    folder = csv_folder(
        minimal_files(
            subscribers="ana@example.com,2026-07-01,active,Instagram,",
            web="\n".join(
                [
                    "v_1,/,2026-09-01 10:00:00,twitter,",
                    "v_1,/subscribe,2026-09-01 10:05:00,,ANA@example.com",
                    "v_2,/,2026-09-02 10:00:00,,",
                ]
            ),
        )
    )
    import_folder(session, settings, folder)

    events = {e.page + e.visitor_id: e for e in session.scalars(select(WebEvent))}
    anonymous_then_identified = events["/v_1"]
    assert anonymous_then_identified.email == "ana@example.com"
    assert anonymous_then_identified.email_backfilled is True
    assert anonymous_then_identified.subscriber_id is not None
    assert session.get(AcquisitionSource, anonymous_then_identified.acquisition_source_id).source == "X"
    assert events["/v_2"].email is None


def test_visitor_with_two_emails_is_not_backfilled(session, settings, csv_folder):
    folder = csv_folder(
        minimal_files(
            web="\n".join(
                [
                    "v_1,/a,2026-09-01 10:00:00,,a@example.com",
                    "v_1,/b,2026-09-01 10:01:00,,b@example.com",
                    "v_1,/c,2026-09-01 10:02:00,,",
                ]
            )
        )
    )
    run = import_folder(session, settings, folder)

    assert session.scalar(select(WebEvent).where(WebEvent.page == "/c")).email is None
    assert run.error_report_path is not None


def test_app_user_with_bad_email_is_kept_unlinked(session, settings, csv_folder):
    folder = csv_folder(minimal_files(app_users="u_1,not-an-email,2026-09-01"))
    import_folder(session, settings, folder)

    user = session.get(AppUser, "u_1")
    assert user.email is None and user.subscriber_id is None


def test_unknown_subscriber_source_is_added(session, settings, csv_folder):
    folder = csv_folder(minimal_files(subscribers="ana@example.com,2026-07-01,active,TikTok,"))
    import_folder(session, settings, folder)

    assert session.scalar(select(AcquisitionSource).where(AcquisitionSource.source == "TikTok")) is not None


def test_missing_file_type_fails_without_touching_data(session, settings, csv_folder):
    import_folder(session, settings, settings.import_source_dir)
    files = minimal_files()
    del files["app_users.csv"]
    files["notes.csv"] = "something,else\n1,2"

    run = import_folder(session, settings, csv_folder(files))

    assert run.status == STATUS_FAILED
    assert "app_users" in run.message
    assert count(session, Subscriber) == 2900  # previous import untouched


def test_files_are_identified_by_headers_not_names(session, settings, csv_folder):
    files = minimal_files(subscribers="ana@example.com,2026-07-01,active,Direct,")
    renamed = {"export_1.csv": files["web_events.csv"], "export_2.csv": files["subscribers.csv"], "export_3.csv": files["app_users.csv"]}
    run = import_folder(session, settings, csv_folder(renamed))

    assert run.status == STATUS_SUCCEEDED
    assert run.file_stats["export_2.csv"]["entity"] == "subscribers"
