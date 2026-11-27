"""Processing collected items into decided stories (RFC §4 steps 4 to 9).

Three stages, each a job of its own, run in order:

1. **Screen.** New items are rated for relevance, in batches. Every outcome is stored
   with its reason. An item that passes becomes a story of its own.
2. **Fetch.** For an item that passed, the article page is fetched where its source
   permits. Anything else stays as it was collected.
3. **Assess.** The model reads each story's observations and returns claims with
   quotations, scores and a suggested class. Code then checks every quotation against the
   stored text, and the policy sets the final class.

In each stage the model calls and fetches happen first, with no transaction open, and the
results are then written together with the stage's completion.

What the model is shown of an item follows its source's ``model_submission`` and nothing
else: nothing for ``none``, the title for ``metadata``, the title and feed summary for
``title_and_summary``, the title and article text for ``full_text``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import (
    AssessmentTier,
    EditorialClass,
    IntegrityStatus,
    LLMCallStatus,
    MembershipAction,
    ModelSubmission,
    ModelTask,
    ScreeningOutcome,
    SourceMode,
    SupportType,
)
from ai_briefing.domain.records import (
    DimensionScores,
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
    EvidenceItem,
    ScreeningDecision,
    Source,
    SourceDocument,
    Story,
    StoryMembershipEvent,
)
from ai_briefing.editorial import integrity
from ai_briefing.editorial.contracts import AssessmentOutput, ScreeningOutput
from ai_briefing.editorial.policy import v0 as policy
from ai_briefing.llm.client import ModelClient
from ai_briefing.prompts import RUBRIC_VERSION, load
from ai_briefing.sources.collect import fetch_body, may_fetch_body, store_body
from ai_briefing.sources.fetcher import Fetcher
from ai_briefing.sources.network import FetchError
from ai_briefing.storage import queries, repositories
from ai_briefing.storage.jobs import JobOutcome, run_job, utc_now

SCREENING_BATCH = 25
SCREENING_MAX_OUTPUT_TOKENS = 4_000
ASSESSMENT_MAX_OUTPUT_TOKENS = 3_000
MAX_SCREENED_PER_RUN = 600
# The model rates relevance from 0 to 4. Code decides what passes: this rating or higher.
PASS_RELEVANCE = 2
MAX_ASSESSED_PER_RUN = 60
# Article text beyond this is not sent. It keeps a prompt well under the size at which
# the inexpensive model's higher price applies, whatever the article's length.
MAX_TEXT_CHARS = 40_000
OWN_STORY_RULE = "own-story"
# How long an item is news is an editorial rule, so it lives with the policy. Older items
# are kept for recognition and are not screened, fetched, assessed or briefed.
FRESHNESS = policy.FRESHNESS


@dataclass(frozen=True)
class Settings:
    application_version: str
    configuration_hash: str
    day: str  # the local date being processed, as YYYY-MM-DD; part of each job's key


def screening_view(
    source: Source, document: SourceDocument, summary: str | None
) -> dict[str, object] | None:
    """What the model may see of an item at screening, or ``None`` if nothing."""
    if not source.enabled or source.model_submission is ModelSubmission.NONE:
        return None
    view: dict[str, object] = {"id": document.id, "source": source.name, "title": document.title}
    if source.model_submission is ModelSubmission.TITLE_AND_SUMMARY and summary:
        view["summary"] = summary
    return view


def assessment_text(source: Source, observation: DocumentObservation) -> str | None:
    """The text of an observation the model may read at assessment, or ``None``."""
    if source.model_submission is ModelSubmission.TITLE_AND_SUMMARY:
        return observation.summary
    if source.model_submission is ModelSubmission.FULL_TEXT and source.mode is SourceMode.FULL_TEXT:
        return observation.body_text[:MAX_TEXT_CHARS] if observation.body_text else None
    return None


def assessment_packet(
    source: Source, document: SourceDocument, observation: DocumentObservation
) -> str:
    """The message sent to the model for one story: its observations, as permitted."""
    shown = {
        "observation_id": observation.id,
        "source_name": source.name,
        "source_role": document.source_role.value,
        "title": document.title,
        "published": document.published_at.isoformat() if document.published_at else None,
        "text": assessment_text(source, observation),
    }
    return json.dumps({"observations": [shown]}, ensure_ascii=False, sort_keys=True)


def best_observation(
    connection: Connection, source: Source, document: SourceDocument
) -> DocumentObservation | None:
    """The observation to assess a document from: the one with article text if the source
    permits sending it and it exists, else the newest from the feed."""
    if document.id is None:
        return None
    if source.model_submission is ModelSubmission.FULL_TEXT:
        with_body = repositories.latest_observation(connection, document.id, with_body=True)
        if with_body is not None and with_body.body_text is not None:
            return with_body
    return repositories.latest_observation(connection, document.id, with_body=False) or (
        repositories.latest_observation(connection, document.id)
    )


def in_turn[T](
    items: Sequence[T],
    *,
    source_of: Callable[[T], str],
    rank: Callable[[T], tuple[float, ...]],
) -> list[T]:
    """Items ordered so that each source takes a turn: every source's best item, then
    every source's second best, and so on. Within a turn, the better-ranked item is first.
    """
    by_source: dict[str, list[T]] = {}
    for item in sorted(items, key=rank):
        by_source.setdefault(source_of(item), []).append(item)
    ordered: list[T] = []
    turn = 0
    while len(ordered) < len(items):
        taking = [queue[turn] for queue in by_source.values() if turn < len(queue)]
        ordered.extend(sorted(taking, key=rank))
        turn += 1
    return ordered


def input_hash(packet: str) -> str:
    """A hash of exactly what an assessment was given: the whole packet sent to the model.

    The packet holds the observation ids, the title and the permitted text. So a corrected
    headline, a changed summary or newly fetched article text each make a new input, and
    the story is assessed again; an unchanged packet is never assessed twice.
    """
    return hashlib.sha256(packet.encode("utf-8")).hexdigest()


def current_input_hash(
    connection: Connection, sources: Mapping[str, Source], item: queries.StoryInput
) -> str | None:
    """The input hash a story would be assessed with now, or ``None`` if it cannot be.

    Assessment and briefing selection both use this, so a briefing shows the assessment
    of what the source says today.
    """
    source = sources.get(item.document.source_id)
    if source is None or not source.enabled or source.model_submission is ModelSubmission.NONE:
        return None
    observation = best_observation(connection, source, item.document)
    if observation is None or observation.id is None:
        return None
    return input_hash(assessment_packet(source, item.document, observation))


# --- Stage 1: screen ----------------------------------------------------------------------------


def screen(
    engine: Engine,
    catalogue: Sequence[Source],
    client: ModelClient,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> JobOutcome:
    prompt = load("screening")
    sources = {s.id: s for s in catalogue}
    submittable = [
        s.id for s in catalogue if s.enabled and s.model_submission is not ModelSubmission.NONE
    ]
    decided: list[ScreeningDecision] = []
    counts = {"screened": 0, "passed": 0, "rejected": 0, "calls_without_result": 0, "unanswered": 0}

    def prepare(job_run_id: int) -> None:
        with engine.connect() as connection:
            documents = queries.unscreened_documents(
                connection, submittable, MAX_SCREENED_PER_RUN, clock() - FRESHNESS
            )
            views: list[dict[str, object]] = []
            for document in documents:
                if document.id is None:
                    continue
                latest = repositories.latest_observation(connection, document.id, with_body=False)
                view = screening_view(
                    sources[document.source_id], document, latest.summary if latest else None
                )
                if view is not None:
                    views.append(view)
        for start in range(0, len(views), SCREENING_BATCH):
            batch = views[start : start + SCREENING_BATCH]
            result = client.call(
                task=ModelTask.SCREENING,
                job_run_id=job_run_id,
                prompt_id=prompt.id,
                system=prompt.text,
                user=json.dumps({"items": batch}, ensure_ascii=False, sort_keys=True),
                output_type=ScreeningOutput,
                max_output_tokens=SCREENING_MAX_OUTPUT_TOKENS,
            )
            if result.status is not LLMCallStatus.SUCCEEDED or result.output is None:
                # Refused, failed or over budget. The items stay unscreened and are tried
                # again on a later run; the call itself is already on record.
                counts["calls_without_result"] += 1
                if result.status is LLMCallStatus.BUDGET_REFUSED:
                    break  # no later batch would fare better today
                continue
            asked = {int(str(view["id"])) for view in batch}
            answered: set[int] = set()
            for item in result.output.results:
                # An id the model was not given, or gave twice, is not a result.
                if item.id not in asked or item.id in answered or result.call.id is None:
                    continue
                answered.add(item.id)
                decided.append(
                    ScreeningDecision(
                        document_id=item.id,
                        outcome=(
                            ScreeningOutcome.PASSED
                            if item.relevance >= PASS_RELEVANCE
                            else ScreeningOutcome.REJECTED
                        ),
                        relevance=item.relevance,
                        reason=item.reason.strip()[:500] or "no reason given",
                        model_call_id=result.call.id,
                        decided_at=clock(),
                    )
                )
            counts["unanswered"] += len(asked - answered)

    def work(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
        for decision in decided:
            repositories.add(connection, decision)
            counts["screened"] += 1
            counts["passed" if decision.outcome is ScreeningOutcome.PASSED else "rejected"] += 1
        # In M1 each document that passes is a story of its own (issue 1.9 adds grouping).
        now = clock()
        for document in queries.passed_documents_without_story(connection):
            if document.id is None:
                continue
            story = repositories.add(
                connection, Story(title=document.title, first_seen_at=now, last_activity_at=now)
            )
            if story.id is None:
                continue
            repositories.record_membership(
                connection,
                StoryMembershipEvent(
                    story_id=story.id,
                    document_id=document.id,
                    action=MembershipAction.ADD,
                    reason="a document that passed screening starts its own story",
                    decided_by_rule=OWN_STORY_RULE,
                    occurred_at=now,
                ),
            )
        return counts

    return run_job(
        engine,
        job="screen",
        idempotency_key=f"screen:{settings.day}",
        application_version=settings.application_version,
        configuration_hash=settings.configuration_hash,
        prepare=prepare,
        work=work,
        clock=clock,
    )


# --- Stage 2: fetch article pages ---------------------------------------------------------------


def fetch_bodies(
    engine: Engine,
    catalogue: Sequence[Source],
    fetcher: Fetcher,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> JobOutcome:
    sources = {s.id: s for s in catalogue}
    page_sources = [
        s.id
        for s in catalogue
        if s.enabled and s.body is not None and s.mode is SourceMode.FULL_TEXT
    ]
    fetched: list[tuple[SourceDocument, str]] = []
    counts = {"bodies_stored": 0, "not_permitted": 0, "fetch_failed": 0, "no_text": 0}

    def prepare(_job_run_id: int) -> None:
        with engine.connect() as connection:
            documents = queries.passed_documents_without_body(
                connection, page_sources, clock() - FRESHNESS
            )
        for document in documents:
            source = sources[document.source_id]
            if not may_fetch_body(source, document):
                counts["not_permitted"] += 1  # stays metadata-only
                continue
            try:
                text = fetch_body(fetcher, source, document)
            except FetchError:
                counts["fetch_failed"] += 1
                continue
            if text:
                fetched.append((document, text))
            else:
                counts["no_text"] += 1

    def work(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
        now = clock()
        for document, text in fetched:
            counts["bodies_stored"] += store_body(
                connection, sources[document.source_id], document, text, now=now
            )
        return counts

    return run_job(
        engine,
        job="fetch-bodies",
        idempotency_key=f"fetch-bodies:{settings.day}",
        application_version=settings.application_version,
        configuration_hash=settings.configuration_hash,
        prepare=prepare,
        work=work,
        clock=clock,
    )


# --- Stage 3: assess, verify, decide ------------------------------------------------------------


@dataclass
class _Assessed:
    story_id: int
    source: Source
    document: SourceDocument
    observation: DocumentObservation
    as_of: datetime
    digest: str
    model_call_id: int
    output: AssessmentOutput
    has_text: bool
    evidence: list[tuple[str, int, str, SupportType, IntegrityStatus]] = field(default_factory=list)


def assess(
    engine: Engine,
    catalogue: Sequence[Source],
    client: ModelClient,
    model_id: str,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> JobOutcome:
    prompt = load("assessment")
    sources = {s.id: s for s in catalogue}
    done: list[_Assessed] = []
    counts = {
        "assessed": 0,
        "calls_without_result": 0,
        "rejected_unknown_citation": 0,
        "evidence_verified": 0,
        "evidence_failed": 0,
        "citations_over_limit": 0,
    }

    def prepare(job_run_id: int) -> None:
        fresh_from = clock() - FRESHNESS
        with engine.connect() as connection:
            pending: list[tuple[int, Source, SourceDocument, DocumentObservation, str, str]] = []
            for item in queries.open_stories(connection):
                source = sources.get(item.document.source_id)
                if source is None or item.story.id is None:
                    continue
                if source.model_submission is ModelSubmission.NONE or not source.enabled:
                    continue
                if item.document.fresh_at < fresh_from:
                    continue  # no longer news; not worth a model call
                observation = best_observation(connection, source, item.document)
                if observation is None or observation.id is None:
                    continue
                packet = assessment_packet(source, item.document, observation)
                digest = input_hash(packet)
                if queries.assessment_exists(
                    connection, item.story.id, digest, prompt.sha256, model_id
                ):
                    continue
                pending.append((item.story.id, source, item.document, observation, packet, digest))
            relevance = queries.screening_relevance(connection)
        # A run assesses a limited number, so the order decides what the day's briefing
        # is made from. Within a source: the most relevant first, then the newest. Across
        # sources: each in turn, so one source that publishes hundreds of items a day
        # cannot use up the run before the others are reached.
        pending = in_turn(
            pending,
            source_of=lambda entry: entry[1].id,
            rank=lambda entry: (
                -relevance.get(entry[2].id or 0, 0),
                -entry[2].fresh_at.timestamp(),
                entry[0],
            ),
        )
        for story_id, source, document, observation, packet, digest in pending[
            :MAX_ASSESSED_PER_RUN
        ]:
            text = assessment_text(source, observation)
            as_of = clock()
            result = client.call(
                task=ModelTask.ASSESSMENT,
                job_run_id=job_run_id,
                prompt_id=prompt.id,
                system=prompt.text,
                user=packet,
                output_type=AssessmentOutput,
                max_output_tokens=ASSESSMENT_MAX_OUTPUT_TOKENS,
            )
            if (
                result.status is not LLMCallStatus.SUCCEEDED
                or result.output is None
                or result.call.id is None
                or observation.id is None
            ):
                counts["calls_without_result"] += 1
                if result.status is LLMCallStatus.BUDGET_REFUSED:
                    break
                continue
            # What the model was given, as it was given: the text is the sent text.
            given = {observation.id: integrity.Shown(observation, text)}
            citations = [c for claim in result.output.claims for c in claim.evidence]
            if any(c.observation_id not in given for c in citations):
                # A citation to something the model was never shown. The whole assessment
                # is rejected (ADR-004): nothing it says can be trusted to be grounded.
                counts["rejected_unknown_citation"] += 1
                continue
            assessed = _Assessed(
                story_id=story_id,
                source=source,
                document=document,
                observation=observation,
                as_of=as_of,
                digest=digest,
                model_call_id=result.call.id,
                output=result.output,
                has_text=bool(text),
            )
            limit = source.excerpt_limit_chars
            for claim in result.output.claims:
                for citation in claim.evidence:
                    quote = citation.quote.strip()
                    if not quote:
                        continue
                    if not source.excerpts_allowed or (limit is not None and len(quote) > limit):
                        # Longer than the source's quotation limit, or from a source that
                        # allows none. It is not kept, not shown, and gives no support.
                        counts["citations_over_limit"] += 1
                        continue
                    holds = integrity.citation_holds(quote, citation.observation_id, given, as_of)
                    assessed.evidence.append(
                        (
                            claim.text.strip()[:1000] or "(no claim text)",
                            citation.observation_id,
                            quote,
                            SupportType(citation.support),
                            IntegrityStatus.VERIFIED if holds else IntegrityStatus.FAILED,
                        )
                    )
            done.append(assessed)

    def work(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
        for item in done:
            output = item.output
            assessment = repositories.add(
                connection,
                EditorialAssessment(
                    story_id=item.story_id,
                    as_of=item.as_of,
                    input_hash=item.digest,
                    prompt_hash=prompt.sha256,
                    model_id=model_id,
                    rubric_version=RUBRIC_VERSION,
                    tier=AssessmentTier.STANDARD,
                    scores=DimensionScores(**output.scores.model_dump()),
                    suggested_class=EditorialClass(output.suggested_class),
                    uncertainty=output.uncertainty.strip() or "Not stated.",
                    draft_text=json.dumps(
                        {
                            "headline": output.headline,
                            "summary": output.summary,
                            "why_it_matters": output.why_it_matters,
                        },
                        ensure_ascii=False,
                    ),
                    model_call_id=item.model_call_id,
                ),
            )
            if assessment.id is None or item.observation.id is None:
                continue
            repositories.add_assessment_inputs(connection, assessment.id, [item.observation.id])
            verified = 0
            for claim_text, observation_id, quote, support, status in item.evidence:
                stored = repositories.add(
                    connection,
                    EvidenceItem(
                        assessment_id=assessment.id,
                        claim_text=claim_text,
                        observation_id=observation_id,
                        quote=quote,
                        support_type=support,
                        integrity_status=status,
                    ),
                )
                verified += stored.counts_as_support
                key = (
                    "evidence_verified" if status is IntegrityStatus.VERIFIED else "evidence_failed"
                )
                counts[key] += 1
            verdict = policy.decide(
                assessment.suggested_class,
                verified_supporting_evidence=verified,
                has_source_text=item.has_text,
                source_roles=[(item.document.source_id, item.document.source_role)],
            )
            repositories.add(
                connection,
                EditorialDecision(
                    assessment_id=assessment.id,
                    policy_version=policy.POLICY_VERSION,
                    final_class=verdict.final_class,
                    ceiling=verdict.ceiling,
                    ceiling_reasons=verdict.ceiling_reasons,
                    independent_source_count=verdict.independent_source_count,
                    eligible=verdict.eligible,
                ),
            )
            counts["assessed"] += 1
        return counts

    return run_job(
        engine,
        job="assess",
        idempotency_key=f"assess:{settings.day}",
        application_version=settings.application_version,
        configuration_hash=settings.configuration_hash,
        prepare=prepare,
        work=work,
        clock=clock,
    )


def redecide(connection: Connection, sources: Mapping[str, Source], *, fresh_from: datetime) -> int:
    """Decide again each fresh story whose standing decision was made under another version
    of the policy (RFC §6.3). Returns how many were decided.

    No model is called. The facts come from stored records: the evidence items of the
    story's current assessment, and the text that assessment was given. The earlier
    decision is kept; the new one is added after it and is the one that stands.

    Composing a briefing calls this first, in its own transaction. So a briefing is always
    made under the policy in force when it is composed, whenever the stories in it were
    assessed, and a policy change takes effect the next time any day is composed.
    """
    made = 0
    standing = queries.assessed_stories(
        connection, fresh_from, lambda item: current_input_hash(connection, sources, item)
    )
    for item in standing:
        source = sources.get(item.document.source_id)
        if item.decision.policy_version == policy.POLICY_VERSION or source is None:
            continue
        if item.assessment.id is None:
            continue
        if queries.decision_exists(connection, item.assessment.id, policy.POLICY_VERSION):
            # There is one decision per assessment and policy version, and this version
            # has made its own. A later decision under another version stands instead:
            # versions only move forward, so that is a correction, not a stale decision.
            continue
        # The assessment is of the story's current input, so the text it was given is the
        # text that would be sent now.
        observation = best_observation(connection, source, item.document)
        text = assessment_text(source, observation) if observation is not None else None
        verdict = policy.decide(
            item.assessment.suggested_class,
            verified_supporting_evidence=sum(e.counts_as_support for e in item.evidence),
            has_source_text=bool(text),
            source_roles=[(item.document.source_id, item.document.source_role)],
        )
        repositories.add(
            connection,
            EditorialDecision(
                assessment_id=item.assessment.id,
                policy_version=policy.POLICY_VERSION,
                final_class=verdict.final_class,
                ceiling=verdict.ceiling,
                ceiling_reasons=verdict.ceiling_reasons,
                independent_source_count=verdict.independent_source_count,
                eligible=verdict.eligible,
            ),
        )
        made += 1
    return made


def process(
    engine: Engine,
    catalogue: Sequence[Source],
    client: ModelClient,
    fetcher: Fetcher,
    model_id: str,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Mapping[str, int]]:
    """Run the three stages for a day. Each is skipped if it already succeeded that day."""
    return {
        "screen": screen(engine, catalogue, client, settings, clock=clock).counts,
        "fetch-bodies": fetch_bodies(engine, catalogue, fetcher, settings, clock=clock).counts,
        "assess": assess(engine, catalogue, client, model_id, settings, clock=clock).counts,
    }
