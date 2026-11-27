"""Selecting the day's stories and storing the briefing (RFC §4 step 11, §6.5, §8.2).

Selection is code, and deterministic: eligible stories are ordered by final class and then
by a fixed tuple of scores. At most five are stories; ``watch`` items go in a short list;
``low`` items are not shown. Nothing here calls a model.

Every URL in a briefing is the stored document's own. The assessment supplies words only,
and those words are length-limited here because the API does not limit them.

A stored briefing is immutable. Composing again produces a new version only when the
content would differ, so composing twice adds nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.engine import Connection

from ai_briefing.briefings.contract import contract_validator, load_schema
from ai_briefing.domain.enums import (
    BriefingItemKind,
    BriefingStatus,
    BriefingVariant,
    Confidence,
    EditorialClass,
    LLMCallStatus,
    SourceKind,
    SourceRole,
)
from ai_briefing.domain.records import Briefing, BriefingItem, Source
from ai_briefing.editorial.policy import v0 as policy
from ai_briefing.editorial.process import FRESHNESS, current_input_hash, redecide
from ai_briefing.sources import hn
from ai_briefing.storage import queries, repositories, schema

SCHEMA_VERSION = "daily_briefing.v1"
MAX_STORIES = 5
MAX_WATCH = 10
MAX_SOURCES = 8  # the contract's limit on a story's evidence list
HEADLINE_CHARS = 200
SUMMARY_CHARS = 800
WHY_CHARS = 600
UNCERTAINTY_CHARS = 250
TITLE_CHARS = 300
SOURCE_NAME_CHARS = 100
WEB_URL = re.compile(r'^https?://[^\s<>"]+$')
ANY_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
URL_REMOVED = "[link removed]"
STORY_CLASSES = (EditorialClass.MAJOR, EditorialClass.PRACTICAL)
BUDGET_REASON = "Budget: some items could not be assessed today."


class BriefingError(RuntimeError):
    """The composed briefing does not satisfy its own contract. Nothing was stored."""


@dataclass(frozen=True)
class Composed:
    briefing: Briefing
    created: bool  # False when an identical version was already stored
    redecided: int = 0  # decisions remade under the current policy version


def without_urls(text: str) -> str:
    """Model-written text with any web address taken out.

    The model is told never to write a URL. If it does, the address is not passed on: the
    only addresses a reader is shown are those of stored documents.
    """
    return ANY_URL.sub(URL_REMOVED, text)


def clip(text: str, limit: int) -> str:
    """Plain text on one line, cut to ``limit`` characters with an ellipsis if longer."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def order_key(item: queries.Assessed) -> tuple[int, int, int, int, int, int, int]:
    """Most significant first: class, then impact, evidence, relevance, novelty, maturity."""
    scores = item.assessment.scores
    return (
        -item.decision.final_class.rank,
        -scores.impact,
        -scores.evidence,
        -scores.professional_relevance,
        -scores.novelty,
        -scores.maturity,
        item.story.id or 0,
    )


def confidence(item: queries.Assessed) -> Confidence:
    """How firmly the story rests on checked quotations. Worked out here, not by the model."""
    verified = sum(1 for evidence in item.evidence if evidence.counts_as_support)
    score = item.assessment.scores.evidence
    if verified >= 2 and score >= 3:
        return Confidence.HIGH
    if verified >= 1 and score >= 2:
        return Confidence.MODERATE
    return Confidence.LOW


def _draft(item: queries.Assessed) -> dict[str, str]:
    try:
        draft = json.loads(item.assessment.draft_text)
    except json.JSONDecodeError:
        draft = {}
    return {
        key: without_urls(str(draft.get(key) or ""))
        for key in ("headline", "summary", "why_it_matters")
    }


def _why(item: queries.Assessed, draft: dict[str, str]) -> str:
    # The uncertainty note always reaches the reader. Room is kept for it first.
    note = "Uncertainty: " + clip(without_urls(item.assessment.uncertainty), UNCERTAINTY_CHARS)
    why = clip(draft["why_it_matters"], WHY_CHARS - len(note) - 1)
    return f"{why} {note}".strip()


def _sources(item: queries.Assessed) -> list[dict[str, str]]:
    """The documents behind a story, the one it is known by first. Every address is a
    stored document's own, or, for a Hacker News item, its discussion page, built from
    the item's stored id."""
    listed = [
        {
            "title": clip(item.document.title, TITLE_CHARS),
            "url": item.document.canonical_url,
            "source_name": clip(item.source_name, SOURCE_NAME_CHARS),
            "source_role": item.document.source_role.value,
        }
    ]
    for other in item.others:
        url = other.document.canonical_url
        if other.source_kind is SourceKind.HN_API:
            try:
                url = hn.discussion_url(other.document.external_id)
            except ValueError:
                continue
        if not WEB_URL.fullmatch(url) or len(listed) >= MAX_SOURCES:
            continue
        listed.append(
            {
                "title": clip(other.document.title, TITLE_CHARS),
                "url": url,
                "source_name": clip(other.source_name, SOURCE_NAME_CHARS),
                "source_role": other.document.source_role.value,
            }
        )
    return listed


