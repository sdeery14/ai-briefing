"""The shapes the model is asked to answer in (RFC §6.1, ADR-004).

Model output is validated against these before anything uses it. The API does not enforce
numeric ranges or string lengths, so every score is one of five listed values and lengths
are checked in code afterwards (ADR-009). No field here is a URL: the model never supplies
one.

Field order matters. The assessment puts claims and their evidence first, so the model
states what the source says before it scores anything.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ScoreValue = Literal[0, 1, 2, 3, 4]
ClassValue = Literal["major", "practical", "watch", "low"]
SupportValue = Literal["supports", "contradicts", "context"]


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScreeningResult(_Output):
    id: int
    relevance: ScoreValue
    reason: str


class ScreeningOutput(_Output):
    results: list[ScreeningResult]


class Citation(_Output):
    observation_id: int
    quote: str
    support: SupportValue


class Claim(_Output):
    text: str
    evidence: list[Citation]


class Scores(_Output):
    impact: ScoreValue
    evidence: ScoreValue
    novelty: ScoreValue
    professional_relevance: ScoreValue
    maturity: ScoreValue


class AssessmentOutput(_Output):
    claims: list[Claim]
    uncertainty: str
    scores: Scores
    suggested_class: ClassValue
    headline: str
    summary: str
    why_it_matters: str


class ConceptOutput(_Output):
    """Whether one of the day's stories needs a concept explained, and the note if so
    (RFC §6.4). The fields other than ``qualifies`` are empty when nothing qualifies."""

    qualifies: bool
    concept: str
    title: str
    body: str
    related_item_id: str


class BaselineStory(_Output):
    document_ids: list[int]
    headline: str
    summary: str
    why_it_matters: str


class BaselineWatch(_Output):
    document_id: int
    headline: str


class BaselineOutput(_Output):
    """The single-prompt digest (RFC §1.1): the day's stories and a watch list, each tied
    to the items it came from by id. Code attaches every link."""

    stories: list[BaselineStory]
    watch: list[BaselineWatch]
