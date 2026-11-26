"""Enumerations shared by every module.

The values are part of stored data, configuration files and the briefing contract, so a
value is never renamed or reused. Where an enumeration mirrors a configuration file or the
JSON Schema, a test keeps the two in step.
"""

from __future__ import annotations

from enum import StrEnum

# --- Sources (config/sources.yaml, ADR-003, ADR-010, ADR-012) -----------------------------


class SourceKind(StrEnum):
    """Which adapter reads the source."""

    RSS = "rss"
    ATOM = "atom"
    HN_API = "hn_api"


class SourceRole(StrEnum):
    """What a source is to a claim it carries (ADR-004)."""

    PRIMARY = "primary"
    VENDOR = "vendor"
    INDEPENDENT = "independent"
    COMMUNITY = "community"
    AGGREGATOR = "aggregator"


class SourceMode(StrEnum):
    """How much of a source may be kept."""

    FULL_TEXT = "full_text"
    FEED_SUMMARY = "feed_summary"
    METADATA_ONLY = "metadata_only"
    DISABLED = "disabled"


class ModelSubmission(StrEnum):
    """What of a source may be sent to the model provider. Separate from storage."""

    NONE = "none"
    METADATA = "metadata"
    TITLE_AND_SUMMARY = "title_and_summary"
    FULL_TEXT = "full_text"


class BodySource(StrEnum):
    """Where a full-text source's article text comes from."""

    FEED = "feed"
    PAGE = "page"


class AutomatedAccess(StrEnum):
    """How firmly a source's terms allow reading it automatically."""

    EXPLICIT = "explicit"
    INTERPRETATION = "interpretation"
    UNCERTAIN = "uncertain"


# --- Documents and stories (RFC §5) --------------------------------------------------------


class FetchStatus(StrEnum):
    OK = "ok"
    NOT_MODIFIED = "not_modified"
    FAILED = "failed"


class ScreeningOutcome(StrEnum):
    """What screening concluded about an item."""

    PASSED = "passed"
    REJECTED = "rejected"


class StoryState(StrEnum):
    OPEN = "open"
    DORMANT = "dormant"
    CLOSED = "closed"


class MembershipAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    MERGE_IN = "merge_in"


# --- Editorial (RFC §6, ADR-004) -----------------------------------------------------------


class EditorialClass(StrEnum):
    """The four classes, from most to least significant."""

    MAJOR = "major"
    PRACTICAL = "practical"
    WATCH = "watch"
    LOW = "low"

    @property
    def rank(self) -> int:
        """Higher is more significant. ``major`` is 3 and ``low`` is 0."""
        return _CLASS_RANK[self]


_CLASS_RANK = {
    EditorialClass.LOW: 0,
    EditorialClass.WATCH: 1,
    EditorialClass.PRACTICAL: 2,
    EditorialClass.MAJOR: 3,
}


class AssessmentTier(StrEnum):
    STANDARD = "standard"
    ESCALATED = "escalated"


class SupportType(StrEnum):
    """What the model says a quotation does for a claim."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class IntegrityStatus(StrEnum):
    """Set by code: whether the cited words were found in the stored text."""

    VERIFIED = "verified"
    FAILED = "failed"


class SupportLabel(StrEnum):
    """Whether a quotation really supports its claim. Only a person, or later a calibrated
    judge, sets this (ADR-004). The labels a reviewer can give arrive with M4.
    """

    UNREVIEWED = "unreviewed"


class Confidence(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


# --- Briefings (RFC §8.2, ADR-006) ---------------------------------------------------------


class BriefingVariant(StrEnum):
    PIPELINE = "pipeline"
    BASELINE = "baseline"


class BriefingStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    EMPTY = "empty"


class BriefingItemKind(StrEnum):
    STORY = "story"
    WATCH = "watch"
    CONCEPT_NOTE = "concept_note"


# --- Model calls and jobs (config/models.yaml, RFC §7, ADR-009) ----------------------------


class ModelTask(StrEnum):
    """The purposes a model call can have. Each is configured in config/models.yaml."""

    SCREENING = "screening"
    ASSESSMENT = "assessment"
    ESCALATED_ASSESSMENT = "escalated_assessment"
    BASELINE_DIGEST = "baseline_digest"
    CONCEPT_NOTE = "concept_note"


class ModelTier(StrEnum):
    INEXPENSIVE = "inexpensive"
    CAPABLE = "capable"


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LLMCallStatus(StrEnum):
    """Every call is recorded, including the ones that never reached the provider."""

    SUCCEEDED = "succeeded"
    REFUSED = "refused"  # the model declined; a normal outcome
    BUDGET_REFUSED = "budget_refused"  # the budget check stopped the call before it was sent
    FAILED = "failed"


class JobStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
