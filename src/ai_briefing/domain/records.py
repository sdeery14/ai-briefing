"""Typed records for the entities in RFC §5 that M1 uses.

These are values, not database rows: every record is immutable and validates itself.
Immutable means all the way down: a field never holds a list or a dictionary that a caller
could change behind the record's back. Sequences are tuples, a mapping is read-only, and a
briefing's content is held as JSON text.
``id`` is ``None`` until storage assigns one. Timestamps are timezone-aware and are held
in UTC. Nothing here reads a file, a database or the network.

The field lists follow RFC §5, which calls them representative. Operational state that
only storage needs (feed cache validators on a source, failure counts) is left to the
storage module.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from ai_briefing.domain.enums import (
    AssessmentTier,
    AutomatedAccess,
    BodySource,
    BriefingItemKind,
    BriefingStatus,
    BriefingVariant,
    EditorialClass,
    FetchStatus,
    IntegrityStatus,
    JobStatus,
    LLMCallStatus,
    MembershipAction,
    ModelSubmission,
    ModelTask,
    ScreeningOutcome,
    SourceKind,
    SourceMode,
    SourceRole,
    StoryState,
    SupportLabel,
    SupportType,
)

MAX_BODY_RETENTION_DAYS = 90  # ADR-010
MIN_SCORE = 0
MAX_SCORE = 4


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""A timezone-aware time, normalised to UTC. A naive time is rejected."""

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[^\s]+$")]
WebUrl = Annotated[str, StringConstraints(pattern=r"^https?://[^\s]+$")]
Score = Annotated[int, Field(ge=MIN_SCORE, le=MAX_SCORE)]
RecordId = Annotated[int, Field(ge=1)]


def _read_only(value: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(value))


Counts = Annotated[
    Mapping[str, Annotated[int, Field(ge=0)]],
    AfterValidator(_read_only),
    PlainSerializer(dict, return_type=dict[str, int]),
]
"""Named counts, held read-only: assigning to a key raises ``TypeError``."""

_JSON_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


