"""The retention purge and the tracer protocol (M1 issue 1.12; ADR-010, ADR-009).

Everything runs offline on the synthetic day.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from ai_briefing.briefings.export import export
from ai_briefing.domain.records import Source
from ai_briefing.llm.config import ModelsConfig
from ai_briefing.runtime import cli, tracing
from ai_briefing.runtime.daily import STAGES
from ai_briefing.storage.retention import body_retention, purge, purge_now, request_retention

from .conftest import (
    CATALOGUE,
    HASH,
    NOW,
    RECORDED,
    VENDOR,
    VENDOR_PAGE_TEXT,
    FakeTransport,
    ScriptedBackend,
    run_day,
)
from .test_daily_run import cli_day, day  # noqa: F401 - cli_day is a fixture
from .test_first_briefing import table

DAYS = timedelta(days=1)


def purged(
    engine: Engine,
    now: datetime,
    catalogue: tuple[Source, ...] = CATALOGUE,
    *,
    run_again: bool = True,
) -> Mapping[str, int]:
    return purge(
        engine,
        catalogue,
        day=now.date().isoformat(),
        application_version="0.0.0",
        configuration_hash=HASH,
        run_again=run_again,
        clock=lambda: now,
    ).counts


def history(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    """Everything stored, except the job records the purge itself adds."""
    names = (
        "source_documents",
        "document_observations",
        "screening_decisions",
        "stories",
        "story_membership_events",
        "editorial_assessments",
        "assessment_inputs",
        "evidence_items",
        "editorial_decisions",
        "llm_calls",
    )
    return {name: table(engine, name) for name in names}


@pytest.fixture
def a_day(engine: Engine, config: ModelsConfig) -> Engine:
    run_day(engine, config, ScriptedBackend(), FakeTransport())
    return engine


def bodies(engine: Engine) -> list[dict[str, Any]]:
    return [o for o in table(engine, "document_observations") if o["body_text"] is not None]


# --- What is purged, and when ------------------------------------------------------------------


def test_how_long_text_is_kept_comes_from_the_catalogue() -> None:
    assert body_retention(CATALOGUE) == {"vendor": 90}
    assert request_retention(CATALOGUE) == 90
    shorter = (
        *CATALOGUE[:1],
        VENDOR.model_copy(
            update={"retention_days": VENDOR.retention_days.model_copy(update={"body": 30})}
        ),
        *CATALOGUE[2:],
    )
    assert request_retention(shorter) == 30
    # With no source that keeps bodies, requests still go at ADR-010's limit.
    assert request_retention(()) == 90


def test_nothing_is_purged_inside_its_retention(a_day: Engine) -> None:
    before = history(a_day)
    assert len(bodies(a_day)) == 1
    counts = purged(a_day, NOW + 89 * DAYS)
    assert counts == {"bodies_purged": 0, "bodies_without_permission": 0, "requests_purged": 0}
    assert history(a_day) == before


def test_after_the_purge_no_old_body_or_request_remains_and_the_hashes_do(a_day: Engine) -> None:
    before = history(a_day)
    (held,) = bodies(a_day)
    assert VENDOR_PAGE_TEXT in held["body_text"]
    calls_before = table(a_day, "llm_calls")
    assert all(c["request_payload"] for c in calls_before)

    when = NOW + 91 * DAYS
    counts = purged(a_day, when)
    assert counts == {
        "bodies_purged": 1,
        "bodies_without_permission": 0,
        "requests_purged": len(calls_before),
    }
    after = history(a_day)
    # No body and no request payload is left, and each says when it went.
    assert bodies(a_day) == []
    observation = next(o for o in after["document_observations"] if o["id"] == held["id"])
    assert (observation["body_text"], observation["body_purged_at"]) == (None, when)
    assert observation["content_hash"] == held["content_hash"]
    for call, was in zip(after["llm_calls"], calls_before, strict=True):
        assert (call["request_payload"], call["request_purged_at"]) == (None, when)
        # The system's own answer, the request's hash and the cost are kept.
        assert call["response_payload"] == was["response_payload"]
        assert call["request_ref"] == was["request_ref"]
        assert call["estimated_cost_usd"] == was["estimated_cost_usd"]
    # An observation that never held a body is not marked as purged.
    others = [o for o in after["document_observations"] if o["id"] != held["id"]]
    assert all(o["body_purged_at"] is None for o in others)
    # Nothing else changed at all: metadata, summaries, hashes, evidence, decisions.
    for name in before:
        if name in ("document_observations", "llm_calls"):
            continue
        assert after[name] == before[name], name
    kept = ("id", "document_id", "retrieved_at", "fetch_status", "summary", "content_hash")
    assert [{k: o[k] for k in kept} for o in after["document_observations"]] == [
        {k: o[k] for k in kept} for o in before["document_observations"]
    ]
    assert any(o["summary"] for o in after["document_observations"])


def test_a_quotation_check_made_before_the_purge_can_still_be_audited(a_day: Engine) -> None:
    (held,) = bodies(a_day)
    evidence_before = [
        e for e in table(a_day, "evidence_items") if e["observation_id"] == held["id"]
    ]
    # The synthetic vendor story has one quotation the page holds and one it does not.
    assert sorted(e["integrity_status"] for e in evidence_before) == ["failed", "verified"]
    purged(a_day, NOW + 91 * DAYS)
    evidence_after = [
        e for e in table(a_day, "evidence_items") if e["observation_id"] == held["id"]
    ]
    assert evidence_after == evidence_before
    verified = next(e for e in evidence_after if e["integrity_status"] == "verified")
    # What an audit needs is all still there: the words, the verdict, which observation
    # they were checked against, and that observation's hash and purge time.
    assert verified["quote"] in VENDOR_PAGE_TEXT
    observation = next(o for o in table(a_day, "document_observations") if o["id"] == held["id"])
    assert observation["content_hash"] == held["content_hash"]
    assert observation["body_purged_at"] is not None
    assert observation["body_text"] is None


def test_the_purge_is_idempotent(a_day: Engine) -> None:
    when = NOW + 91 * DAYS
    first = purged(a_day, when)
    assert first["bodies_purged"] == 1
    once = history(a_day)
    again = purged(a_day, when + DAYS)
    assert again == {"bodies_purged": 0, "bodies_without_permission": 0, "requests_purged": 0}
    # The time of the purge is the first one: nothing is stamped twice.
    assert history(a_day) == once
    assert len([j for j in table(a_day, "job_runs") if j["job"] == "purge"]) == 2


def test_the_purge_is_once_a_day_as_a_stage_and_whenever_asked_as_a_command(a_day: Engine) -> None:
    when = NOW + 91 * DAYS
    assert purged(a_day, when, run_again=False)["bodies_purged"] == 1
    runs = [j for j in table(a_day, "job_runs") if j["job"] == "purge"]
    assert [(j["idempotency_key"], j["status"]) for j in runs] == [
        (f"purge:{when.date().isoformat()}", "succeeded")
    ]
    assert json.loads(runs[0]["counts"])["requests_purged"] > 0
    # The same day again, as the daily run would: nothing is done and no row is added.
    purged(a_day, when, run_again=False)
    assert len([j for j in table(a_day, "job_runs") if j["job"] == "purge"]) == 1


def test_a_shorter_retention_is_honoured(a_day: Engine) -> None:
    month = VENDOR.model_copy(
        update={"retention_days": VENDOR.retention_days.model_copy(update={"body": 30})}
    )
    catalogue = (CATALOGUE[0], month, CATALOGUE[2])
    assert purged(a_day, NOW + 29 * DAYS, catalogue)["bodies_purged"] == 0
    counts = purged(a_day, NOW + 31 * DAYS, catalogue)
    assert counts["bodies_purged"] == 1
    assert counts["requests_purged"] == len(table(a_day, "llm_calls"))


def test_text_from_a_source_that_no_longer_permits_it_is_purged_at_once(a_day: Engine) -> None:
    without_vendor = tuple(s for s in CATALOGUE if s.id != "vendor")
    counts = purged(a_day, NOW + timedelta(minutes=1), without_vendor)
    assert counts["bodies_purged"] == counts["bodies_without_permission"] == 1
    assert counts["requests_purged"] == 0  # requests are still inside their 90 days
    assert bodies(a_day) == []


def test_the_database_allows_the_purge_and_nothing_else(a_day: Engine) -> None:
    (held,) = bodies(a_day)
    for statement in (
        "UPDATE document_observations SET summary = 'changed'",
        "UPDATE document_observations SET body_text = 'rewritten'",
        "UPDATE document_observations SET body_text = NULL",  # no purge time recorded
        "DELETE FROM document_observations",
        "UPDATE llm_calls SET request_payload = NULL, tokens_in = 0, request_purged_at = 'x'",
        "DELETE FROM llm_calls",
    ):
        with pytest.raises(IntegrityError), a_day.begin() as connection:
            connection.execute(text(statement))
    assert bodies(a_day) == [held]


def test_a_failed_purge_changes_nothing(a_day: Engine) -> None:
    before = history(a_day)

    class StopError(Exception):
        pass

    def attempt() -> None:
        with a_day.begin() as connection:
            purge_now(connection, CATALOGUE, NOW + 91 * DAYS)
            raise StopError

    with pytest.raises(StopError):
        attempt()
    assert history(a_day) == before


# --- Part of the daily run ---------------------------------------------------------------------


def test_the_purge_is_the_last_stage_of_the_day(engine: Engine, config: ModelsConfig) -> None:
    assert STAGES[-1] == "purge"
    result, lines = day(engine, config)
    assert result.ok is True
    assert result.stages["purge"] == {
        "bodies_purged": 0,
        "bodies_without_permission": 0,
        "requests_purged": 0,
    }
    started = [line["stage"] for line in lines if line["event"] == "stage.start"]
    assert started[-1] == "purge"
    # A day 91 days on purges what the first day stored, as part of its own run.
    later = NOW + 91 * DAYS
    result, _ = day(engine, config, local_date=later.date(), now=later)
    assert result.ok is True
    assert result.stages["purge"]["bodies_purged"] == 1
    assert result.stages["purge"]["requests_purged"] >= 9
    assert bodies(engine) == []


def test_the_purge_command_reports_what_it_removed(
    cli_day: list[str],  # noqa: F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["retention", "purge", *cli_day]) == 1
    assert "db upgrade" in capsys.readouterr().err
    cli.main(["db", "upgrade", *cli_day])
    cli.main(["run", "--replay", str(RECORDED), *cli_day])
    capsys.readouterr()
    assert cli.main(["retention", "purge", *cli_day]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "bodies_purged": 0,
        "bodies_without_permission": 0,
        "requests_purged": 0,
    }
    monkeypatch.setattr(cli, "current_time", lambda: NOW + 91 * DAYS)
    assert cli.main(["retention", "purge", *cli_day]) == 0
    first = json.loads(capsys.readouterr().out)
    assert (first["bodies_purged"], first["requests_purged"] > 0) == (1, True)
    # And again, the same day: the command runs, and finds nothing left.
    assert cli.main(["retention", "purge", *cli_day]) == 0
    assert json.loads(capsys.readouterr().out)["bodies_purged"] == 0


# --- The tracer ----------------------------------------------------------------------------------


class Recording:
    """A tracer that writes down every span and how it ended."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, Any], str]] = []

    def span(
        self, name: str, attributes: Mapping[str, tracing.Attribute]
    ) -> AbstractContextManager[object]:
        @contextmanager
        def recorded() -> Iterator[None]:
            try:
                yield
            except BaseException as error:
                self.spans.append((name, dict(attributes), type(error).__name__))
                raise
            self.spans.append((name, dict(attributes), "ok"))

        return recorded()


