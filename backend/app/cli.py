"""Command line tasks: python -m app.cli <command>"""

import argparse
import getpass
import os
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.auth.api_keys import create_api_key, revoke_api_key, rotate_api_key
from app.auth.passwords import hash_password
from app.config import BACKEND_DIR, get_settings
from app.db import open_session
from app.importer.service import run_import
from app.importer.sources import LocalFolderSource
from app.models import ApiClient, User
from app.seeds import seed_reference_data
from app.segments.catalog import seed_segments

MIN_PASSWORD_LENGTH = 12


def init_db() -> None:
    """Apply migrations and seed reference data. Safe to run repeatedly."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    command.upgrade(config, "head")
    with open_session() as session:
        seed_reference_data(session)
        added = seed_segments(session)
    print("Database ready:", settings.resolved_database_url, f"({added} catalog segments added)")


def _read_password(from_env: bool) -> str:
    # Only the start-up script reads CDP_INITIAL_PASSWORD (it passes --password-from-env). Otherwise always
    # prompt: that variable holds the first admin's password, and must never become another user's.
    password = os.environ.get("CDP_INITIAL_PASSWORD", "") if from_env else getpass.getpass("Password: ")
    if from_env and not password:
        raise SystemExit("--password-from-env needs CDP_INITIAL_PASSWORD to be set")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="apply migrations and seed reference data")
    sub.add_parser("import", help="import the CSVs from the configured source folder")
    user = sub.add_parser("create-user", help="create a UI user, or reset the password of an existing one")
    user.add_argument("username")
    user.add_argument("--admin", action="store_true")
    user.add_argument("--password-from-env", action="store_true", help="read the password from CDP_INITIAL_PASSWORD")
    user.add_argument("--if-missing", action="store_true", help="do nothing if the user already exists (for start-up)")
    key = sub.add_parser("create-api-key", help="create an API key for an external client")
    key.add_argument("name")
    sub.add_parser("list-api-keys", help="show API keys (prefixes only)")
    rotate = sub.add_parser("rotate-api-key", help="issue a replacement key; the old one works for 24 hours")
    rotate.add_argument("api_client_id", type=int)
    revoke = sub.add_parser("revoke-api-key", help="stop a key working immediately")
    revoke.add_argument("api_client_id", type=int)
    args = parser.parse_args(argv)

    if args.command == "init-db":
        init_db()
        return 0

    with open_session() as session:
        if args.command == "import":
            settings = get_settings()
            run = run_import(session, LocalFolderSource(settings.import_source_dir), settings)
            print(f"{run.status}: {run.message}")
            for name, stats in run.file_stats.items():
                print(f"  {name}: {stats}")
            if run.error_report_path:
                print(f"  error report: {run.error_report_path}")
            return 0 if run.status == "succeeded" else 1

        if args.command == "create-user":
            existing = session.scalar(select(User).where(User.username == args.username))
            if existing and args.if_missing:
                print(f"User {args.username} already exists; left unchanged")
                return 0
            password_hash = hash_password(_read_password(args.password_from_env))
            if existing:
                existing.password_hash = password_hash
                existing.is_admin = existing.is_admin or args.admin
            else:
                session.add(User(username=args.username, password_hash=password_hash, is_admin=args.admin))
            session.commit()
            print(f"{'Updated' if existing else 'Created'} user {args.username}")
        elif args.command == "create-api-key":
            print(create_api_key(session, args.name))
            print("Store this key now; it can't be shown again.", file=sys.stderr)
        elif args.command == "list-api-keys":
            for c in session.scalars(select(ApiClient).order_by(ApiClient.api_client_id)):
                state = "revoked" if c.revoked_at else f"expires {c.expires_at:%Y-%m-%d %H:%M}" if c.expires_at else "active"
                print(f"{c.api_client_id:>4}  {c.key_prefix}...  {c.name:<24} {state}")
        elif args.command == "rotate-api-key":
            print(rotate_api_key(session, args.api_client_id))
            print("New key above; the old key stops working in 24 hours.", file=sys.stderr)
        elif args.command == "revoke-api-key":
            revoke_api_key(session, args.api_client_id)
            print(f"Revoked API key {args.api_client_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