class Record(BaseModel):
    """Base for every record: immutable, and unknown fields are an error.

    Defaults are validated like supplied values, so a default goes through the same
    constraints and the same read-only wrapping.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


# --- Sources -------------------------------------------------------------------------------


class RateLimit(Record):
    min_seconds_between_requests: float = Field(gt=0)
    max_connections: int = Field(ge=1)


class StoragePermissions(Record):
    """What of a source may be kept in the database."""

    metadata: bool
    feed_summary: bool
    body: bool


class BodyPolicy(Record):
    """Where a full-text source's article text comes from, and the only hosts a page may
    be fetched from. A link to any other host stays metadata-only (ADR-012).
    """

    source: BodySource
    hosts: tuple[NonEmptyStr, ...] = Field(min_length=1)


class RetentionDays(Record):
    """``None`` means kept indefinitely; 0 means never kept."""

    metadata: int | None = Field(ge=0)
    feed_summary: int | None = Field(ge=0)
    body: int | None = Field(default=None, ge=1, le=MAX_BODY_RETENTION_DAYS)


class TermsRecord(Record):
    """The usage-terms record a source needs before it can be enabled (ADR-010)."""

    reviewed_on: date
    approved_by_owner_on: date
    urls: tuple[HttpsUrl, ...] = Field(min_length=1)
    automated_access: AutomatedAccess
    restrictions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    uncertainties: tuple[NonEmptyStr, ...] = Field(min_length=1)


class Source(Record):
    """One entry in the source catalogue, with what may be stored and sent to the model.

    The shape is that of an entry in ``config/sources.yaml``. Access, storage and model
    submission are separate permissions, and the checks below keep them consistent with
    the source's mode.
    """

    id: NonEmptyStr
    name: NonEmptyStr
    kind: SourceKind
    url: HttpsUrl
    role: SourceRole
    enabled: bool
    mode: SourceMode
    polling_interval_minutes: int = Field(ge=1)
    rate_limit: RateLimit
    store: StoragePermissions
    body: BodyPolicy | None = None
    stored_fields: tuple[NonEmptyStr, ...] | None = None
    model_submission: ModelSubmission
    retention_days: RetentionDays
    excerpts_allowed: bool
    excerpt_limit_chars: int | None = Field(default=None, ge=1)
    attribution: NonEmptyStr
    terms: TermsRecord

    @model_validator(mode="after")
    def _permissions_agree_with_the_mode(self) -> Self:
        mode = self.mode
        problems: list[str] = []
        if self.enabled != (mode is not SourceMode.DISABLED):
            problems.append("enabled must be true exactly when the mode is not disabled")
        if self.terms.automated_access is AutomatedAccess.UNCERTAIN and self.enabled:
            problems.append("a source with uncertain automated access cannot be enabled")
        if self.terms.approved_by_owner_on < self.terms.reviewed_on:
            problems.append("terms cannot be approved before they were reviewed")

        if mode is SourceMode.DISABLED:
            if self.store.metadata or self.store.feed_summary or self.store.body:
                problems.append("a disabled source stores nothing")
            if self.model_submission is not ModelSubmission.NONE:
                problems.append("a disabled source submits nothing to the model")
        elif not self.store.metadata:
            problems.append("an enabled source stores its metadata")

        full_text = mode is SourceMode.FULL_TEXT
        if self.store.body != full_text:
            problems.append("article text is stored exactly when the mode is full_text")
        if full_text:
            if self.body is None:
                problems.append("a full_text source says where its text comes from")
            if self.retention_days.body is None:
                problems.append("a full_text source states its body retention")
            if not self.excerpts_allowed or self.excerpt_limit_chars is None:
                problems.append("a full_text source states its quotation limit")
        else:
            if self.body is not None:
                problems.append("only a full_text source has a body policy")
            if self.retention_days.body is not None:
                problems.append("only a full_text source has a body retention")
            if self.model_submission is ModelSubmission.FULL_TEXT:
                problems.append("only a full_text source submits article text")

        if self.store.feed_summary and mode is not SourceMode.FEED_SUMMARY:
            problems.append("a feed summary is stored only in feed_summary mode")
        if self.model_submission is ModelSubmission.TITLE_AND_SUMMARY and (
            mode is not SourceMode.FEED_SUMMARY
        ):
            problems.append("a summary is submitted only in feed_summary mode")
        if mode is SourceMode.METADATA_ONLY and self.excerpts_allowed:
            problems.append("a metadata_only source has nothing to quote")
        if not self.excerpts_allowed and self.excerpt_limit_chars is not None:
            problems.append("a quotation limit needs excerpts to be allowed")

        if problems:
            raise ValueError(f"source {self.id!r}: " + "; ".join(problems))
        return self


# --- Documents -----------------------------------------------------------------------------


class SourceDocument(Record):
    """One item from a source. Its identity is stable; its published time is never guessed."""

    id: RecordId | None = None
    source_id: NonEmptyStr
    external_id: NonEmptyStr
    canonical_url: WebUrl
    title: NonEmptyStr
    published_at: UtcDatetime | None = None
    first_seen_at: UtcDatetime
    source_role: SourceRole

    @property
    def fresh_at(self) -> datetime:
        """The time freshness is counted from: when the source says it was published, or,
        when the source gives no time, when it was first seen (RFC §6.3)."""
        return self.published_at or self.first_seen_at


class DocumentObservation(Record):
    """What was seen when a document was fetched. Append-only; the hash survives a purge."""

    id: RecordId | None = None
    document_id: RecordId
    retrieved_at: UtcDatetime
    fetch_status: FetchStatus
    etag: str | None = None
    last_modified: str | None = None
    summary: str | None = None
    body_text: str | None = None
    body_purged_at: UtcDatetime | None = None
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def _a_purged_body_is_gone(self) -> Self:
        if self.body_purged_at is not None and self.body_text is not None:
            raise ValueError("an observation whose body was purged holds no body text")
        return self


class ScreeningDecision(Record):
    """Whether an item is worth assessing, and why. Every screened item has one, so a
    missed item can be found afterwards (RFC §4 step 4).
    """

    id: RecordId | None = None
    document_id: RecordId
    outcome: ScreeningOutcome
    relevance: Score
    reason: NonEmptyStr
    model_call_id: RecordId
    decided_at: UtcDatetime


# --- Stories -------------------------------------------------------------------------------


class Story(Record):
    """Coverage of one development. Never deleted; a merge leaves a redirect."""

    id: RecordId | None = None
    title: NonEmptyStr
    state: StoryState = StoryState.OPEN
    first_seen_at: UtcDatetime
    last_activity_at: UtcDatetime
    merged_into_id: RecordId | None = None
    last_briefed_decision_id: RecordId | None = None

    @model_validator(mode="after")
    def _times_and_merges_make_sense(self) -> Self:
        if self.last_activity_at < self.first_seen_at:
            raise ValueError("a story's last activity cannot precede its first sighting")
        if self.merged_into_id is not None and self.merged_into_id == self.id:
            raise ValueError("a story cannot be merged into itself")
        return self


class StoryMembershipEvent(Record):
    """One change to which documents a story holds. Append-only.

    Exactly one of ``decided_by_rule`` and ``decided_by_model_call_id`` is set, so every
    grouping decision names what made it.
    """

    id: RecordId | None = None
    story_id: RecordId
    document_id: RecordId
    action: MembershipAction
    reason: NonEmptyStr
    decided_by_rule: NonEmptyStr | None = None
    decided_by_model_call_id: RecordId | None = None
    occurred_at: UtcDatetime

    @model_validator(mode="after")
    def _one_decider(self) -> Self:
        if (self.decided_by_rule is None) == (self.decided_by_model_call_id is None):
            raise ValueError("a membership event is decided by one rule or one model call")
        return self


# --- Assessment, evidence, decision --------------------------------------------------------


class DimensionScores(Record):
    """The five dimensions, each 0 to 4. They are never combined into one number (ADR-004)."""

    impact: Score
    evidence: Score
    novelty: Score
    professional_relevance: Score
    maturity: Score


class EditorialAssessment(Record):
    """What the model said about a story from one exact set of inputs. Immutable.

    ``suggested_class`` is the model's suggestion only. The final class is set by the
    policy and recorded in an :class:`EditorialDecision`.
    """

    id: RecordId | None = None
    story_id: RecordId
    as_of: UtcDatetime
    input_hash: Sha256Hex
    prompt_hash: Sha256Hex
    model_id: NonEmptyStr
    rubric_version: NonEmptyStr
    tier: AssessmentTier
    scores: DimensionScores
    suggested_class: EditorialClass
    uncertainty: NonEmptyStr
    draft_text: str
    model_call_id: RecordId


class AssessmentInput(Record):
    """One observation that was shown to the model for an assessment."""

    assessment_id: RecordId
    observation_id: RecordId


class EvidenceItem(Record):
    """A claim, the words quoted for it, and two separate judgements about that quotation.

    ``integrity_status`` says whether code found the quoted words in the stored text.
    ``support_label`` says whether a reviewer judged that the words support the claim.
    Neither implies the other, and neither shows the claim is true.
    """

    id: RecordId | None = None
    assessment_id: RecordId
    claim_text: NonEmptyStr
    observation_id: RecordId
    quote: NonEmptyStr
    support_type: SupportType
    integrity_status: IntegrityStatus
    support_label: SupportLabel = SupportLabel.UNREVIEWED

    @property
    def counts_as_support(self) -> bool:
        """True only for a supporting quotation that passed the integrity check."""
        return (
            self.support_type is SupportType.SUPPORTS
            and self.integrity_status is IntegrityStatus.VERIFIED
        )


def lower_class(first: EditorialClass, second: EditorialClass) -> EditorialClass:
    """The less significant of two classes. The final class is the lower of the model's
    suggestion and the policy's ceiling (RFC §6.2).
    """
    return first if first.rank <= second.rank else second


class EditorialDecision(Record):
    """The policy's decision on an assessment. Append-only; made again when the policy
    version changes, with no model call.
    """

    id: RecordId | None = None
    assessment_id: RecordId
    policy_version: NonEmptyStr
    final_class: EditorialClass
    ceiling: EditorialClass
    ceiling_reasons: tuple[NonEmptyStr, ...] = ()
    independent_source_count: int = Field(ge=0)
    eligible: bool

    @model_validator(mode="after")
    def _the_final_class_respects_the_ceiling(self) -> Self:
        if self.final_class.rank > self.ceiling.rank:
            raise ValueError("the final class cannot exceed the ceiling")
        if self.ceiling is not EditorialClass.MAJOR and not self.ceiling_reasons:
            raise ValueError("a ceiling below major states its reasons")
        return self


# --- Briefings -----------------------------------------------------------------------------


class Briefing(Record):
    """One immutable version of a day's briefing. Unique on date, variant and version.

    ``content`` is the briefing document as JSON text, not a dictionary, so the version
    cannot be altered after ``content_hash`` was taken. :meth:`document` parses a fresh
    copy each time; changing that copy changes nothing here.
    """

    id: RecordId | None = None
    local_date: date
    timezone: NonEmptyStr
    variant: BriefingVariant
    version: int = Field(ge=1)
    status: BriefingStatus
    content: NonEmptyStr
    content_hash: Sha256Hex
    configuration_hash: Sha256Hex
    profile: NonEmptyStr = "default"

    @field_validator("content")
    @classmethod
    def _content_is_a_json_object(cls, value: str) -> str:
        _JSON_OBJECT.validate_json(value)
        return value

    def document(self) -> dict[str, JsonValue]:
        """The briefing document, parsed afresh. The caller owns the returned copy."""
        return _JSON_OBJECT.validate_json(self.content)


class BriefingItem(Record):
    """One entry in a briefing. A story or watch item is traceable to its decision."""

    id: RecordId | None = None
    briefing_id: RecordId
    position: int = Field(ge=1)
    kind: BriefingItemKind
    story_id: RecordId | None = None
    decision_id: RecordId | None = None
    text: NonEmptyStr
    inclusion_reason: NonEmptyStr

    @model_validator(mode="after")
    def _a_story_item_names_its_decision(self) -> Self:
        if self.kind is not BriefingItemKind.CONCEPT_NOTE and (
            self.story_id is None or self.decision_id is None
        ):
            raise ValueError("a story or watch item names its story and its decision")
        return self


# --- Model calls and jobs ------------------------------------------------------------------


class LLMCall(Record):
    """One call to a model, or one attempt the budget check refused. Written for every
    call, whatever its outcome (ADR-009).
    """

    id: RecordId | None = None
    job_run_id: RecordId
    purpose: ModelTask
    prompt_id: NonEmptyStr
    prompt_hash: Sha256Hex
    provider: NonEmptyStr
    model_id: NonEmptyStr
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=0)
    price_table_version: NonEmptyStr
    latency_ms: int | None = Field(default=None, ge=0)
    status: LLMCallStatus
    error_class: str | None = None
    retries: int = Field(default=0, ge=0)
    request_ref: str | None = None
    response_ref: str | None = None

    @model_validator(mode="after")
    def _a_call_that_was_never_sent_used_nothing(self) -> Self:
        if self.status is LLMCallStatus.BUDGET_REFUSED and (
            self.tokens_in or self.tokens_out or self.estimated_cost_usd
        ):
            raise ValueError("a call refused by the budget check used no tokens and cost nothing")
        return self


class JobRun(Record):
    """One run of a job. Running a completed idempotency key again adds nothing."""

    id: RecordId | None = None
    job: NonEmptyStr
    idempotency_key: NonEmptyStr
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None
    status: JobStatus
    counts: Counts = Field(default_factory=dict)
    error: str | None = None
    application_version: NonEmptyStr
    configuration_hash: Sha256Hex

    @model_validator(mode="after")
    def _status_and_times_agree(self) -> Self:
        if (self.status is JobStatus.RUNNING) != (self.ended_at is None):
            raise ValueError("a job has an end time exactly when it is no longer running")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("a job cannot end before it starts")
        return self
