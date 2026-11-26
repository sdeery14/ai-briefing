"""Writing domain records to the database and reading them back.

The interface for history is deliberately small: :func:`add` and :func:`get`. There is no
function here that updates or deletes a history record, and the database's own triggers
refuse it if some other code tries (see ``migrations/``). Queries that only a later issue
needs are added by that issue.

Almost every function takes an open connection, so the caller decides the transaction. A
job passes the connection :func:`ai_briefing.storage.jobs.run_job` gives it, which makes
the job's writes and its completion one transaction.

The exception is :func:`record_model_call`. A model call has been paid for whatever
happens next, so its record is committed at once, in a transaction of its own, and cannot
be lost when a job fails and rolls back.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

from sqlalchemy import Engine, Table, delete, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import MembershipAction
from ai_briefing.domain.records import (
    AssessmentInput,
    Briefing,
    BriefingItem,
    DimensionScores,
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
    EvidenceItem,
    JobRun,
    LLMCall,
    Record,
    Source,
    SourceDocument,
    Story,
    StoryMembershipEvent,
)
from ai_briefing.storage import schema
from ai_briefing.storage.jobs import utc_now

R = TypeVar("R", bound=Record)
Row = Mapping[str, Any]

_SCORES = ("impact", "evidence", "novelty", "professional_relevance", "maturity")


def _plain(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.value if isinstance(v, Enum) else v) for k, v in values.items()}


def _columns(record: Record) -> dict[str, Any]:
    """A record's fields as column values, without the id the database assigns."""
    values = record.model_dump()
    values.pop("id", None)
    return _plain(values)


def _assessment_to_row(record: Record) -> dict[str, Any]:
    values = _columns(record)
    scores = values.pop("scores")
    values.update({f"score_{name}": scores[name] for name in _SCORES})
    return values


def _assessment_from_row(row: Row) -> dict[str, Any]:
    values = dict(row)
    values["scores"] = DimensionScores(**{name: values.pop(f"score_{name}") for name in _SCORES})
    return values


def _decision_to_row(record: Record) -> dict[str, Any]:
    values = _columns(record)
    values["ceiling_reasons"] = json.dumps(list(values["ceiling_reasons"]))
    return values


def _decision_from_row(row: Row) -> dict[str, Any]:
    values = dict(row)
    values["ceiling_reasons"] = tuple(json.loads(values["ceiling_reasons"]))
    return values


def _job_from_row(row: Row) -> dict[str, Any]:
    values = dict(row)
    values["counts"] = json.loads(values["counts"])
    return values


def _call_from_row(row: Row) -> dict[str, Any]:
    values = dict(row)
    for extra in ("request_payload", "request_purged_at", "response_payload", "created_at"):
        values.pop(extra)
    return values


# For each stored record type: its table, and how its fields map to and from columns.
_STORED: dict[
    type[Record],
    tuple[Table, Callable[[Record], dict[str, Any]], Callable[[Row], dict[str, Any]]],
] = {
    SourceDocument: (schema.source_documents, _columns, dict),
    DocumentObservation: (schema.document_observations, _columns, dict),
    Story: (schema.stories, _columns, dict),
    StoryMembershipEvent: (schema.story_membership_events, _columns, dict),
    EditorialAssessment: (schema.editorial_assessments, _assessment_to_row, _assessment_from_row),
    EvidenceItem: (schema.evidence_items, _columns, dict),
    EditorialDecision: (schema.editorial_decisions, _decision_to_row, _decision_from_row),
    Briefing: (schema.briefings, _columns, dict),
    BriefingItem: (schema.briefing_items, _columns, dict),
    LLMCall: (schema.llm_calls, _columns, _call_from_row),
    JobRun: (schema.job_runs, _columns, _job_from_row),
}
# JobRun is written only by run_job. LLMCall is written only by record_model_call, in its
# own transaction, so that a job that rolls back cannot take the record of a paid call
# with it.
_NOT_ADDED_HERE = (JobRun, LLMCall)


def add[R: Record](connection: Connection, record: R) -> R:
    """Insert a new record and return it with the id the database gave it."""
    kind = type(record)
    if kind in _NOT_ADDED_HERE or kind not in _STORED:
        raise TypeError(f"{kind.__name__} is not added through this function")
    if getattr(record, "id", None) is not None:
        raise ValueError(f"this {kind.__name__} already has an id; history is not rewritten")
    table, to_row, _ = _STORED[kind]
    new_id = connection.execute(
        insert(table).values(**to_row(record)).returning(table.c.id)
    ).scalar_one()
    return record.model_copy(update={"id": new_id})


