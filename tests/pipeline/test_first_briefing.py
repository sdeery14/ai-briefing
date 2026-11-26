"""The first briefing, end to end, on a synthetic day (issue 1.6's done-when; ADR-004,
ADR-006, ADR-009, ADR-010). No network and no API key: the offline guard is on throughout.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from ai_briefing.briefings.compose import compose
from ai_briefing.briefings.contract import contract_validator, load_schema
from ai_briefing.briefings.render import to_markdown
from ai_briefing.domain.enums import EditorialClass, IntegrityStatus
from ai_briefing.domain.records import (
    BriefingItem,
    DocumentObservation,
    EditorialAssessment,
    EditorialDecision,
)
from ai_briefing.editorial.policy import v0 as policy
from ai_briefing.llm.backends import ModelRequest, ModelResponse, ReplayBackend
from ai_briefing.llm.budget import month_to_date
from ai_briefing.llm.config import ModelsConfig
from ai_briefing.llm.pricing import Usage
from ai_briefing.prompts import RUBRIC_VERSION, load
from ai_briefing.runtime import cli
from ai_briefing.storage import database, repositories, schema

from .conftest import (
    HASH,
    MODEL_ID,
    NOW,
    RECORDED,
    VENDOR_PAGE_TEXT,
    FakeTransport,
    ScriptedBackend,
    catalogue_yaml,
    make_fetcher,
    run_day,
    scripted,
)

LOCAL_DATE = date(2026, 11, 19)
VALIDATOR = contract_validator(load_schema("daily_briefing.v1"))


def briefing(engine: Engine, *, now: datetime = NOW) -> tuple[dict[str, Any], bool]:
    with engine.begin() as connection:
        composed = compose(
            connection, local_date=LOCAL_DATE, timezone="UTC", configuration_hash=HASH, now=now
        )
    return composed.briefing.document(), composed.created


def table(engine: Engine, name: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(select(schema.metadata.tables[name])).mappings().all()
    return [dict(row) for row in rows]


def row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            name: connection.execute(select(func.count()).select_from(found)).scalar_one()
            for name, found in schema.metadata.tables.items()
        }


def by_title(engine: Engine) -> dict[str, dict[str, Any]]:
    """For each document title: its story, assessment, decision and evidence rows."""
    documents = {row["id"]: row for row in table(engine, "source_documents")}
    stories = {row["document_id"]: row["story_id"] for row in table(engine, "story_documents")}
    assessments = {row["story_id"]: row for row in table(engine, "editorial_assessments")}
    decisions = {row["assessment_id"]: row for row in table(engine, "editorial_decisions")}
    evidence = table(engine, "evidence_items")
    found: dict[str, dict[str, Any]] = {}
    for document_id, document in documents.items():
        assessment = assessments.get(stories.get(document_id, -1))
        found[document["title"]] = {
            "document": document,
            "story_id": stories.get(document_id),
            "assessment": assessment,
            "decision": decisions.get(assessment["id"]) if assessment else None,
            "evidence": [
                e for e in evidence if assessment and e["assessment_id"] == assessment["id"]
            ],
        }
    return found


@pytest.fixture
def day(engine: Engine, config: ModelsConfig) -> tuple[ScriptedBackend, FakeTransport]:
    backend, transport = ScriptedBackend(), FakeTransport()
    run_day(engine, config, backend, transport)
    return backend, transport


# --- From recordings, a schema-valid briefing -------------------------------------------------


def test_recorded_fixtures_produce_a_schema_valid_briefing_with_no_network_or_key(
    engine: Engine, config: ModelsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    counts = run_day(engine, config, ReplayBackend(RECORDED), FakeTransport())
    assert counts["screen"]["screened"] == 9
    assert counts["assess"]["calls_without_result"] == 0  # every request found its recording
    content, created = briefing(engine)
    assert created is True
    assert list(VALIDATOR.iter_errors(content)) == []
    assert content["status"] == "ready"
    assert [story["headline"] for story in content["stories"]] == [
        "Library version 2 released",
        "A sound paper on retrieval",
        "Tokeniser throughput measured <b>on two machines</b>",
    ]
    assert [item["headline"] for item in content["watchlist"]] == [
        "A paper that claims a great deal",
        "A post that lives on another site",
        "An item known only by its headline",
    ]


def test_the_recordings_are_exactly_what_the_script_answers(
    engine: Engine, config: ModelsConfig
) -> None:
    # If a prompt, an output shape or the synthetic day changes, this fails until
    # tests/pipeline/make_recordings.py is run again and its output reviewed.
    backend = ScriptedBackend()
    run_day(engine, config, backend, FakeTransport())
    replay = ReplayBackend(RECORDED)
    assert len(replay) == len(backend.requests) == 9
    for request in backend.requests:
        assert replay.create(request) == scripted(request)
    for path in RECORDED.glob("*.json"):
        assert "Synthetic" in json.loads(path.read_text(encoding="utf-8"))["_note"]


def test_one_command_sequence_produces_a_briefing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sources.yaml").write_text(catalogue_yaml(), encoding="utf-8")
    real_models = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
    (config_dir / "models.yaml").write_bytes(real_models.read_bytes())
    monkeypatch.setenv("AI_BRIEFING_CONFIG", str(config_dir))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_BRIEFING_TIMEZONE", raising=False)
    transport = FakeTransport()
    monkeypatch.setattr(cli, "make_fetcher", lambda: make_fetcher(transport))
    db = ["--database", str(tmp_path / "data" / "briefing.sqlite3")]

    assert cli.main(["db", "upgrade", *db]) == 0
    assert cli.main(["collect", *db]) == 0
    assert cli.main(["process", "--replay", str(RECORDED), *db]) == 0
    capsys.readouterr()
    assert cli.main(["briefing", "generate", "--format", "json", *db]) == 0
    content = json.loads(capsys.readouterr().out)
    assert list(VALIDATOR.iter_errors(content)) == []
    assert len(content["stories"]) == 3
    assert len(content["watchlist"]) == 3
    assert cli.main(["briefing", "generate", *db]) == 0
    markdown = capsys.readouterr().out
    assert markdown.startswith("# AI Briefing: ")
    assert "## Library version 2 released" in markdown


def test_process_without_a_key_or_recordings_says_what_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AI_BRIEFING_ENV_FILE", str(tmp_path / "no-such.env"))
    assert cli.main(["process", "--database", str(tmp_path / "x.sqlite3")]) == 1
    error = capsys.readouterr().err
    assert "no API key" in error
    assert "ANTHROPIC_API_KEY" in error


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--date", "19/11/2026"], "not a date"),
        (["--timezone", "Mars/Olympus"], "unknown time zone"),
    ],
)
def test_a_bad_date_or_time_zone_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], arguments: list[str], message: str
) -> None:
    db = ["--database", str(tmp_path / "x.sqlite3")]
    assert cli.main(["briefing", "generate", *arguments, *db]) == 1
    assert message in capsys.readouterr().err


# --- Citations ----------------------------------------------------------------------------------


def test_an_assessment_citing_an_id_it_was_not_given_is_rejected(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    found = by_title(engine)["A paper assessed with an invented citation"]
    assert found["story_id"] is not None  # it passed screening and has a story
    assert found["assessment"] is None  # but its assessment was not stored
    with engine.connect() as connection:
        calls = connection.execute(
            select(schema.llm_calls.c.status, schema.llm_calls.c.purpose)
        ).all()
    # The call was paid for and is on record all the same.
    assert len([c for c in calls if c.purpose == "assessment"]) == 8
    content, _ = briefing(engine)
    assert "invented citation" not in json.dumps(content)


def test_a_quote_that_is_not_in_the_stored_text_is_marked_failed_and_gives_no_support(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    hype = by_title(engine)["A paper that claims a great deal"]
    assert [e["integrity_status"] for e in hype["evidence"]] == ["failed"]
    assert hype["assessment"]["suggested_class"] == "major"
    # With nothing verified behind it, the story cannot be more than watch.
    assert hype["decision"]["final_class"] == "watch"
    assert hype["decision"]["ceiling"] == "watch"
    assert json.loads(hype["decision"]["ceiling_reasons"]) == [policy.NO_VERIFIED_EVIDENCE]
    content, _ = briefing(engine)
    assert "A paper that claims a great deal" not in [s["headline"] for s in content["stories"]]
    assert "A paper that claims a great deal" in [w["headline"] for w in content["watchlist"]]


def test_verified_and_failed_quotes_are_kept_apart_on_one_story(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    vendor = by_title(engine)["Library version 2 released"]
    statuses = {e["quote"]: e["integrity_status"] for e in vendor["evidence"]}
    assert statuses == {
        "Today we are releasing version 2 of our library.": "verified",
        "Independent benchmarks confirm it is the fastest library.": "failed",
    }
    # Passing the integrity check says nothing about whether the claim is supported.
    assert {e["support_label"] for e in vendor["evidence"]} == {"unreviewed"}
    sound = by_title(engine)["A sound paper on retrieval"]
    assert [e["integrity_status"] for e in sound["evidence"]] == ["verified", "verified"]
    assert sound["decision"]["final_class"] == "practical"
    assert sound["decision"]["ceiling"] == "major"


def test_a_story_known_only_from_metadata_cannot_exceed_watch(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    notes = by_title(engine)["An item known only by its headline"]
    assert notes["assessment"]["suggested_class"] == "practical"
    assert notes["decision"]["final_class"] == "watch"
    assert set(json.loads(notes["decision"]["ceiling_reasons"])) == {
        policy.NO_VERIFIED_EVIDENCE,
        policy.METADATA_ONLY,
    }
    # Its source allows no quotations, so the one the model offered was not even kept.
    assert notes["evidence"] == []


def test_a_low_story_is_recorded_and_not_shown(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    low = by_title(engine)["[low] A minor note on formatting"]
    assert low["decision"]["final_class"] == "low"
    assert low["decision"]["eligible"] is False
    assert "[low]" not in json.dumps(briefing(engine)[0])


def test_a_briefing_item_traces_to_what_the_model_was_shown(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    briefing(engine)
    with engine.connect() as connection:
        item = repositories.get(connection, BriefingItem, 1)
        assert item is not None
        assert item.decision_id is not None
        decision = repositories.get(connection, EditorialDecision, item.decision_id)
        assert decision is not None
        assessment = repositories.get(connection, EditorialAssessment, decision.assessment_id)
        assert assessment is not None
        assert assessment.id is not None
        (shown,) = repositories.assessment_input_ids(connection, assessment.id)
        observation = repositories.get(connection, DocumentObservation, shown)
    assert item.text == "Library version 2 released"
    assert observation is not None
    assert observation.body_text == "Library version 2 released\n\n" + VENDOR_PAGE_TEXT
    assert assessment.prompt_hash == load("assessment").sha256
    assert assessment.rubric_version == RUBRIC_VERSION
    assert assessment.model_id == MODEL_ID
    assert decision.policy_version == policy.POLICY_VERSION


# --- What a reader is shown ---------------------------------------------------------------------


def test_every_url_in_the_briefing_is_a_stored_documents(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    content, _ = briefing(engine)
    stored = {row["canonical_url"] for row in table(engine, "source_documents")}
    in_json = [e["url"] for s in content["stories"] for e in s["evidence"]]
    in_json += [w["url"] for w in content["watchlist"]]
    assert in_json
    assert set(in_json) <= stored
    markdown = to_markdown(content)
    linked = re.findall(r"\]\(<([^>]+)>\)", markdown)
    assert sorted(linked) == sorted(in_json)
    # The model wrote an address into its summary. It is nowhere in the briefing.
    assert "evil.example.com" not in json.dumps(content)
    assert "evil.example.com" not in markdown
    assert "[link removed]" in json.dumps(content)


def test_source_and_model_text_is_rendered_as_inert_text(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    content, _ = briefing(engine)
    markdown = to_markdown(content)
    # The JSON carries the words as data; the consumer escapes them (RFC 8.3).
    assert "Tokeniser throughput measured <b>on two machines</b>" in json.dumps(content)
    # In Markdown nothing can act as markup: no tag, and no link the model wrote.
    assert "<b>" not in markdown
    assert "<script" not in markdown.lower()
    assert "&lt;b&gt;on two machines&lt;/b&gt;" in markdown
    assert "\\[Click here\\]" in markdown
    assert len(re.findall(r"\]\(<", markdown)) == 6  # three stories and three watch items


def test_uncertainty_reaches_the_reader(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    content, _ = briefing(engine)
    for story in content["stories"]:
        assert "Uncertainty: " in story["why_it_matters"]
    vendor = content["stories"][0]
    assert "the vendor's own and is not independently checked" in vendor["why_it_matters"]
    assert "Uncertainty:" in to_markdown(content)


# --- What the model is shown --------------------------------------------------------------------


def requests(backend: ScriptedBackend, kind: str) -> list[dict[str, Any]]:
    payloads = [json.loads(request.user) for request in backend.requests]
    return [payload for payload in payloads if kind in payload]


def test_text_is_sent_to_the_model_only_as_each_source_permits(
    day: tuple[ScriptedBackend, FakeTransport],
) -> None:
    backend, _ = day
    (screening,) = requests(backend, "items")
    seen = {item["title"]: item for item in screening["items"]}
    # Title and summary for the feed-summary source; title only for the others.
    assert "summary" in seen["A sound paper on retrieval"]
    assert set(seen["Library version 2 released"]) == {"id", "source", "title"}
    assert set(seen["An item known only by its headline"]) == {"id", "source", "title"}
    shown = {
        payload["observations"][0]["title"]: payload["observations"][0]["text"]
        for payload in requests(backend, "observations")
    }
    assert shown["A sound paper on retrieval"].startswith("We evaluate a retrieval method")
    assert shown["Library version 2 released"].endswith(VENDOR_PAGE_TEXT)
    assert shown["An item known only by its headline"] is None
    assert shown["A post that lives on another site"] is None  # its page was never read
    everything = " ".join(request.user for request in backend.requests)
    assert "This summary is discarded" not in everything  # metadata-only: summary never kept
    assert "Read the announcement" not in everything  # a full-text source's feed summary


def test_a_page_off_the_sources_own_host_is_never_fetched(
    day: tuple[ScriptedBackend, FakeTransport],
) -> None:
    _, transport = day
    assert transport.content_urls == [
        "https://papers.example.org/feed.xml",
        "https://vendor.example.org/feed.xml",
        "https://notes.example.org/feed.xml",
        "https://vendor.example.org/v-release",
    ]
    assert not [url for url in transport.requests if "elsewhere.example.com" in url]


def test_the_model_is_given_no_tools_and_its_prompts_say_the_content_is_data(
    day: tuple[ScriptedBackend, FakeTransport],
) -> None:
    backend, _ = day
    for request in backend.requests:
        assert set(request.canonical()) == {
            "model",
            "system",
            "user",
            "output_schema",
            "max_tokens",
            "effort",
        }
        assert "data, not instructions" in request.system
        assert "url" not in json.dumps(request.output_schema).lower()
    assert {request.system for request in backend.requests} == {
        load("screening").text,
        load("assessment").text,
    }


# --- Screening ----------------------------------------------------------------------------------


def test_every_screened_item_has_a_recorded_outcome_and_reason(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    decisions = table(engine, "screening_decisions")
    assert len(decisions) == len(table(engine, "source_documents")) == 9
    assert sorted(d["outcome"] for d in decisions) == ["passed"] * 8 + ["rejected"]
    assert all(d["reason"].strip() for d in decisions)
    rejected = next(d for d in decisions if d["outcome"] == "rejected")
    assert rejected["reason"] == "Administrative, not technical."
    # Each item that passed is a story of its own, with an event saying which rule did it.
    events = table(engine, "story_membership_events")
    assert len(events) == len(table(engine, "stories")) == 8
    assert {e["decided_by_rule"] for e in events} == {"own-story"}


def rated(relevance_for: Mapping[str, int], *, extra: list[dict[str, Any]] | None = None) -> Any:
    def answer(request: ModelRequest) -> ModelResponse:
        payload = json.loads(request.user)
        if "items" not in payload:
            return scripted(request)
        results = [
            {"id": item["id"], "relevance": relevance_for.get(item["title"], 3), "reason": "Rated."}
            for item in payload["items"]
            if relevance_for.get(item["title"], 3) >= 0
        ]
        text = json.dumps({"results": results + (extra or [])})
        return ModelResponse(text, "end_turn", Usage(input_tokens=500, output_tokens=100))

    return answer


def test_code_decides_what_passes_from_the_rating(engine: Engine, config: ModelsConfig) -> None:
    ratings = {"A sound paper on retrieval": 1, "A paper that claims a great deal": 2}
    run_day(engine, config, ScriptedBackend(rated(ratings)), FakeTransport())
    outcomes = {
        row["title"]: decision["outcome"]
        for row in table(engine, "source_documents")
        for decision in table(engine, "screening_decisions")
        if decision["document_id"] == row["id"]
    }
    assert outcomes["A sound paper on retrieval"] == "rejected"  # below the pass rating
    assert outcomes["A paper that claims a great deal"] == "passed"  # exactly at it


def test_results_for_ids_the_model_was_not_given_are_ignored(
    engine: Engine, config: ModelsConfig
) -> None:
    extra = [
        {"id": 424242, "relevance": 4, "reason": "An item nobody asked about."},
        {"id": 1, "relevance": 0, "reason": "A second answer for an item already answered."},
    ]
    counts = run_day(engine, config, ScriptedBackend(rated({}, extra=extra)), FakeTransport())
    assert counts["screen"]["screened"] == 9
    decisions = table(engine, "screening_decisions")
    assert 424242 not in {d["document_id"] for d in decisions}
    assert next(d for d in decisions if d["document_id"] == 1)["relevance"] == 3  # the first answer


def test_an_item_the_model_left_out_stays_unscreened_and_is_asked_about_again(
    engine: Engine, config: ModelsConfig
) -> None:
    skipped = {"A sound paper on retrieval": -1}  # left out of the answer
    counts = run_day(engine, config, ScriptedBackend(rated(skipped)), FakeTransport())
    assert counts["screen"]["unanswered"] == 1
    assert len(table(engine, "screening_decisions")) == 8
    again = ScriptedBackend()
    counts = run_day(engine, config, again, FakeTransport(), day="2026-11-20")
    assert counts["screen"]["screened"] == 1
    (screening,) = requests(again, "items")
    assert [item["title"] for item in screening["items"]] == ["A sound paper on retrieval"]


# --- Running twice ------------------------------------------------------------------------------


def test_running_the_days_jobs_twice_adds_no_rows_and_makes_no_model_calls(
    engine: Engine, config: ModelsConfig
) -> None:
    run_day(engine, config, ScriptedBackend(), FakeTransport())
    briefing(engine)
    before = row_counts(engine)
    spent = month_to_date(engine, NOW)
    again = ScriptedBackend()
    counts = run_day(engine, config, again, FakeTransport())
    content, created = briefing(engine)
    assert again.requests == []
    assert created is False
    assert row_counts(engine) == before
    assert month_to_date(engine, NOW) == spent
    assert counts["assess"] == {**counts["assess"], "assessed": 7}  # the first run's counts
    assert content["briefing_id"] == "b-2026-11-19-1"


def test_a_later_day_finds_nothing_left_to_do(engine: Engine, config: ModelsConfig) -> None:
    run_day(engine, config, ScriptedBackend(), FakeTransport())
    before = row_counts(engine)
    again = ScriptedBackend()
    counts = run_day(engine, config, again, FakeTransport(), day="2026-11-20")
    # Only the story whose assessment was rejected is tried again. Nothing else is
    # screened, fetched or assessed a second time.
    assert counts["screen"]["screened"] == 0
    assert counts["fetch-bodies"]["bodies_stored"] == 0
    assert len(again.requests) == 1
    assert "invented citation" in again.requests[0].user
    after = row_counts(engine)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {"job_runs", "llm_calls"}


def test_composing_twice_stores_one_version_and_a_change_stores_a_second(
    engine: Engine, config: ModelsConfig
) -> None:
    run_day(engine, config, ScriptedBackend(), FakeTransport())
    first, created = briefing(engine)
    same, created_again = briefing(engine, now=NOW.replace(hour=20))
    assert (created, created_again) == (True, False)
    assert same == first  # the stored version, with its original generated_at
    assert len(table(engine, "briefings")) == 1
    assert len(table(engine, "briefing_items")) == 6
    # A new decision under another policy version changes the day, so a second version
    # is stored and the first is left as it was.
    with engine.begin() as connection:
        decision = repositories.get(connection, EditorialDecision, 1)
        assert decision is not None
        repositories.add(
            connection,
            decision.model_copy(
                update={
                    "id": None,
                    "policy_version": "test",
                    "final_class": EditorialClass.LOW,
                    "eligible": False,
                }
            ),
        )
    second, created = briefing(engine, now=NOW.replace(hour=21))
    assert created is True
    assert second["briefing_id"] == "b-2026-11-19-2"
    versions = table(engine, "briefings")
    assert [row["version"] for row in versions] == [1, 2]
    assert json.loads(versions[0]["content"]) == first


# --- When calls fail ----------------------------------------------------------------------------


def test_one_failed_assessment_does_not_stop_the_others(
    engine: Engine, config: ModelsConfig
) -> None:
    def answer(request: ModelRequest) -> ModelResponse:
        if "sound paper" in request.user and "observations" in request.user:
            return ModelResponse("", "refusal", Usage(input_tokens=100, output_tokens=1))
        return scripted(request)

    counts = run_day(engine, config, ScriptedBackend(answer), FakeTransport())
    assert counts["assess"]["calls_without_result"] == 1
    assert counts["assess"]["assessed"] == 6
    content, _ = briefing(engine)
    assert "A sound paper on retrieval" not in json.dumps(content)
    assert content["status"] == "ready"


def test_a_spent_budget_leaves_items_unassessed_and_the_briefing_says_so(
    engine: Engine, config: ModelsConfig
) -> None:
    tight = config.model_copy(
        update={"budget": config.budget.model_copy(update={"daily_allowance": Decimal("0.0028")})}
    )
    backend = ScriptedBackend()
    counts = run_day(engine, tight, backend, FakeTransport())
    assert counts["screen"]["screened"] == 9  # the day's allowance covered screening
    assert 0 < counts["assess"]["assessed"] < 7  # and only some of the assessments
    assert counts["assess"]["calls_without_result"] == 1  # it stopped at the first refusal
    with engine.connect() as connection:
        statuses = connection.execute(select(schema.llm_calls.c.status)).scalars().all()
    assert statuses.count("budget_refused") == 1
    assert month_to_date(engine, NOW) <= Decimal("0.0028")
    content, _ = briefing(engine)
    assert content["status"] == "degraded"
    assert content["degraded_reasons"] == ["Budget: some items could not be assessed today."]
    assert list(VALIDATOR.iter_errors(content)) == []
    assert "> Note: Budget" in to_markdown(content)


def test_a_day_with_nothing_eligible_is_an_empty_briefing(engine: Engine) -> None:
    content, created = briefing(engine)
    assert created is True
    assert content["status"] == "empty"
    assert content["stories"] == content["watchlist"] == []
    assert list(VALIDATOR.iter_errors(content)) == []
    assert "Nothing to report today." in to_markdown(content)


def test_only_evidence_that_passed_the_check_counts(
    engine: Engine, day: tuple[ScriptedBackend, FakeTransport]
) -> None:
    evidence = table(engine, "evidence_items")
    assert {e["integrity_status"] for e in evidence} == {
        IntegrityStatus.VERIFIED.value,
        IntegrityStatus.FAILED.value,
    }
    assert len([e for e in evidence if e["integrity_status"] == "verified"]) == 5
    # Failed: the hype paper's, the vendor's unsupported one, and the off-site post's.
    assert len([e for e in evidence if e["integrity_status"] == "failed"]) == 3
    with engine.connect() as connection:
        database.settings(connection)  # the connection is the configured one


# --- What the model was actually given ----------------------------------------------------------


def test_a_quote_from_beyond_the_part_of_an_article_that_was_sent_is_not_verified(
    engine: Engine, config: ModelsConfig
) -> None:
    from ai_briefing.editorial import process as processing

    # A long article. The sentence the model will "quote" is real and is stored, but it
    # lies past the point where the text sent to the model was cut off.
    filler = "This sentence pads the article with ordinary words. " * 1_000
    tail = "Independent benchmarks confirm it is the fastest library."
    assert len(filler) > processing.MAX_TEXT_CHARS
    page = (
        "<html><body><article><p>Today we are releasing version 2 of our library.</p>"
        f"<p>{filler}</p><p>{tail}</p></article></body></html>"
    ).encode()
    transport = FakeTransport({"https://vendor.example.org/v-release": page})
    backend = ScriptedBackend()
    run_day(engine, config, backend, transport)
    vendor = by_title(engine)["Library version 2 released"]
    with engine.connect() as connection:
        stored = repositories.get(
            connection, DocumentObservation, vendor["evidence"][0]["observation_id"]
        )
    assert stored is not None
    assert stored.body_text is not None
    assert tail in stored.body_text  # the words are in the stored article
    sent = next(
        json.loads(request.user)["observations"][0]["text"]
        for request in backend.requests
        if "version 2 released" in request.user and "observations" in request.user
    )
    assert len(sent) == processing.MAX_TEXT_CHARS
    assert tail not in sent  # and were never sent to the model
    statuses = {e["quote"]: e["integrity_status"] for e in vendor["evidence"]}
    assert statuses == {
        "Today we are releasing version 2 of our library.": "verified",
        tail: "failed",
    }


def test_a_corrected_headline_is_assessed_again(engine: Engine, config: ModelsConfig) -> None:
    run_day(engine, config, ScriptedBackend(), FakeTransport())
    first = by_title(engine)["An item known only by its headline"]["assessment"]
    # The source corrects its headline. For a metadata-only source that is the whole input.
    with engine.begin() as connection:
        connection.execute(
            schema.source_documents.update()
            .where(schema.source_documents.c.title == "An item known only by its headline")
            .values(title="An item whose release was postponed")
        )
    again = ScriptedBackend()
    counts = run_day(engine, config, again, FakeTransport(), day="2026-11-20")
    assessed = [r for r in again.requests if "observations" in r.user]
    assert any("An item whose release was postponed" in r.user for r in assessed)
    assert counts["assess"]["assessed"] == 1
    assessments = [
        row
        for row in table(engine, "editorial_assessments")
        if row["story_id"] == first["story_id"]
    ]
    assert len(assessments) == 2  # the earlier assessment is kept; a new one is added
    assert assessments[0]["input_hash"] != assessments[1]["input_hash"]
    assert (
        json.loads(assessments[1]["draft_text"])["headline"]
        == "An item whose release was postponed"
    )


def test_the_input_hash_is_of_the_packet_the_model_was_sent(
    engine: Engine, config: ModelsConfig
) -> None:
    import hashlib

    backend = ScriptedBackend()
    run_day(engine, config, backend, FakeTransport())
    sent = {
        hashlib.sha256(request.user.encode("utf-8")).hexdigest()
        for request in backend.requests
        if "observations" in request.user
    }
    stored = {row["input_hash"] for row in table(engine, "editorial_assessments")}
    assert stored <= sent
    assert len(stored) == 7
