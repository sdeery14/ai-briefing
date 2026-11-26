"""Citation integrity: did the source really say these words? (RFC §4 step 8, ADR-004)

This checks three things about a citation, exactly and in code:

- the observation it cites was one the model was given;
- the quoted words occur in that observation's stored text, after whitespace and Unicode
  normalisation and nothing else;
- the observation was made before the assessment.

Passing shows that the source contains those words. It does not show that the claim is
true, or that the words support it. Nothing here, and nothing built on it, may present a
verified quotation as a verified claim.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime

from ai_briefing.domain.records import DocumentObservation

# A "quote" this short could be found in almost any text and proves nothing.
MIN_QUOTE_CHARS = 12


def normalise(text: str) -> str:
    """Unicode compatibility form, with every run of whitespace as one space."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def shown_text(observation: DocumentObservation) -> str | None:
    """The text of an observation that a quotation can be checked against."""
    return observation.body_text or observation.summary


def quote_is_in(quote: str, observation: DocumentObservation) -> bool:
    text = shown_text(observation)
    wanted = normalise(quote)
    if text is None or len(wanted) < MIN_QUOTE_CHARS:
        return False
    return wanted in normalise(text)


def citation_holds(
    quote: str,
    observation_id: int,
    shown: dict[int, DocumentObservation],
    as_of: datetime,
) -> bool:
    """True when a citation passes all three checks."""
    observation = shown.get(observation_id)
    if observation is None:
        return False
    if observation.retrieved_at > as_of:
        return False
    return quote_is_in(quote, observation)