def _again(item: queries.Assessed, returning: Mapping[int, str]) -> str:
    why = returning.get(item.story.id or 0)
    return f"; briefed before, and {why}" if why else ""


def repetition(
    connection: Connection, assessed: list[queries.Assessed], local_date: date
) -> tuple[list[queries.Assessed], dict[int, str]]:
    """Apply the repetition rule (RFC §6.3): the stories that may be in this day's briefing,
    and, for each one that was in an earlier day's, the reason it may appear again.
    """
    briefed = queries.last_briefed(connection, local_date, BriefingVariant.PIPELINE)
    allowed: list[queries.Assessed] = []
    returning: dict[int, str] = {}
    for item in assessed:
        before = briefed.get(item.story.id or 0)
        if before is None:
            allowed.append(item)
            continue
        why = policy.may_appear_again(
            briefed_class=before.final_class,
            current_class=item.decision.final_class,
            new_independent_evidence=_new_evidence(
                item, before.observation_ids, partial(_role_of, connection, item)
            ),
        )
        if why is not None and item.story.id is not None:
            allowed.append(item)
            returning[item.story.id] = why
    return allowed, returning


def _role_of(
    connection: Connection, item: queries.Assessed, observation_id: int
) -> SourceRole | None:
    """The role of the source of the document an observation is of, if it is in the story."""
    observation = queries.observation(connection, observation_id)
    if observation is None:
        return None
    for document in item.documents:
        if document.id == observation.document_id:
            return document.source_role
    return None


def _new_evidence(
    item: queries.Assessed,
    already_shown: frozenset[int],
    role_of: Callable[[int], SourceRole | None],
) -> bool:
    """Whether a verified quotation rests on an observation the previously briefed
    assessment had not been shown, from a primary or independent source.

    Compared by observation, not by time: what counts is that the evidence is not what the
    reader was already given. The role is that of the source that was quoted, whichever
    document the story is known by.
    """
    return any(
        evidence.counts_as_support
        and evidence.observation_id not in already_shown
        and role_of(evidence.observation_id) in policy.INDEPENDENT_ROLES
        for evidence in item.evidence
    )


def build(
    assessed: list[queries.Assessed],
    *,
    local_date: date,
    timezone: str,
    generated_at: datetime,
    version: int,
    degraded_reasons: list[str],
    returning: Mapping[int, str] | None = None,
) -> tuple[dict[str, Any], list[tuple[BriefingItemKind, queries.Assessed, str, str]]]:
    """The briefing document, and the items in it with the reason each was included.

    ``returning`` maps a story that was in an earlier day's briefing and may appear again
    to the reason it may; that reason is stored with the item.
    """
    returning = returning or {}
    usable = [
        item
        for item in sorted(assessed, key=order_key)
        if item.decision.eligible and WEB_URL.fullmatch(item.document.canonical_url)
    ]
    chosen: list[queries.Assessed] = []
    watching: list[queries.Assessed] = []
    for item in usable:  # best first, so of two near-duplicates the better one is kept
        if item.decision.final_class in STORY_CLASSES:
            place, limit = chosen, MAX_STORIES
        elif item.decision.final_class is EditorialClass.WATCH:
            place, limit = watching, MAX_WATCH
        else:
            continue
        if len(place) >= limit:
            continue
        if any(
            policy.similar_titles(item.document.title, kept.document.title)
            for kept in (*chosen, *watching)
        ):
            continue  # the same headline twice in one briefing (RFC §6.3)
        place.append(item)
    items: list[tuple[BriefingItemKind, queries.Assessed, str, str]] = []
    stories: list[dict[str, Any]] = []
    watchlist: list[dict[str, Any]] = []
    for item in chosen:
        draft = _draft(item)
        headline = clip(draft["headline"] or item.document.title, HEADLINE_CHARS)
        item_id = f"i{len(items) + 1}"
        stories.append(
            {
                "item_id": item_id,
                "story_id": f"s-{item.story.id}",
                "decision_id": f"d-{item.decision.id}",
                "class": item.decision.final_class.value,
                "confidence": confidence(item).value,
                "headline": headline,
                "summary": clip(draft["summary"] or item.document.title, SUMMARY_CHARS),
                "why_it_matters": _why(item, draft),
                "independent_source_count": item.decision.independent_source_count,
                "evidence": _sources(item),
            }
        )
        reason = f"class {item.decision.final_class.value}, ranked {len(stories)} of the day"
        reason += _again(item, returning)
        items.append((BriefingItemKind.STORY, item, headline, reason))
    for item in watching:
        headline = clip(_draft(item)["headline"] or item.document.title, HEADLINE_CHARS)
        watchlist.append(
            {
                "item_id": f"i{len(items) + 1}",
                "headline": headline,
                "url": item.document.canonical_url,
            }
        )
        why = "; ".join(item.decision.ceiling_reasons) or "suggested as watch"
        reason = f"class watch: {why}" + _again(item, returning)
        items.append((BriefingItemKind.WATCH, item, headline, reason))
    if not stories and not watchlist:
        status, reasons = BriefingStatus.EMPTY, degraded_reasons
    elif degraded_reasons:
        status, reasons = BriefingStatus.DEGRADED, degraded_reasons
    else:
        status, reasons = BriefingStatus.READY, []
    content = {
        "schema_version": SCHEMA_VERSION,
        "briefing_id": f"b-{local_date.isoformat()}-{version}",
        "local_date": local_date.isoformat(),
        "timezone": timezone,
        "generated_at": generated_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status.value,
        # An empty briefing may still say why it is empty; the schema allows that.
        "degraded_reasons": reasons if status is not BriefingStatus.READY else [],
        "stories": stories,
        "watchlist": watchlist,
    }
    return content, items