def record_model_call(
    engine: Engine,
    call: LLMCall,
    *,
    now: Callable[[], datetime] = utc_now,
    request_payload: str | None = None,
    response_payload: str | None = None,
) -> LLMCall:
    """Record a model call durably, at once, and return it with its id.

    This opens and commits its own transaction. Call it from a job's ``prepare`` step,
    where no transaction is open: SQLite has one writer, so calling it while the job's
    write transaction is open would wait for that transaction and then fail.

    The request payload holds source text, so the retention purge nulls it later
    (ADR-010). The response is the system's own and is kept.
    """
    if call.id is not None:
        raise ValueError("this LLMCall already has an id; history is not rewritten")
    table = schema.llm_calls
    values = _columns(call)
    values["created_at"] = now()
    values["request_payload"] = request_payload
    values["response_payload"] = response_payload
    with engine.begin() as connection:
        new_id = connection.execute(
            insert(table).values(**values).returning(table.c.id)
        ).scalar_one()
    return call.model_copy(update={"id": new_id})


def get[R: Record](connection: Connection, kind: type[R], record_id: int) -> R | None:
    """The record of this type with this id, or ``None``."""
    table, _, from_row = _STORED[kind]
    row = connection.execute(select(table).where(table.c.id == record_id)).mappings().one_or_none()
    return None if row is None else kind.model_validate(from_row(dict(row)))


def add_assessment_inputs(
    connection: Connection, assessment_id: int, observation_ids: list[int]
) -> list[AssessmentInput]:
    """Record exactly which observations an assessment was shown."""
    inputs = [
        AssessmentInput(assessment_id=assessment_id, observation_id=observation_id)
        for observation_id in observation_ids
    ]
    if inputs:
        connection.execute(insert(schema.assessment_inputs), [i.model_dump() for i in inputs])
    return inputs


def assessment_input_ids(connection: Connection, assessment_id: int) -> list[int]:
    table = schema.assessment_inputs
    rows = connection.execute(
        select(table.c.observation_id)
        .where(table.c.assessment_id == assessment_id)
        .order_by(table.c.observation_id)
    )
    return [row.observation_id for row in rows]


def record_membership(connection: Connection, event: StoryMembershipEvent) -> StoryMembershipEvent:
    """Append a membership event and bring the current-state table into line with it.

    Both writes use the caller's transaction, so the history and the current state cannot
    disagree.
    """
    stored = add(connection, event)
    current = schema.story_documents
    if event.action is MembershipAction.REMOVE:
        connection.execute(delete(current).where(current.c.document_id == event.document_id))
    else:
        statement = sqlite_insert(current).values(
            document_id=event.document_id, story_id=event.story_id
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[current.c.document_id], set_={"story_id": event.story_id}
            )
        )
    return stored


def story_of(connection: Connection, document_id: int) -> int | None:
    current = schema.story_documents
    return connection.execute(
        select(current.c.story_id).where(current.c.document_id == document_id)
    ).scalar_one_or_none()


def upsert_source(connection: Connection, source: Source) -> None:
    """Bring a source's row into line with the catalogue. Operational state is kept."""
    table = schema.sources
    values = {
        "id": source.id,
        "name": source.name,
        "kind": source.kind.value,
        "url": source.url,
        "role": source.role.value,
        "mode": source.mode.value,
        "enabled": source.enabled,
    }
    statement = sqlite_insert(table).values(**values)
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.id], set_={k: v for k, v in values.items() if k != "id"}
        )
    )


def find_document(
    connection: Connection, source_id: str, external_id: str
) -> SourceDocument | None:
    """The document with this identity, if it has been seen before."""
    table = schema.source_documents
    row = (
        connection.execute(
            select(table).where(table.c.source_id == source_id, table.c.external_id == external_id)
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else SourceDocument.model_validate(dict(row))


def latest_observation(
    connection: Connection, document_id: int, *, with_body: bool | None = None
) -> DocumentObservation | None:
    """The newest observation of a document, if any.

    ``with_body`` narrows it to observations that carry article text (or carried it before
    the retention purge), or to those that never did. A page-backed document has both
    kinds, one from the feed and one from the page, and each is compared with its own.
    """
    table = schema.document_observations
    query = select(table).where(table.c.document_id == document_id)
    had_body = table.c.body_text.is_not(None) | table.c.body_purged_at.is_not(None)
    if with_body is True:
        query = query.where(had_body)
    elif with_body is False:
        query = query.where(~had_body)
    row = connection.execute(query.order_by(table.c.id.desc())).mappings().first()
    return None if row is None else DocumentObservation.model_validate(dict(row))
