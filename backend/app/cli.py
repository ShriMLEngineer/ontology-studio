"""Operational commands.

Usage (from the ``backend`` directory)::

    python -m app.cli migrate        # apply Alembic migrations
    python -m app.cli seed           # load the Supply Chain demo project into an empty database
    python -m app.cli seed-samples   # upload samples/supply-chain/*.csv|pdf into the demo project
"""

import argparse
import sys

from app.core.config import REPO_ROOT, get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_db_engine, create_session_factory
from app.modules.seed.service import seed_demo_data, seed_sample_sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["migrate", "seed", "seed-samples"])
    args = parser.parse_args(argv)
    settings = get_settings()

    upgrade_database(settings.database_url)
    if args.command == "migrate":
        print(f"Database migrated: {settings.database_url}")
        return 0

    engine = create_db_engine(settings.database_url)
    try:
        with create_session_factory(engine)() as session:
            if args.command == "seed":
                seeded = seed_demo_data(session)
                print("Seeded Supply Chain demo project." if seeded else "Database already has projects; seed skipped.")
            else:
                seed_demo_data(session)
                uploaded = seed_sample_sources(session, REPO_ROOT / "samples" / "supply-chain")
                print(f"Uploaded {len(uploaded)} sample source(s): {', '.join(uploaded) or 'none (already present)'}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
