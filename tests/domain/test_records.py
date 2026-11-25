"""The domain records hold their invariants (RFC §5, ADR-004, ADR-010, ADR-012)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ai_briefing.domain.enums import (
    AssessmentTier,
    BriefingItemKind,
    BriefingStatus,
    BriefingVariant,
    EditorialClass,
    FetchStatus,
    IntegrityStatus,
    JobStatus,
    LLMCallStatus,
    MembershipAction,
    ModelTask,
    SourceRole,
    StoryState,
    SupportLabel,
    SupportType,
)
from ai_briefing.domain.records import (
    AssessmentInput,
    Briefing,
    BriefingItem,
    DimensionScores,
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
    EvidenceItem,
    JobRun,
    LLMCall,
    Source,
    SourceDocument,
    Story,
    StoryMembershipEvent,
    lower_class,
)

NOW = datetime(2026, 11, 19, 11, 15, tzinfo=UTC)
HASH = "a" * 64
CONTENT = (
    '{"schema_version": "daily_briefing.v1", '
    '"stories": [{"item_id": "i1", "evidence": [{"url": "https://example.org/a"}]}]}'
)


def full_text_source(**changes: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "example-blog",
        "name": "Example blog",
        "kind": "rss",
        "url": "https://example.org/feed.xml",
        "role": "vendor",
        "enabled": True,
        "mode": "full_text",
        "polling_interval_minutes": 360,
        "rate_limit": {"min_seconds_between_requests": 10, "max_connections": 1},
        "store": {"metadata": True, "feed_summary": False, "body": True},
        "body": {"source": "page", "hosts": ["example.org"]},
        "model_submission": "full_text",
        "retention_days": {"metadata": None, "feed_summary": 0, "body": 90},
        "excerpts_allowed": True,
        "excerpt_limit_chars": 300,
        "attribution": "Link to the original post.",
        "terms": {
            "reviewed_on": date(2026, 11, 21),
            "approved_by_owner_on": date(2026, 11, 23),
            "urls": ["https://example.org/terms"],
            "automated_access": "explicit",
            "restrictions": ["None stated."],
            "uncertainties": ["The terms are silent on private copies."],
        },
    }
    entry.update(changes)
    return entry


def metadata_only_source(**changes: Any) -> dict[str, Any]:
    entry = full_text_source(
        mode="metadata_only",
        store={"metadata": True, "feed_summary": False, "body": False},
        model_submission="metadata",
        retention_days={"metadata": None, "feed_summary": 0},
        excerpts_allowed=False,
    )
    del entry["body"]
    del entry["excerpt_limit_chars"]
    entry.update(changes)
    return entry


def disabled_source(**changes: Any) -> dict[str, Any]:
    entry = metadata_only_source(
        enabled=False,
        mode="disabled",
        store={"metadata": False, "feed_summary": False, "body": False},
        model_submission="none",
        retention_days={"metadata": 0, "feed_summary": 0},
    )
    entry.update(changes)
    return entry


def rejected(entry: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as raised:
        Source.model_validate(entry)
    return str(raised.value)


# --- Source --------------------------------------------------------------------------------


def test_the_three_example_sources_are_valid() -> None:
    for entry in (full_text_source(), metadata_only_source(), disabled_source()):
        Source.model_validate(entry)


def test_a_source_is_enabled_exactly_when_its_mode_is_not_disabled() -> None:
    assert "enabled must be true exactly when" in rejected(full_text_source(enabled=False))
    assert "enabled must be true exactly when" in rejected(disabled_source(enabled=True))


def test_a_source_with_uncertain_access_cannot_be_enabled() -> None:
    entry = metadata_only_source()
    entry["terms"]["automated_access"] = "uncertain"
    assert "uncertain automated access" in rejected(entry)
    disabled = disabled_source()
    disabled["terms"]["automated_access"] = "uncertain"
    Source.model_validate(disabled)


def test_a_disabled_source_stores_and_submits_nothing() -> None:
    stores = disabled_source(store={"metadata": True, "feed_summary": False, "body": False})
    assert "a disabled source stores nothing" in rejected(stores)
    assert "submits nothing" in rejected(disabled_source(model_submission="metadata"))


def test_article_text_is_stored_only_in_full_text_mode() -> None:
    entry = metadata_only_source(store={"metadata": True, "feed_summary": False, "body": True})
    assert "stored exactly when the mode is full_text" in rejected(entry)
    entry = full_text_source(store={"metadata": True, "feed_summary": False, "body": False})
    assert "stored exactly when the mode is full_text" in rejected(entry)


def test_a_full_text_source_states_its_hosts_retention_and_quotation_limit() -> None:
    no_body = full_text_source()
    del no_body["body"]
    assert "says where its text comes from" in rejected(no_body)
    no_retention = full_text_source(retention_days={"metadata": None, "feed_summary": 0})
    assert "states its body retention" in rejected(no_retention)
    no_limit = full_text_source()
    del no_limit["excerpt_limit_chars"]
    assert "states its quotation limit" in rejected(no_limit)
    assert "hosts" in rejected(full_text_source(body={"source": "page", "hosts": []}))


@pytest.mark.parametrize("days", [0, 91, 365])
def test_body_retention_is_between_one_and_ninety_days(days: int) -> None:
    entry = full_text_source(retention_days={"metadata": None, "feed_summary": 0, "body": days})
    assert "body" in rejected(entry)


def test_only_a_full_text_source_submits_article_text_or_has_a_body_policy() -> None:
    assert "only a full_text source submits article text" in rejected(
        metadata_only_source(model_submission="full_text")
    )
    assert "only a full_text source has a body policy" in rejected(
        metadata_only_source(body={"source": "feed", "hosts": ["example.org"]})
    )


def test_a_metadata_only_source_keeps_no_summary_and_quotes_nothing() -> None:
    summary = metadata_only_source(store={"metadata": True, "feed_summary": True, "body": False})
    assert "feed summary is stored only in feed_summary mode" in rejected(summary)
    assert "summary is submitted only in feed_summary mode" in rejected(
        metadata_only_source(model_submission="title_and_summary")
    )
    assert "nothing to quote" in rejected(metadata_only_source(excerpts_allowed=True))


def test_a_source_must_use_https_and_known_values() -> None:
    assert "url" in rejected(full_text_source(url="http://example.org/feed.xml"))
    assert "mode" in rejected(full_text_source(mode="body_enabled"))
    assert "kind" in rejected(full_text_source(kind="scraper"))
    assert "fetch_body" in rejected(full_text_source(fetch_body=True))


def test_terms_cannot_be_approved_before_they_were_reviewed() -> None:
    entry = full_text_source()
    entry["terms"]["approved_by_owner_on"] = date(2026, 11, 20)
    assert "approved before they were reviewed" in rejected(entry)


# --- Time ----------------------------------------------------------------------------------


def document(**changes: Any) -> SourceDocument:
    fields: dict[str, Any] = {
        "source_id": "example-blog",
        "external_id": "post-1",
        "canonical_url": "https://example.org/post-1",
        "title": "A post",
        "first_seen_at": NOW,
        "source_role": SourceRole.VENDOR,
    }
    fields.update(changes)
    return SourceDocument(**fields)


def test_a_naive_time_is_rejected_and_an_aware_time_is_held_in_utc() -> None:
    with pytest.raises(ValidationError):
        document(first_seen_at=datetime(2026, 11, 19, 11, 15))
    eastern = timezone(timedelta(hours=-5))
    held = document(first_seen_at=datetime(2026, 11, 19, 6, 15, tzinfo=eastern)).first_seen_at
    assert held == NOW
    assert held.utcoffset() == timedelta(0)


def test_a_published_time_is_optional_and_never_defaulted() -> None:
    assert document().published_at is None


def test_records_are_immutable_and_reject_unknown_fields() -> None:
    record = document()
    with pytest.raises(ValidationError):
        record.title = "changed"
    with pytest.raises(ValidationError):
        document(body_text="not a document field")
    assert record.model_copy(update={"id": 7}).id == 7
    assert record.id is None


# --- Observations, stories -----------------------------------------------------------------


def test_a_purged_observation_holds_no_body_but_keeps_its_hash() -> None:
    fields: dict[str, Any] = {
        "document_id": 1,
        "retrieved_at": NOW,
        "fetch_status": FetchStatus.OK,
        "content_hash": HASH,
    }
    purged = DocumentObservation(**fields, body_purged_at=NOW)
    assert purged.body_text is None
    assert purged.content_hash == HASH
    with pytest.raises(ValidationError, match="purged"):
        DocumentObservation(**fields, body_text="text", body_purged_at=NOW)
    with pytest.raises(ValidationError):
        DocumentObservation(**{**fields, "content_hash": "not-a-hash"})


def test_a_story_cannot_be_active_before_it_was_seen_or_merged_into_itself() -> None:
    story = Story(title="A story", first_seen_at=NOW, last_activity_at=NOW)
    assert story.state is StoryState.OPEN
    with pytest.raises(ValidationError, match="last activity"):
        Story(title="A story", first_seen_at=NOW, last_activity_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="merged into itself"):
        Story(id=3, title="A story", first_seen_at=NOW, last_activity_at=NOW, merged_into_id=3)


def test_a_membership_event_names_exactly_one_decider() -> None:
    fields: dict[str, Any] = {
        "story_id": 1,
        "document_id": 2,
        "action": MembershipAction.ADD,
        "reason": "shares a canonical URL",
        "occurred_at": NOW,
    }
    StoryMembershipEvent(**fields, decided_by_rule="canonical-url")
    StoryMembershipEvent(**fields, decided_by_model_call_id=5)
    with pytest.raises(ValidationError, match="one rule or one model call"):
        StoryMembershipEvent(**fields)
    with pytest.raises(ValidationError, match="one rule or one model call"):
        StoryMembershipEvent(**fields, decided_by_rule="canonical-url", decided_by_model_call_id=5)


# --- Assessment, evidence, decision --------------------------------------------------------


@pytest.mark.parametrize("score", [-1, 5])
def test_a_dimension_score_is_between_zero_and_four(score: int) -> None:
    scores = {"impact": 2, "evidence": 2, "novelty": 2, "professional_relevance": 2, "maturity": 2}
    DimensionScores(**scores)
    with pytest.raises(ValidationError):
        DimensionScores(**{**scores, "evidence": score})


def test_the_scores_are_five_separate_dimensions_with_no_total() -> None:
    assert set(DimensionScores.model_fields) == {
        "impact",
        "evidence",
        "novelty",
        "professional_relevance",
        "maturity",
    }
    assert not {"total", "score", "weighted"} & set(dir(DimensionScores))


def test_an_assessment_carries_a_suggestion_not_a_final_class() -> None:
    assessment = EditorialAssessment(
        story_id=1,
        as_of=NOW,
        input_hash=HASH,
        prompt_hash=HASH,
        model_id="claude-haiku-5-5",
        rubric_version="v0",
        tier=AssessmentTier.STANDARD,
        scores=DimensionScores(
            impact=3, evidence=1, novelty=2, professional_relevance=3, maturity=1
        ),
        suggested_class=EditorialClass.MAJOR,
        uncertainty="Only the vendor reports this.",
        draft_text="",
        model_call_id=9,
    )
    assert "final_class" not in EditorialAssessment.model_fields
    assert assessment.suggested_class is EditorialClass.MAJOR
    assert AssessmentInput(assessment_id=1, observation_id=2).observation_id == 2


def evidence(**changes: Any) -> EvidenceItem:
    fields: dict[str, Any] = {
        "assessment_id": 1,
        "claim_text": "The model scores 90 on the benchmark.",
        "observation_id": 2,
        "quote": "scores 90",
        "support_type": SupportType.SUPPORTS,
        "integrity_status": IntegrityStatus.VERIFIED,
    }
    fields.update(changes)
    return EvidenceItem(**fields)


def test_only_a_verified_supporting_quotation_counts_as_support() -> None:
    assert evidence().counts_as_support is True
    assert evidence(integrity_status=IntegrityStatus.FAILED).counts_as_support is False
    assert evidence(support_type=SupportType.CONTRADICTS).counts_as_support is False
    assert evidence(support_type=SupportType.CONTEXT).counts_as_support is False


def test_integrity_and_semantic_support_are_separate_fields() -> None:
    item = evidence()
    assert item.integrity_status is IntegrityStatus.VERIFIED
    # Passing the integrity check does not label the quotation as supporting the claim.
    assert item.support_label is SupportLabel.UNREVIEWED


def test_classes_are_ordered_and_the_lower_of_two_is_chosen() -> None:
    ordered = sorted(EditorialClass, key=lambda c: c.rank)
    assert [c.value for c in ordered] == ["low", "watch", "practical", "major"]
    assert lower_class(EditorialClass.MAJOR, EditorialClass.WATCH) is EditorialClass.WATCH
    assert lower_class(EditorialClass.WATCH, EditorialClass.MAJOR) is EditorialClass.WATCH
    assert lower_class(EditorialClass.LOW, EditorialClass.PRACTICAL) is EditorialClass.LOW
    assert lower_class(EditorialClass.MAJOR, EditorialClass.MAJOR) is EditorialClass.MAJOR


def test_a_decision_cannot_exceed_its_ceiling_and_a_ceiling_states_its_reasons() -> None:
    fields: dict[str, Any] = {
        "assessment_id": 1,
        "policy_version": "v0",
        "independent_source_count": 0,
        "eligible": True,
    }
    EditorialDecision(
        **fields,
        final_class=EditorialClass.WATCH,
        ceiling=EditorialClass.WATCH,
        ceiling_reasons=("no evidence item passed the integrity check",),
    )
    with pytest.raises(ValidationError, match="cannot exceed the ceiling"):
        EditorialDecision(
            **fields,
            final_class=EditorialClass.MAJOR,
            ceiling=EditorialClass.WATCH,
            ceiling_reasons=("metadata-only story",),
        )
    with pytest.raises(ValidationError, match="states its reasons"):
        EditorialDecision(
            **fields, final_class=EditorialClass.WATCH, ceiling=EditorialClass.PRACTICAL
        )
    EditorialDecision(**fields, final_class=EditorialClass.MAJOR, ceiling=EditorialClass.MAJOR)


# --- Briefings, model calls, jobs ----------------------------------------------------------


def test_a_briefing_is_versioned_and_has_a_default_profile() -> None:
    briefing = Briefing(
        local_date=date(2026, 11, 19),
        timezone="America/New_York",
        variant=BriefingVariant.PIPELINE,
        version=1,
        status=BriefingStatus.READY,
        content=CONTENT,
        content_hash=HASH,
        configuration_hash=HASH,
    )
    assert briefing.profile == "default"
    with pytest.raises(ValidationError):
        briefing.model_validate({**briefing.model_dump(), "version": 0})


def briefing_record(content: str = CONTENT) -> Briefing:
    return Briefing(
        local_date=date(2026, 11, 19),
        timezone="America/New_York",
        variant=BriefingVariant.PIPELINE,
        version=1,
        status=BriefingStatus.READY,
        content=content,
        content_hash=HASH,
        configuration_hash=HASH,
    )


def test_a_briefing_version_cannot_be_changed_through_its_content() -> None:
    briefing = briefing_record()
    document = briefing.document()
    assert document["stories"] == [
        {"item_id": "i1", "evidence": [{"url": "https://example.org/a"}]}
    ]
    # The caller may do anything to its copy. The stored version does not move.
    stories = document["stories"]
    assert isinstance(stories, list)
    stories.clear()
    document["injected"] = True
    assert briefing.content == CONTENT
    assert briefing.document()["stories"] != []
    assert "injected" not in briefing.document()
    # Each call hands out a separate copy, nested values included.
    first, second = briefing.document(), briefing.document()
    assert first == second
    assert first is not second
    assert first["stories"] is not second["stories"]
    with pytest.raises(ValidationError):
        briefing.content = "{}"


@pytest.mark.parametrize("content", ["", "not json", "[1, 2]", '"text"', "null", "{"])
def test_briefing_content_must_be_a_json_object(content: str) -> None:
    with pytest.raises(ValidationError):
        briefing_record(content)


def test_no_record_field_holds_a_mutable_container() -> None:
    import ai_briefing.domain.records as records

    mutable: list[str] = []
    for name in dir(records):
        model = getattr(records, name)
        if not (isinstance(model, type) and issubclass(model, records.Record)):
            continue
        for field_name, info in model.model_fields.items():
            text = str(info.annotation)
            if "dict[" in text or "list[" in text or "set[" in text:
                mutable.append(f"{name}.{field_name}: {text}")
    assert mutable == []


def test_a_story_or_watch_item_names_its_decision() -> None:
    fields: dict[str, Any] = {
        "briefing_id": 1,
        "position": 1,
        "text": "Headline",
        "inclusion_reason": "class practical, ranked first",
    }
    BriefingItem(**fields, kind=BriefingItemKind.STORY, story_id=2, decision_id=3)
    BriefingItem(**fields, kind=BriefingItemKind.CONCEPT_NOTE)
    for kind in (BriefingItemKind.STORY, BriefingItemKind.WATCH):
        with pytest.raises(ValidationError, match="names its story and its decision"):
            BriefingItem(**fields, kind=kind, story_id=2)


def call(**changes: Any) -> LLMCall:
    fields: dict[str, Any] = {
        "job_run_id": 1,
        "purpose": ModelTask.SCREENING,
        "prompt_id": "screening",
        "prompt_hash": HASH,
        "provider": "anthropic",
        "model_id": "claude-haiku-5-5",
        "tokens_in": 1200,
        "tokens_out": 300,
        "estimated_cost_usd": Decimal("0.00027"),
        "price_table_version": "2026-11-21",
        "status": LLMCallStatus.SUCCEEDED,
    }
    fields.update(changes)
    return LLMCall(**fields)


def test_a_call_refused_by_the_budget_check_is_recorded_with_no_usage() -> None:
    refused = call(
        status=LLMCallStatus.BUDGET_REFUSED,
        tokens_in=0,
        tokens_out=0,
        estimated_cost_usd=Decimal(0),
    )
    assert refused.status is LLMCallStatus.BUDGET_REFUSED
    with pytest.raises(ValidationError, match="used no tokens"):
        call(status=LLMCallStatus.BUDGET_REFUSED)
    # A refusal by the model did reach the provider, so it has usage and a cost.
    assert call(status=LLMCallStatus.REFUSED).tokens_in == 1200


def test_cost_is_exact_decimal_and_never_negative() -> None:
    assert call().estimated_cost_usd == Decimal("0.00027")
    with pytest.raises(ValidationError):
        call(estimated_cost_usd=Decimal("-0.01"))
    with pytest.raises(ValidationError):
        call(tokens_out=-1)


def test_a_job_has_an_end_time_exactly_when_it_has_finished() -> None:
    fields: dict[str, Any] = {
        "job": "collect",
        "idempotency_key": "collect:2026-11-19",
        "started_at": NOW,
        "application_version": "0.0.0",
        "configuration_hash": HASH,
    }
    assert JobRun(**fields, status=JobStatus.RUNNING).counts == {}
    given = {"documents": 3}
    done = JobRun(**fields, status=JobStatus.SUCCEEDED, ended_at=NOW, counts=given)
    assert done.counts == {"documents": 3}
    # The counts are read-only, and are a copy: neither route changes the record.
    with pytest.raises(TypeError):
        done.counts["documents"] = 99  # type: ignore[index]
    given["documents"] = 99
    assert done.counts == {"documents": 3}
    assert done.model_dump()["counts"] == {"documents": 3}
    with pytest.raises(ValidationError):
        JobRun(**fields, status=JobStatus.RUNNING, counts={"documents": -1})
    with pytest.raises(ValidationError, match="end time exactly when"):
        JobRun(**fields, status=JobStatus.SUCCEEDED)
    with pytest.raises(ValidationError, match="end time exactly when"):
        JobRun(**fields, status=JobStatus.RUNNING, ended_at=NOW)
    with pytest.raises(ValidationError, match="cannot end before it starts"):
        JobRun(**fields, status=JobStatus.FAILED, ended_at=NOW - timedelta(seconds=1))
