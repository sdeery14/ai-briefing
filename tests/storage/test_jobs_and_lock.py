"""A job runs once per idempotency key, and only one writer runs at a time (ADR-002)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import JobStatus
from ai_briefing.domain.records import JobRun, Story
from ai_briefing.runtime import cli
from ai_briefing.storage import repositories, schema
from ai_briefing.storage.jobs import JobOutcome, run_job
from ai_briefing.storage.lock import LockHeld, job_lock, lock_path

from .conftest import HASH, NOW


def row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            name: connection.execute(select(func.count()).select_from(table)).scalar_one()
            for name, table in schema.metadata.tables.items()
        }


def add_a_story(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
    repositories.add(connection, Story(title="A story", first_seen_at=NOW, last_activity_at=NOW))
    return {"stories": 1}


def run(engine: Engine, key: str = "collect:2026-11-19", work: object = add_a_story) -> JobOutcome:
    return run_job(
        engine,
        job="collect",
        idempotency_key=key,
        application_version="0.0.0",
        configuration_hash=HASH,
        work=work,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


# --- Idempotency ----------------------------------------------------------------------------


def test_running_a_job_twice_with_one_key_adds_no_rows(engine: Engine) -> None:
    first = run(engine)
    after_first = row_counts(engine)
    second = run(engine)
    assert first.ran is True
    assert second.ran is False
    assert second.job_run_id == first.job_run_id
    assert second.counts == {"stories": 1}
    assert row_counts(engine) == after_first
    assert after_first["stories"] == 1
    assert after_first["job_runs"] == 1


def test_the_work_is_not_called_again_for_a_key_that_succeeded(engine: Engine) -> None:
    calls: list[int] = []

    def work(connection: Connection, job_run_id: int) -> Mapping[str, int]:
        calls.append(job_run_id)
        return add_a_story(connection, job_run_id)

    for _ in range(3):
        run(engine, work=work)
    assert len(calls) == 1


def test_a_different_key_runs(engine: Engine) -> None:
    assert run(engine, key="collect:2026-11-19").ran is True
    assert run(engine, key="collect:2026-11-20").ran is True
    assert row_counts(engine)["stories"] == 2
    assert row_counts(engine)["job_runs"] == 2


def test_a_succeeded_run_is_recorded_as_a_valid_job_run(engine: Engine) -> None:
    outcome = run(engine)
    with engine.connect() as connection:
        stored = repositories.get(connection, JobRun, outcome.job_run_id)
    assert stored is not None
    assert stored.status is JobStatus.SUCCEEDED
    assert stored.counts == {"stories": 1}
    assert stored.ended_at == NOW
    assert stored.idempotency_key == "collect:2026-11-19"


def test_a_failed_job_writes_none_of_its_work_and_is_recorded_as_failed(engine: Engine) -> None:
    def work(connection: Connection, job_run_id: int) -> Mapping[str, int]:
        add_a_story(connection, job_run_id)
        raise RuntimeError("the feed was unreadable")

    with pytest.raises(RuntimeError, match="unreadable"):
        run(engine, work=work)
    counts = row_counts(engine)
    assert counts["stories"] == 0  # the work was rolled back
    assert counts["job_runs"] == 1  # the failure was recorded
    with engine.connect() as connection:
        stored = repositories.get(connection, JobRun, 1)
    assert stored is not None
    assert stored.status is JobStatus.FAILED
    assert stored.error == "RuntimeError: the feed was unreadable"


def test_a_key_that_failed_can_be_run_again_and_reuses_its_record(engine: Engine) -> None:
    def failing(connection: Connection, job_run_id: int) -> Mapping[str, int]:
        raise RuntimeError("first attempt")

    with pytest.raises(RuntimeError):
        run(engine, work=failing)
    outcome = run(engine)
    assert outcome.ran is True
    counts = row_counts(engine)
    assert counts["job_runs"] == 1
    assert counts["stories"] == 1
    with engine.connect() as connection:
        stored = repositories.get(connection, JobRun, outcome.job_run_id)
    assert stored is not None
    assert stored.status is JobStatus.SUCCEEDED
    assert stored.error is None
    # And now that it has succeeded, it does not run a third time.
    assert run(engine).ran is False


def test_a_job_and_its_completion_are_one_transaction(engine: Engine) -> None:
    seen: dict[str, int] = {}

    def work(connection: Connection, job_run_id: int) -> Mapping[str, int]:
        add_a_story(connection, job_run_id)
        # Another connection cannot see the story or the run until the job commits.
        seen.update(row_counts_uncommitted(engine))
        return {}

    def row_counts_uncommitted(other: Engine) -> dict[str, int]:
        import sqlite3

        path = other.url.database
        assert path is not None
        raw = sqlite3.connect(path)
        try:
            return {
                "stories": raw.execute("SELECT count(*) FROM stories").fetchone()[0],
                "job_runs": raw.execute("SELECT count(*) FROM job_runs").fetchone()[0],
            }
        finally:
            raw.close()

    run(engine, work=work)
    assert seen == {"stories": 0, "job_runs": 0}
    assert row_counts(engine)["stories"] == 1


# --- One writer -----------------------------------------------------------------------------


def test_a_second_writer_is_refused_while_the_lock_is_held(database_file: Path) -> None:
    with job_lock(database_file) as held:
        assert held == lock_path(database_file)
        with pytest.raises(LockHeld, match="another job holds"), job_lock(database_file):
            pytest.fail("a second writer got the lock")
    # Released: the next writer gets it.
    with job_lock(database_file):
        pass


def test_the_lock_is_released_when_the_job_fails(database_file: Path) -> None:
    with pytest.raises(RuntimeError), job_lock(database_file):
        raise RuntimeError("job failed")
    with job_lock(database_file):
        pass


HOLDER = """
import sys, time
from ai_briefing.storage.lock import job_lock
with job_lock(sys.argv[1]):
    sys.stdout.write("held\\n"); sys.stdout.flush()
    sys.stdin.readline()
"""


def test_another_process_is_refused_while_the_lock_is_held(database_file: Path) -> None:
    command = [sys.executable, "-c", HOLDER, str(database_file)]
    with subprocess.Popen(  # noqa: S603 - a fixed command: this interpreter and the script above
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    ) as holder:
        try:
            assert holder.stdout is not None
            assert holder.stdin is not None
            assert holder.stdout.readline().strip() == "held"
            with pytest.raises(LockHeld), job_lock(database_file):
                pytest.fail("got the lock while another process held it")
            holder.stdin.write("\n")
            holder.stdin.flush()
            assert holder.wait(timeout=30) == 0
        finally:
            if holder.poll() is None:
                holder.kill()
    with job_lock(database_file):
        pass


# --- ai-briefing db upgrade ------------------------------------------------------------------


def test_db_upgrade_creates_and_migrates_the_database(
    database_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["db", "upgrade", "--database", str(database_file)]) == 0
    assert "upgraded from empty to 0001_first_schema" in capsys.readouterr().out
    assert database_file.is_file()
    assert cli.main(["db", "upgrade", "--database", str(database_file)]) == 0
    assert "already at 0001_first_schema" in capsys.readouterr().out


def test_db_upgrade_uses_the_environment_when_no_path_is_given(
    database_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_BRIEFING_DATABASE", str(database_file))
    assert cli.main(["db", "upgrade"]) == 0
    assert database_file.is_file()


def test_db_upgrade_will_not_run_while_a_job_holds_the_lock(
    database_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with job_lock(database_file):
        assert cli.main(["db", "upgrade", "--database", str(database_file)]) == 1
    assert "another job holds" in capsys.readouterr().err
    assert not database_file.exists()
