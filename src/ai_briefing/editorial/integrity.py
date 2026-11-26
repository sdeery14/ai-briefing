"""Citation integrity: did the source really say these words? (RFC §4 step 8, ADR-004)

This checks three things about a citation, exactly and in code:

- the observation it cites was one the model was given;
- the quoted words occur in the text of that observation that was sent to the model,
  after whitespace and Unicode normalisation and nothing else;
- the observation was made before the assessment.

Passing shows that the source contains those words. It does not show that the claim is
true, or that the words support it. Nothing here, and nothing built on it, may present a
verified quotation as a verified claim.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime

from ai_briefing.domain.records import DocumentObservation

# A "quote" this short could be found in almost any text and proves nothing.
MIN_QUOTE_CHARS = 12


def normalise(text: str) -> str:
    """Unicode compatibility form, with every run of whitespace as one space."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def quote_is_in(quote: str, text: str | None) -> bool:
    """True when the quoted words occur in ``text``, after normalisation."""
    wanted = normalise(quote)
    if text is None or len(wanted) < MIN_QUOTE_CHARS:
        return False
    return wanted in normalise(text)


@dataclass(frozen=True)
class Shown:
    """One observation as the model was given it.

    ``text`` is exactly what was sent, which can be less than what is stored: a long
    article is cut before it is sent. A quotation is checked against this, never against
    the stored text, so words the model did not see cannot count as evidence.
    """

    observation: DocumentObservation
    text: str | None


def citation_holds(
    quote: str, observation_id: int, shown: dict[int, Shown], as_of: datetime
) -> bool:
    """True when a citation passes all three checks."""
    given = shown.get(observation_id)
    if given is None:
        return False
    if given.observation.retrieved_at > as_of:
        return False
    return quote_is_in(quote, given.text)
