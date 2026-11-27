"""Running a job once per idempotency key (ADR-002, RFC §5 ``JobRun``).

A job has three steps, each its own transaction:

1. The run is recorded as ``running``, and committed, so that anything the job does next
   can refer to it.
2. ``prepare`` runs with no transaction open. This is where a job calls a model. Each call
   is recorded at once, in its own transaction, by
   :func:`ai_briefing.storage.repositories.record_model_call`. A call costs money whether
   or not the job goes on to succeed, so its record must not depend on the job's success.
3. ``work`` writes the job's results, and the run is marked ``succeeded``, in one
   transaction. Either both exist or neither does.

Running a key that has already succeeded does nothing. A failure rolls step 3 back, is
recorded, and leaves the key free to run again; the model calls already recorded stay.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import JobStatus
from ai_briefing.runtime import tracing
from ai_briefing.storage import schema

Clock = Callable[[], datetime]
Prepare = Callable[[int], None]
"""Step 2: given the job run's id, do whatever must happen outside a transaction."""
Work = Callable[[Connection, int], Mapping[str, int] | None]
"""Step 3: given the open transaction and the job run's id, write the results and return
counts to record."""


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
    prepare: Prepare | None = None,
    run_again: bool = False,
    clock: Clock = utc_now,
) -> JobOutcome:
    """Run a job unless this key has already succeeded.

    With ``run_again`` the job runs even if the key succeeded before, reusing its record.
    That is for a job whose own work is what makes a repeat harmless, such as composing a
    briefing, which stores a new version only when the content differs.

    The caller holds the job lock (:func:`ai_briefing.storage.lock.job_lock`), so no other
    writer runs at the same time and a run left ``running`` by a crash can be taken over.
    """
    runs = schema.job_runs
    with engine.begin() as connection:
        existing = connection.execute(
            select(runs.c.id, runs.c.status, runs.c.counts).where(
                runs.c.idempotency_key == idempotency_key
            )
        ).one_or_none()
        succeeded = existing is not None and existing.status == JobStatus.SUCCEEDED.value
        if existing is not None and succeeded and not run_again:
            return JobOutcome(existing.id, ran=False, counts=json.loads(existing.counts))
        values = {
            "job": job,
            "started_at": clock(),
            "ended_at": None,
            "status": JobStatus.RUNNING.value,
            "counts": "{}",
            "error": None,
            "application_version": application_version,
            "configuration_hash": configuration_hash,
        }
        if existing is None:
            job_run_id: int = connection.execute(
                insert(runs).values(idempotency_key=idempotency_key, **values).returning(runs.c.id)
            ).scalar_one()
        else:
            # An earlier attempt failed or crashed, or the job is one that runs again.
            # The same row is used.
            job_run_id = existing.id
            connection.execute(update(runs).where(runs.c.id == job_run_id).values(**values))
    try:
        # The job's root span (ADR-009). With no tracer installed this does nothing.
        with tracing.span("job", job=job, job_run_id=job_run_id):
            if prepare is not None:
                prepare(job_run_id)
            with engine.begin() as connection:
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
    except Exception as error:
        with engine.begin() as connection:
            connection.execute(
                update(runs)
                .where(runs.c.id == job_run_id)
                .values(
                    status=JobStatus.FAILED.value,
                    ended_at=clock(),
                    error=f"{type(error).__name__}: {error}"[:500],
                )
            )
        raise
    return JobOutcome(job_run_id, ran=True, counts=counts)
