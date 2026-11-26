"""The ``ai-briefing`` command.

Subcommands are added by the issues that implement them (RFC §3.5). So far there is
``db upgrade``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ai_briefing import __version__

DESCRIPTION = (
    "Evidence-first briefings on developments in AI, machine learning, data science and "
    "software engineering."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-briefing", description=DESCRIPTION)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")

    db = commands.add_parser("db", help="manage the database")
    db_commands = db.add_subparsers(dest="db_command", metavar="action", required=True)
    upgrade = db_commands.add_parser("upgrade", help="apply migrations")
    upgrade.add_argument(
        "--database",
        help="path to the database file (default: $AI_BRIEFING_DATABASE, "
        "else data/ai_briefing.sqlite3)",
    )
    return parser


def _db_upgrade(database: str | None) -> int:
    # Imported here so that `--help` and `--version` open no database library.
    from ai_briefing.storage import database as storage
    from ai_briefing.storage.lock import LockHeld, job_lock

    path = storage.database_path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with job_lock(path):
            engine = storage.create_database_engine(path)
            try:
                before = storage.current_revision(engine)
                storage.upgrade(engine)
                after = storage.current_revision(engine)
            finally:
                engine.dispose()
    except (LockHeld, storage.StorageError) as error:
        sys.stderr.write(f"ai-briefing: {error}\n")
        return 1
    if before == after:
        sys.stdout.write(f"{path}: already at {after}\n")
    else:
        sys.stdout.write(f"{path}: upgraded from {before or 'empty'} to {after}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command. ``--help`` and ``--version`` exit through argparse with status 0."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "db" and args.db_command == "upgrade":
        return _db_upgrade(args.database)
    # No command given: show what the command is.
    parser.print_help()
    return 0
