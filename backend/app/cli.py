"""Command line tasks: python -m app.cli <command>"""

import argparse
import sys

from alembic import command
from alembic.config import Config

from app.auth.api_keys import create_api_key
from app.config import BACKEND_DIR, get_settings
from app.db import open_session
from app.importer.service import run_import
from app.importer.sources import LocalFolderSource
from app.seeds import seed_reference_data


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
    print("Database ready:", settings.resolved_database_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="apply migrations and seed reference data")
    key = sub.add_parser("create-api-key", help="create an API key for an external client")
    key.add_argument("name")
    sub.add_parser("import", help="import the CSVs from the configured source folder")
    args = parser.parse_args(argv)

    if args.command == "init-db":
        init_db()
        return 0

    with open_session() as session:
        if args.command == "create-api-key":
            print(create_api_key(session, args.name))
            print("Store this key now; it can't be shown again.", file=sys.stderr)
        elif args.command == "import":
            settings = get_settings()
            run = run_import(session, LocalFolderSource(settings.import_source_dir), settings)
            print(f"{run.status}: {run.message}")
            for name, stats in run.file_stats.items():
                print(f"  {name}: {stats}")
            if run.error_report_path:
                print(f"  error report: {run.error_report_path}")
            return 0 if run.status == "succeeded" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
