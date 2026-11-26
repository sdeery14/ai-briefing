"""The ``ai-briefing`` command.

Subcommands are added by the issues that implement them (RFC §3.5). So far there are
``db upgrade``, ``sources list`` and ``collect``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ai_briefing import __version__

if TYPE_CHECKING:
    from ai_briefing.sources.fetcher import Fetcher

DESCRIPTION = (
    "Evidence-first briefings on developments in AI, machine learning, data science and "
    "software engineering."
)
DATABASE_HELP = (
    "path to the database file (default: $AI_BRIEFING_DATABASE, else data/ai_briefing.sqlite3)"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-briefing", description=DESCRIPTION)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")

    db = commands.add_parser("db", help="manage the database")
    db_commands = db.add_subparsers(dest="db_command", metavar="action", required=True)
    upgrade = db_commands.add_parser("upgrade", help="apply migrations")
    upgrade.add_argument("--database", help=DATABASE_HELP)

    sources = commands.add_parser("sources", help="show the source catalogue")
    source_commands = sources.add_subparsers(
        dest="sources_command", metavar="action", required=True
    )
    source_commands.add_parser("list", help="list every source and what may be kept from it")

    collect = commands.add_parser("collect", help="fetch new items from the enabled sources")
    collect.add_argument("--source", help="collect from this source only (its id)")
    collect.add_argument("--database", help=DATABASE_HELP)
    return parser


def _fail(error: Exception) -> int:
    sys.stderr.write(f"ai-briefing: {error}\n")
    return 1


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
        return _fail(error)
    if before == after:
        sys.stdout.write(f"{path}: already at {after}\n")
    else:
        sys.stdout.write(f"{path}: upgraded from {before or 'empty'} to {after}\n")
    return 0


def _sources_list() -> int:
    from ai_briefing.sources.catalogue import CatalogueError, load_catalogue

    try:
        catalogue = load_catalogue()
    except CatalogueError as error:
        return _fail(error)
    width = max(len(source.id) for source in catalogue)
    for source in catalogue:
        state = "enabled " if source.enabled else "disabled"
        sys.stdout.write(
            f"{source.id.ljust(width)}  {state}  {source.mode.value:<13}  "
            f"model sees: {source.model_submission.value}\n"
        )
    return 0


def make_fetcher() -> Fetcher:
    """The fetcher used against real sources: the real transport and resolver, under the
    default network policy."""
    from ai_briefing.sources.fetcher import Fetcher
    from ai_briefing.sources.network import SystemResolver
    from ai_briefing.sources.transport import HttpTransport

    return Fetcher(
        transport=HttpTransport(),
        resolver=SystemResolver(),
        user_agent=f"ai-briefing/{__version__}",
    )


def _collect(database: str | None, only: str | None) -> int:
    from ai_briefing.sources.catalogue import CatalogueError, config_directory, load_catalogue
    from ai_briefing.sources.collect import collect
    from ai_briefing.storage import database as storage
    from ai_briefing.storage.lock import LockHeld, job_lock

    path = storage.database_path(database)
    try:
        catalogue = load_catalogue()
        configuration = (config_directory() / "sources.yaml").read_bytes()
        if not path.is_file():
            raise storage.StorageError(f"{path} does not exist; run `ai-briefing db upgrade` first")
        with job_lock(path):
            engine = storage.create_database_engine(path)
            try:
                if storage.current_revision(engine) != storage.head_revision():
                    raise storage.StorageError(
                        f"{path} is not at the current schema; run `ai-briefing db upgrade`"
                    )
                outcome = collect(
                    engine,
                    catalogue,
                    make_fetcher(),
                    application_version=__version__,
                    configuration_hash=hashlib.sha256(configuration).hexdigest(),
                    only=only,
                )
            finally:
                engine.dispose()
    except (CatalogueError, LockHeld, storage.StorageError, ValueError) as error:
        return _fail(error)
    sys.stdout.write(json.dumps(dict(outcome.counts), sort_keys=True) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command. ``--help`` and ``--version`` exit through argparse with status 0."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "db" and args.db_command == "upgrade":
        return _db_upgrade(args.database)
    if args.command == "sources" and args.sources_command == "list":
        return _sources_list()
    if args.command == "collect":
        return _collect(args.database, args.source)
    # No command given: show what the command is.
    parser.print_help()
    return 0
