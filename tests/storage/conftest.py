"""Fixtures for storage tests: a migrated database in a temporary directory, and builders
for a chain of records that reaches from a source to a briefing item.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import (
    AssessmentTier,
    BriefingItemKind,
    BriefingStatus,
    BriefingVariant,
    EditorialClass,
    FetchStatus,
    IntegrityStatus,
    LLMCallStatus,
    MembershipAction,
    ModelTask,
    SourceRole,
    SupportType,
)
from ai_briefing.domain.records import (
    Briefing,
    BriefingItem,
    DimensionScores,
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
    EvidenceItem,
    LLMCall,
    SourceDocument,
    Story,
    StoryMembershipEvent,
)
from ai_briefing.storage import database, repositories, schema

NOW = datetime(2026, 11, 19, 11, 15, tzinfo=UTC)
HASH = "a" * 64
OTHER_HASH = "b" * 64


@pytest.fixture
def database_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "test.sqlite3"


@pytest.fixture
def empty_engine(database_file: Path) -> Iterator[Engine]:
    database_file.parent.mkdir(parents=True)
    engine = database.create_database_engine(database_file)
    yield engine
    engine.dispose()


@pytest.fixture
def engine(empty_engine: Engine) -> Engine:
    database.upgrade(empty_engine)
    return empty_engine


@dataclass(frozen=True)
class Chain:
    """One of everything, linked: the records behind a single briefing item."""

    document: SourceDocument
    observation: DocumentObservation
    story: Story
    membership: StoryMembershipEvent
    call: LLMCall
    assessment: EditorialAssessment
    evidence: EvidenceItem
    decision: EditorialDecision
    briefing: Briefing
    item: BriefingItem


def add_source(connection: Connection, source_id: str = "example-blog") -> str:
    connection.execute(
        insert(schema.sources).values(
            id=source_id,
            name="Example blog",
            kind="rss",
            url="https://example.org/feed.xml",
            role="vendor",
            mode="full_text",
            enabled=True,
        )
    )
    return source_id


def add_job_run(connection: Connection, key: str = "test:setup") -> int:
    job_run_id: int = connection.execute(
        insert(schema.job_runs)
        .values(
            job="test",
            idempotency_key=key,
            started_at=NOW,
            ended_at=NOW,
            status="succeeded",
            counts="{}",
            application_version="0.0.0",
            configuration_hash=HASH,
        )
        .returning(schema.job_runs.c.id)
    ).scalar_one()
    return job_run_id


def model_call(job_run_id: int) -> LLMCall:
    return LLMCall(
        job_run_id=job_run_id,
        purpose=ModelTask.ASSESSMENT,
        prompt_id="assessment",
        prompt_hash=HASH,
        provider="anthropic",
        model_id="claude-haiku-5-5",
        tokens_in=1200,
        tokens_out=300,
        estimated_cost_usd=Decimal("0.00027"),
        price_table_version="2026-11-21",
        latency_ms=850,
        status=LLMCallStatus.SUCCEEDED,
    )


def add_chain(engine: Engine, *, external_id: str = "post-1") -> Chain:
    """Build the chain the way a job does: the run, then the model call on its own, then
    everything else in one transaction.
    """
    with engine.begin() as connection:
        source_id = add_source(connection) if external_id == "post-1" else "example-blog"
        job_run_id = add_job_run(connection, key=f"test:setup:{external_id}")
    call = repositories.record_model_call(engine, model_call(job_run_id), now=lambda: NOW)
    with engine.begin() as connection:
        return _add_rest(connection, source_id, call, external_id)


def _add_rest(connection: Connection, source_id: str, call: LLMCall, external_id: str) -> Chain:
    add = repositories.add
    document = add(
        connection,
        SourceDocument(
            source_id=source_id,
            external_id=external_id,
            canonical_url=f"https://example.org/{external_id}",
            title="A post",
            published_at=NOW,
            first_seen_at=NOW,
            source_role=SourceRole.VENDOR,
        ),
    )
    assert document.id is not None
    observation = add(
        connection,
        DocumentObservation(
            document_id=document.id,
            retrieved_at=NOW,
            fetch_status=FetchStatus.OK,
            summary="A synthetic summary.",
            body_text="The synthetic model scores 90 on the synthetic benchmark.",
            content_hash=HASH,
        ),
    )
    story = add(connection, Story(title="A story", first_seen_at=NOW, last_activity_at=NOW))
    assert story.id is not None
    assert observation.id is not None
    membership = repositories.record_membership(
        connection,
        StoryMembershipEvent(
            story_id=story.id,
            document_id=document.id,
            action=MembershipAction.ADD,
            reason="first document of the story",
            decided_by_rule="own-story",
            occurred_at=NOW,
        ),
    )
    assert call.id is not None
    assessment = add(
        connection,
        EditorialAssessment(
            story_id=story.id,
            as_of=NOW,
            input_hash=HASH,
            prompt_hash=HASH,
            model_id="claude-haiku-5-5",
            rubric_version="v0",
            tier=AssessmentTier.STANDARD,
            scores=DimensionScores(
                impact=3, evidence=1, novelty=2, professional_relevance=4, maturity=0
            ),
            suggested_class=EditorialClass.MAJOR,
            uncertainty="Only the vendor reports this.",
            draft_text="Draft.",
            model_call_id=call.id,
        ),
    )
    assert assessment.id is not None
    repositories.add_assessment_inputs(connection, assessment.id, [observation.id])
    evidence = add(
        connection,
        EvidenceItem(
            assessment_id=assessment.id,
            claim_text="The model scores 90.",
            observation_id=observation.id,
            quote="scores 90",
            support_type=SupportType.SUPPORTS,
            integrity_status=IntegrityStatus.VERIFIED,
        ),
    )
    decision = add(
        connection,
        EditorialDecision(
            assessment_id=assessment.id,
            policy_version="v0",
            final_class=EditorialClass.PRACTICAL,
            ceiling=EditorialClass.PRACTICAL,
            ceiling_reasons=("vendor only: a release exists",),
            independent_source_count=0,
            eligible=True,
        ),
    )
    assert decision.id is not None
    briefing = add(
        connection,
        Briefing(
            local_date=date(2026, 11, 19),
            timezone="America/New_York",
            variant=BriefingVariant.PIPELINE,
            version=1 if external_id == "post-1" else 2,
            status=BriefingStatus.READY,
            content='{"schema_version": "daily_briefing.v1", "stories": []}',
            content_hash=HASH,
            configuration_hash=HASH,
        ),
    )
    assert briefing.id is not None
    item = add(
        connection,
        BriefingItem(
            briefing_id=briefing.id,
            position=1,
            kind=BriefingItemKind.STORY,
            story_id=story.id,
            decision_id=decision.id,
            text="Headline",
            inclusion_reason="class practical, ranked first",
        ),
    )
    return Chain(
        document,
        observation,
        story,
        membership,
        call,
        assessment,
        evidence,
        decision,
        briefing,
        item,
    )