class Broken:
    """A tracer whose every operation fails, as with a tracking server that is down."""

    def __init__(self, where: str) -> None:
        self.where = where

    def span(
        self, name: str, attributes: Mapping[str, tracing.Attribute]
    ) -> AbstractContextManager[object]:
        if self.where == "span":
            raise ConnectionError("tracking server unreachable")
        broken = self

        class Manager:
            def __enter__(self) -> None:
                if broken.where == "enter":
                    raise ConnectionError("tracking server unreachable")

            def __exit__(self, *_: object) -> bool:
                if broken.where == "exit":
                    raise ConnectionError("tracking server unreachable")
                return broken.where == "swallow"  # tries to hide the work's own error

        return Manager()


@pytest.fixture
def no_tracer() -> Iterator[None]:
    yield
    tracing.install(None)


def test_the_default_tracer_does_nothing_and_every_job_completes_with_it(
    engine: Engine, config: ModelsConfig
) -> None:
    assert isinstance(tracing.installed(), tracing.NoopTracer)
    result, _ = day(engine, config)
    assert result.ok is True
    assert list(result.stages) == list(STAGES)
    assert {j["status"] for j in table(engine, "job_runs")} == {"succeeded"}
    with tracing.span("anything", job="x"):
        pass


def test_an_installed_tracer_sees_job_roots_model_calls_and_the_export(
    engine: Engine, config: ModelsConfig, tmp_path: Path, no_tracer: None
) -> None:
    recorder = Recording()
    tracing.install(recorder)
    result, _ = day(engine, config)
    assert result.ok is True
    jobs = [attributes["job"] for name, attributes, _ in recorder.spans if name == "job"]
    assert jobs == list(STAGES)
    calls = [attributes for name, attributes, _ in recorder.spans if name == "model_call"]
    assert len(calls) == len(table(engine, "llm_calls"))
    assert {c["task"] for c in calls} == {"screening", "assessment", "concept_note"}
    assert all(end == "ok" for _, _, end in recorder.spans)
    (briefing,) = table(engine, "briefings")
    export(json.loads(briefing["content"]), tmp_path / "out")
    assert recorder.spans[-1] == ("export", {"briefing_id": "b-2026-11-19-1"}, "ok")
    # A span carries identifiers and counts, never text from a source or the model.
    for _, attributes, _ in recorder.spans:
        assert set(attributes) <= {"job", "job_run_id", "task", "model", "briefing_id"}
        for value in attributes.values():
            assert isinstance(value, int) or len(str(value)) <= tracing.MAX_ATTRIBUTE_CHARS


