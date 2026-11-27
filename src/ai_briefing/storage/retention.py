"""The retention purge (ADR-010, RFC §11).

Fetched article text and model-call request payloads are private and are kept for a
limited time. After that this job sets them to null and records when it did. Nothing
else changes: the observation's content hash, the document's metadata, the feed summary
and the quotations already stored as evidence all remain, so a quotation check made
before the purge can still be audited after it.

How long each is kept:

- **Article text:** the source's ``retention_days.body``, counted from when the text was
  retrieved. Text held for a source that states no body retention now (it left the
  catalogue, or no longer stores bodies) has no permission behind it and is purged at once.
- **Request payloads:** they contain source text from any source, so they are kept for the
  shortest body retention in the catalogue, and never longer than ADR-010's 90 days.

The database allows exactly this change to these two tables and no other (see
``schema.PURGEABLE``). Running the purge twice changes nothing the second time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Engine, select, update
from sqlalchemy.engine import Connection

from ai_briefing.domain.records import MAX_BODY_RETENTION_DAYS, Source
from ai_briefing.storage import schema
from ai_briefing.storage.jobs import JobOutcome, run_job, utc_now


def body_retention(catalogue: Sequence[Source]) -> dict[str, int]:
    """Days each source's article text is kept, for the sources that state it."""
    return {
        source.id: source.retention_days.body
        for source in catalogue
        if source.retention_days.body is not None
    }


def request_retention(catalogue: Sequence[Source]) -> int:
    """Days a model-call request payload is kept."""
    return min([MAX_BODY_RETENTION_DAYS, *body_retention(catalogue).values()])


def purge_now(connection: Connection, catalogue: Sequence[Source], now: datetime) -> dict[str, int]:
    """Null what is past its retention, in the caller's transaction, and return counts."""
    observations = schema.document_observations
    documents = schema.source_documents
    calls = schema.llm_calls
    days = body_retention(catalogue)

    def purge_bodies(of_source: ColumnElement[bool], older_than: datetime | None) -> int:
        held = observations.c.body_text.is_not(None)
        from_source = observations.c.document_id.in_(select(documents.c.id).where(of_source))
        statement = update(observations).where(held, from_source)
        if older_than is not None:
            statement = statement.where(observations.c.retrieved_at <= older_than)
        result = connection.execute(statement.values(body_text=None, body_purged_at=now))
        return int(result.rowcount)

    bodies = 0
    for source_id, kept_for in sorted(days.items()):
        bodies += purge_bodies(documents.c.source_id == source_id, now - timedelta(days=kept_for))
    unpermitted = purge_bodies(documents.c.source_id.not_in(list(days)), None)
    requests = connection.execute(
        update(calls)
        .where(
            calls.c.request_payload.is_not(None),
            calls.c.created_at <= now - timedelta(days=request_retention(catalogue)),
        )
        .values(request_payload=None, request_purged_at=now)
    )
    return {
        "bodies_purged": bodies + unpermitted,
        "bodies_without_permission": unpermitted,
        "requests_purged": int(requests.rowcount),
    }


def purge(
    engine: Engine,
    catalogue: Sequence[Source],
    *,
    day: str,
    application_version: str,
    configuration_hash: str,
    run_again: bool = False,
    clock: Callable[[], datetime] = utc_now,
) -> JobOutcome:
    """Apply the retention policy as a recorded job, once for ``day`` unless ``run_again``."""

    def work(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
        return purge_now(connection, catalogue, clock())

    return run_job(
        engine,
        job="purge",
        idempotency_key=f"purge:{day}",
        application_version=application_version,
        configuration_hash=configuration_hash,
        work=work,
        run_again=run_again,
        clock=clock,
    )
