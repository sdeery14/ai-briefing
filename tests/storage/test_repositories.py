"""Records round-trip through the database, history is append-only, and the idempotency
keys hold (ADR-002, ADR-010).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from ai_briefing.domain.enums import JobStatus, MembershipAction, SourceRole
from ai_briefing.domain.records import (
    Briefing,
    BriefingItem,
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
    EvidenceItem,
    JobRun,
    LLMCall,
    Source,
    SourceDocument,
    Story,
    StoryMembershipEvent,
)
from ai_briefing.storage import repositories, schema

from .conftest import NOW, OTHER_HASH, Chain, add_chain, add_job_run, model_call


@pytest.fixture
def chain(engine: Engine) -> Chain:
    return add_chain(engine)


# --- Round trips ------------------------------------------------------------------------------


def test_every_record_type_reads_back_exactly_as_it_was_written(
    engine: Engine, chain: Chain
) -> None:
    stored = [
        chain.document,
        chain.observation,
        chain.story,
        chain.membership,
        chain.call,
        chain.assessment,
        chain.evidence,
        chain.decision,
        chain.briefing,
        chain.item,
    ]
    with engine.connect() as connection:
        for record in stored:
            record_id = getattr(record, "id", None)
            assert isinstance(record_id, int)
            assert repositories.get(connection, type(record), record_id) == record
        assert repositories.get(connection, Story, 999) is None


def test_a_briefing_item_can_be_traced_back_to_what_the_model_saw(
    engine: Engine, chain: Chain
) -> None:
    get = repositories.get
    with engine.connect() as connection:
        assert chain.item.id is not None
        item = get(connection, BriefingItem, chain.item.id)
        assert item is not None
        assert item.decision_id is not None
        decision = get(connection, EditorialDecision, item.decision_id)
        assert decision is not None
        assessment = get(connection, EditorialAssessment, decision.assessment_id)
        assert assessment is not None
        assert assessment.id is not None
        shown = repositories.assessment_input_ids(connection, assessment.id)
        assert shown == [chain.observation.id]
        observation = get(connection, DocumentObservation, shown[0])
        assert observation is not None
        assert observation.body_text is not None
        assert chain.evidence.quote in observation.body_text
        call = get(connection, LLMCall, assessment.model_call_id)
    assert call is not None
    assert call.estimated_cost_usd == Decimal("0.00027")


def test_times_are_stored_in_utc_and_a_naive_time_is_refused(engine: Engine) -> None:
    eastern = timezone(timedelta(hours=-5))
    local = datetime(2026, 11, 19, 6, 15, 30, 123456, tzinfo=eastern)
    with engine.begin() as connection:
        story = repositories.add(
            connection, Story(title="A story", first_seen_at=local, last_activity_at=local)
        )
        raw = connection.execute(text("SELECT first_seen_at FROM stories")).scalar_one()
    assert raw == "2026-11-19T11:15:30.123456+00:00"
    assert story.first_seen_at == local
    assert story.first_seen_at.tzinfo == UTC
    with pytest.raises(StatementError, match="without a time zone"), engine.begin() as connection:
        connection.execute(
            schema.stories.insert().values(
                title="x",
                state="open",
                first_seen_at=datetime(2026, 11, 19, 11, 15),
                last_activity_at=NOW,
            )
        )


def test_money_is_stored_exactly(engine: Engine) -> None:
    with engine.begin() as connection:
        job_run_id = add_job_run(connection)
    tiny = model_call(job_run_id).model_copy(
        update={"estimated_cost_usd": Decimal("0.000000100000000001")}
    )
    stored = repositories.record_model_call(engine, tiny, now=lambda: NOW)
    assert stored.id is not None
    with engine.connect() as connection:
        read = repositories.get(connection, LLMCall, stored.id)
    assert read is not None
    assert read.estimated_cost_usd == Decimal("0.000000100000000001")


# --- Append-only history ----------------------------------------------------------------------


@pytest.mark.parametrize("table", schema.APPEND_ONLY)
def test_an_append_only_table_refuses_update_and_delete(
    engine: Engine, chain: Chain, table: str
) -> None:
    column = next(iter(schema.metadata.tables[table].columns)).name
    with engine.connect() as connection:
        before = connection.execute(text(f"SELECT * FROM {table}")).all()  # noqa: S608
    assert before, f"the fixture has no row in {table}"
    for statement in (
        f"UPDATE {table} SET {column} = {column}",  # noqa: S608 - a table name from the schema
        f"DELETE FROM {table}",  # noqa: S608
    ):
        with (
            pytest.raises(IntegrityError, match="append-only"),
            engine.begin() as connection,
        ):
            connection.execute(text(statement))
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT * FROM {table}")).all() == before  # noqa: S608


def test_the_repository_offers_no_way_to_rewrite_history() -> None:
    functions = {
        name
        for name, value in vars(repositories).items()
        if callable(value) and getattr(value, "__module__", None) == repositories.__name__
    }
    assert {"add", "get", "record_membership", "upsert_source"} <= functions
    writers = {n for n in functions if n.split("_")[0] in {"update", "delete", "remove", "set"}}
    assert writers == set()
    # The module does not even import SQLAlchemy's UPDATE construct. DELETE is used once,
    # on the current-state table, which is derived data and not history.
    source = Path(repositories.__file__).read_text(encoding="utf-8")
    imported = re.findall(r"^from sqlalchemy import (.+)$", source, re.MULTILINE)
    assert imported == ["Engine, Table, delete, insert, select"]
    assert source.count("delete(") == 1
    assert "delete(current)" in source


def test_a_record_that_already_has_an_id_cannot_be_added_again(
    engine: Engine, chain: Chain
) -> None:
    with (
        pytest.raises(ValueError, match="history is not rewritten"),
        engine.begin() as connection,
    ):
        repositories.add(connection, chain.evidence)


def test_a_model_call_is_recorded_only_through_its_own_durable_function(engine: Engine) -> None:
    with engine.begin() as connection:
        job_run_id = add_job_run(connection)
    with pytest.raises(TypeError, match="not added through"), engine.begin() as connection:
        repositories.add(connection, model_call(job_run_id))
    stored = repositories.record_model_call(engine, model_call(job_run_id), now=lambda: NOW)
    assert stored.id is not None
    with pytest.raises(ValueError, match="history is not rewritten"):
        repositories.record_model_call(engine, stored)


def test_a_job_run_is_written_only_by_the_job_runner(engine: Engine) -> None:
    run = JobRun(
        job="collect",
        idempotency_key="k",
        started_at=NOW,
        status=JobStatus.RUNNING,
        application_version="0.0.0",
        configuration_hash=OTHER_HASH,
    )
    with pytest.raises(TypeError, match="not added through"), engine.begin() as connection:
        repositories.add(connection, run)


# --- The retention purge is the one permitted change --------------------------------------------


def test_an_observation_can_be_purged_and_keeps_its_hash(engine: Engine, chain: Chain) -> None:
    assert chain.observation.id is not None
    with engine.begin() as connection:
        connection.execute(
            schema.document_observations.update()
            .where(schema.document_observations.c.id == chain.observation.id)
            .values(body_text=None, body_purged_at=NOW)
        )
        purged = repositories.get(connection, DocumentObservation, chain.observation.id)
    assert purged is not None
    assert purged.body_text is None
    assert purged.body_purged_at == NOW
    assert purged.content_hash == chain.observation.content_hash
    assert purged.summary == chain.observation.summary


@pytest.mark.parametrize(
    "change",
    [
        "body_text = 'rewritten'",
        "body_text = NULL",  # nulling without recording when
        "content_hash = 'tampered', body_text = NULL, body_purged_at = 'now'",
        "summary = 'rewritten', body_text = NULL, body_purged_at = 'now'",
        "retrieved_at = 'later', body_text = NULL, body_purged_at = 'now'",
        "document_id = document_id + 0, fetch_status = 'failed'",
    ],
)
def test_an_observation_cannot_be_changed_in_any_other_way(
    engine: Engine, chain: Chain, change: str
) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(f"UPDATE document_observations SET {change}"))  # noqa: S608
    with engine.connect() as connection:
        assert chain.observation.id is not None
        assert (
            repositories.get(connection, DocumentObservation, chain.observation.id)
            == chain.observation
        )


@pytest.mark.parametrize("table", sorted(schema.PURGEABLE))
def test_a_purgeable_table_refuses_delete(engine: Engine, chain: Chain, table: str) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608


def test_a_model_call_can_only_have_its_request_payload_purged(
    engine: Engine, chain: Chain
) -> None:
    calls = schema.llm_calls
    with pytest.raises(IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(calls.update().values(tokens_in=0))
    with pytest.raises(IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(calls.update().values(estimated_cost_usd=Decimal(0)))
    with engine.begin() as connection:
        connection.execute(calls.update().values(request_payload=None, request_purged_at=NOW))
        assert chain.call.id is not None
        assert repositories.get(connection, LLMCall, chain.call.id) == chain.call


# --- Idempotency keys ---------------------------------------------------------------------------


def test_a_document_is_unique_on_source_and_external_id(engine: Engine, chain: Chain) -> None:
    again = chain.document.model_copy(update={"id": None, "title": "Seen again"})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        repositories.add(connection, again)
    other = chain.document.model_copy(update={"id": None, "external_id": "post-2"})
    with engine.begin() as connection:
        assert repositories.add(connection, other).id != chain.document.id


def test_an_assessment_is_unique_on_story_inputs_prompt_and_model(
    engine: Engine, chain: Chain
) -> None:
    again = chain.assessment.model_copy(update={"id": None, "draft_text": "A second opinion."})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        repositories.add(connection, again)
    for field, value in (
        ("input_hash", OTHER_HASH),
        ("prompt_hash", OTHER_HASH),
        ("model_id", "claude-sonnet-5-5"),
    ):
        changed = chain.assessment.model_copy(update={"id": None, field: value})
        with engine.begin() as connection:
            assert repositories.add(connection, changed).id is not None


def test_a_briefing_is_unique_on_date_variant_and_version(engine: Engine, chain: Chain) -> None:
    again = chain.briefing.model_copy(update={"id": None})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        repositories.add(connection, again)
    next_version = chain.briefing.model_copy(update={"id": None, "version": 2})
    with engine.begin() as connection:
        assert repositories.add(connection, next_version).id is not None


def test_a_decision_is_unique_on_assessment_and_policy_version(
    engine: Engine, chain: Chain
) -> None:
    again = chain.decision.model_copy(update={"id": None})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        repositories.add(connection, again)
    # A new policy version decides again, with no new assessment and no model call.
    redecided = chain.decision.model_copy(update={"id": None, "policy_version": "v1"})
    with engine.begin() as connection:
        calls_before = connection.execute(select(schema.llm_calls.c.id)).all()
        assert repositories.add(connection, redecided).id is not None
        assert connection.execute(select(schema.llm_calls.c.id)).all() == calls_before


def test_the_database_itself_rejects_values_outside_the_enumerations(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            schema.stories.insert().values(
                title="x", state="archived", first_seen_at=NOW, last_activity_at=NOW
            )
        )


# --- Membership ---------------------------------------------------------------------------------


def test_membership_events_keep_the_current_state_in_step(engine: Engine, chain: Chain) -> None:
    assert chain.document.id is not None
    assert chain.story.id is not None
    with engine.begin() as connection:
        assert repositories.story_of(connection, chain.document.id) == chain.story.id
        other = repositories.add(
            connection, Story(title="Another story", first_seen_at=NOW, last_activity_at=NOW)
        )
        assert other.id is not None

        def event(story_id: int, action: MembershipAction) -> StoryMembershipEvent:
            assert chain.document.id is not None
            return StoryMembershipEvent(
                story_id=story_id,
                document_id=chain.document.id,
                action=action,
                reason="regrouped",
                decided_by_rule="canonical-url",
                occurred_at=NOW,
            )

        repositories.record_membership(connection, event(other.id, MembershipAction.MERGE_IN))
        assert repositories.story_of(connection, chain.document.id) == other.id
        repositories.record_membership(connection, event(other.id, MembershipAction.REMOVE))
        assert repositories.story_of(connection, chain.document.id) is None
        history = connection.execute(
            select(schema.story_membership_events.c.action).order_by(
                schema.story_membership_events.c.id
            )
        ).all()
    # Every change is still there, in order.
    assert [row.action for row in history] == ["add", "merge_in", "remove"]


def test_an_event_and_the_current_state_roll_back_together(engine: Engine, chain: Chain) -> None:
    assert chain.document.id is not None
    assert chain.story.id is not None
    event = chain.membership.model_copy(update={"id": None, "action": MembershipAction.REMOVE})

    def regroup_then_fail() -> None:
        with engine.begin() as connection:
            repositories.record_membership(connection, event)
            raise RuntimeError("the job failed after regrouping")

    with pytest.raises(RuntimeError, match="after regrouping"):
        regroup_then_fail()
    with engine.connect() as connection:
        assert repositories.story_of(connection, chain.document.id) == chain.story.id
        events = connection.execute(select(schema.story_membership_events.c.id)).all()
    assert len(events) == 1


def test_earlier_assessments_still_resolve_after_a_story_is_merged(
    engine: Engine, chain: Chain
) -> None:
    assert chain.assessment.id is not None
    with engine.begin() as connection:
        target = repositories.add(
            connection, Story(title="Merged into", first_seen_at=NOW, last_activity_at=NOW)
        )
        connection.execute(
            schema.stories.update()
            .where(schema.stories.c.id == chain.story.id)
            .values(state="closed", merged_into_id=target.id)
        )
        assessment = repositories.get(connection, EditorialAssessment, chain.assessment.id)
        assert assessment == chain.assessment
        shown = repositories.assessment_input_ids(connection, chain.assessment.id)
    assert shown == [chain.observation.id]


# --- Sources ------------------------------------------------------------------------------------


def catalogue_source(**changes: object) -> Source:
    entry: dict[str, object] = {
        "id": "example-blog",
        "name": "Example blog",
        "kind": "rss",
        "url": "https://example.org/feed.xml",
        "role": "vendor",
        "enabled": True,
        "mode": "metadata_only",
        "polling_interval_minutes": 360,
        "rate_limit": {"min_seconds_between_requests": 10, "max_connections": 1},
        "store": {"metadata": True, "feed_summary": False, "body": False},
        "model_submission": "metadata",
        "retention_days": {"metadata": None, "feed_summary": 0},
        "excerpts_allowed": False,
        "attribution": "Link to the original post.",
        "terms": {
            "reviewed_on": "2026-11-21",
            "approved_by_owner_on": "2026-11-23",
            "urls": ["https://example.org/terms"],
            "automated_access": "explicit",
            "restrictions": ["None stated."],
            "uncertainties": ["Silent on private copies."],
        },
    }
    entry.update(changes)
    return Source.model_validate(entry)


def test_upserting_a_source_follows_the_catalogue_and_keeps_operational_state(
    engine: Engine,
) -> None:
    sources = schema.sources
    with engine.begin() as connection:
        repositories.upsert_source(connection, catalogue_source())
        connection.execute(sources.update().values(feed_etag='"abc"', consecutive_failures=2))
        repositories.upsert_source(connection, catalogue_source(name="Example blog, renamed"))
        row = connection.execute(select(sources)).mappings().one()
    assert row["name"] == "Example blog, renamed"
    assert row["mode"] == "metadata_only"
    assert row["feed_etag"] == '"abc"'
    assert row["consecutive_failures"] == 2


def test_a_document_needs_a_source_that_exists(engine: Engine) -> None:
    orphan = SourceDocument(
        source_id="no-such-source",
        external_id="x",
        canonical_url="https://example.org/x",
        title="x",
        first_seen_at=NOW,
        source_role=SourceRole.VENDOR,
    )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        repositories.add(connection, orphan)


def test_evidence_and_briefing_types_are_the_ones_stored() -> None:
    stored = set(repositories._STORED)
    assert {EvidenceItem, Briefing, JobRun, LLMCall} <= stored
    assert len(stored) == 13