def stable_hash(content: dict[str, Any]) -> str:
    """A hash of what a briefing says, leaving out when it was generated and its version."""
    said = {k: v for k, v in content.items() if k not in ("generated_at", "briefing_id")}
    return hashlib.sha256(json.dumps(said, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def day_bounds(local_date: date, timezone: str) -> tuple[datetime, datetime]:
    """The start and end of a local calendar day, in UTC."""
    zone = ZoneInfo(timezone)
    start = datetime.combine(local_date, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return start, end


def _budget_refusals(connection: Connection, start: datetime, end: datetime) -> int:
    calls = schema.llm_calls
    rows = connection.execute(
        select(calls.c.id).where(
            calls.c.status == LLMCallStatus.BUDGET_REFUSED.value,
            calls.c.created_at >= start,
            calls.c.created_at < end,
        )
    ).all()
    return len(rows)


def latest_briefing(
    connection: Connection, local_date: date, variant: BriefingVariant
) -> Briefing | None:
    table = schema.briefings
    row = (
        connection.execute(
            select(table)
            .where(table.c.local_date == local_date, table.c.variant == variant.value)
            .order_by(table.c.version.desc())
        )
        .mappings()
        .first()
    )
    return None if row is None else Briefing.model_validate(dict(row))


def compose(
    connection: Connection,
    catalogue: Sequence[Source],
    *,
    local_date: date,
    timezone: str,
    configuration_hash: str,
    now: datetime,
) -> Composed:
    """Compose the pipeline briefing for a day and store it as a new version if it differs
    from the latest. The caller's transaction holds all of it.
    """
    start, end = day_bounds(local_date, timezone)
    # The same clock as processing: an item is news for FRESHNESS after it was published,
    # counted back from now. So anything processing just paid to assess is still fresh
    # here. A briefing composed for an earlier day counts back from that day's end.
    reference = min(now, end)
    sources = {source.id: source for source in catalogue}
    # The briefing is made under the policy in force now (RFC §6.3). Any story decided
    # under another version is decided again first, from stored facts, with no model call.
    redecided = redecide(connection, sources, fresh_from=reference - FRESHNESS)
    assessed = queries.assessed_stories(
        connection,
        reference - FRESHNESS,
        lambda item: current_input_hash(connection, sources, item),
    )
    assessed = [item for item in assessed if item.fresh_at < end]
    assessed, returning = repetition(connection, assessed, local_date)
    reasons = [BUDGET_REASON] if _budget_refusals(connection, start, end) else []
    previous = latest_briefing(connection, local_date, BriefingVariant.PIPELINE)
    version = previous.version + 1 if previous else 1
    content, items = build(
        assessed,
        local_date=local_date,
        timezone=timezone,
        generated_at=now,
        version=version,
        degraded_reasons=reasons,
        returning=returning,
    )
    digest = stable_hash(content)
    if previous is not None and previous.content_hash == digest:
        return Composed(previous, created=False, redecided=redecided)
    errors = sorted(
        f"{'/'.join(str(p) for p in error.absolute_path) or '(document)'}: {error.message}"
        for error in contract_validator(load_schema(SCHEMA_VERSION)).iter_errors(content)
    )
    if errors:
        raise BriefingError("the composed briefing is not valid: " + "; ".join(errors[:5]))
    briefing = repositories.add(
        connection,
        Briefing(
            local_date=local_date,
            timezone=timezone,
            variant=BriefingVariant.PIPELINE,
            version=version,
            status=BriefingStatus(content["status"]),
            content=json.dumps(content, ensure_ascii=False, sort_keys=True),
            content_hash=digest,
            configuration_hash=configuration_hash,
        ),
    )
    if briefing.id is None:
        raise BriefingError("the briefing was not stored")
    for position, (kind, item, headline, reason) in enumerate(items, start=1):
        repositories.add(
            connection,
            BriefingItem(
                briefing_id=briefing.id,
                position=position,
                kind=kind,
                story_id=item.story.id,
                decision_id=item.decision.id,
                text=headline,
                inclusion_reason=reason,
            ),
        )
    return Composed(briefing, created=True, redecided=redecided)
