"""Opening the SQLite database with the settings ADR-002 requires, and migrating it.

Every connection gets foreign keys on, a busy timeout and write-ahead logging. A write
transaction takes its lock at ``BEGIN`` (``BEGIN IMMEDIATE``), so two writers cannot both
read and then collide on the write.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import Connection

BUSY_TIMEOUT_MS = 5000
DATABASE_ENV = "AI_BRIEFING_DATABASE"
MIGRATIONS_ENV = "AI_BRIEFING_MIGRATIONS"
DEFAULT_DATABASE = Path("data") / "ai_briefing.sqlite3"


class StorageError(RuntimeError):
    """The database could not be opened or migrated as asked."""


def database_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Where the database is: the argument, else ``AI_BRIEFING_DATABASE``, else ``data/``."""
    chosen = explicit or os.environ.get(DATABASE_ENV) or DEFAULT_DATABASE
    return Path(chosen)


def create_database_engine(path: str | os.PathLike[str]) -> Engine:
    """An engine for the database file at ``path``, with the required settings applied."""
    engine = create_engine(f"sqlite:///{Path(path).as_posix()}")

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection: Any, _record: Any) -> None:
        # The driver would otherwise open transactions on its own schedule. Autocommit
        # mode leaves that to the "begin" hook below.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _begin_immediate(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def settings(connection: Connection) -> dict[str, Any]:
    """The settings in force on a connection, for ``doctor`` and for tests."""
    return {
        "foreign_keys": connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one(),
        "busy_timeout": connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one(),
        "journal_mode": connection.exec_driver_sql("PRAGMA journal_mode").scalar_one(),
    }


def migrations_directory() -> Path:
    """The Alembic scripts: ``AI_BRIEFING_MIGRATIONS``, else ``migrations/`` in the checkout.

    RFC §3.4 puts migrations at the repository root, outside the package. From a source
    checkout that is three levels above this file. An installation that does not sit in a
    checkout must say where they are.
    """
    override = os.environ.get(MIGRATIONS_ENV)
    directory = Path(override) if override else Path(__file__).resolve().parents[3] / "migrations"
    if not (directory / "env.py").is_file():
        raise StorageError(
            f"no migrations found at {directory}; set {MIGRATIONS_ENV} to the migrations directory"
        )
    return directory


def _alembic_config(connection: Connection) -> Config:
    config = Config()
    config.set_main_option("script_location", migrations_directory().as_posix())
    config.attributes["connection"] = connection
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Apply migrations up to ``revision``."""
    with engine.connect() as connection:
        command.upgrade(_alembic_config(connection), revision)
        connection.commit()


def downgrade(engine: Engine, revision: str) -> None:
    """Undo migrations down to ``revision`` (``base`` for an empty database)."""
    with engine.connect() as connection:
        command.downgrade(_alembic_config(connection), revision)
        connection.commit()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> str | None:
    config = Config()
    config.set_main_option("script_location", migrations_directory().as_posix())
    return ScriptDirectory.from_config(config).get_current_head()
