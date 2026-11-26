"""Policy v0, the minimal rules for the first briefing (M1 issue 1.6).

The model suggests a class. This code decides it: the final class is the lower of the
suggestion and a ceiling worked out from facts about the evidence. However persuasive a
source is, it cannot talk its way past the ceiling.

Only two of the ceilings in RFC §6.2 are here: no verified evidence, and a story known
only from metadata. The vendor, corroboration and community rules arrive with issue 1.10,
as a new policy version.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ai_briefing.domain.enums import EditorialClass, SourceRole
from ai_briefing.domain.records import lower_class

POLICY_VERSION = "v0.1"

NO_VERIFIED_EVIDENCE = "no evidence item passed the integrity check"
METADATA_ONLY = "metadata-only story: no source text was available to assess"

# Sources that can corroborate independently (ADR-004).
INDEPENDENT_ROLES = frozenset({SourceRole.PRIMARY, SourceRole.INDEPENDENT})


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
    reasons: list[str] = []
    if verified_supporting_evidence < 1:
        reasons.append(NO_VERIFIED_EVIDENCE)
    if not has_source_text:
        reasons.append(METADATA_ONLY)
    ceiling = EditorialClass.WATCH if reasons else EditorialClass.MAJOR
    final = lower_class(suggested, ceiling)
    independent = len({source for source, role in source_roles if role in INDEPENDENT_ROLES})
    return Verdict(
        final_class=final,
        ceiling=ceiling,
        ceiling_reasons=tuple(reasons),
        independent_source_count=independent,
        # A low story is recorded and never shown.
        eligible=final is not EditorialClass.LOW,
    )
