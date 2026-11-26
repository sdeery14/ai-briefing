"""Reads that the processing and briefing stages need. Each returns domain records.

These find rows in a known state: documents not yet screened, items that passed and have
no story, stories with no assessment of their current inputs. A stage that has done its
work finds nothing here the next time, which is what makes running it twice add nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import ScreeningOutcome
from ai_briefing.domain.records import (
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
    EvidenceItem,
    SourceDocument,
    Story,
)
from ai_briefing.storage import repositories, schema


def _documents(connection: Connection, query: object) -> list[SourceDocument]:
    rows = connection.execute(query).mappings().all()  # type: ignore[call-overload]
    return [SourceDocument.model_validate(dict(row)) for row in rows]


def fresh_since(since: datetime) -> ColumnElement[bool]:
    """A document published at or after ``since``; or, where its source gave no published
    time, first seen at or after it (RFC §6.3)."""
    documents = schema.source_documents
    return or_(
        and_(documents.c.published_at.is_not(None), documents.c.published_at >= since),
        and_(documents.c.published_at.is_(None), documents.c.first_seen_at >= since),
    )


def unscreened_documents(
    connection: Connection, source_ids: list[str], limit: int, since: datetime
) -> list[SourceDocument]:
    """Fresh documents from these sources that have no screening decision yet.

    A feed read for the first time carries its whole back catalogue. Those items are
    stored, so they are recognised next time, but they are not news and are not screened.
    """
    documents = schema.source_documents
    decided = exists().where(schema.screening_decisions.c.document_id == documents.c.id)
    return _documents(
        connection,
        select(documents)
        .where(documents.c.source_id.in_(source_ids), ~decided, fresh_since(since))
        .order_by(documents.c.id)
        .limit(limit),
    )


def screening_relevance(connection: Connection) -> dict[int, int]:
    """Each screened document's relevance rating."""
    decisions = schema.screening_decisions
    rows = connection.execute(select(decisions.c.document_id, decisions.c.relevance))
    return {row.document_id: row.relevance for row in rows}


def passed_documents_without_story(connection: Connection) -> list[SourceDocument]:
    documents = schema.source_documents
    decisions = schema.screening_decisions
    in_story = exists().where(schema.story_documents.c.document_id == documents.c.id)
    return _documents(
        connection,
        select(documents)
        .join(decisions, decisions.c.document_id == documents.c.id)
        .where(decisions.c.outcome == ScreeningOutcome.PASSED.value, ~in_story)
        .order_by(documents.c.id),
    )


def passed_documents_without_body(
    connection: Connection, source_ids: list[str], since: datetime
) -> list[SourceDocument]:
    """Fresh documents that passed screening, from these sources, with no article text yet."""
    documents = schema.source_documents
    decisions = schema.screening_decisions
    observations = schema.document_observations
    has_body = exists().where(
        and_(
            observations.c.document_id == documents.c.id,
            observations.c.body_text.is_not(None) | observations.c.body_purged_at.is_not(None),
        )
    )
    return _documents(
        connection,
        select(documents)
        .join(decisions, decisions.c.document_id == documents.c.id)
        .where(
            decisions.c.outcome == ScreeningOutcome.PASSED.value,
            documents.c.source_id.in_(source_ids),
            ~has_body,
            fresh_since(since),
        )
        .order_by(documents.c.id),
    )


@dataclass(frozen=True)
class StoryInput:
    """A story with the document it holds. In M1 each story has exactly one document."""

    story: Story
    document: SourceDocument


def open_stories(connection: Connection) -> list[StoryInput]:
    stories = schema.stories
    documents = schema.source_documents
    current = schema.story_documents
    rows = connection.execute(
        select(stories.c.id.label("story_id"), documents.c.id.label("document_id"))
        .join(current, current.c.story_id == stories.c.id)
        .join(documents, documents.c.id == current.c.document_id)
        .where(stories.c.state == "open")
        .order_by(stories.c.id, documents.c.id)
    ).all()
    found: list[StoryInput] = []
    for row in rows:
        story = repositories.get(connection, Story, row.story_id)
        document = repositories.get(connection, SourceDocument, row.document_id)
        if story is not None and document is not None:
            found.append(StoryInput(story, document))
    return found


def assessment_exists(
    connection: Connection, story_id: int, input_hash: str, prompt_hash: str, model_id: str
) -> bool:
    table = schema.editorial_assessments
    return (
        connection.execute(
            select(table.c.id).where(
                table.c.story_id == story_id,
                table.c.input_hash == input_hash,
                table.c.prompt_hash == prompt_hash,
                table.c.model_id == model_id,
            )
        ).first()
        is not None
    )


def observation(connection: Connection, observation_id: int) -> DocumentObservation | None:
    return repositories.get(connection, DocumentObservation, observation_id)


@dataclass(frozen=True)
class Assessed:
    """Everything behind one story's place in a briefing."""

    story: Story
    document: SourceDocument
    source_name: str
    assessment: EditorialAssessment
    decision: EditorialDecision
    evidence: tuple[EvidenceItem, ...]


def assessed_stories(
    connection: Connection,
    fresh_from: datetime,
    current_input: Callable[[StoryInput], str | None],
) -> list[Assessed]:
    """Each open story whose document is fresh since ``fresh_from``, with the assessment of
    its *current* input and that assessment's newest decision.

    ``current_input`` gives the input hash a story would be assessed with now. Only an
    assessment made from exactly that input is used: an assessment of a headline or text
    the source has since changed is history, not the story's standing. A story with no
    assessment of its current input, or no decision, is left out.
    """
    found: list[Assessed] = []
    assessments = schema.editorial_assessments
    decisions = schema.editorial_decisions
    evidence = schema.evidence_items
    for item in open_stories(connection):
        if item.document.fresh_at < fresh_from or item.story.id is None:
            continue
        wanted = current_input(item)
        if wanted is None:
            continue
        assessment_row = (
            connection.execute(
                select(assessments.c.id)
                .where(
                    assessments.c.story_id == item.story.id,
                    assessments.c.input_hash == wanted,
                )
                .order_by(assessments.c.id.desc())
            )
        ).first()
        if assessment_row is None:
            continue
        decision_row = (
            connection.execute(
                select(decisions.c.id)
                .where(decisions.c.assessment_id == assessment_row.id)
                .order_by(decisions.c.id.desc())
            )
        ).first()
        if decision_row is None:
            continue
        assessment = repositories.get(connection, EditorialAssessment, assessment_row.id)
        decision = repositories.get(connection, EditorialDecision, decision_row.id)
        if assessment is None or decision is None:
            continue
        items = connection.execute(
            select(evidence)
            .where(evidence.c.assessment_id == assessment_row.id)
            .order_by(evidence.c.id)
        ).mappings()
        source_name = connection.execute(
            select(schema.sources.c.name).where(schema.sources.c.id == item.document.source_id)
        ).scalar_one()
        found.append(
            Assessed(
                story=item.story,
                document=item.document,
                source_name=source_name,
                assessment=assessment,
                decision=decision,
                evidence=tuple(EvidenceItem.model_validate(dict(row)) for row in items),
            )
        )
    return found
