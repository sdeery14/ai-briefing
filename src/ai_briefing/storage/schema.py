"""The tables of the system of record (RFC §5, ADR-002).

This module describes the current schema. The database itself is built by the Alembic
migrations in ``migrations/``; a test fails if the two disagree.

History tables are append-only: observations, membership events, assessments, their
inputs, evidence items, decisions, briefings and briefing items are never updated or
deleted. The one exception is the retention purge (ADR-010), which may null an
observation's body text and a model call's request payload, recording when. The migration
enforces this inside the database with triggers, so no code path can get round it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    Dialect,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator

from ai_briefing.domain.enums import (
    AssessmentTier,
    BriefingItemKind,
    BriefingStatus,
    BriefingVariant,
    EditorialClass,
    FetchStatus,
    IntegrityStatus,
    JobStatus,
    LLMCallStatus,
    MembershipAction,
    ModelTask,
    SourceKind,
    SourceMode,
    SourceRole,
    StoryState,
    SupportLabel,
    SupportType,
)

# Constraint names are fixed so that Alembic's batch mode can find them on SQLite.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING)


class UtcDateTime(TypeDecorator[datetime]):
    """A time stored as ISO-8601 text in UTC.

    SQLite has no time type and drops time zones, so the text is written here, always with
    a ``+00:00`` offset and microseconds, which also makes it sort correctly as text.
    A naive time is refused.
    """

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("a time without a time zone cannot be stored")
        return value.astimezone(UTC).isoformat(timespec="microseconds")

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)


class DecimalText(TypeDecorator[Decimal]):
    """An exact decimal stored as text. SQLite's own numbers are floating point."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else format(value, "f")

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


def _one_of(column: str, enum: type[Any], name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=name)


def _pk() -> Column[int]:
    return Column("id", Integer, primary_key=True, autoincrement=True)


sources = Table(
    "sources",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("url", Text, nullable=False),
    Column("role", String(20), nullable=False),
    Column("mode", String(20), nullable=False),
    Column("enabled", Boolean(create_constraint=True, name="enabled_bool"), nullable=False),
    # Operational state, kept by the collector (issue 1.4).
    Column("feed_etag", Text),
    Column("feed_last_modified", Text),
    Column("last_success_at", UtcDateTime),
    Column("consecutive_failures", Integer, nullable=False, server_default="0"),
    _one_of("kind", SourceKind, "kind"),
    _one_of("role", SourceRole, "role"),
    _one_of("mode", SourceMode, "mode"),
)

