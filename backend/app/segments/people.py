"""The people view: one row per person with the metrics segments, the Subscribers table and lookups use.

A person is either a subscriber (profile s_<id>, with linked app users and web events) or an app user
with no subscription (profile u_<id>, including webhook placeholders). Metrics are computed live from
the event tables, so a webhook event changes segment membership straight away.
"""

from sqlalchemy import Integer, String, and_, case, cast, distinct, exists, func, literal, or_, select, union_all
from sqlalchemy.sql import Subquery

from app.models import AcquisitionSource, AppEvent, AppUser, Subscriber, WebEvent


def _later(a, b):
    """The later of two nullable timestamps (SQLite's max() returns NULL if either side is NULL)."""
    return case((a.is_(None), b), (b.is_(None), a), (a > b, a), else_=b)


def build_people() -> Subquery:
    # Web activity per subscriber, and per email for web events not tied to a subscriber.
    web_by_subscriber = (
        select(
            WebEvent.subscriber_id.label("key"),
            func.count().label("web_event_count"),
            func.count(distinct(func.date(WebEvent.timestamp))).label("web_active_days"),
            func.max(WebEvent.timestamp).label("last_web_visit"),
        )
        .where(WebEvent.subscriber_id.is_not(None))
        .group_by(WebEvent.subscriber_id)
        .subquery()
    )
    web_by_email = (
        select(
            WebEvent.email.label("key"),
            func.count().label("web_event_count"),
            func.count(distinct(func.date(WebEvent.timestamp))).label("web_active_days"),
            func.max(WebEvent.timestamp).label("last_web_visit"),
        )
        .where(WebEvent.subscriber_id.is_(None), WebEvent.email.is_not(None))
        .group_by(WebEvent.email)
        .subquery()
    )

    # First source: the UTM value of the person's oldest web event that has one.
    ranked_utm = select(
        WebEvent.subscriber_id.label("subscriber_id"),
        WebEvent.email.label("email"),
        WebEvent.utm_source.label("utm_source"),
        func.row_number()
        .over(partition_by=func.coalesce(cast(WebEvent.subscriber_id, String), WebEvent.email), order_by=WebEvent.timestamp)
        .label("rank"),
    ).where(WebEvent.utm_source.is_not(None), WebEvent.email.is_not(None)).subquery()
    first_utm = select(ranked_utm.c.subscriber_id, ranked_utm.c.email, ranked_utm.c.utm_source).where(ranked_utm.c.rank == 1).subquery()

    # App accounts and app activity per subscriber, and per app user.
    app_by_subscriber = (
        select(
            AppUser.subscriber_id.label("key"),
            func.min(AppUser.app_user_id).label("app_user_id"),
            func.min(AppUser.created_at).label("app_created_at"),
        )
        .where(AppUser.subscriber_id.is_not(None))
        .group_by(AppUser.subscriber_id)
        .subquery()
    )
    app_events_by_subscriber = (
        select(
            AppUser.subscriber_id.label("key"),
            func.count(AppEvent.event_id).label("app_event_count"),
            func.max(AppEvent.timestamp).label("last_app_activity"),
        )
        .join(AppEvent, AppEvent.app_user_id == AppUser.app_user_id)
        .where(AppUser.subscriber_id.is_not(None))
        .group_by(AppUser.subscriber_id)
        .subquery()
    )
    app_events_by_user = (
        select(
            AppEvent.app_user_id.label("key"),
            func.count().label("app_event_count"),
            func.max(AppEvent.timestamp).label("last_app_activity"),
        )
        .where(AppEvent.app_user_id.is_not(None))
        .group_by(AppEvent.app_user_id)
        .subquery()
    )

    subscribers = (
        select(
            (literal("s_") + cast(Subscriber.subscriber_id, String)).label("profile_id"),
            Subscriber.subscriber_id.label("subscriber_id"),
            app_by_subscriber.c.app_user_id.label("app_user_id"),
            Subscriber.email.label("email"),
            Subscriber.status.label("status"),
            AcquisitionSource.source.label("acquisition_source"),
            Subscriber.signup_date.label("signup_date"),
            Subscriber.last_open_date.label("last_open_date"),
            literal(1, Integer).label("is_subscriber"),
            case((app_by_subscriber.c.app_user_id.is_not(None), 1), else_=0).label("has_app_account"),
            literal(0, Integer).label("is_placeholder"),
            app_by_subscriber.c.app_created_at.label("app_created_at"),
            func.coalesce(app_events_by_subscriber.c.app_event_count, 0).label("app_event_count"),
            app_events_by_subscriber.c.last_app_activity.label("last_app_activity"),
            func.coalesce(web_by_subscriber.c.web_event_count, 0).label("web_event_count"),
            func.coalesce(web_by_subscriber.c.web_active_days, 0).label("web_active_days"),
            web_by_subscriber.c.last_web_visit.label("last_web_visit"),
            first_utm.c.utm_source.label("first_utm_source"),
            _later(web_by_subscriber.c.last_web_visit, app_events_by_subscriber.c.last_app_activity).label("last_seen"),
        )
        .outerjoin(AcquisitionSource, AcquisitionSource.acquisition_source_id == Subscriber.acquisition_source_id)
        .outerjoin(app_by_subscriber, app_by_subscriber.c.key == Subscriber.subscriber_id)
        .outerjoin(app_events_by_subscriber, app_events_by_subscriber.c.key == Subscriber.subscriber_id)
        .outerjoin(web_by_subscriber, web_by_subscriber.c.key == Subscriber.subscriber_id)
        .outerjoin(first_utm, first_utm.c.subscriber_id == Subscriber.subscriber_id)
    )

    app_only = (
        select(
            (literal("u_") + AppUser.app_user_id).label("profile_id"),
            literal(None, Integer).label("subscriber_id"),
            AppUser.app_user_id.label("app_user_id"),
            AppUser.email.label("email"),
            literal(None, Integer).label("status"),
            literal(None, String).label("acquisition_source"),
            literal(None).label("signup_date"),
            literal(None).label("last_open_date"),
            literal(0, Integer).label("is_subscriber"),
            literal(1, Integer).label("has_app_account"),
            cast(AppUser.is_placeholder, Integer).label("is_placeholder"),
            AppUser.created_at.label("app_created_at"),
            func.coalesce(app_events_by_user.c.app_event_count, 0).label("app_event_count"),
            app_events_by_user.c.last_app_activity.label("last_app_activity"),
            func.coalesce(web_by_email.c.web_event_count, 0).label("web_event_count"),
            func.coalesce(web_by_email.c.web_active_days, 0).label("web_active_days"),
            web_by_email.c.last_web_visit.label("last_web_visit"),
            first_utm.c.utm_source.label("first_utm_source"),
            _later(web_by_email.c.last_web_visit, app_events_by_user.c.last_app_activity).label("last_seen"),
        )
        .outerjoin(app_events_by_user, app_events_by_user.c.key == AppUser.app_user_id)
        .outerjoin(web_by_email, web_by_email.c.key == AppUser.email)
        .outerjoin(first_utm, and_(first_utm.c.subscriber_id.is_(None), first_utm.c.email == AppUser.email))
        .where(AppUser.subscriber_id.is_(None))
    )

    return union_all(subscribers, app_only).subquery("people")


