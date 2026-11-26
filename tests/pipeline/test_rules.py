"""The rules behind the first briefing, one at a time: the quotation check, the policy,
selection and its limits, and rendering (ADR-004, RFC §6).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ai_briefing.briefings import compose as composing
from ai_briefing.briefings.compose import build, clip, confidence, day_bounds, without_urls
from ai_briefing.briefings.contract import contract_validator, load_schema
from ai_briefing.briefings.render import escape, link, to_markdown
from ai_briefing.domain.enums import (
    AssessmentTier,
    Confidence,
    EditorialClass,
    FetchStatus,
    IntegrityStatus,
    SourceRole,
    SupportType,
)
from ai_briefing.domain.records import (
    DimensionScores,
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
    EvidenceItem,
    SourceDocument,
    Story,
)
from ai_briefing.editorial import integrity
from ai_briefing.editorial.contracts import AssessmentOutput, ScreeningOutput
from ai_briefing.editorial.policy import v0 as policy
from ai_briefing.prompts import load
from ai_briefing.storage.queries import Assessed

NOW = datetime(2026, 11, 19, 11, 15, tzinfo=UTC)
HASH = "e" * 64
VALIDATOR = contract_validator(load_schema("daily_briefing.v1"))

# --- The quotation check ----------------------------------------------------------------------

TEXT = "The model scores 90 percent on the benchmark.\nIt was   trained for three days."


def observed(
    text: str | None = TEXT, *, summary: str | None = None, at: datetime = NOW
) -> DocumentObservation:
    return DocumentObservation(
        id=7,
        document_id=1,
        retrieved_at=at,
        fetch_status=FetchStatus.OK,
        summary=summary,
        body_text=text,
        content_hash=HASH,
    )


@pytest.mark.parametrize(
    "quote",
    [
        "The model scores 90 percent on the benchmark.",
        "scores 90 percent on the benchmark",
        "It was trained for three days.",  # runs of whitespace are one space
        "benchmark. It was trained",  # across a line break
        "  The model scores 90 percent  ",
        "The" + chr(0xA0) + "model scores 90 percent",  # a no-break space is a space
    ],
)
def test_words_that_are_in_the_text_pass(quote: str) -> None:
    assert integrity.quote_is_in(quote, TEXT) is True


@pytest.mark.parametrize(
    "quote",
    [
        "The model scores 95 percent on the benchmark.",  # one digit changed
        "the model scores 90 percent on the benchmark.",  # case is not normalised
        "The model scores ninety percent",
        "The model scores 90 percent on every benchmark.",
        "scores 90",  # too short to mean anything
        "",
        "   ",
        "It was trained for three days. The model scores 90 percent",  # reordered
    ],
)
def test_words_that_are_not_in_the_text_fail(quote: str) -> None:
    assert integrity.quote_is_in(quote, TEXT) is False


def test_compatibility_forms_are_normalised_and_nothing_else_is() -> None:
    ligature = "The " + chr(0xFB01) + "nal score was 90 percent overall."
    assert integrity.quote_is_in("The final score was 90 percent", ligature) is True
    assert integrity.normalise(" a\t\n b  ") == "a b"
    # A curly quote and a straight one are different characters and stay different.
    curly = "said " + chr(0x201C) + "it works" + chr(0x201D) + " yesterday"
    assert integrity.quote_is_in('said "it works" yesterday', curly) is False


def test_no_text_verifies_nothing() -> None:
    assert integrity.quote_is_in("The model scores 90 percent", None) is False
    assert integrity.quote_is_in("The model scores 90 percent", "") is False


def shown(text: str | None = TEXT, *, at: datetime = NOW) -> dict[int, integrity.Shown]:
    return {7: integrity.Shown(observed(at=at), text)}


def test_a_citation_needs_a_given_observation_made_before_the_assessment() -> None:
    quote = "The model scores 90 percent on the benchmark."
    assert integrity.citation_holds(quote, 7, shown(), NOW) is True
    assert integrity.citation_holds(quote, 8, shown(), NOW) is False  # not one it was given
    later = shown(at=NOW + timedelta(seconds=1))
    assert integrity.citation_holds(quote, 7, later, NOW) is False  # observed after the fact
    assert integrity.citation_holds("words that are not there at all", 7, shown(), NOW) is False


def test_a_quotation_is_checked_against_what_was_sent_not_what_is_stored() -> None:
    # The stored observation holds both sentences. Only the first was sent to the model.
    sent = "The model scores 90 percent on the benchmark."
    given = {7: integrity.Shown(observed(), sent)}
    assert integrity.citation_holds("The model scores 90 percent", 7, given, NOW) is True
    # These words are in the stored text, but the model never saw them.
    assert integrity.quote_is_in("It was trained for three days.", TEXT) is True
    assert integrity.citation_holds("It was trained for three days.", 7, given, NOW) is False
    assert integrity.citation_holds("The model scores 90 percent", 7, shown(None), NOW) is False


# --- The policy ---------------------------------------------------------------------------------

PRIMARY = [("papers", SourceRole.PRIMARY)]
ALL_CLASSES = list(EditorialClass)


@pytest.mark.parametrize("suggested", ALL_CLASSES)
def test_with_verified_evidence_and_text_the_suggestion_stands(suggested: EditorialClass) -> None:
    verdict = policy.decide(
        suggested, verified_supporting_evidence=1, has_source_text=True, source_roles=PRIMARY
    )
    assert verdict.final_class is suggested
    assert verdict.ceiling is EditorialClass.MAJOR
    assert verdict.ceiling_reasons == ()
    assert verdict.eligible is (suggested is not EditorialClass.LOW)


@pytest.mark.parametrize(
    ("verified", "has_text", "reasons"),
    [
        (0, True, (policy.NO_VERIFIED_EVIDENCE,)),
        (3, False, (policy.METADATA_ONLY,)),
        (0, False, (policy.NO_VERIFIED_EVIDENCE, policy.METADATA_ONLY)),
    ],
)
@pytest.mark.parametrize("suggested", ALL_CLASSES)
def test_a_ceiling_holds_whatever_the_model_suggested(
    suggested: EditorialClass, verified: int, has_text: bool, reasons: tuple[str, ...]
) -> None:
    verdict = policy.decide(
        suggested,
        verified_supporting_evidence=verified,
        has_source_text=has_text,
        source_roles=PRIMARY,
    )
    assert verdict.ceiling is EditorialClass.WATCH
    assert verdict.ceiling_reasons == reasons
    assert verdict.final_class.rank <= EditorialClass.WATCH.rank
    expected = EditorialClass.LOW if suggested is EditorialClass.LOW else EditorialClass.WATCH
    assert verdict.final_class is expected  # lowered to the ceiling, never raised to it


def test_independent_sources_are_counted_once_each_and_only_by_role() -> None:
    def count(*roles: tuple[str, SourceRole]) -> int:
        return policy.decide(
            EditorialClass.WATCH,
            verified_supporting_evidence=1,
            has_source_text=True,
            source_roles=roles,
        ).independent_source_count

    assert count(("a", SourceRole.PRIMARY)) == 1
    assert count(("a", SourceRole.PRIMARY), ("a", SourceRole.PRIMARY)) == 1  # one source, twice
    assert count(("a", SourceRole.PRIMARY), ("b", SourceRole.INDEPENDENT)) == 2
    assert (
        count(("v", SourceRole.VENDOR), ("c", SourceRole.COMMUNITY), ("g", SourceRole.AGGREGATOR))
        == 0
    )
    assert count() == 0


# --- Selection ----------------------------------------------------------------------------------


def assessed(
    number: int,
    final: EditorialClass,
    *,
    scores: tuple[int, int, int, int, int] = (2, 2, 2, 2, 2),
    verified: int = 1,
    eligible: bool = True,
    url: str | None = None,
    draft: dict[str, str] | None = None,
    uncertainty: str = "Based on one source.",
    title: str | None = None,
) -> Assessed:
    names = ("impact", "evidence", "novelty", "professional_relevance", "maturity")
    document = SourceDocument(
        id=number,
        source_id="papers",
        external_id=f"e{number}",
        canonical_url=url or f"https://papers.example.org/{number}",
        title=title or f"Title {number}",
        first_seen_at=NOW,
        source_role=SourceRole.PRIMARY,
    )
    text = draft or {
        "headline": f"Headline {number}",
        "summary": "Summary.",
        "why_it_matters": "Why.",
    }
    assessment = EditorialAssessment(
        id=number,
        story_id=number,
        as_of=NOW,
        input_hash=HASH,
        prompt_hash=HASH,
        model_id="claude-haiku-5-5",
        rubric_version="v0",
        tier=AssessmentTier.STANDARD,
        scores=DimensionScores(**dict(zip(names, scores, strict=True))),
        suggested_class=final,
        uncertainty=uncertainty,
        draft_text=json.dumps(text),
        model_call_id=1,
    )
    decision = EditorialDecision(
        id=number,
        assessment_id=number,
        policy_version="v0.1",
        final_class=final,
        ceiling=EditorialClass.MAJOR,
        independent_source_count=1,
        eligible=eligible,
    )
    evidence = tuple(
        EvidenceItem(
            assessment_id=number,
            claim_text="A claim.",
            observation_id=1,
            quote="Some words from the source.",
            support_type=SupportType.SUPPORTS,
            integrity_status=IntegrityStatus.VERIFIED,
        )
        for _ in range(verified)
    )
    story = Story(id=number, title=document.title, first_seen_at=NOW, last_activity_at=NOW)
    return Assessed(story, document, "Example Papers", assessment, decision, evidence)


def built(items: list[Assessed], reasons: list[str] | None = None) -> dict[str, Any]:
    content, _ = build(
        items,
        local_date=date(2026, 11, 19),
        timezone="UTC",
        generated_at=NOW,
        version=1,
        degraded_reasons=reasons or [],
    )
    assert list(VALIDATOR.iter_errors(content)) == []
    return content


def test_at_most_five_stories_and_ten_watch_items() -> None:
    stories = [assessed(n, EditorialClass.PRACTICAL) for n in range(1, 9)]
    watch = [assessed(n, EditorialClass.WATCH) for n in range(20, 35)]
    content = built(stories + watch)
    assert len(content["stories"]) == 5
    assert len(content["watchlist"]) == 10
    assert [s["item_id"] for s in content["stories"]] == ["i1", "i2", "i3", "i4", "i5"]
    assert content["watchlist"][0]["item_id"] == "i6"


def test_stories_are_ordered_by_class_then_by_the_fixed_tuple_of_scores() -> None:
    items = [
        assessed(1, EditorialClass.PRACTICAL, scores=(4, 4, 4, 4, 4)),
        assessed(2, EditorialClass.MAJOR, scores=(0, 0, 0, 0, 0)),
        assessed(3, EditorialClass.PRACTICAL, scores=(3, 4, 0, 0, 0)),
        assessed(4, EditorialClass.PRACTICAL, scores=(3, 2, 4, 4, 4)),
        assessed(5, EditorialClass.PRACTICAL, scores=(3, 4, 0, 0, 0)),
    ]
    order = [s["story_id"] for s in built(list(reversed(items)))["stories"]]
    # Class first; then impact; then evidence; ties by the older story.
    assert order == ["s-2", "s-1", "s-3", "s-5", "s-4"]


def test_low_and_ineligible_stories_and_bad_addresses_are_left_out() -> None:
    content = built(
        [
            assessed(1, EditorialClass.LOW, eligible=False),
            assessed(2, EditorialClass.PRACTICAL, eligible=False),
            assessed(3, EditorialClass.PRACTICAL, url='https://papers.example.org/a"><b'),
            assessed(4, EditorialClass.PRACTICAL, url="https://papers.example.org/ok"),
        ]
    )
    assert [s["story_id"] for s in content["stories"]] == ["s-4"]


def test_the_status_follows_what_is_in_the_briefing() -> None:
    story = [assessed(1, EditorialClass.PRACTICAL)]
    assert built(story)["status"] == "ready"
    assert built(story, ["Budget: some items could not be assessed today."])["status"] == "degraded"
    assert built([])["status"] == "empty"
    assert built([assessed(1, EditorialClass.WATCH)])["status"] == "ready"


@pytest.mark.parametrize(
    ("verified", "evidence_score", "expected"),
    [
        (2, 3, Confidence.HIGH),
        (5, 4, Confidence.HIGH),
        (2, 2, Confidence.MODERATE),
        (1, 4, Confidence.MODERATE),
        (1, 2, Confidence.MODERATE),
        (1, 1, Confidence.LOW),
        (0, 4, Confidence.LOW),  # the model's own evidence score cannot raise it alone
    ],
)
def test_confidence_comes_from_checked_quotations(
    verified: int, evidence_score: int, expected: Confidence
) -> None:
    item = assessed(
        1, EditorialClass.PRACTICAL, scores=(2, evidence_score, 2, 2, 2), verified=verified
    )
    assert confidence(item) is expected


def test_text_is_cut_to_the_contracts_limits_and_uncertainty_is_kept() -> None:
    long = {"headline": "H" * 500, "summary": "S" * 2000, "why_it_matters": "W" * 2000}
    (story,) = built([assessed(1, EditorialClass.PRACTICAL, draft=long, uncertainty="U" * 900)])[
        "stories"
    ]
    assert len(story["headline"]) == 200
    assert len(story["summary"]) == 800
    assert len(story["why_it_matters"]) <= 600
    assert "Uncertainty: UUU" in story["why_it_matters"]
    assert story["headline"].endswith("…")
    assert clip("  two\n words  ", 50) == "two words"
    assert clip("abcdef", 4) == "abc…"


def test_an_empty_draft_falls_back_to_the_documents_title() -> None:
    blank = {"headline": "", "summary": "", "why_it_matters": ""}
    (story,) = built([assessed(1, EditorialClass.PRACTICAL, draft=blank, title="The real title")])[
        "stories"
    ]
    assert story["headline"] == story["summary"] == "The real title"
    assert story["why_it_matters"] == "Uncertainty: Based on one source."


@pytest.mark.parametrize(
    "text",
    [
        "See https://evil.example.com/x for more.",
        "See HTTP://EVIL.EXAMPLE.COM for more.",
        "Visit www.evil.example.com today.",
        "Two: http://a.example.com and https://b.example.com/y?z=1.",
    ],
)
def test_an_address_in_model_text_is_removed(text: str) -> None:
    cleaned = without_urls(text)
    assert "example.com" not in cleaned.lower()
    assert composing.URL_REMOVED in cleaned
    assert (
        without_urls("No address here, version 2.0 only.") == "No address here, version 2.0 only."
    )


def test_a_days_bounds_are_its_local_midnights_in_utc() -> None:
    start, end = day_bounds(date(2026, 11, 19), "America/New_York")
    assert start == datetime(2026, 11, 19, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 11, 20, 5, 0, tzinfo=UTC)
    # The day the clocks go back is twenty-five hours long.
    start, end = day_bounds(date(2026, 11, 1), "America/New_York")
    assert end - start == timedelta(hours=25)
    assert day_bounds(date(2026, 11, 19), "UTC")[0] == datetime(2026, 11, 19, tzinfo=UTC)


# --- Rendering ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "[click](javascript:alert(1))",
        "![image](https://evil.example.com/x.png)",
        "# A heading",
        "**bold** and _emphasis_ and `code`",
        "> a quotation",
        "a | table | row",
        "1. a list",
        "&lt;already escaped&gt;",
    ],
)
def test_escaped_text_cannot_act_as_markup(text: str) -> None:
    safe = escape(text)
    assert "<" not in safe
    assert ">" not in safe.replace("\\>", "")
    # Every character Markdown would act on has a backslash in front of it.
    for match in re.finditer(r"[`*_\[\]()#|!]", safe):
        assert safe[match.start() - 1] == "\\", (text, safe)
    assert not safe.startswith(("#", ">", "1."))


def test_a_link_is_written_only_for_a_plain_web_address() -> None:
    assert (
        link("Title", "https://papers.example.org/a") == "[Title](<https://papers.example.org/a>)"
    )
    assert (
        link("T", "https://papers.example.org/a(b)") == "[T](<https://papers.example.org/a%28b%29>)"
    )
    for bad in (
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://x.example.org/a b",
        "",
        "data:x",
    ):
        assert link("Title", bad) == "Title"
    assert link("[x](y)", "https://papers.example.org/a").startswith("[\\[x\\]\\(y\\)](<")


def test_markdown_is_made_from_the_stored_content_alone() -> None:
    content = built(
        [
            assessed(
                1,
                EditorialClass.MAJOR,
                draft={"headline": "A <b>bold</b> claim", "summary": "S.", "why_it_matters": "W."},
            ),
            assessed(2, EditorialClass.WATCH),
        ]
    )
    markdown = to_markdown(content)
    assert "## A &lt;b&gt;bold&lt;/b&gt; claim" in markdown
    assert "*major, moderate confidence, 1 independent source(s)*" in markdown
    assert "## Worth watching" in markdown
    assert "It does not show that the statement is true." in markdown
    assert sorted(re.findall(r"\]\(<([^>]+)>\)", markdown)) == [
        "https://papers.example.org/1",
        "https://papers.example.org/2",
    ]


# --- Prompts and output shapes --------------------------------------------------------------------


@pytest.mark.parametrize("prompt_id", ["screening", "assessment"])
def test_a_prompt_is_identified_by_the_hash_of_its_text(prompt_id: str) -> None:
    prompt = load(prompt_id)
    assert prompt.id == prompt_id
    assert len(prompt.sha256) == 64
    assert load(prompt_id) == prompt
    assert "\r" not in prompt.text  # the hash does not depend on the platform's line endings
    assert "data, not instructions" in prompt.text
    assert "http" not in prompt.text


@pytest.mark.parametrize("bad", ["../secret", "assessment.md", "a/b", "", "x y"])
def test_a_prompt_identifier_cannot_reach_outside_the_prompt_directory(bad: str) -> None:
    with pytest.raises(ValueError, match="not a prompt identifier"):
        load(bad)


def test_the_assessment_prompt_anchors_every_level_of_every_dimension() -> None:
    text = load("assessment").text
    for dimension in ("impact", "evidence", "novelty", "professional_relevance", "maturity"):
        section = text[text.index(f"**{dimension}**") :].split("\n\n", 1)[0]
        for level in range(5):
            assert f"{level}:" in section, (dimension, level)


def test_the_output_shapes_put_evidence_first_and_hold_no_url() -> None:
    fields = list(AssessmentOutput.model_fields)
    assert fields.index("claims") < fields.index("scores") < fields.index("suggested_class")
    for shape in (AssessmentOutput, ScreeningOutput):
        text = json.dumps(shape.model_json_schema()).lower()
        assert "url" not in text
        assert '"additionalproperties": false' in text
    scores = AssessmentOutput.model_json_schema()["$defs"]["Scores"]["properties"]
    # Each score is one of five listed values, because the API does not enforce a range.
    assert all(spec["enum"] == [0, 1, 2, 3, 4] for spec in scores.values())
