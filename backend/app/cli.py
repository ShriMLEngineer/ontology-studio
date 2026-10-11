"""Operational commands.

Usage (from the ``backend`` directory)::

    python -m app.cli migrate   # apply Alembic migrations
    python -m app.cli seed      # load the Supply Chain demo project into an empty database
"""

import argparse
import sys

from app.core.config import get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_db_engine, create_session_factory
from app.modules.seed.service import seed_demo_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["migrate", "seed"])
    args = parser.parse_args(argv)
    settings = get_settings()

    upgrade_database(settings.database_url)
    if args.command == "migrate":
        print(f"Database migrated: {settings.database_url}")
        return 0

    engine = create_db_engine(settings.database_url)
    try:
        with create_session_factory(engine)() as session:
            seeded = seed_demo_data(session)
    finally:
        engine.dispose()
    print("Seeded Supply Chain demo project." if seeded else "Database already has projects; seed skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
