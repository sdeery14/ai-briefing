"""The day as one command, and the commands for looking at its state: ``run``, ``doctor``
and ``budget status`` (issue 1.7's done-when; RFC §3.5, §7.2, §9.3).
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from ai_briefing.llm.backends import ModelRequest, ModelResponse, ReplayBackend
from ai_briefing.llm.budget import current_spend, month_to_date, spend_by_task
from ai_briefing.llm.client import ModelClient
from ai_briefing.llm.config import ModelsConfig
from ai_briefing.llm.pricing import Usage
from ai_briefing.runtime import cli, doctor
from ai_briefing.runtime.daily import STAGES, DayResult, run_day
from ai_briefing.runtime.logs import MAX_STRING, JsonLog
from ai_briefing.sources.network import FetchError
from ai_briefing.storage import schema

from .conftest import (
    CATALOGUE,
    HASH,
    HOSTILE,
    MODEL_ID,
    NOW,
    RECORDED,
    SOUND,
    VENDOR_PAGE_TEXT,
    FakeTransport,
    ScriptedBackend,
    catalogue_yaml,
    make_fetcher,
    scripted,
)

DAY = date(2026, 11, 19)
FAKE_KEY = "sk-ant-test-0000-not-a-real-key"


def day(
    engine: Engine,
    config: ModelsConfig,
    backend: Any = None,
    transport: FakeTransport | None = None,
    *,
    local_date: date = DAY,
    now: datetime = NOW,
) -> tuple[DayResult, list[dict[str, Any]]]:
    """Run a day and return its result with the log lines it wrote."""
    stream = io.StringIO()
    backend = backend or ScriptedBackend()
    result = run_day(
        engine,
        CATALOGUE,
        ModelClient(engine=engine, config=config, backend=backend, clock=lambda: now),
        make_fetcher(transport or FakeTransport()),
        model_id=MODEL_ID,
        local_date=local_date,
        timezone="UTC",
        application_version="0.0.0",
        configuration_hash=HASH,
        log=JsonLog(stream, clock=lambda: now),
        clock=lambda: now,
    )
    return result, [json.loads(line) for line in stream.getvalue().splitlines()]


def row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            name: connection.execute(select(func.count()).select_from(table)).scalar_one()
            for name, table in schema.metadata.tables.items()
        }


# --- One command for the day ----------------------------------------------------------------------


def test_the_day_runs_every_stage_in_order_and_produces_the_briefing(
    engine: Engine, config: ModelsConfig
) -> None:
    result, lines = day(engine, config)
    assert result.ok is True
    assert list(result.stages) == list(STAGES)
    assert result.stages["collect"]["documents_added"] == 9
    assert result.stages["screen"]["passed"] == 8
    assert result.stages["fetch-bodies"]["bodies_stored"] == 1
    assert result.stages["assess"]["assessed"] == 7
    assert result.stages["briefing"] == {"stories": 3, "watchlist": 3, "version": 1}
    assert (result.briefing_id, result.briefing_status) == ("b-2026-11-19-1", "ready")
    started = [line["stage"] for line in lines if line["event"] == "stage.start"]
    assert started == list(STAGES)
    assert lines[0]["event"] == "day.start"
    assert lines[-1] == {
        "ts": "2026-11-19T11:15:00Z",
        "event": "day.done",
        "day": "2026-11-19",
        "ok": True,
        "failed": None,
        "briefing_id": "b-2026-11-19-1",
        "briefing_status": "ready",
    }


def test_each_stage_is_a_recorded_job_run(engine: Engine, config: ModelsConfig) -> None:
    day(engine, config)
    with engine.connect() as connection:
        runs = connection.execute(
            select(
                schema.job_runs.c.job, schema.job_runs.c.idempotency_key, schema.job_runs.c.status
            )
        ).all()
    assert [(r.job, r.idempotency_key, r.status) for r in runs] == [
        ("collect", "collect:2026-11-19", "succeeded"),
        ("screen", "screen:2026-11-19", "succeeded"),
        ("fetch-bodies", "fetch-bodies:2026-11-19", "succeeded"),
        ("assess", "assess:2026-11-19", "succeeded"),
        ("briefing", "briefing:2026-11-19", "succeeded"),
        ("purge", "purge:2026-11-19", "succeeded"),
    ]


def test_running_the_day_again_adds_no_rows(engine: Engine, config: ModelsConfig) -> None:
    day(engine, config)
    before = row_counts(engine)
    spent = month_to_date(engine, NOW)
    backend, transport = ScriptedBackend(), FakeTransport()
    result, lines = day(engine, config, backend, transport)
    assert result.ok is True
    assert row_counts(engine) == before
    assert month_to_date(engine, NOW) == spent
    assert backend.requests == []  # no model call
    assert transport.requests == []  # and no fetch
    assert result.skipped == list(STAGES)
    assert result.briefing_id == "b-2026-11-19-1"
    done = {line["stage"]: line["ran"] for line in lines if line["event"] == "stage.done"}
    assert done == dict.fromkeys(STAGES, False)


def test_the_next_day_is_a_new_run(engine: Engine, config: ModelsConfig) -> None:
    day(engine, config)
    tomorrow = NOW + timedelta(days=1)
    result, _ = day(engine, config, local_date=DAY + timedelta(days=1), now=tomorrow)
    assert result.ok is True
    assert result.skipped == []
    # Nothing new was published, so nothing new was stored or screened.
    assert result.stages["collect"]["documents_added"] == 0
    assert result.stages["screen"]["screened"] == 0


# --- A failing stage ------------------------------------------------------------------------------


class Unreachable(FakeTransport):
    def send(self, request: Any) -> Any:
        raise FetchError("the network is down")


def test_a_failed_collection_is_per_source_and_the_day_still_succeeds(
    engine: Engine, config: ModelsConfig
) -> None:
    # Every source failing is not a failed stage: collection records each one and goes on.
    result, _ = day(engine, config, transport=Unreachable())
    assert result.ok is True
    assert result.stages["collect"]["sources_failed"] == 3
    assert result.briefing_status == "empty"


def test_a_stage_that_fails_is_recorded_and_the_later_stages_still_run(
    engine: Engine, config: ModelsConfig
) -> None:
    def broken(request: ModelRequest) -> ModelResponse:
        if "items" in request.user:
            raise RuntimeError(f"an unexpected failure quoting the source: {SOUND}")
        return scripted(request)

    result, lines = day(engine, config, ScriptedBackend(broken))
    assert result.ok is False
    assert result.failed == {"screen": "RuntimeError"}
    # The stages after it ran, on what was already in the database.
    assert set(result.stages) == {"collect", "fetch-bodies", "assess", "briefing", "purge"}
    assert result.briefing_status == "empty"
    with engine.connect() as connection:
        failed = connection.execute(
            select(schema.job_runs.c.status, schema.job_runs.c.error).where(
                schema.job_runs.c.job == "screen"
            )
        ).one()
    assert failed.status == "failed"
    assert failed.error.startswith("RuntimeError")
    with engine.connect() as connection:
        keys = (
            connection.execute(
                select(schema.job_runs.c.idempotency_key).order_by(schema.job_runs.c.id)
            )
            .scalars()
            .all()
        )
    # The stages that ran after the failure are recorded as partial, not as the day's run.
    assert keys == [
        "collect:2026-11-19",
        "screen:2026-11-19",
        "fetch-bodies:2026-11-19:after-failure",
        "assess:2026-11-19:after-failure",
        "briefing:2026-11-19",
        # The purge depends on no earlier stage, so it is the day's run either way.
        "purge:2026-11-19",
    ]
    events = [(line["event"], line.get("stage")) for line in lines]
    assert ("stage.failed", "screen") in events
    assert events[-1][0] == "day.done"
    assert lines[-1]["ok"] is False
    assert lines[-1]["failed"] == "screen"


def test_a_stage_that_failed_can_be_run_again_the_same_day(
    engine: Engine, config: ModelsConfig
) -> None:
    def broken(request: ModelRequest) -> ModelResponse:
        raise RuntimeError("down")

    first, _ = day(engine, config, ScriptedBackend(broken))
    assert set(first.failed) == {"screen"}
    second, _ = day(engine, config)
    assert second.ok is True
    # Only collection had truly run. The stages after the failure were recorded as
    # partial runs, so now they run properly. The purge depends on none of them and had
    # run too.
    assert second.skipped == ["collect", "purge"]
    assert second.stages["fetch-bodies"]["bodies_stored"] == 1
    assert second.stages["screen"]["passed"] == 8
    assert second.stages["assess"]["assessed"] == 7
    assert second.briefing_status == "ready"


# --- Logs -----------------------------------------------------------------------------------------


def test_log_lines_are_json_and_hold_no_article_text_model_text_or_key(
    engine: Engine, config: ModelsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)

    def broken(request: ModelRequest) -> ModelResponse:
        if "observations" in request.user and "sound paper" in request.user:
            raise RuntimeError(f"failure quoting {SOUND} and {FAKE_KEY}")
        return scripted(request)

    stream = io.StringIO()
    run_day(
        engine,
        CATALOGUE,
        ModelClient(engine=engine, config=config, backend=ScriptedBackend(broken)),
        make_fetcher(FakeTransport()),
        model_id=MODEL_ID,
        local_date=DAY,
        timezone="UTC",
        application_version="0.0.0",
        configuration_hash=HASH,
        log=JsonLog(stream),
        clock=lambda: NOW,
    )
    text = stream.getvalue()
    lines = text.splitlines()
    assert len(lines) == 14  # day.start, a start and an end for each of six stages, day.done
    for line in lines:
        record = json.loads(line)
        assert {"ts", "event"} <= set(record)
        for value in record.values():
            assert isinstance(value, str | int | float | bool | dict | type(None))
    for forbidden in (SOUND, HOSTILE, VENDOR_PAGE_TEXT, FAKE_KEY, "synthetic summary", "sk-ant-"):
        assert forbidden not in text
    assert "RuntimeError" in text  # the kind of failure is logged; its message is not


def test_a_log_value_cannot_carry_more_than_a_short_string() -> None:
    stream = io.StringIO()
    log = JsonLog(stream, clock=lambda: NOW)
    article = "An article. " * 500
    log.event(
        "test",
        text=article,
        counts={"added": 3, "note": article},
        nested={"a": {"b": article}},
        things=[article],
        number=7,
        flag=True,
        nothing=None,
    )
    record = json.loads(stream.getvalue())
    assert len(record["text"]) == MAX_STRING
    assert len(record["counts"]["note"]) == MAX_STRING
    assert record["counts"]["added"] == 3
    # Anything that is not a number, a boolean or a mapping of them becomes a short string.
    assert isinstance(record["nested"]["a"], str)
    assert isinstance(record["things"], str)
    assert len(record["things"]) <= MAX_STRING
    assert (record["number"], record["flag"], record["nothing"]) == (7, True, None)
    assert stream.getvalue().count("\n") == 1


# --- budget status --------------------------------------------------------------------------------


def test_budget_status_equals_the_sum_of_recorded_calls_including_refused_and_failed(
    engine: Engine, config: ModelsConfig
) -> None:
    def mixed(request: ModelRequest) -> ModelResponse:
        if "observations" in request.user and "sound paper" in request.user:
            return ModelResponse("", "refusal", Usage(input_tokens=400, output_tokens=2))
        if "observations" in request.user and "great deal" in request.user:
            return ModelResponse(
                '{"not": "the shape"}', "end_turn", Usage(input_tokens=400, output_tokens=9)
            )
        return scripted(request)

    tight = config.model_copy(
        update={"budget": config.budget.model_copy(update={"daily_allowance": Decimal("0.02")})}
    )
    day(engine, tight, ScriptedBackend(mixed))
    with engine.connect() as connection:
        calls = connection.execute(
            select(
                schema.llm_calls.c.status,
                schema.llm_calls.c.purpose,
                schema.llm_calls.c.estimated_cost_usd,
            )
        ).all()
    statuses = {call.status for call in calls}
    assert {"succeeded", "refused", "failed"} <= statuses
    total = sum((call.estimated_cost_usd for call in calls), Decimal(0))
    tasks = spend_by_task(engine, NOW)
    assert sum((t.cost for t in tasks), Decimal(0)) == total == month_to_date(engine, NOW)
    assert sum(t.calls for t in tasks) == len(calls)  # every call, whatever its outcome
    # The concept-note question is a task of its own since issue 1.11.
    assert [t.task for t in tasks] == ["assessment", "concept_note", "screening"]
    spend = current_spend(engine, tight.budget, NOW)
    assert spend.month_to_date == total
    assert spend.left_this_month == Decimal("15.00") - total


@pytest.fixture
def cli_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A synthetic configuration and fetcher for commands run through ``cli.main``."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sources.yaml").write_text(catalogue_yaml(), encoding="utf-8")
    real = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
    (config_dir / "models.yaml").write_bytes(real.read_bytes())
    monkeypatch.setenv("AI_BRIEFING_CONFIG", str(config_dir))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_BRIEFING_TIMEZONE", raising=False)
    monkeypatch.setattr(cli, "make_fetcher", lambda: make_fetcher(FakeTransport()))
    # The synthetic feeds are dated; the commands run as if it were that day.
    monkeypatch.setattr(cli, "current_time", lambda: NOW)
    return ["--database", str(tmp_path / "data" / "briefing.sqlite3")]


def test_the_run_command_is_the_whole_day_and_reports_it(
    cli_day: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["db", "upgrade", *cli_day]) == 0
    capsys.readouterr()
    assert cli.main(["run", "--replay", str(RECORDED), *cli_day]) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["ok"] is True
    assert summary["briefing_status"] == "ready"
    assert summary["stages"]["briefing"]["stories"] == 3
    # The log goes to standard error, one JSON object per line.
    assert [json.loads(line)["event"] for line in captured.err.splitlines()][-1] == "day.done"
    # Again: nothing to do, and still a success.
    assert cli.main(["run", "--replay", str(RECORDED), *cli_day]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["already_run"] == list(STAGES)
    assert again["briefing_id"] == summary["briefing_id"]


def test_the_run_command_exits_nonzero_when_a_stage_failed(
    cli_day: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["db", "upgrade", *cli_day])
    bad = tmp_path / "bad-recordings"
    bad.mkdir()
    (bad / "broken.json").write_text("{ not json", encoding="utf-8")
    # Recordings that cannot be read are reported before anything runs.
    assert cli.main(["run", "--replay", str(bad), *cli_day]) == 1
    capsys.readouterr()
    empty = tmp_path / "no-recordings"
    empty.mkdir()
    # With no recordings every model call fails, which is a result and not a failed stage.
    assert cli.main(["run", "--replay", str(empty), *cli_day]) == 0
    assert json.loads(capsys.readouterr().out)["briefing_status"] == "empty"


def test_the_budget_status_command_agrees_with_the_recorded_calls(
    cli_day: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["db", "upgrade", *cli_day])
    cli.main(["run", "--replay", str(RECORDED), *cli_day])
    capsys.readouterr()
    assert cli.main(["budget", "status", "--format", "json", *cli_day]) == 0
    status = json.loads(capsys.readouterr().out)
    assert Decimal(status["monthly_limit"]) == Decimal("15")
    tasks = {t["task"]: t for t in status["tasks"]}
    assert set(tasks) == {"assessment", "concept_note", "screening"}
    assert tasks["concept_note"]["calls"] == 1
    assert tasks["assessment"]["calls"] == 8
    assert tasks["screening"]["calls"] == 1
    total = sum((Decimal(t["cost"]) for t in status["tasks"]), Decimal(0))
    assert Decimal(status["month_to_date"]) == total > 0
    assert Decimal(status["left_this_month"]) == Decimal("15.00") - total
    assert cli.main(["budget", "status", *cli_day]) == 0
    text = capsys.readouterr().out
    assert "of 15.00 USD spent" in text
    assert "assessment" in text


def test_budget_status_before_any_call_shows_nothing_spent(
    cli_day: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["db", "upgrade", *cli_day])
    capsys.readouterr()
    assert cli.main(["budget", "status", *cli_day]) == 0
    text = capsys.readouterr().out
    assert "0.0000 of 15.00 USD spent" in text
    assert "(no model calls recorded this month)" in text


# --- doctor ---------------------------------------------------------------------------------------


def statuses(checks: list[doctor.Check]) -> dict[str, str]:
    return {check.name: check.status for check in checks}


def test_doctor_reports_a_healthy_system_after_a_day(engine: Engine, config: ModelsConfig) -> None:
    day(engine, config)
    checks = [
        *doctor.check_sources(engine, CATALOGUE, NOW),
        *doctor.check_last_runs(engine),
        doctor.check_budget(engine, config.budget, NOW),
    ]
    assert set(statuses(checks).values()) == {doctor.OK}
    assert set(statuses(checks)) == {
        "source papers",
        "source vendor",
        "source notes",
        "job collect",
        "job screen",
        "job fetch-bodies",
        "job assess",
        "job briefing",
        "job purge",
        "budget",
    }
    assert doctor.worst(checks) == doctor.OK


def test_doctor_warns_about_a_failing_or_stale_source(engine: Engine, config: ModelsConfig) -> None:
    day(engine, config)
    with engine.begin() as connection:
        connection.execute(
            schema.sources.update()
            .where(schema.sources.c.id == "papers")
            .values(consecutive_failures=3)
        )
    found = statuses(doctor.check_sources(engine, CATALOGUE, NOW))
    assert found["source papers"] == doctor.WARN
    assert found["source vendor"] == doctor.OK
    week_later = NOW + timedelta(days=7)
    assert set(statuses(doctor.check_sources(engine, CATALOGUE, week_later)).values()) == {
        doctor.WARN
    }


def test_doctor_reports_a_failed_job_by_its_kind_and_not_its_message(
    engine: Engine, config: ModelsConfig
) -> None:
    def broken(request: ModelRequest) -> ModelResponse:
        raise RuntimeError(f"quoting the source: {SOUND}")

    day(engine, config, ScriptedBackend(broken))
    checks = doctor.check_last_runs(engine)
    screen = next(check for check in checks if check.name == "job screen")
    assert screen.status == doctor.FAIL
    assert "(RuntimeError)" in screen.detail
    assert SOUND not in doctor.render(checks)
    assert doctor.worst(checks) == doctor.FAIL


def test_doctor_reports_the_budget(engine: Engine, config: ModelsConfig) -> None:
    assert doctor.check_budget(engine, config.budget, NOW).status == doctor.OK
    used_today = config.budget.model_copy(update={"daily_allowance": Decimal(0)})
    assert doctor.check_budget(engine, used_today, NOW).status == doctor.WARN
    spent = config.budget.model_copy(update={"monthly_limit": Decimal(0)})
    assert doctor.check_budget(engine, spent, NOW).status == doctor.FAIL


def test_doctor_checks_the_database_and_the_disk(tmp_path: Path, engine: Engine) -> None:
    missing, usable = doctor.check_database(tmp_path / "absent.sqlite3")
    assert (missing.status, usable) == (doctor.FAIL, False)
    assert "db upgrade" in missing.detail
    path = Path(str(engine.url.database))
    present, usable = doctor.check_database(path)
    assert (present.status, usable) == (doctor.OK, True)
    assert doctor.check_disk(path, free=lambda _folder: 50_000_000_000).status == doctor.OK
    low = doctor.check_disk(path, free=lambda _folder: 200_000_000)
    assert (low.status, "0.2 GB free" in low.detail) == (doctor.WARN, True)


def test_the_doctor_command_passes_after_a_day_and_fails_without_a_database(
    cli_day: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["doctor", *cli_day]) == 1  # no database yet
    out = capsys.readouterr().out
    assert "fail  database" in out
    assert "ok    catalogue" in out
    cli.main(["db", "upgrade", *cli_day])
    cli.main(["run", "--replay", str(RECORDED), *cli_day])
    capsys.readouterr()
    assert cli.main(["doctor", *cli_day]) == 0
    out = capsys.readouterr().out
    for name in (
        "catalogue",
        "models",
        "database",
        "disk",
        "source papers",
        "job assess",
        "budget",
    ):
        assert name in out
    assert not [line for line in out.splitlines() if line.startswith("fail")]
    assert "2026-11-19" in out


def test_replay_needs_no_key_and_a_live_run_without_one_says_so(
    cli_day: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(["db", "upgrade", *cli_day])
    monkeypatch.setenv("AI_BRIEFING_ENV_FILE", str(tmp_path / "no-such.env"))
    capsys.readouterr()
    assert cli.main(["run", *cli_day]) == 1
    assert "no API key" in capsys.readouterr().err
    assert len(ReplayBackend(RECORDED)) == 10  # nine in processing, and the concept question


# --- The briefing stage is a job ------------------------------------------------------------------


def briefing_run(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(select(schema.job_runs).where(schema.job_runs.c.job == "briefing"))
            .mappings()
            .one()
        )
    return dict(row)


def test_composing_is_recorded_with_its_counts_and_the_version_that_ran(
    engine: Engine, config: ModelsConfig
) -> None:
    day(engine, config)
    run = briefing_run(engine)
    assert run["status"] == "succeeded"
    assert json.loads(run["counts"]) == {"stories": 3, "watchlist": 3, "version": 1}
    assert run["application_version"] == "0.0.0"
    assert run["configuration_hash"] == HASH


def test_composing_again_reuses_its_record_and_stores_no_second_version(
    engine: Engine, config: ModelsConfig
) -> None:
    day(engine, config)
    before = row_counts(engine)
    later = NOW + timedelta(hours=5)
    result, _ = day(engine, config, now=later)
    assert row_counts(engine) == before  # one job record for the day, one briefing version
    assert result.briefing_id == "b-2026-11-19-1"
    assert briefing_run(engine)["started_at"] == later  # the record shows the latest attempt


def test_a_failed_composition_is_recorded_and_doctor_reports_it(
    engine: Engine, config: ModelsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_briefing.briefings.compose import BriefingError
    from ai_briefing.runtime import daily

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise BriefingError("the composed briefing is not valid")

    monkeypatch.setattr(daily, "compose", broken)
    result, lines = day(engine, config)
    assert result.failed == {"briefing": "BriefingError"}
    assert result.briefing_id is None
    run = briefing_run(engine)
    assert run["status"] == "failed"
    assert run["error"].startswith("BriefingError")
    found = {check.name: check for check in doctor.check_last_runs(engine)}
    assert found["job briefing"].status == doctor.FAIL
    assert "(BriefingError)" in found["job briefing"].detail
    assert found["job assess"].status == doctor.OK
    assert lines[-1]["failed"] == "briefing"
    # Fixed and run again the same day: the same record now shows success.
    monkeypatch.undo()
    again, _ = day(engine, config)
    assert again.ok is True
    assert briefing_run(engine)["status"] == "succeeded"
    assert again.briefing_id == "b-2026-11-19-1"


def test_doctor_judges_a_job_by_its_latest_attempt_not_its_newest_row(
    engine: Engine, config: ModelsConfig
) -> None:
    # Two days run and succeed. Then the older day is retried and fails: its row is the
    # older one, but its attempt is the latest.
    day(engine, config)
    day(engine, config, local_date=DAY + timedelta(days=1), now=NOW + timedelta(days=1))
    retried = NOW + timedelta(days=2)
    with engine.begin() as connection:
        connection.execute(
            schema.job_runs.update()
            .where(schema.job_runs.c.idempotency_key == "collect:2026-11-19")
            .values(status="failed", started_at=retried, ended_at=retried, error="FetchError: down")
        )
    found = {check.name: check for check in doctor.check_last_runs(engine)}
    assert found["job collect"].status == doctor.FAIL
    assert "(FetchError)" in found["job collect"].detail
    assert found["job screen"].status == doctor.OK


# --- What the first live run showed ---------------------------------------------------------------


def test_a_source_that_fails_says_why_in_the_log(engine: Engine, config: ModelsConfig) -> None:
    class OneDown(FakeTransport):
        def send(self, request: Any) -> Any:
            if request.host == "vendor.example.org" and request.path == "/feed.xml":
                raise FetchError("vendor.example.org answered 503")
            return super().send(request)

    result, lines = day(engine, config, transport=OneDown())
    assert result.ok is True
    assert result.stages["collect"]["sources_failed"] == 1
    failures = [line for line in lines if line["event"] == "source.failed"]
    assert failures == [
        {
            "ts": "2026-11-19T11:15:00Z",
            "event": "source.failed",
            "day": "2026-11-19",
            "source": "vendor",
            "error": "FetchError: vendor.example.org answered 503",
        }
    ]


def test_the_collect_command_says_why_a_source_was_not_collected(
    cli_day: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Redirecting(FakeTransport):
        def send(self, request: Any) -> Any:
            if request.host == "papers.example.org" and request.path == "/feed.xml":
                from ai_briefing.sources.transport import HopResponse

                return HopResponse(status=301, headers={"location": "https://cdn.example.com/feed"})
            return super().send(request)

    monkeypatch.setattr(cli, "make_fetcher", lambda: make_fetcher(Redirecting()))
    cli.main(["db", "upgrade", *cli_day])
    capsys.readouterr()
    assert cli.main(["collect", *cli_day]) == 0
    error = capsys.readouterr().err
    assert "papers was not collected: Blocked: cdn.example.com is not a host" in error