def has_app_event(people: Subquery, *conditions):
    """True when the person has an app event matching `conditions`. Each EXISTS is correlated to the
    people row explicitly, one level deep, so it can't silently turn into a cross join."""
    for_subscriber = exists(
        select(1)
        .select_from(AppEvent)
        .join(AppUser, AppUser.app_user_id == AppEvent.app_user_id)
        .where(AppUser.subscriber_id == people.c.subscriber_id, *conditions)
        .correlate(people)
    )
    for_app_user = exists(
        select(1).select_from(AppEvent).where(AppEvent.app_user_id == people.c.app_user_id, *conditions).correlate(people)
    )
    return or_(
        and_(people.c.subscriber_id.is_not(None), for_subscriber),
        and_(people.c.subscriber_id.is_(None), for_app_user),
    )


def has_web_event(people: Subquery, *conditions):
    """True when the person has a linked web event matching `conditions`."""
    for_subscriber = exists(
        select(1).select_from(WebEvent).where(WebEvent.subscriber_id == people.c.subscriber_id, *conditions).correlate(people)
    )
    for_app_user = exists(
        select(1)
        .select_from(WebEvent)
        .where(WebEvent.subscriber_id.is_(None), WebEvent.email == people.c.email, *conditions)
        .correlate(people)
    )
    return or_(
        and_(people.c.subscriber_id.is_not(None), for_subscriber),
        and_(people.c.subscriber_id.is_(None), for_app_user),
    )
