"""Running a job once per idempotency key (ADR-002, RFC §5 ``JobRun``).

A job's work and the record that it succeeded are written in one transaction. So either
both exist or neither does, and running a key that has already succeeded does nothing.
A failure rolls the work back and is then recorded on its own, so it can be seen and the
key can be run again.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import JobStatus
from ai_briefing.storage import schema

Clock = Callable[[], datetime]
Work = Callable[[Connection, int], Mapping[str, int] | None]
"""The job's work: given the open transaction and the job run's id, do the writes and
return counts to record."""


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class JobOutcome:
    job_run_id: int
    ran: bool  # False when the key had already succeeded and nothing was done
    counts: Mapping[str, int]


def run_job(
    engine: Engine,
    *,
    job: str,
    idempotency_key: str,
    application_version: str,
    configuration_hash: str,
    work: Work,
    clock: Clock = utc_now,
) -> JobOutcome:
    """Run ``work`` unless this key has already succeeded.

    The caller holds the job lock (:func:`ai_briefing.storage.lock.job_lock`), so no other
    writer runs at the same time.
    """
    runs = schema.job_runs
    started = clock()
    try:
        with engine.begin() as connection:
            existing = connection.execute(
                select(runs.c.id, runs.c.status, runs.c.counts).where(
                    runs.c.idempotency_key == idempotency_key
                )
            ).one_or_none()
            if existing is not None and existing.status == JobStatus.SUCCEEDED.value:
                return JobOutcome(existing.id, ran=False, counts=json.loads(existing.counts))
            values = {
                "job": job,
                "started_at": started,
                "ended_at": None,
                "status": JobStatus.RUNNING.value,
                "counts": "{}",
                "error": None,
                "application_version": application_version,
                "configuration_hash": configuration_hash,
            }
            if existing is None:
                job_run_id = connection.execute(
                    insert(runs)
                    .values(idempotency_key=idempotency_key, **values)
                    .returning(runs.c.id)
                ).scalar_one()
            else:
                # An earlier attempt failed. The same row is used again.
                job_run_id = existing.id
                connection.execute(update(runs).where(runs.c.id == job_run_id).values(**values))
            counts = dict(work(connection, job_run_id) or {})
            connection.execute(
                update(runs)
                .where(runs.c.id == job_run_id)
                .values(
                    status=JobStatus.SUCCEEDED.value,
                    ended_at=clock(),
                    counts=json.dumps(counts, sort_keys=True),
                )
            )
            return JobOutcome(job_run_id, ran=True, counts=counts)
    except Exception as error:
        _record_failure(
            engine,
            job=job,
            idempotency_key=idempotency_key,
            application_version=application_version,
            configuration_hash=configuration_hash,
            started=started,
            ended=clock(),
            error=f"{type(error).__name__}: {error}"[:500],
        )
        raise


def _record_failure(
    engine: Engine,
    *,
    job: str,
    idempotency_key: str,
    application_version: str,
    configuration_hash: str,
    started: datetime,
    ended: datetime,
    error: str,
) -> None:
    runs = schema.job_runs
    values = {
        "job": job,
        "started_at": started,
        "ended_at": ended,
        "status": JobStatus.FAILED.value,
        "counts": "{}",
        "error": error,
        "application_version": application_version,
        "configuration_hash": configuration_hash,
    }
    with engine.begin() as connection:
        existing = connection.execute(
            select(runs.c.id, runs.c.status).where(runs.c.idempotency_key == idempotency_key)
        ).one_or_none()
        if existing is None:
            connection.execute(insert(runs).values(idempotency_key=idempotency_key, **values))
        elif existing.status != JobStatus.SUCCEEDED.value:
            connection.execute(update(runs).where(runs.c.id == existing.id).values(**values))
