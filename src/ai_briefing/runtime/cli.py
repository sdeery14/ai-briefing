"""The ``ai-briefing`` command.

Subcommands are added by the issues that implement them (RFC §3.5). So far there are
``db upgrade``, ``sources list``, ``collect``, ``process`` and ``briefing generate``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from ai_briefing import __version__

if TYPE_CHECKING:
    from ai_briefing.sources.fetcher import Fetcher

DESCRIPTION = (
    "Evidence-first briefings on developments in AI, machine learning, data science and "
    "software engineering."
)
TIMEZONE_ENV = "AI_BRIEFING_TIMEZONE"
TIMEZONE_HELP = "IANA time zone of the briefing's day (default: $AI_BRIEFING_TIMEZONE, else UTC)"
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

    process = commands.add_parser(
        "process", help="screen, fetch, assess, verify and decide the collected items"
    )
    process.add_argument("--date", help="the local date to process (default: today)")
    process.add_argument("--timezone", help=TIMEZONE_HELP)
    process.add_argument("--database", help=DATABASE_HELP)
    process.add_argument(
        "--replay",
        metavar="DIR",
        help="answer model calls from recorded responses in DIR; uses no API key",
    )

    briefing = commands.add_parser("briefing", help="compose and show briefings")
    briefing_commands = briefing.add_subparsers(
        dest="briefing_command", metavar="action", required=True
    )
    generate = briefing_commands.add_parser("generate", help="compose and store a day's briefing")
    generate.add_argument("--date", help="the local date of the briefing (default: today)")
    generate.add_argument("--timezone", help=TIMEZONE_HELP)
    generate.add_argument("--database", help=DATABASE_HELP)
    generate.add_argument(
        "--format", choices=("markdown", "json"), default="markdown", help="what to print"
    )
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


def _day(date_text: str | None, timezone_text: str | None) -> tuple[date, str]:
    """The local date and time zone a command is for."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    timezone = timezone_text or os.environ.get(TIMEZONE_ENV) or "UTC"
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"unknown time zone {timezone!r}") from error
    if date_text is None:
        return datetime.now(zone).date(), timezone
    try:
        return date.fromisoformat(date_text), timezone
    except ValueError as error:
        raise ValueError(f"not a date (YYYY-MM-DD): {date_text!r}") from error


def _configuration_hash() -> str:
    """A hash of the configuration files a run was made under."""
    from ai_briefing.sources.catalogue import config_directory

    digest = hashlib.sha256()
    for name in ("sources.yaml", "models.yaml"):
        digest.update((config_directory() / name).read_bytes())
    return digest.hexdigest()


def _process(
    database: str | None, date_text: str | None, timezone_text: str | None, replay: str | None
) -> int:
    from pathlib import Path

    from ai_briefing.domain.enums import ModelTask
    from ai_briefing.editorial.process import Settings, process
    from ai_briefing.llm.backends import AnthropicBackend, Backend, ReplayBackend
    from ai_briefing.llm.client import ModelClient
    from ai_briefing.llm.config import ModelsConfigError, load_models_config
    from ai_briefing.llm.credentials import MissingApiKey, load_api_key
    from ai_briefing.sources.catalogue import CatalogueError, load_catalogue
    from ai_briefing.storage import database as storage
    from ai_briefing.storage.lock import LockHeld, job_lock

    path = storage.database_path(database)
    try:
        day, _timezone = _day(date_text, timezone_text)
        catalogue = load_catalogue()
        config = load_models_config()
        backend: Backend
        if replay is not None:
            backend = ReplayBackend(Path(replay))
        else:
            key = load_api_key(config.provider.api_key_env)
            backend = AnthropicBackend(key, api_version=config.provider.api_version)
        if not path.is_file():
            raise storage.StorageError(f"{path} does not exist; run `ai-briefing db upgrade` first")
        with job_lock(path):
            engine = storage.create_database_engine(path)
            try:
                if storage.current_revision(engine) != storage.head_revision():
                    raise storage.StorageError(
                        f"{path} is not at the current schema; run `ai-briefing db upgrade`"
                    )
                counts = process(
                    engine,
                    catalogue,
                    ModelClient(engine=engine, config=config, backend=backend),
                    make_fetcher(),
                    config.for_task(ModelTask.ASSESSMENT)[0],
                    Settings(
                        application_version=__version__,
                        configuration_hash=_configuration_hash(),
                        day=day.isoformat(),
                    ),
                )
            finally:
                engine.dispose()
    except (
        CatalogueError,
        ModelsConfigError,
        MissingApiKey,
        LockHeld,
        storage.StorageError,
        ValueError,
        OSError,
    ) as error:
        return _fail(error)
    sys.stdout.write(json.dumps({k: dict(v) for k, v in counts.items()}, sort_keys=True) + "\n")
    return 0


def _briefing_generate(
    database: str | None, date_text: str | None, timezone_text: str | None, output: str
) -> int:
    from ai_briefing.briefings.compose import BriefingError, compose
    from ai_briefing.briefings.render import to_markdown
    from ai_briefing.sources.catalogue import CatalogueError, load_catalogue
    from ai_briefing.storage import database as storage
    from ai_briefing.storage.lock import LockHeld, job_lock

    path = storage.database_path(database)
    try:
        day, timezone = _day(date_text, timezone_text)
        catalogue = load_catalogue()
        if not path.is_file():
            raise storage.StorageError(f"{path} does not exist; run `ai-briefing db upgrade` first")
        with job_lock(path):
            engine = storage.create_database_engine(path)
            try:
                with engine.begin() as connection:
                    composed = compose(
                        connection,
                        catalogue,
                        local_date=day,
                        timezone=timezone,
                        configuration_hash=_configuration_hash(),
                        now=datetime.now(UTC),
                    )
            finally:
                engine.dispose()
    except (
        BriefingError,
        CatalogueError,
        LockHeld,
        storage.StorageError,
        ValueError,
        OSError,
    ) as error:
        return _fail(error)
    content = composed.briefing.document()
    if output == "json":
        sys.stdout.write(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(to_markdown(content))
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
    if args.command == "process":
        return _process(args.database, args.date, args.timezone, args.replay)
    if args.command == "briefing" and args.briefing_command == "generate":
        return _briefing_generate(args.database, args.date, args.timezone, args.format)
    # No command given: show what the command is.
    parser.print_help()
    return 0
