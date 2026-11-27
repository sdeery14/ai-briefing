"""The blind comparison between a day's pipeline briefing and its baseline digest
(ADR-007 point 4, RFC §10.2).

The reader is shown both, unlabelled, in an order chosen at random, and says which they
prefer. The choice is stored as what they saw (the first or the second) together with the
order, which they were not shown, and the policy and prompt hashes in force.

Both briefings are shown through one plain view: headline, summary, why it matters, and
links; then the watch list. Anything only one of them can have is left out (the class and
confidence line, source roles, the background note, the notes about a degraded day), so
the layout does not give away which is which. The wording and the choice of stories are
what is being compared.

Nothing here reveals the order. It is in the database for the analysis that follows the
comparison period, which is a later issue.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from ai_briefing.briefings.compose import latest_briefing
from ai_briefing.briefings.render import escape, link
from ai_briefing.domain.enums import BriefingVariant, ComparisonChoice, PresentationOrder
from ai_briefing.domain.records import Briefing, ComparisonJudgment
from ai_briefing.editorial.policy import v0 as policy
from ai_briefing.prompts import DIRECTORY as PROMPTS
from ai_briefing.prompts import load
from ai_briefing.storage import queries, repositories
from ai_briefing.storage.jobs import utc_now

LABELS = ("A", "B")
QUESTION = "Which do you prefer? [a / b / n = no preference] "
ANSWERS = {
    "a": ComparisonChoice.FIRST,
    "b": ComparisonChoice.SECOND,
    "n": ComparisonChoice.NO_PREFERENCE,
}
MAX_ASKS = 3


class ComparisonError(RuntimeError):
    """The comparison could not be made, or no choice was recorded."""


class AlreadyCompared(ComparisonError):  # noqa: N818 - reads as a statement of fact
    """The day already has a judgement, and another was not asked for."""


@dataclass(frozen=True)
class ViewStory:
    headline: str
    summary: str
    why_it_matters: str
    sources: tuple[tuple[str, str, str], ...]  # title, address, source name


@dataclass(frozen=True)
class View:
    """What the reader is shown of a briefing: the same fields whichever it is."""

    local_date: str
    stories: tuple[ViewStory, ...]
    watch: tuple[tuple[str, str], ...]  # headline, address


def reader_view(content: dict[str, Any]) -> View:
    """The plain view of a stored briefing, pipeline or baseline."""
    stories = []
    for story in content.get("stories", []):
        listed = story.get("evidence") or story.get("sources") or []
        stories.append(
            ViewStory(
                headline=str(story["headline"]),
                summary=str(story["summary"]),
                why_it_matters=str(story.get("why_it_matters") or ""),
                sources=tuple(
                    (str(s["title"]), str(s["url"]), str(s["source_name"])) for s in listed
                ),
            )
        )
    watch = tuple(
        (str(item["headline"]), str(item["url"])) for item in content.get("watchlist", [])
    )
    return View(str(content["local_date"]), tuple(stories), watch)


def to_markdown(view: View, label: str) -> str:
    """One briefing as the reader sees it in a comparison, under a neutral label."""
    lines = [f"# Briefing {escape(label)}: {escape(view.local_date)}", ""]
    if not view.stories and not view.watch:
        lines += ["Nothing to report today.", ""]
    for story in view.stories:
        lines += [f"## {escape(story.headline)}", "", escape(story.summary), ""]
        if story.why_it_matters:
            lines += [f"**Why it matters:** {escape(story.why_it_matters)}", ""]
        lines += ["Sources:", ""]
        lines += [f"- {link(title, url)} ({escape(name)})" for title, url, name in story.sources]
        lines.append("")
    if view.watch:
        lines += ["## Worth watching", ""]
        lines += [f"- {link(headline, url)}" for headline, url in view.watch]
        lines.append("")
    return "\n".join(lines)


def in_force() -> dict[str, Any]:
    """The policy version, and the hashes of the policy and of every prompt, right now."""
    digest = hashlib.sha256()
    for path in sorted(Path(policy.__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update("\n".join(path.read_text(encoding="utf-8").splitlines()).encode())
    prompts = {path.stem: load(path.stem).sha256 for path in sorted(PROMPTS.glob("*.md"))}
    return {
        "policy_version": policy.POLICY_VERSION,
        "policy_sha256": digest.hexdigest(),
        "prompts": prompts,
    }


def random_order() -> bool:
    """Whether the pipeline briefing is shown first. A fair coin from the system's source
    of randomness."""
    return secrets.randbelow(2) == 0


def compare(
    engine: Engine,
    *,
    local_date: date,
    show: Callable[[str], None],
    ask: Callable[[str], str],
    pipeline_first: Callable[[], bool] | None = None,
    again: bool = False,
    writing: Callable[[], AbstractContextManager[Any]] = nullcontext,
    clock: Callable[[], datetime] = utc_now,
) -> ComparisonJudgment:
    """Show the day's two briefings unlabelled, ask for a preference and store it.

    ``show`` is given each briefing as Markdown; ``ask`` puts the question and returns
    what was typed. ``pipeline_first`` decides the order; left out, it is a fair coin.
    ``writing`` is entered around the one write, so the caller can hold
    the job lock for that moment and not while the reader is reading.

    Nothing is stored unless a choice is made. The order is not returned to the reader
    through ``show`` or ``ask`` at any point.
    """
    with engine.connect() as connection:
        pipeline = latest_briefing(connection, local_date, BriefingVariant.PIPELINE)
        baseline = latest_briefing(connection, local_date, BriefingVariant.BASELINE)
        earlier = queries.comparison_judgments(connection, local_date)
    day = local_date.isoformat()
    if pipeline is None or pipeline.id is None:
        raise ComparisonError(f"there is no briefing for {day}; run `ai-briefing run` first")
    if baseline is None or baseline.id is None:
        raise ComparisonError(
            f"there is no baseline digest for {day}; run `ai-briefing baseline generate` first"
        )
    if earlier and not again:
        raise AlreadyCompared(
            f"a preference for {day} is already recorded "
            f"({len(earlier)} so far, the latest at {earlier[-1].recorded_at.isoformat()}). "
            "Use --again to record another; the earlier ones are kept."
        )
    first_is_pipeline = bool((pipeline_first or random_order)())
    ordered: tuple[Briefing, Briefing] = (
        (pipeline, baseline) if first_is_pipeline else (baseline, pipeline)
    )
    for label, briefing in zip(LABELS, ordered, strict=True):
        show(to_markdown(reader_view(briefing.document()), label))
    choice: ComparisonChoice | None = None
    for _ in range(MAX_ASKS):
        typed = ask(QUESTION).strip().lower()
        choice = ANSWERS.get(typed[:1]) if typed else None
        if choice is not None:
            break
    if choice is None:
        raise ComparisonError("no choice was made, so nothing was recorded")
    judgment = ComparisonJudgment(
        local_date=local_date,
        sequence=len(earlier) + 1,
        pipeline_briefing_id=pipeline.id,
        baseline_briefing_id=baseline.id,
        presentation_order=(
            PresentationOrder.PIPELINE_FIRST
            if first_is_pipeline
            else PresentationOrder.BASELINE_FIRST
        ),
        choice=choice,
        in_force=json.dumps(in_force(), sort_keys=True),
        recorded_at=clock(),
    )
    with writing(), engine.begin() as connection:
        return repositories.add(connection, judgment)
