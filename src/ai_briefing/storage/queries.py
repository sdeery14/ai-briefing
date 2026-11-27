"""Reads that the processing and briefing stages need. Each returns domain records.

These find rows in a known state: documents not yet screened, items that passed and have
no story, stories with no assessment of their current inputs. A stage that has done its
work finds nothing here the next time, which is what makes running it twice add nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import (
    BriefingVariant,
    EditorialClass,
    ScreeningOutcome,
    SourceKind,
    SourceRole,
)
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


# A community or aggregator document passes a story on or discusses it. It is never the
# document a story is known by while the story holds any other kind.
_PASSES_ON = frozenset({SourceRole.COMMUNITY, SourceRole.AGGREGATOR})


def newest_evidence_at(documents: Sequence[SourceDocument]) -> datetime:
    """When a story's newest evidence was published (RFC §6.3): the latest of its documents
    that can be evidence. A community or aggregator document is attention, not evidence,
    so a new discussion of an old post does not make the post news again; a story that
    holds nothing else is dated by what it has.
    """
    evidence = [d for d in documents if d.source_role not in _PASSES_ON] or list(documents)
    return max(d.fresh_at for d in evidence)


@dataclass(frozen=True)
class StoryInput:
    """A story with the documents it holds now. Grouping can give it several."""

    story: Story
    documents: tuple[SourceDocument, ...]

    @property
    def document(self) -> SourceDocument:
        """The document the story is known by: the earliest that is not from a community
        or aggregator source, or the earliest of those if it has no other."""
        return min(self.documents, key=lambda d: (d.source_role in _PASSES_ON, d.id or 0))

    @property
    def fresh_at(self) -> datetime:
        """The time the story's freshness is counted from: its newest evidence."""
        return newest_evidence_at(self.documents)


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
    held: dict[int, list[SourceDocument]] = {}
    for row in rows:
        document = repositories.get(connection, SourceDocument, row.document_id)
        if document is not None:
            held.setdefault(row.story_id, []).append(document)
    found: list[StoryInput] = []
    for story_id, members in held.items():
        story = repositories.get(connection, Story, story_id)
        if story is not None:
            found.append(StoryInput(story, tuple(members)))
    return found


def open_story_addresses(connection: Connection) -> list[tuple[int, str]]:
    """Each open story with the address of each document in it, earliest story first."""
    stories = schema.stories
    documents = schema.source_documents
    current = schema.story_documents
    rows = connection.execute(
        select(current.c.story_id, documents.c.canonical_url)
        .join(stories, stories.c.id == current.c.story_id)
        .join(documents, documents.c.id == current.c.document_id)
        .where(stories.c.state == "open")
        .order_by(current.c.story_id, documents.c.id)
    ).all()
    return [(row.story_id, row.canonical_url) for row in rows]


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


def decision_exists(connection: Connection, assessment_id: int, policy_version: str) -> bool:
    table = schema.editorial_decisions
    return (
        connection.execute(
            select(table.c.id).where(
                table.c.assessment_id == assessment_id, table.c.policy_version == policy_version
            )
        ).first()
        is not None
    )


def observation(connection: Connection, observation_id: int) -> DocumentObservation | None:
    return repositories.get(connection, DocumentObservation, observation_id)


@dataclass(frozen=True)
class Also:
    """Another document in a story, beside the one it is known by."""

    document: SourceDocument
    source_name: str
    source_kind: SourceKind


@dataclass(frozen=True)
class Assessed:
    """Everything behind one story's place in a briefing."""

    story: Story
    document: SourceDocument
    source_name: str
    assessment: EditorialAssessment
    decision: EditorialDecision
    evidence: tuple[EvidenceItem, ...]
    others: tuple[Also, ...] = ()

    @property
    def documents(self) -> tuple[SourceDocument, ...]:
        return (self.document, *(other.document for other in self.others))

    @property
    def fresh_at(self) -> datetime:
        """The time the story's freshness is counted from: its newest evidence."""
        return newest_evidence_at(self.documents)


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
        if item.fresh_at < fresh_from or item.story.id is None:
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
        named = {
            row.id: (row.name, SourceKind(row.kind))
            for row in connection.execute(
                select(schema.sources.c.id, schema.sources.c.name, schema.sources.c.kind)
            )
        }
        source_name = named[item.document.source_id][0]
        others = tuple(
            Also(document, *named[document.source_id])
            for document in item.documents
            if document.id != item.document.id and document.source_id in named
        )
        found.append(
            Assessed(
                story=item.story,
                document=item.document,
                source_name=source_name,
                assessment=assessment,
                decision=decision,
                evidence=tuple(EvidenceItem.model_validate(dict(row)) for row in items),
                others=others,
            )
        )
    return found


@dataclass(frozen=True)
class Briefed:
    """A story's most recent place in an earlier day's briefing."""

    local_date: date
    final_class: EditorialClass
    observation_ids: frozenset[int]
    """The observations the assessment behind that place had been shown."""


def last_briefed(
    connection: Connection, before: date, variant: BriefingVariant
) -> dict[int, Briefed]:
    """For each story in a briefing for a day before ``before``: the latest such day, the
    class the story had in it, and what the assessment behind it had been shown.

    Only the newest version of each day's briefing counts: it is the day's briefing, and
    the versions it replaced are history.
    """
    briefings = schema.briefings
    items = schema.briefing_items
    decisions = schema.editorial_decisions
    inputs = schema.assessment_inputs
    newest = (
        select(briefings.c.local_date, func.max(briefings.c.version).label("version"))
        .where(briefings.c.variant == variant.value, briefings.c.local_date < before)
        .group_by(briefings.c.local_date)
        .subquery()
    )
    rows = connection.execute(
        select(
            items.c.story_id,
            briefings.c.local_date,
            decisions.c.final_class,
            decisions.c.assessment_id,
        )
        .join(briefings, briefings.c.id == items.c.briefing_id)
        .join(
            newest,
            and_(
                newest.c.local_date == briefings.c.local_date,
                newest.c.version == briefings.c.version,
            ),
        )
        .join(decisions, decisions.c.id == items.c.decision_id)
        .where(briefings.c.variant == variant.value, items.c.story_id.is_not(None))
        .order_by(briefings.c.local_date, items.c.position)
    ).all()
    found: dict[int, Briefed] = {}
    for row in rows:  # ascending by day, so the latest day is the one kept
        shown = connection.execute(
            select(inputs.c.observation_id).where(inputs.c.assessment_id == row.assessment_id)
        ).scalars()
        found[row.story_id] = Briefed(
            row.local_date, EditorialClass(row.final_class), frozenset(shown)
        )
    return found