@pytest.mark.parametrize("where", ["span", "enter", "exit"])
def test_a_tracer_that_fails_never_fails_a_job(
    engine: Engine, config: ModelsConfig, where: str, no_tracer: None
) -> None:
    tracing.install(Broken(where))
    result, _ = day(engine, config)
    assert result.ok is True
    assert result.briefing_status == "ready"
    assert {j["status"] for j in table(engine, "job_runs")} == {"succeeded"}


@pytest.mark.parametrize("where", ["exit", "swallow"])
def test_a_tracer_cannot_hide_or_replace_an_error_in_the_work(where: str, no_tracer: None) -> None:
    tracing.install(Broken(where))
    with pytest.raises(ValueError, match="the work failed"), tracing.span("job"):
        raise ValueError("the work failed")


def test_a_job_that_fails_is_seen_to_fail_and_still_fails(
    engine: Engine, config: ModelsConfig, no_tracer: None
) -> None:
    recorder = Recording()
    tracing.install(recorder)

    def broken(request: Any) -> Any:
        raise RuntimeError("down")

    result, _ = day(engine, config, ScriptedBackend(broken))
    assert set(result.failed) == {"screen"}
    ends = {attributes["job"]: end for name, attributes, end in recorder.spans if name == "job"}
    assert ends["screen"] == "RuntimeError"
    assert ends["collect"] == "ok"


def test_a_long_attribute_is_cut_short(no_tracer: None) -> None:
    recorder = Recording()
    tracing.install(recorder)
    with tracing.span("job", job="x" * 500, job_run_id=7):
        pass
    ((_, attributes, _),) = recorder.spans
    assert (len(attributes["job"]), attributes["job_run_id"]) == (tracing.MAX_ATTRIBUTE_CHARS, 7)
