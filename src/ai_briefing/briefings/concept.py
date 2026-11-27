"""The concept note: optional background written by the model, tied to one of the day's
stories (RFC §6.4, ADR-005).

The model proposes; code decides. A note is used only when the model says a concept
qualifies, the concept has not been explained in the last 30 days, and the story it
names is one of the day's selected stories. Otherwise the day has no note, which is the
usual case.

The model is shown the selected stories' headlines and summaries: the briefing's own
text. It is not shown source text here, so the note quotes nothing and is evidence for
nothing. It never supplies a link; any address in what it writes is removed before a
reader sees it.

At most one answered call is made for a day. Composing the day again reuses the note
already stored. If an answer is on record with no note stored yet, that answer is judged
again against the day's stories, and the model is not asked a second time.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import BriefingVariant, LLMCallStatus, ModelTask
from ai_briefing.editorial.contracts import ConceptOutput
from ai_briefing.llm.client import ModelClient
from ai_briefing.prompts import load
from ai_briefing.storage import queries

PROMPT_ID = "concept_note"
REPEAT_DAYS = 30
"""A concept is not explained again within this many days (ADR-005)."""
MAX_OUTPUT_TOKENS = 800
KEY_CHARS = 80
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class ConceptNote:
    """A note that may be attached to a briefing, if its story is in it."""

    key: str
    title: str
    body: str
    story_id: int


def concept_key(name: str) -> str:
    """A concept's name in one normal form, so the same concept is recognised again:
    lower case, compatibility forms folded, words joined by hyphens."""
    words = _WORD.findall(unicodedata.normalize("NFKC", name).casefold())
    return "-".join(words)[:KEY_CHARS].strip("-")


def packet(stories: Sequence[Mapping[str, Any]], recent: Collection[str]) -> str:
    """What the model is sent: the selected stories as the briefing words them, and the
    concepts explained recently."""
    shown = [
        {"item_id": s["item_id"], "headline": s["headline"], "summary": s["summary"]}
        for s in stories
    ]
    return json.dumps(
        {"stories": shown, "recently_explained": sorted(recent)},
        ensure_ascii=False,
        sort_keys=True,
    )


def accept(
    output: ConceptOutput, story_of_item: Mapping[str, int], recent: Collection[str]
) -> ConceptNote | None:
    """The note the model proposed, if code accepts it; otherwise ``None``."""
    if not output.qualifies:
        return None
    key = concept_key(output.concept)
    title, body = " ".join(output.title.split()), " ".join(output.body.split())
    if not key or not title or not body:
        return None
    if key in recent:
        return None  # explained within the last 30 days
    story_id = story_of_item.get(output.related_item_id)
    if story_id is None:
        return None  # tied to an item that was not given
    return ConceptNote(key=key, title=title, body=body, story_id=story_id)


def propose(
    client: ModelClient,
    job_run_id: int,
    stories: Sequence[Mapping[str, Any]],
    recent: Collection[str],
) -> ConceptNote | None:
    """Ask the model once whether a story needs a concept explained. The call goes through
    the budget check and is recorded like any other, whatever comes of it."""
    if not stories:
        return None
    prompt = load(PROMPT_ID)
    result = client.call(
        task=ModelTask.CONCEPT_NOTE,
        job_run_id=job_run_id,
        prompt_id=prompt.id,
        system=prompt.text,
        user=packet(stories, recent),
        output_type=ConceptOutput,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    if result.status is not LLMCallStatus.SUCCEEDED or result.output is None:
        return None
    return accept(result.output, _story_of_item(stories), recent)


def recover(
    answer: str | None, stories: Sequence[Mapping[str, Any]], recent: Collection[str]
) -> ConceptNote | None:
    """The note from an answer already paid for and stored, judged as a fresh one would be.

    A run can stop after the model answered and before the briefing was stored. The answer
    is on record with its call, so the next composition uses it and does not ask again.
    """
    if answer is None:
        return None
    try:
        output = ConceptOutput.model_validate_json(answer)
    except ValueError:
        return None
    return accept(output, _story_of_item(stories), recent)


def _story_of_item(stories: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {str(s["item_id"]): int(str(s["story_id"]).removeprefix("s-")) for s in stories}


def standing(connection: Connection, local_date: date) -> ConceptNote | None:
    """The note in the day's latest stored briefing, to be used again as it is."""
    stored = queries.latest_concept_note(connection, local_date, BriefingVariant.PIPELINE)
    if stored is None:
        return None
    content, key = stored
    note = content.get("concept_note")
    if not isinstance(note, dict):
        return None
    for story in content.get("stories", []):
        if story.get("item_id") == note.get("related_item_id"):
            return ConceptNote(
                key=key,
                title=str(note["title"]),
                body=str(note["body"]),
                story_id=int(str(story["story_id"]).removeprefix("s-")),
            )
    return None
