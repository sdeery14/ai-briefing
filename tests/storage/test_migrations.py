"""The first migration builds the schema, can be undone, and matches the schema module
(ADR-002).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from ai_briefing.storage import database, schema

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "migrations"
FIRST = "0001_first_schema"
HEAD = "0002_screening_decisions"
REVISIONS = (FIRST, HEAD)


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def triggers(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
        ).all()
    return {row.name: row.sql for row in rows}


def test_an_empty_database_upgrades_to_the_head_revision(empty_engine: Engine) -> None:
    assert database.current_revision(empty_engine) is None
    database.upgrade(empty_engine)
    assert database.current_revision(empty_engine) == database.head_revision() == HEAD
    assert tables(empty_engine) == {*schema.metadata.tables, "alembic_version"}


def test_upgrade_then_downgrade_leaves_an_empty_database(empty_engine: Engine) -> None:
    database.upgrade(empty_engine)
    database.downgrade(empty_engine, "base")
    assert tables(empty_engine) == {"alembic_version"}
    assert triggers(empty_engine) == {}
    assert database.current_revision(empty_engine) is None
    # And it can be built again from there.
    database.upgrade(empty_engine)
    assert tables(empty_engine) == {*schema.metadata.tables, "alembic_version"}


def test_upgrading_twice_changes_nothing(engine: Engine) -> None:
    before = (tables(engine), triggers(engine))
    database.upgrade(engine)
    assert (tables(engine), triggers(engine)) == before


def test_the_migrated_database_matches_the_schema_module(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"render_as_batch": True})
        differences = compare_metadata(context, schema.metadata)
    assert differences == []


def test_the_migrated_triggers_are_the_ones_the_schema_module_defines(engine: Engine) -> None:
    def squash(statement: str) -> str:
        return re.sub(r"\s+", " ", statement).strip()

    found = {name: squash(sql) for name, sql in triggers(engine).items()}
    expected = {name: squash(sql) for name, sql in schema.trigger_statements().items()}
    assert found == expected
    assert len(expected) == 2 * len(schema.APPEND_ONLY) + 2 * len(schema.PURGEABLE)


def test_the_migration_is_frozen_and_uses_batch_mode() -> None:
    for revision in REVISIONS:
        migration = (MIGRATIONS / "versions" / f"{revision}.py").read_text(encoding="utf-8")
        # A migration that imported the application would change when the application does.
        assert not re.search(r"^\s*(?:from|import)\s+ai_briefing", migration, re.MULTILINE)
    assert "render_as_batch=True" in (MIGRATIONS / "env.py").read_text(encoding="utf-8")
    found = sorted(p.name for p in (MIGRATIONS / "versions").glob("*.py"))
    assert found == [f"{revision}.py" for revision in REVISIONS]


def test_each_migration_can_be_undone_one_step_at_a_time(empty_engine: Engine) -> None:
    database.upgrade(empty_engine)
    for revision in reversed(REVISIONS[:-1]):
        database.downgrade(empty_engine, revision)
        assert database.current_revision(empty_engine) == revision
    assert "screening_decisions" not in tables(empty_engine)
    assert "source_documents" in tables(empty_engine)
    assert not [name for name in triggers(empty_engine) if name.startswith("screening_")]
    database.upgrade(empty_engine)
    assert database.current_revision(empty_engine) == HEAD


def test_every_connection_has_the_required_settings(engine: Engine) -> None:
    for _ in range(2):  # a second connection is configured like the first
        with engine.connect() as connection:
            assert database.settings(connection) == {
                "foreign_keys": 1,
                "busy_timeout": database.BUSY_TIMEOUT_MS,
                "journal_mode": "wal",
            }
        engine.dispose()


def test_foreign_keys_are_enforced(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO document_observations "
                "(document_id, retrieved_at, fetch_status, content_hash) "
                "VALUES (999, '2026-11-19T11:15:00.000000+00:00', 'ok', :hash)"
            ),
            {"hash": "a" * 64},
        )


def test_a_write_transaction_takes_its_lock_at_the_start(engine: Engine) -> None:
    statements: list[str] = []
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        assert raw is not None
        raw.set_trace_callback(statements.append)
        with connection.begin():
            connection.execute(text("SELECT 1"))
        raw.set_trace_callback(None)
    assert statements[0] == "BEGIN IMMEDIATE"


def test_a_missing_migrations_directory_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(database.MIGRATIONS_ENV, str(tmp_path / "nowhere"))
    with pytest.raises(database.StorageError, match="no migrations found"):
        database.migrations_directory()
    monkeypatch.setenv(database.MIGRATIONS_ENV, str(MIGRATIONS))
    assert database.migrations_directory() == MIGRATIONS


def test_the_database_path_comes_from_the_argument_then_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(database.DATABASE_ENV, raising=False)
    assert database.database_path() == database.DEFAULT_DATABASE
    monkeypatch.setenv(database.DATABASE_ENV, str(tmp_path / "env.sqlite3"))
    assert database.database_path() == tmp_path / "env.sqlite3"
    assert database.database_path(tmp_path / "arg.sqlite3") == tmp_path / "arg.sqlite3"
