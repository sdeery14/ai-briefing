"""Policy v0: the editorial rules, as tables in code (RFC §6.2, §6.3, §6.5; ADR-004).

The model suggests a class. This code decides it: the final class is the lower of the
suggestion and a ceiling worked out from facts about the evidence. However persuasive a
source is, it cannot talk its way past the ceiling.

Three kinds of rule are here, and nothing else decides what a reader sees:

- **Ceilings** (:data:`CEILINGS`): facts that cap a story's class.
- **Freshness and repetition** (:data:`FRESHNESS`, :func:`may_appear_again`): how long an
  item is news, and when a story already briefed may come back.
- **Near-duplicates** (:func:`similar_titles`): two items in one briefing that are the
  same headline twice.

Every rule is a pure function of facts the caller supplies. Nothing here reads a database
or calls a model, so re-deciding under a new version of these rules costs nothing.

The vendor and corroboration rules of RFC §6.2 are not here. They arrive with M3.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta

from ai_briefing.domain.enums import EditorialClass, SourceRole
from ai_briefing.domain.records import lower_class

POLICY_VERSION = "v0.2"
"""Changes whenever a rule in this file changes. Each decision records the version that
made it, and a story decided under an older version is decided again (RFC §6.3)."""

# --- Ceilings (RFC §6.2) -----------------------------------------------------------------------

NO_VERIFIED_EVIDENCE = "no evidence item passed the integrity check"
METADATA_ONLY = "metadata-only story: no source text was available to assess"
COMMUNITY_ONLY = "only community or aggregator sources"

# Sources that can corroborate independently (ADR-004).
INDEPENDENT_ROLES = frozenset({SourceRole.PRIMARY, SourceRole.INDEPENDENT})
# Sources that pass things on or discuss them, and are not themselves a source for a claim.
COMMUNITY_ROLES = frozenset({SourceRole.COMMUNITY, SourceRole.AGGREGATOR})


@dataclass(frozen=True)
class Facts:
    """What is known about a story's evidence, from stored records. No model opinion."""

    verified_supporting_evidence: int
    has_source_text: bool
    source_roles: tuple[tuple[str, SourceRole], ...]
    """One ``(source id, role)`` pair per document in the story."""


@dataclass(frozen=True)
class Ceiling:
    reason: str
    ceiling: EditorialClass
    applies: Callable[[Facts], bool]


CEILINGS: tuple[Ceiling, ...] = (
    Ceiling(
        NO_VERIFIED_EVIDENCE,
        EditorialClass.WATCH,
        lambda facts: facts.verified_supporting_evidence < 1,
    ),
    Ceiling(
        METADATA_ONLY,
        EditorialClass.WATCH,
        lambda facts: not facts.has_source_text,
    ),
    Ceiling(
        COMMUNITY_ONLY,
        EditorialClass.WATCH,
        lambda facts: (
            bool(facts.source_roles)
            and all(role in COMMUNITY_ROLES for _, role in facts.source_roles)
        ),
    ),
)
"""The table. Every ceiling that applies is recorded as a reason; the lowest one holds."""


@dataclass(frozen=True)
class Verdict:
    final_class: EditorialClass
    ceiling: EditorialClass
    ceiling_reasons: tuple[str, ...]
    independent_source_count: int
    eligible: bool


def decide(
    suggested: EditorialClass,
    *,
    verified_supporting_evidence: int,
    has_source_text: bool,
    source_roles: Iterable[tuple[str, SourceRole]],
) -> Verdict:
    """The final class for an assessment.

    ``source_roles`` is one ``(source id, role)`` pair per document in the story. Several
    documents from one source count once.
    """
    facts = Facts(verified_supporting_evidence, has_source_text, tuple(source_roles))
    applying = [rule for rule in CEILINGS if rule.applies(facts)]
    ceiling = EditorialClass.MAJOR
    for rule in applying:
        ceiling = lower_class(ceiling, rule.ceiling)
    final = lower_class(suggested, ceiling)
    independent = len({source for source, role in facts.source_roles if role in INDEPENDENT_ROLES})
    return Verdict(
        final_class=final,
        ceiling=ceiling,
        ceiling_reasons=tuple(rule.reason for rule in applying),
        independent_source_count=independent,
        # A low story is recorded and never shown.
        eligible=final is not EditorialClass.LOW,
    )


# --- Freshness and repetition (RFC §6.3) -------------------------------------------------------

FRESHNESS = timedelta(hours=72)
"""An item is news for this long after it was published, or after it was first seen when
its source gives no published time. Older items are kept for recognition only."""

CLASS_CHANGED = "its class changed since it was last briefed"
NEW_EVIDENCE = "new primary or independent evidence arrived since it was last briefed"


def may_appear_again(
    *,
    briefed_class: EditorialClass,
    current_class: EditorialClass,
    new_independent_evidence: bool,
) -> str | None:
    """Why a story already in an earlier day's briefing may be in another, or ``None``.

    A story is briefed once. It comes back only with a material update: its final class is
    different now, or a verified quotation from a primary or independent source has
    arrived since. A new assessment that says the same thing is not an update.
    """
    if current_class is not briefed_class:
        return CLASS_CHANGED
    if new_independent_evidence:
        return NEW_EVIDENCE
    return None


# --- Near-duplicates within one briefing (RFC §6.3, §6.5) --------------------------------------

TITLE_SIMILARITY = 0.8
"""Two titles sharing at least this fraction of their distinct words are one headline."""
MIN_TITLE_WORDS = 4
"""Shorter titles are compared only for being the same: a few shared words prove little."""

_WORD = re.compile(r"[^\W_]+")


def title_words(title: str) -> frozenset[str]:
    """The distinct words of a title, ignoring case, punctuation and compatibility forms."""
    return frozenset(_WORD.findall(unicodedata.normalize("NFKC", title).casefold()))


def similar_titles(first: str, second: str) -> bool:
    """Whether two titles are near-duplicates.

    The measure is the share of distinct words the two have in common, out of all the
    distinct words in either (Jaccard similarity), against :data:`TITLE_SIMILARITY`.
    """
    a, b = title_words(first), title_words(second)
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < MIN_TITLE_WORDS:
        return False
    return len(a & b) / len(a | b) >= TITLE_SIMILARITY