source_documents = Table(
    "source_documents",
    metadata,
    _pk(),
    Column("source_id", ForeignKey("sources.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("canonical_url", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("published_at", UtcDateTime),
    Column("first_seen_at", UtcDateTime, nullable=False),
    Column("source_role", String(20), nullable=False),
    UniqueConstraint("source_id", "external_id", name="uq_source_documents_identity"),
    _one_of("source_role", SourceRole, "source_role"),
)

document_observations = Table(
    "document_observations",
    metadata,
    _pk(),
    Column("document_id", ForeignKey("source_documents.id"), nullable=False),
    Column("retrieved_at", UtcDateTime, nullable=False),
    Column("fetch_status", String(20), nullable=False),
    Column("etag", Text),
    Column("last_modified", Text),
    Column("summary", Text),
    Column("body_text", Text),
    Column("body_purged_at", UtcDateTime),
    Column("content_hash", String(64), nullable=False),
    _one_of("fetch_status", FetchStatus, "fetch_status"),
    CheckConstraint("body_purged_at IS NULL OR body_text IS NULL", name="purged_body_is_gone"),
)

stories = Table(
    "stories",
    metadata,
    _pk(),
    Column("title", Text, nullable=False),
    Column("state", String(20), nullable=False),
    Column("first_seen_at", UtcDateTime, nullable=False),
    Column("last_activity_at", UtcDateTime, nullable=False),
    Column("merged_into_id", ForeignKey("stories.id")),
    # A plain number: the decision table refers to stories through assessments, and a
    # foreign key back would make the two tables depend on each other.
    Column("last_briefed_decision_id", Integer),
    _one_of("state", StoryState, "state"),
    CheckConstraint("merged_into_id IS NULL OR merged_into_id != id", name="not_merged_into_self"),
)

story_membership_events = Table(
    "story_membership_events",
    metadata,
    _pk(),
    Column("story_id", ForeignKey("stories.id"), nullable=False),
    Column("document_id", ForeignKey("source_documents.id"), nullable=False),
    Column("action", String(20), nullable=False),
    Column("reason", Text, nullable=False),
    Column("decided_by_rule", Text),
    Column("decided_by_model_call_id", ForeignKey("llm_calls.id")),
    Column("occurred_at", UtcDateTime, nullable=False),
    _one_of("action", MembershipAction, "action"),
    CheckConstraint(
        "(decided_by_rule IS NULL) != (decided_by_model_call_id IS NULL)", name="one_decider"
    ),
)

# Which story each document belongs to now. Derived from the events above and updated in
# the same transaction; the events are the history.
story_documents = Table(
    "story_documents",
    metadata,
    Column("document_id", ForeignKey("source_documents.id"), primary_key=True),
    Column("story_id", ForeignKey("stories.id"), nullable=False),
)

editorial_assessments = Table(
    "editorial_assessments",
    metadata,
    _pk(),
    Column("story_id", ForeignKey("stories.id"), nullable=False),
    Column("as_of", UtcDateTime, nullable=False),
    Column("input_hash", String(64), nullable=False),
    Column("prompt_hash", String(64), nullable=False),
    Column("model_id", String(100), nullable=False),
    Column("rubric_version", String(50), nullable=False),
    Column("tier", String(20), nullable=False),
    Column("score_impact", Integer, nullable=False),
    Column("score_evidence", Integer, nullable=False),
    Column("score_novelty", Integer, nullable=False),
    Column("score_professional_relevance", Integer, nullable=False),
    Column("score_maturity", Integer, nullable=False),
    Column("suggested_class", String(20), nullable=False),
    Column("uncertainty", Text, nullable=False),
    Column("draft_text", Text, nullable=False),
    Column("model_call_id", ForeignKey("llm_calls.id"), nullable=False),
    UniqueConstraint(
        "story_id", "input_hash", "prompt_hash", "model_id", name="uq_editorial_assessments_inputs"
    ),
    _one_of("tier", AssessmentTier, "tier"),
    _one_of("suggested_class", EditorialClass, "suggested_class"),
    *(
        CheckConstraint(f"score_{name} BETWEEN 0 AND 4", name=f"score_{name}_range")
        for name in ("impact", "evidence", "novelty", "professional_relevance", "maturity")
    ),
)

assessment_inputs = Table(
    "assessment_inputs",
    metadata,
    Column("assessment_id", ForeignKey("editorial_assessments.id"), primary_key=True),
    Column("observation_id", ForeignKey("document_observations.id"), primary_key=True),
)

evidence_items = Table(
    "evidence_items",
    metadata,
    _pk(),
    Column("assessment_id", ForeignKey("editorial_assessments.id"), nullable=False),
    Column("claim_text", Text, nullable=False),
    Column("observation_id", ForeignKey("document_observations.id"), nullable=False),
    Column("quote", Text, nullable=False),
    Column("support_type", String(20), nullable=False),
    Column("integrity_status", String(20), nullable=False),
    Column("support_label", String(20), nullable=False),
    _one_of("support_type", SupportType, "support_type"),
    _one_of("integrity_status", IntegrityStatus, "integrity_status"),
    _one_of("support_label", SupportLabel, "support_label"),
)

editorial_decisions = Table(
    "editorial_decisions",
    metadata,
    _pk(),
    Column("assessment_id", ForeignKey("editorial_assessments.id"), nullable=False),
    Column("policy_version", String(50), nullable=False),
    Column("final_class", String(20), nullable=False),
    Column("ceiling", String(20), nullable=False),
    Column("ceiling_reasons", Text, nullable=False),  # a JSON list of strings
    Column("independent_source_count", Integer, nullable=False),
    Column("eligible", Boolean(create_constraint=True, name="eligible_bool"), nullable=False),
    UniqueConstraint("assessment_id", "policy_version", name="uq_editorial_decisions_policy"),
    _one_of("final_class", EditorialClass, "final_class"),
    _one_of("ceiling", EditorialClass, "ceiling"),
    CheckConstraint("independent_source_count >= 0", name="source_count_not_negative"),
)

briefings = Table(
    "briefings",
    metadata,
    _pk(),
    Column("local_date", Date, nullable=False),
    Column("timezone", String(64), nullable=False),
    Column("variant", String(20), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(20), nullable=False),
    Column("content", Text, nullable=False),  # the briefing document as JSON text
    Column("content_hash", String(64), nullable=False),
    Column("configuration_hash", String(64), nullable=False),
    Column("profile", String(50), nullable=False),
    UniqueConstraint("local_date", "variant", "version", name="uq_briefings_version"),
    _one_of("variant", BriefingVariant, "variant"),
    _one_of("status", BriefingStatus, "status"),
    CheckConstraint("version >= 1", name="version_positive"),
)

briefing_items = Table(
    "briefing_items",
    metadata,
    _pk(),
    Column("briefing_id", ForeignKey("briefings.id"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("kind", String(20), nullable=False),
    Column("story_id", ForeignKey("stories.id")),
    Column("decision_id", ForeignKey("editorial_decisions.id")),
    Column("text", Text, nullable=False),
    Column("inclusion_reason", Text, nullable=False),
    UniqueConstraint("briefing_id", "position", name="uq_briefing_items_position"),
    _one_of("kind", BriefingItemKind, "kind"),
    CheckConstraint(
        "kind = 'concept_note' OR (story_id IS NOT NULL AND decision_id IS NOT NULL)",
        name="story_item_names_decision",
    ),
)

llm_calls = Table(
    "llm_calls",
    metadata,
    _pk(),
    Column("job_run_id", ForeignKey("job_runs.id"), nullable=False),
    Column("purpose", String(30), nullable=False),
    Column("prompt_id", String(100), nullable=False),
    Column("prompt_hash", String(64), nullable=False),
    Column("provider", String(50), nullable=False),
    Column("model_id", String(100), nullable=False),
    Column("tokens_in", Integer, nullable=False),
    Column("tokens_out", Integer, nullable=False),
    Column("estimated_cost_usd", DecimalText, nullable=False),
    Column("price_table_version", String(50), nullable=False),
    Column("latency_ms", Integer),
    Column("status", String(20), nullable=False),
    Column("error_class", String(100)),
    Column("retries", Integer, nullable=False),
    Column("request_ref", Text),
    Column("response_ref", Text),
    # The payloads themselves, written by the model client (issue 1.5). A request holds
    # source text, so the retention purge nulls it and records when (ADR-010).
    Column("request_payload", Text),
    Column("request_purged_at", UtcDateTime),
    Column("response_payload", Text),
    Column("created_at", UtcDateTime, nullable=False),
    _one_of("purpose", ModelTask, "purpose"),
    _one_of("status", LLMCallStatus, "status"),
    CheckConstraint("tokens_in >= 0 AND tokens_out >= 0 AND retries >= 0", name="not_negative"),
    CheckConstraint(
        "request_purged_at IS NULL OR request_payload IS NULL", name="purged_request_is_gone"
    ),
)

job_runs = Table(
    "job_runs",
    metadata,
    _pk(),
    Column("job", String(100), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("started_at", UtcDateTime, nullable=False),
    Column("ended_at", UtcDateTime),
    Column("status", String(20), nullable=False),
    Column("counts", Text, nullable=False),  # a JSON object of name to count
    Column("error", Text),
    Column("application_version", String(50), nullable=False),
    Column("configuration_hash", String(64), nullable=False),
    UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency_key"),
    _one_of("status", JobStatus, "status"),
    CheckConstraint("(status = 'running') = (ended_at IS NULL)", name="ended_when_not_running"),
)

# Never updated, never deleted.
APPEND_ONLY = (
    "story_membership_events",
    "editorial_assessments",
    "assessment_inputs",
    "evidence_items",
    "editorial_decisions",
    "briefings",
    "briefing_items",
)
# Never deleted. The only update allowed nulls the first column and sets the second,
# changing nothing else: the retention purge.
PURGEABLE = {
    "document_observations": ("body_text", "body_purged_at"),
    "llm_calls": ("request_payload", "request_purged_at"),
}


def trigger_statements() -> dict[str, str]:
    """The triggers that make history append-only, by name.

    The first migration creates these; a test compares the migrated database with this
    function, so the schema here and the migrations cannot drift apart unnoticed.
    """
    statements: dict[str, str] = {}

    def refuse(table: str, when: str, event: str, suffix: str, condition: str = "") -> None:
        name = f"{table}_{suffix}"
        message = f"{table} is append-only: {when}"
        statements[name] = (
            f"CREATE TRIGGER {name} BEFORE {event} ON {table} FOR EACH ROW {condition}"
            f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
        )

    for table in APPEND_ONLY:
        refuse(table, "a row is never updated", "UPDATE", "no_update")
        refuse(table, "a row is never deleted", "DELETE", "no_delete")
    for table, (payload, stamp) in PURGEABLE.items():
        kept = [c.name for c in metadata.tables[table].columns if c.name not in (payload, stamp)]
        unchanged = " AND ".join(f"NEW.{column} IS OLD.{column}" for column in kept)
        is_purge = f"{unchanged} AND NEW.{payload} IS NULL AND NEW.{stamp} IS NOT NULL"
        refuse(
            table,
            "only the retention purge may change a row",
            "UPDATE",
            "purge_only",
            f"WHEN NOT ({is_purge}) ",
        )
        refuse(table, "a row is never deleted", "DELETE", "no_delete")
    return statements
