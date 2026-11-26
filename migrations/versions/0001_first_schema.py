"""First schema: the M1 tables, and the triggers that make history append-only.

Times are ISO-8601 text in UTC and money is decimal text; ``ai_briefing.storage.schema``
has the reasons. This file is frozen: it must keep building the schema as it was at this
revision, so it imports nothing from the application.

Revision ID: 0001_first_schema
Revises:
Create Date: 2026-11-26 09:07:37.796039
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_first_schema"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# name -> statement. Written out once from the schema module's trigger_statements().
TRIGGERS: dict[str, str] = {
    "story_membership_events_no_update": (
        "CREATE TRIGGER story_membership_events_no_update BEFORE UPDATE ON story_membersh"
        "ip_events FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'story_membership_events is app"
        "end-only: a row is never updated'); END"
    ),
    "story_membership_events_no_delete": (
        "CREATE TRIGGER story_membership_events_no_delete BEFORE DELETE ON story_membersh"
        "ip_events FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'story_membership_events is app"
        "end-only: a row is never deleted'); END"
    ),
    "editorial_assessments_no_update": (
        "CREATE TRIGGER editorial_assessments_no_update BEFORE UPDATE ON editorial_assess"
        "ments FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'editorial_assessments is append-on"
        "ly: a row is never updated'); END"
    ),
    "editorial_assessments_no_delete": (
        "CREATE TRIGGER editorial_assessments_no_delete BEFORE DELETE ON editorial_assess"
        "ments FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'editorial_assessments is append-on"
        "ly: a row is never deleted'); END"
    ),
    "assessment_inputs_no_update": (
        "CREATE TRIGGER assessment_inputs_no_update BEFORE UPDATE ON assessment_inputs FO"
        "R EACH ROW BEGIN SELECT RAISE(ABORT, 'assessment_inputs is append-only: a row is"
        " never updated'); END"
    ),
    "assessment_inputs_no_delete": (
        "CREATE TRIGGER assessment_inputs_no_delete BEFORE DELETE ON assessment_inputs FO"
        "R EACH ROW BEGIN SELECT RAISE(ABORT, 'assessment_inputs is append-only: a row is"
        " never deleted'); END"
    ),
    "evidence_items_no_update": (
        "CREATE TRIGGER evidence_items_no_update BEFORE UPDATE ON evidence_items FOR EACH"
        " ROW BEGIN SELECT RAISE(ABORT, 'evidence_items is append-only: a row is never up"
        "dated'); END"
    ),
    "evidence_items_no_delete": (
        "CREATE TRIGGER evidence_items_no_delete BEFORE DELETE ON evidence_items FOR EACH"
        " ROW BEGIN SELECT RAISE(ABORT, 'evidence_items is append-only: a row is never de"
        "leted'); END"
    ),
    "editorial_decisions_no_update": (
        "CREATE TRIGGER editorial_decisions_no_update BEFORE UPDATE ON editorial_decision"
        "s FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'editorial_decisions is append-only: a "
        "row is never updated'); END"
    ),
    "editorial_decisions_no_delete": (
        "CREATE TRIGGER editorial_decisions_no_delete BEFORE DELETE ON editorial_decision"
        "s FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'editorial_decisions is append-only: a "
        "row is never deleted'); END"
    ),
    "briefings_no_update": (
        "CREATE TRIGGER briefings_no_update BEFORE UPDATE ON briefings FOR EACH ROW BEGIN"
        " SELECT RAISE(ABORT, 'briefings is append-only: a row is never updated'); END"
    ),
    "briefings_no_delete": (
        "CREATE TRIGGER briefings_no_delete BEFORE DELETE ON briefings FOR EACH ROW BEGIN"
        " SELECT RAISE(ABORT, 'briefings is append-only: a row is never deleted'); END"
    ),
    "briefing_items_no_update": (
        "CREATE TRIGGER briefing_items_no_update BEFORE UPDATE ON briefing_items FOR EACH"
        " ROW BEGIN SELECT RAISE(ABORT, 'briefing_items is append-only: a row is never up"
        "dated'); END"
    ),
    "briefing_items_no_delete": (
        "CREATE TRIGGER briefing_items_no_delete BEFORE DELETE ON briefing_items FOR EACH"
        " ROW BEGIN SELECT RAISE(ABORT, 'briefing_items is append-only: a row is never de"
        "leted'); END"
    ),
    "document_observations_purge_only": (
        "CREATE TRIGGER document_observations_purge_only BEFORE UPDATE ON document_observ"
        "ations FOR EACH ROW WHEN NOT (NEW.id IS OLD.id AND NEW.document_id IS OLD.docume"
        "nt_id AND NEW.retrieved_at IS OLD.retrieved_at AND NEW.fetch_status IS OLD.fetch"
        "_status AND NEW.etag IS OLD.etag AND NEW.last_modified IS OLD.last_modified AND "
        "NEW.summary IS OLD.summary AND NEW.content_hash IS OLD.content_hash AND NEW.body"
        "_text IS NULL AND NEW.body_purged_at IS NOT NULL) BEGIN SELECT RAISE(ABORT, 'doc"
        "ument_observations is append-only: only the retention purge may change a row'); "
        "END"
    ),
    "document_observations_no_delete": (
        "CREATE TRIGGER document_observations_no_delete BEFORE DELETE ON document_observa"
        "tions FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'document_observations is append-on"
        "ly: a row is never deleted'); END"
    ),
    "llm_calls_purge_only": (
        "CREATE TRIGGER llm_calls_purge_only BEFORE UPDATE ON llm_calls FOR EACH ROW WHEN"
        " NOT (NEW.id IS OLD.id AND NEW.job_run_id IS OLD.job_run_id AND NEW.purpose IS O"
        "LD.purpose AND NEW.prompt_id IS OLD.prompt_id AND NEW.prompt_hash IS OLD.prompt_"
        "hash AND NEW.provider IS OLD.provider AND NEW.model_id IS OLD.model_id AND NEW.t"
        "okens_in IS OLD.tokens_in AND NEW.tokens_out IS OLD.tokens_out AND NEW.estimated"
        "_cost_usd IS OLD.estimated_cost_usd AND NEW.price_table_version IS OLD.price_tab"
        "le_version AND NEW.latency_ms IS OLD.latency_ms AND NEW.status IS OLD.status AND"
        " NEW.error_class IS OLD.error_class AND NEW.retries IS OLD.retries AND NEW.reque"
        "st_ref IS OLD.request_ref AND NEW.response_ref IS OLD.response_ref AND NEW.respo"
        "nse_payload IS OLD.response_payload AND NEW.created_at IS OLD.created_at AND NEW"
        ".request_payload IS NULL AND NEW.request_purged_at IS NOT NULL) BEGIN SELECT RAI"
        "SE(ABORT, 'llm_calls is append-only: only the retention purge may change a row')"
        "; END"
    ),
    "llm_calls_no_delete": (
        "CREATE TRIGGER llm_calls_no_delete BEFORE DELETE ON llm_calls FOR EACH ROW BEGIN"
        " SELECT RAISE(ABORT, 'llm_calls is append-only: a row is never deleted'); END"
    ),
}


def upgrade() -> None:
    op.create_table(
        "briefings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("profile", sa.String(length=50), nullable=False),
        sa.CheckConstraint(
            "status IN ('ready', 'degraded', 'empty')", name=op.f("ck_briefings_status")
        ),
        sa.CheckConstraint(
            "variant IN ('pipeline', 'baseline')", name=op.f("ck_briefings_variant")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_briefings_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_briefings")),
        sa.UniqueConstraint("local_date", "variant", "version", name="uq_briefings_version"),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("started_at", sa.String(length=32), nullable=False),
        sa.Column("ended_at", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("counts", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("application_version", sa.String(length=50), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "(status = 'running') = (ended_at IS NULL)",
            name=op.f("ck_job_runs_ended_when_not_running"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name=op.f("ck_job_runs_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
        sa.UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency_key"),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(create_constraint=True, name="enabled_bool"), nullable=False
        ),
        sa.Column("feed_etag", sa.Text(), nullable=True),
        sa.Column("feed_last_modified", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.String(length=32), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("kind IN ('rss', 'atom', 'hn_api')", name=op.f("ck_sources_kind")),
        sa.CheckConstraint(
            "mode IN ('full_text', 'feed_summary', 'metadata_only', 'disabled')",
            name=op.f("ck_sources_mode"),
        ),
        sa.CheckConstraint(
            "role IN ('primary', 'vendor', 'independent', 'community', 'aggregator')",
            name=op.f("ck_sources_role"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
    )
    op.create_table(
        "stories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("first_seen_at", sa.String(length=32), nullable=False),
        sa.Column("last_activity_at", sa.String(length=32), nullable=False),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("last_briefed_decision_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("state IN ('open', 'dormant', 'closed')", name=op.f("ck_stories_state")),
        sa.CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id != id",
            name=op.f("ck_stories_not_merged_into_self"),
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["stories.id"], name=op.f("fk_stories_merged_into_id_stories")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stories")),
    )
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_run_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("prompt_id", sa.String(length=100), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.String(length=40), nullable=False),
        sa.Column("price_table_version", sa.String(length=50), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_class", sa.String(length=100), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("request_ref", sa.Text(), nullable=True),
        sa.Column("response_ref", sa.Text(), nullable=True),
        sa.Column("request_payload", sa.Text(), nullable=True),
        sa.Column("request_purged_at", sa.String(length=32), nullable=True),
        sa.Column("response_payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('screening', 'assessment', 'escalated_assessment', 'baseline_digest', 'concept_note')",
            name=op.f("ck_llm_calls_purpose"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'refused', 'budget_refused', 'failed')",
            name=op.f("ck_llm_calls_status"),
        ),
        sa.CheckConstraint(
            "request_purged_at IS NULL OR request_payload IS NULL",
            name=op.f("ck_llm_calls_purged_request_is_gone"),
        ),
        sa.CheckConstraint(
            "tokens_in >= 0 AND tokens_out >= 0 AND retries >= 0",
            name=op.f("ck_llm_calls_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["job_run_id"], ["job_runs.id"], name=op.f("fk_llm_calls_job_run_id_job_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", sa.String(length=32), nullable=True),
        sa.Column("first_seen_at", sa.String(length=32), nullable=False),
        sa.Column("source_role", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "source_role IN ('primary', 'vendor', 'independent', 'community', 'aggregator')",
            name=op.f("ck_source_documents_source_role"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=op.f("fk_source_documents_source_id_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_documents")),
        sa.UniqueConstraint("source_id", "external_id", name="uq_source_documents_identity"),
    )
    op.create_table(
        "document_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("retrieved_at", sa.String(length=32), nullable=False),
        sa.Column("fetch_status", sa.String(length=20), nullable=False),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_purged_at", sa.String(length=32), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "fetch_status IN ('ok', 'not_modified', 'failed')",
            name=op.f("ck_document_observations_fetch_status"),
        ),
        sa.CheckConstraint(
            "body_purged_at IS NULL OR body_text IS NULL",
            name=op.f("ck_document_observations_purged_body_is_gone"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.id"],
            name=op.f("fk_document_observations_document_id_source_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_observations")),
    )
    op.create_table(
        "editorial_assessments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("rubric_version", sa.String(length=50), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("score_impact", sa.Integer(), nullable=False),
        sa.Column("score_evidence", sa.Integer(), nullable=False),
        sa.Column("score_novelty", sa.Integer(), nullable=False),
        sa.Column("score_professional_relevance", sa.Integer(), nullable=False),
        sa.Column("score_maturity", sa.Integer(), nullable=False),
        sa.Column("suggested_class", sa.String(length=20), nullable=False),
        sa.Column("uncertainty", sa.Text(), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("model_call_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "suggested_class IN ('major', 'practical', 'watch', 'low')",
            name=op.f("ck_editorial_assessments_suggested_class"),
        ),
        sa.CheckConstraint(
            "tier IN ('standard', 'escalated')", name=op.f("ck_editorial_assessments_tier")
        ),
        sa.CheckConstraint(
            "score_evidence BETWEEN 0 AND 4",
            name=op.f("ck_editorial_assessments_score_evidence_range"),
        ),
        sa.CheckConstraint(
            "score_impact BETWEEN 0 AND 4", name=op.f("ck_editorial_assessments_score_impact_range")
        ),
        sa.CheckConstraint(
            "score_maturity BETWEEN 0 AND 4",
            name=op.f("ck_editorial_assessments_score_maturity_range"),
        ),
        sa.CheckConstraint(
            "score_novelty BETWEEN 0 AND 4",
            name=op.f("ck_editorial_assessments_score_novelty_range"),
        ),
        sa.CheckConstraint(
            "score_professional_relevance BETWEEN 0 AND 4",
            name=op.f("ck_editorial_assessments_score_professional_relevance_range"),
        ),
        sa.ForeignKeyConstraint(
            ["model_call_id"],
            ["llm_calls.id"],
            name=op.f("fk_editorial_assessments_model_call_id_llm_calls"),
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name=op.f("fk_editorial_assessments_story_id_stories")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editorial_assessments")),
        sa.UniqueConstraint(
            "story_id",
            "input_hash",
            "prompt_hash",
            "model_id",
            name="uq_editorial_assessments_inputs",
        ),
    )
    op.create_table(
        "story_documents",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.id"],
            name=op.f("fk_story_documents_document_id_source_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name=op.f("fk_story_documents_story_id_stories")
        ),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_story_documents")),
    )
    op.create_table(
        "story_membership_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by_rule", sa.Text(), nullable=True),
        sa.Column("decided_by_model_call_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "action IN ('add', 'remove', 'merge_in')",
            name=op.f("ck_story_membership_events_action"),
        ),
        sa.CheckConstraint(
            "(decided_by_rule IS NULL) != (decided_by_model_call_id IS NULL)",
            name=op.f("ck_story_membership_events_one_decider"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_model_call_id"],
            ["llm_calls.id"],
            name=op.f("fk_story_membership_events_decided_by_model_call_id_llm_calls"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.id"],
            name=op.f("fk_story_membership_events_document_id_source_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name=op.f("fk_story_membership_events_story_id_stories")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_story_membership_events")),
    )
    op.create_table(
        "assessment_inputs",
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["editorial_assessments.id"],
            name=op.f("fk_assessment_inputs_assessment_id_editorial_assessments"),
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["document_observations.id"],
            name=op.f("fk_assessment_inputs_observation_id_document_observations"),
        ),
        sa.PrimaryKeyConstraint(
            "assessment_id", "observation_id", name=op.f("pk_assessment_inputs")
        ),
    )
    op.create_table(
        "editorial_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("final_class", sa.String(length=20), nullable=False),
        sa.Column("ceiling", sa.String(length=20), nullable=False),
        sa.Column("ceiling_reasons", sa.Text(), nullable=False),
        sa.Column("independent_source_count", sa.Integer(), nullable=False),
        sa.Column(
            "eligible", sa.Boolean(create_constraint=True, name="eligible_bool"), nullable=False
        ),
        sa.CheckConstraint(
            "ceiling IN ('major', 'practical', 'watch', 'low')",
            name=op.f("ck_editorial_decisions_ceiling"),
        ),
        sa.CheckConstraint(
            "final_class IN ('major', 'practical', 'watch', 'low')",
            name=op.f("ck_editorial_decisions_final_class"),
        ),
        sa.CheckConstraint(
            "independent_source_count >= 0",
            name=op.f("ck_editorial_decisions_source_count_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["editorial_assessments.id"],
            name=op.f("fk_editorial_decisions_assessment_id_editorial_assessments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editorial_decisions")),
        sa.UniqueConstraint(
            "assessment_id", "policy_version", name="uq_editorial_decisions_policy"
        ),
    )
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("support_type", sa.String(length=20), nullable=False),
        sa.Column("integrity_status", sa.String(length=20), nullable=False),
        sa.Column("support_label", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "integrity_status IN ('verified', 'failed')",
            name=op.f("ck_evidence_items_integrity_status"),
        ),
        sa.CheckConstraint(
            "support_label IN ('unreviewed')", name=op.f("ck_evidence_items_support_label")
        ),
        sa.CheckConstraint(
            "support_type IN ('supports', 'contradicts', 'context')",
            name=op.f("ck_evidence_items_support_type"),
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["editorial_assessments.id"],
            name=op.f("fk_evidence_items_assessment_id_editorial_assessments"),
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["document_observations.id"],
            name=op.f("fk_evidence_items_observation_id_document_observations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_items")),
    )
    op.create_table(
        "briefing_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("briefing_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=True),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("inclusion_reason", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind = 'concept_note' OR (story_id IS NOT NULL AND decision_id IS NOT NULL)",
            name=op.f("ck_briefing_items_story_item_names_decision"),
        ),
        sa.CheckConstraint(
            "kind IN ('story', 'watch', 'concept_note')", name=op.f("ck_briefing_items_kind")
        ),
        sa.ForeignKeyConstraint(
            ["briefing_id"], ["briefings.id"], name=op.f("fk_briefing_items_briefing_id_briefings")
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["editorial_decisions.id"],
            name=op.f("fk_briefing_items_decision_id_editorial_decisions"),
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name=op.f("fk_briefing_items_story_id_stories")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_briefing_items")),
        sa.UniqueConstraint("briefing_id", "position", name="uq_briefing_items_position"),
    )
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("briefing_items")
    op.drop_table("evidence_items")
    op.drop_table("editorial_decisions")
    op.drop_table("assessment_inputs")
    op.drop_table("story_membership_events")
    op.drop_table("story_documents")
    op.drop_table("editorial_assessments")
    op.drop_table("document_observations")
    op.drop_table("source_documents")
    op.drop_table("llm_calls")
    op.drop_table("stories")
    op.drop_table("sources")
    op.drop_table("job_runs")
    op.drop_table("briefings")
