"""The baseline digest: one prompt over the day's collected items (RFC §1.1, ADR-007).

This is the simple thing the pipeline has to beat. The model is shown the day's fresh
items once and writes the briefing itself: it picks the stories, groups them and words
them. There is no screening, no assessment, no evidence check and no editorial policy.

Two things are the same as for the pipeline, because they are not what is being compared:

- **Source permissions.** Each item is shown exactly as the screening stage would show it
  (:func:`ai_briefing.editorial.process.screening_view`): a title, and a summary only
  where the source's terms allow one to be sent. No body text is sent.
- **Budget rules.** The call goes through the model client, so it is checked against the
  budget and recorded like any other.

And one safety rule: the model never supplies a link. It names documents by id, and every
address in the digest is a stored document's own.

The digest is stored as a briefing of the ``baseline`` variant. A day has one: generating
it again makes no call and stores nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from ai_briefing.briefings.compose import (
    HEADLINE_CHARS,
    MAX_SOURCES,
    MAX_STORIES,
    MAX_WATCH,
    SOURCE_NAME_CHARS,
    SUMMARY_CHARS,
    TITLE_CHARS,
    WEB_URL,
    WHY_CHARS,
    clip,
    day_bounds,
    latest_briefing,
    stable_hash,
    without_urls,
)
from ai_briefing.domain.enums import (
    BriefingStatus,
    BriefingVariant,
    LLMCallStatus,
    ModelSubmission,
    ModelTask,
)
from ai_briefing.domain.records import Briefing, Source, SourceDocument
from ai_briefing.editorial.contracts import BaselineOutput
from ai_briefing.editorial.process import FRESHNESS, screening_view
from ai_briefing.llm.client import ModelClient
from ai_briefing.prompts import load
from ai_briefing.storage import queries, repositories
from ai_briefing.storage.jobs import run_job, utc_now

PROMPT_ID = "baseline_digest"
SCHEMA_VERSION = "baseline_digest.v1"
MAX_ITEMS = 300
"""The newest items shown to the model. It keeps the one call well inside the lower price
tier; the digest records how many items there were and how many were shown."""
MAX_OUTPUT_TOKENS = 4_000


@dataclass(frozen=True)
class Generated:
    """What came of generating a day's baseline. ``briefing`` is ``None`` when the model
    gave no usable answer, and ``reason`` then says why in a few words."""

    briefing: Briefing | None
    created: bool
    reason: str | None = None


def packet(views: Sequence[Mapping[str, object]], local_date: date) -> str:
    """What the model is sent: the day's items as the source permissions allow, and the
    size the digest may be."""
    return json.dumps(
        {
            "date": local_date.isoformat(),
            "documents": list(views),
            "limits": {"stories": MAX_STORIES, "watch": MAX_WATCH},
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def shown_ids(request: str | None) -> list[int] | None:
    """The document ids a stored request showed the model, or ``None`` if it cannot be
    read (retention removes request text in time)."""
    if request is None:
        return None
    try:
        documents = json.loads(json.loads(request)["user"])["documents"]
        return [int(d["id"]) for d in documents]
    except (ValueError, KeyError, TypeError):
        return None


def _text(value: str, limit: int) -> str:
    return clip(without_urls(" ".join(value.split())), limit)


def build(
    output: BaselineOutput,
    shown: Mapping[int, SourceDocument],
    source_names: Mapping[str, str],
    *,
    local_date: date,
    timezone: str,
    generated_at: datetime,
    documents_fresh: int,
) -> dict[str, Any]:
    """The digest as stored, from the model's answer and the stored documents it names.

    Code decides what of the answer is used. A document the model was not shown is not a
    source; a story with no source left, or with no words, is dropped; anything past the
    limits is dropped; an address in the model's words is removed.
    """

    def source(document: SourceDocument) -> dict[str, str] | None:
        if not WEB_URL.fullmatch(document.canonical_url):
            return None
        return {
            "title": clip(document.title, TITLE_CHARS),
            "url": document.canonical_url,
            "source_name": clip(
                source_names.get(document.source_id, document.source_id), SOURCE_NAME_CHARS
            ),
        }

    stories: list[dict[str, Any]] = []
    used: set[int] = set()
    for story in output.stories:
        if len(stories) >= MAX_STORIES:
            break
        ids = [i for i in dict.fromkeys(story.document_ids) if i in shown]
        sources = [s for s in (source(shown[i]) for i in ids) if s is not None][:MAX_SOURCES]
        headline = _text(story.headline, HEADLINE_CHARS)
        summary = _text(story.summary, SUMMARY_CHARS)
        if not sources or not headline or not summary:
            continue
        used.update(ids)
        stories.append(
            {
                "item_id": f"i{len(stories) + 1}",
                "headline": headline,
                "summary": summary,
                "why_it_matters": _text(story.why_it_matters, WHY_CHARS),
                "document_ids": ids,
                "sources": sources,
            }
        )
    watchlist: list[dict[str, Any]] = []
    for item in output.watch:
        if len(watchlist) >= MAX_WATCH:
            break
        document = shown.get(item.document_id)
        if document is None or item.document_id in used:
            continue
        listed = source(document)
        if listed is None:
            continue
        used.add(item.document_id)
        watchlist.append(
            {
                "headline": _text(item.headline, HEADLINE_CHARS) or listed["title"],
                "url": listed["url"],
                "document_id": item.document_id,
            }
        )
    status = BriefingStatus.READY if stories or watchlist else BriefingStatus.EMPTY
    return {
        "schema_version": SCHEMA_VERSION,
        "briefing_id": f"baseline-{local_date.isoformat()}-1",
        "variant": BriefingVariant.BASELINE.value,
        "local_date": local_date.isoformat(),
        "timezone": timezone,
        "generated_at": generated_at.isoformat(),
        "status": status.value,
        "stories": stories,
        "watchlist": watchlist,
        "input": {"documents_fresh": documents_fresh, "documents_shown": len(shown)},
    }


@dataclass
class _Attempt:
    existing: Briefing | None = None
    output: BaselineOutput | None = None
    ids: list[int] = field(default_factory=list)
    fresh: int = 0
    reason: str | None = None


def generate(
    engine: Engine,
    catalogue: Sequence[Source],
    client: ModelClient,
    *,
    local_date: date,
    timezone: str,
    application_version: str,
    configuration_hash: str,
    clock: Callable[[], datetime] = utc_now,
) -> Generated:
    """Generate and store the day's baseline digest, as a recorded job.

    One answered call a day at most. If the day already has a digest, nothing is asked
    and nothing is stored. If an earlier attempt was answered and then stopped before the
    digest was stored, that answer is used, with the documents its own request showed.
    """
    prompt = load(PROMPT_ID)
    sources = {s.id: s for s in catalogue}
    submittable = [
        s.id for s in catalogue if s.enabled and s.model_submission is not ModelSubmission.NONE
    ]
    attempt = _Attempt()
    made: list[Briefing] = []

    def prepare(job_run_id: int) -> None:
        now = clock()
        _start, end = day_bounds(local_date, timezone)
        views: list[dict[str, object]] = []
        with engine.connect() as connection:
            attempt.existing = latest_briefing(connection, local_date, BriefingVariant.BASELINE)
            if attempt.existing is not None:
                return
            documents, attempt.fresh = queries.fresh_documents(
                connection, submittable, MAX_ITEMS, min(now, end) - FRESHNESS, end
            )
            earlier = queries.latest_answer(connection, job_run_id, ModelTask.BASELINE_DIGEST)
            if earlier is not None:
                answer, request = earlier
                ids = shown_ids(request)
                if answer is not None and ids is not None:
                    try:
                        attempt.output = BaselineOutput.model_validate_json(answer)
                        attempt.ids = ids
                        return
                    except ValueError:
                        pass  # not usable; ask again below
            for document in documents:
                if document.id is None:
                    continue
                latest = repositories.latest_observation(connection, document.id, with_body=False)
                view = screening_view(
                    sources[document.source_id], document, latest.summary if latest else None
                )
                if view is not None:
                    views.append(view)
        attempt.ids = [int(str(view["id"])) for view in views]
        if not views:
            # Nothing was collected that may be shown: the digest is empty, and no call
            # is made to say so.
            attempt.output = BaselineOutput(stories=[], watch=[])
            return
        result = client.call(
            task=ModelTask.BASELINE_DIGEST,
            job_run_id=job_run_id,
            prompt_id=prompt.id,
            system=prompt.text,
            user=packet(views, local_date),
            output_type=BaselineOutput,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        if result.status is not LLMCallStatus.SUCCEEDED or result.output is None:
            # Refused, failed or over budget. The call is on record; there is no digest
            # today unless a later attempt is answered.
            attempt.reason = result.reason or result.status.value
            return
        attempt.output = result.output

    def work(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
        if attempt.existing is not None:
            return {"stored": 0, "already_stored": 1}
        if attempt.output is None:
            return {"stored": 0, "without_answer": 1}
        content = build(
            attempt.output,
            queries.documents_by_id(connection, attempt.ids),
            {s.id: s.name for s in catalogue},
            local_date=local_date,
            timezone=timezone,
            generated_at=clock(),
            documents_fresh=attempt.fresh,
        )
        briefing = repositories.add(
            connection,
            Briefing(
                local_date=local_date,
                timezone=timezone,
                variant=BriefingVariant.BASELINE,
                version=1,
                status=BriefingStatus(content["status"]),
                content=json.dumps(content, ensure_ascii=False, sort_keys=True),
                content_hash=stable_hash(content),
                configuration_hash=configuration_hash,
            ),
        )
        made.append(briefing)
        return {
            "stored": 1,
            "stories": len(content["stories"]),
            "watch": len(content["watchlist"]),
            "documents_shown": len(attempt.ids),
        }

    run_job(
        engine,
        job="baseline",
        idempotency_key=f"baseline:{local_date.isoformat()}",
        application_version=application_version,
        configuration_hash=configuration_hash,
        prepare=prepare,
        work=work,
        run_again=True,
        clock=clock,
    )
    if attempt.existing is not None:
        return Generated(attempt.existing, created=False)
    if not made:
        return Generated(None, created=False, reason=attempt.reason or "no answer")
    return Generated(made[0], created=True)
