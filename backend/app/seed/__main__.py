"""``python -m app.seed`` — generate and load the corpus.

Run at image build time (docs/12 §3.7) and locally when iterating on the corpus. It is
not part of container start: cold start is already 45–75 s and generation would add to
it for no benefit, since the data is identical every time.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.db.engine import Database
from app.seed import clear, generate, write
from app.seed.generator import SEED, SEED_VERSION

#: `backend/`, from `backend/app/seed/__main__.py`.
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def ensure_schema(db_path: Path) -> None:
    """Bring the database to the migration head before touching a row.

    docs/12 §3.7 says "migrate, then seed", and until now that ordering lived only in the
    Dockerfile. Every other caller — `scripts/dev.sh` on a fresh clone, both CI workflows,
    a contributor following the getting-started guide — ran the seed against a database
    with no tables and got `no such table: ticket_event` from three frames deep in
    SQLAlchemy, which names neither the cause nor the fix.

    Doing it here makes the ordering a property of the command rather than a thing each
    caller has to remember.
    """
    # Imported lazily: alembic is only needed for this, and `--dry-run` should not pay for
    # it just to print counts.
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    # Both set explicitly. `script_location` is relative in alembic.ini, so it resolves
    # against the working directory — which is whatever the caller happened to be in.
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{db_path}")
    command.upgrade(config, "head")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.seed", description=__doc__)
    parser.add_argument("--output", type=Path, help="database path (default: settings.db_path)")
    parser.add_argument("--reset", action="store_true", help="delete existing rows first")
    parser.add_argument("--seed", type=int, default=SEED, help=f"RNG seed (default {SEED})")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate and report counts without touching a database",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("app.seed")

    corpus = generate(args.seed)
    counts = corpus.counts()

    log.info("seed=%s version=%s digest=%s", args.seed, SEED_VERSION, corpus.digest()[:16])
    for name, count in counts.items():
        log.info("  %-14s %5d", name, count)
    log.info("  %-14s %5d", "TOTAL", corpus.total_rows())

    if args.dry_run:
        return 0

    if args.output is not None:
        db_path = args.output
    else:
        from app.config import get_settings

        db_path = get_settings().db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_schema(db_path)

    db = Database(db_path)
    try:
        if args.reset:
            clear(db)
        write(db, corpus)
    finally:
        db.dispose()

    log.info("wrote %s rows to %s", corpus.total_rows(), db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
