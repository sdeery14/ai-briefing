"""The model client: every call is budget-checked, validated and recorded, and the whole
of it runs from recordings with no key and no network (issue 1.5's done-when; ADR-009).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest
from sqlalchemy import Engine, func, select

from ai_briefing.domain.enums import Effort, LLMCallStatus, ModelTask
from ai_briefing.domain.records import LLMCall
from ai_briefing.llm.backends import (
    AnthropicBackend,
    BackendError,
    ModelRequest,
    ModelResponse,
    NoRecording,
    ReplayBackend,
    recording,
)
from ai_briefing.llm.budget import DAILY, MONTHLY, current_spend, daily_allowance, month_to_date
from ai_briefing.llm.client import ModelClient, ModelResult
from ai_briefing.llm.config import ModelsConfig
from ai_briefing.llm.credentials import ApiKey
from ai_briefing.llm.pricing import Usage, cost, prompt_token_ceiling, worst_case_cost
from ai_briefing.storage import repositories, schema
from ai_briefing.storage.jobs import run_job

from .conftest import (
    HASH,
    MAX_OUTPUT_TOKENS,
    NOW,
    RECORDED,
    SYSTEM,
    USER,
    CountingBackend,
    Verdict,
    spend,
)

FAKE_KEY = "sk-ant-test-0000-not-a-real-key"


def ask(client: ModelClient, job_run_id: int, key: str, **changes: Any) -> ModelResult[Verdict]:
    options: dict[str, Any] = {
        "task": ModelTask.SCREENING,
        "job_run_id": job_run_id,
        "prompt_id": "screening",
        "system": SYSTEM,
        "user": USER[key],
        "output_type": Verdict,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    options.update(changes)
    return client.call(**options)


def rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        found = connection.execute(select(schema.llm_calls).order_by(schema.llm_calls.c.id))
        return [dict(row) for row in found.mappings()]


# --- A successful call --------------------------------------------------------------------------


def test_a_call_returns_validated_output_and_is_recorded(
    client: ModelClient, engine: Engine, job_run_id: int, backend: CountingBackend
) -> None:
    result = ask(client, job_run_id, "relevant")
    assert result.status is LLMCallStatus.SUCCEEDED
    assert result.output == Verdict(relevant=True, reason="It is about evaluation methods.")
    call = result.call
    assert call.id is not None
    assert (call.purpose, call.model_id, call.provider) == (
        ModelTask.SCREENING,
        "claude-haiku-5-5",
        "anthropic",
    )
    assert (call.tokens_in, call.tokens_out) == (1200, 300)
    assert call.estimated_cost_usd == Decimal("0.00027")
    assert call.price_table_version == "2026-11-21"
    assert call.prompt_id == "screening"
    assert call.request_ref == backend.requests[0].digest()
    with engine.connect() as connection:
        assert repositories.get(connection, LLMCall, call.id) == call
    (row,) = rows(engine)
    assert json.loads(row["request_payload"])["user"] == USER["relevant"]
    assert json.loads(row["response_payload"])["relevant"] is True
    assert row["created_at"] == NOW


def test_the_request_has_no_tools_and_no_sampling_parameters(
    client: ModelClient, job_run_id: int, backend: CountingBackend, config: ModelsConfig
) -> None:
    ask(client, job_run_id, "relevant")
    (request,) = backend.requests
    assert set(request.canonical()) == {
        "model",
        "system",
        "user",
        "output_schema",
        "max_tokens",
        "effort",
    }
    assert request.effort is Effort.LOW  # the task's configured effort, set explicitly
    assert request.max_tokens == MAX_OUTPUT_TOKENS
    assert request.output_schema["additionalProperties"] is False


# --- Outcomes that are not a success --------------------------------------------------------------


def test_a_refusal_is_recorded_with_its_cost_and_does_not_fail_the_run(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    result = ask(client, job_run_id, "refusal")
    assert result.status is LLMCallStatus.REFUSED
    assert result.output is None
    assert result.reason == "Synthetic refusal for the test."
    assert result.call.tokens_in == 1100
    assert result.call.estimated_cost_usd == Decimal("0.000116")  # a refusal is still paid for
    # The run goes on: the next call works.
    assert ask(client, job_run_id, "relevant").status is LLMCallStatus.SUCCEEDED
    assert [row["status"] for row in rows(engine)] == ["refused", "succeeded"]


@pytest.mark.parametrize(
    ("key", "error_class"),
    [
        ("invalid", "InvalidOutput"),
        ("extra_field", "InvalidOutput"),  # a field the schema does not have, such as a URL
        ("truncated", "OutputTruncated"),
    ],
)
def test_output_that_is_not_the_asked_shape_is_recorded_and_never_returned(
    client: ModelClient, engine: Engine, job_run_id: int, key: str, error_class: str
) -> None:
    result = ask(client, job_run_id, key)
    assert result.status is LLMCallStatus.FAILED
    assert result.output is None
    assert result.reason == error_class
    recorded = rows(engine)
    # A wrong shape is asked for once more; a cut-off answer is not.
    assert len(recorded) == (1 if error_class == "OutputTruncated" else 2)
    for row in recorded:
        assert (row["status"], row["error_class"]) == ("failed", error_class)
        assert row["tokens_in"] == 1000  # the tokens were used, so they are counted
        assert Decimal(row["estimated_cost_usd"]) > 0
        assert row["response_payload"]  # what came back is kept for diagnosis


def test_a_provider_failure_is_recorded_and_returned_not_raised(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    result = ask(client, job_run_id, "error")
    assert result.status is LLMCallStatus.FAILED
    assert result.reason == "RateLimitError"
    (row,) = rows(engine)
    assert (row["status"], row["error_class"]) == ("failed", "RateLimitError")
    assert (row["tokens_in"], row["tokens_out"]) == (0, 0)
    assert Decimal(row["estimated_cost_usd"]) == 0


def test_a_request_with_no_recording_fails_and_is_recorded(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    result = ask(client, job_run_id, "relevant", user="Something nobody recorded.")
    assert result.status is LLMCallStatus.FAILED
    assert result.reason == "NoRecording"
    assert len(rows(engine)) == 1


def test_costs_are_recorded_at_long_prompt_and_cache_prices(
    client: ModelClient, job_run_id: int
) -> None:
    long = ask(client, job_run_id, "long")
    assert long.call.tokens_in == 150_000
    assert long.call.estimated_cost_usd == Decimal("0.0775")
    cached = ask(client, job_run_id, "cached")
    assert cached.call.tokens_in == 62_000  # uncached, read from cache and written to it
    assert cached.call.estimated_cost_usd == Decimal("0.002")


# --- The budget -----------------------------------------------------------------------------------


def test_a_call_that_would_exceed_the_cap_is_refused_before_any_request(
    client: ModelClient, engine: Engine, job_run_id: int, backend: CountingBackend
) -> None:
    spend(engine, job_run_id, "14.9999")
    result = ask(client, job_run_id, "relevant")
    assert result.status is LLMCallStatus.BUDGET_REFUSED
    assert result.output is None
    assert "monthly budget of 15" in (result.reason or "")
    assert backend.requests == []  # nothing was sent
    refused = rows(engine)[-1]
    assert (refused["status"], refused["error_class"]) == ("budget_refused", MONTHLY)
    assert (refused["tokens_in"], refused["tokens_out"]) == (0, 0)
    assert Decimal(refused["estimated_cost_usd"]) == 0
    assert month_to_date(engine, NOW) == Decimal("14.9999")  # the refusal cost nothing


def test_the_check_uses_the_worst_case_not_the_likely_cost(
    client: ModelClient, engine: Engine, job_run_id: int, backend: CountingBackend
) -> None:
    # Ten thousand characters of plain English are about 2,500 tokens, which with the
    # output would cost roughly $0.00035. The check does not trust that guess: it counts
    # every byte as a token and the whole output limit as used, about $0.0012.
    spend(engine, job_run_id, "14.99")
    long_prompt = "plain words " * 834
    result = ask(client, job_run_id, "relevant", user=long_prompt)
    assert result.status is LLMCallStatus.BUDGET_REFUSED
    assert backend.requests == []
    # A short prompt from the same position is let through.
    assert ask(client, job_run_id, "relevant").status is LLMCallStatus.SUCCEEDED


def test_a_call_within_the_cap_goes_ahead(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    spend(engine, job_run_id, "14.99")
    assert ask(client, job_run_id, "relevant").status is LLMCallStatus.SUCCEEDED
    assert month_to_date(engine, NOW) == Decimal("14.99027")


def test_spend_is_counted_per_calendar_month(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    last_month = datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)
    first_of_month = datetime(2026, 11, 1, 0, 0, 0, tzinfo=UTC)
    spend(engine, job_run_id, "14.99", at=last_month)
    assert month_to_date(engine, NOW) == 0
    assert ask(client, job_run_id, "relevant").status is LLMCallStatus.SUCCEEDED
    spend(engine, job_run_id, "1.50", at=first_of_month)
    assert month_to_date(engine, NOW) == Decimal("1.50027")
    assert month_to_date(engine, datetime(2026, 12, 1, tzinfo=UTC)) == 0


def test_month_to_date_is_the_sum_of_every_recorded_call(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    for key in ("relevant", "refusal", "invalid", "error", "long"):
        ask(client, job_run_id, key)
    recorded = [Decimal(row["estimated_cost_usd"]) for row in rows(engine)]
    assert len(recorded) == 6  # the invalid answer was asked for twice
    assert month_to_date(engine, NOW) == sum(recorded)
    # $0.00027 + $0.000116 + 2 x $0.00012 + nothing for the failed call + $0.0775
    assert month_to_date(engine, NOW) == Decimal("0.078126")


def test_a_large_output_limit_alone_can_be_refused(
    client: ModelClient, engine: Engine, job_run_id: int, backend: CountingBackend
) -> None:
    spend(engine, job_run_id, "14.95")
    # 128,000 output tokens could cost $0.064, which would pass the cap from $14.95.
    result = ask(client, job_run_id, "relevant", max_output_tokens=128_000)
    assert result.status is LLMCallStatus.BUDGET_REFUSED
    assert backend.requests == []


@pytest.mark.parametrize("limit", [0, -1, 128_001])
def test_the_output_limit_must_be_within_the_models(
    client: ModelClient, job_run_id: int, limit: int
) -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        ask(client, job_run_id, "relevant", max_output_tokens=limit)


def test_every_call_leaves_exactly_one_record(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    for count, key in enumerate(("relevant", "refusal", "truncated", "error"), start=1):
        ask(client, job_run_id, key)
        assert len(rows(engine)) == count
    ask(client, job_run_id, "invalid")  # two requests: the first answer and the retry
    assert len(rows(engine)) == 6
    spend(engine, job_run_id, "15")
    ask(client, job_run_id, "relevant")
    statuses = [row["status"] for row in rows(engine)]
    assert statuses[-1] == "budget_refused"
    assert len(statuses) == 8


def test_a_call_made_by_a_job_that_then_fails_is_still_on_record(
    engine: Engine, config: ModelsConfig, backend: CountingBackend
) -> None:
    client = ModelClient(engine=engine, config=config, backend=backend, clock=lambda: NOW)

    def prepare(job_run_id: int) -> None:
        assert ask(client, job_run_id, "relevant").status is LLMCallStatus.SUCCEEDED

    def work(connection: Any, job_run_id: int) -> None:
        raise RuntimeError("the results could not be written")

    with pytest.raises(RuntimeError):
        run_job(
            engine,
            job="process",
            idempotency_key="process:2026-11-19",
            application_version="0.0.0",
            configuration_hash=HASH,
            prepare=prepare,
            work=work,
            clock=lambda: NOW,
        )
    assert month_to_date(engine, NOW) == Decimal("0.00027")


# --- Replay -----------------------------------------------------------------------------------------


def test_the_client_runs_from_recordings_with_no_key(
    client: ModelClient, job_run_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    # The offline guard is on for every test, so this also shows no network is used.
    assert ask(client, job_run_id, "relevant").status is LLMCallStatus.SUCCEEDED


def test_every_recording_is_synthetic_and_matches_exactly_its_own_request() -> None:
    files = sorted(RECORDED.glob("*.json"))
    assert len(files) == len(ReplayBackend(RECORDED)) == 8
    for path in files:
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert "Synthetic" in entry["_note"]
        assert entry["request"]["system"] == SYSTEM
        assert entry["request"]["user"] in USER.values()
        assert ("response" in entry) != ("error_class" in entry)
        assert "sk-ant-" not in path.read_text(encoding="utf-8")


def test_a_recording_answers_only_the_request_it_was_made_for() -> None:
    replay = ReplayBackend(RECORDED)
    base = ModelRequest(
        model="claude-haiku-5-5",
        system=SYSTEM,
        user=USER["relevant"],
        output_schema=Verdict.model_json_schema(),
        max_tokens=MAX_OUTPUT_TOKENS,
        effort=Effort.LOW,
    )
    assert replay.create(base).stop_reason == "end_turn"
    for change in (
        {"model": "claude-sonnet-5-5"},
        {"system": SYSTEM + " "},
        {"user": USER["relevant"] + "!"},
        {"max_tokens": MAX_OUTPUT_TOKENS + 1},
        {"effort": Effort.HIGH},
        {"output_schema": {"type": "object"}},
    ):
        other = ModelRequest(**{**base.__dict__, **change})
        assert other.digest() != base.digest()
        with pytest.raises(NoRecording):
            replay.create(other)


def test_two_recordings_of_one_request_are_refused(tmp_path: Path) -> None:
    source = (RECORDED / "screening_relevant.json").read_text(encoding="utf-8")
    (tmp_path / "a.json").write_text(source, encoding="utf-8")
    (tmp_path / "b.json").write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match="already recorded"):
        ReplayBackend(tmp_path)


def test_a_recording_can_be_written_from_a_request_and_a_response(tmp_path: Path) -> None:
    request = ModelRequest("m", "s", "u", {"type": "object"}, 10, Effort.LOW)
    response = ModelResponse('{"a": 1}', "end_turn", Usage(input_tokens=3, output_tokens=2))
    (tmp_path / "one.json").write_text(json.dumps(recording(request, response)), encoding="utf-8")
    assert ReplayBackend(tmp_path).create(request) == response


# --- The provider backend, against a stand-in for the SDK's client ----------------------------------


class FakeMessages:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def sdk_message(**changes: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "content": [
            SimpleNamespace(type="thinking", thinking="private"),
            SimpleNamespace(type="text", text='{"relevant": true, "reason": "ok"}'),
        ],
        "stop_reason": "end_turn",
        "stop_details": None,
        "usage": SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=3,
            cache_creation_input_tokens=None,
        ),
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


REQUEST = ModelRequest(
    model="claude-haiku-5-5",
    system=SYSTEM,
    user="A synthetic item.",
    output_schema=Verdict.model_json_schema(),
    max_tokens=200,
    effort=Effort.LOW,
)


def provider(reply: Any) -> tuple[AnthropicBackend, FakeMessages]:
    messages = FakeMessages(reply)
    backend = AnthropicBackend(
        ApiKey(FAKE_KEY), api_version="2026-10-21", client=SimpleNamespace(messages=messages)
    )
    return backend, messages


def test_the_provider_request_is_exactly_what_the_api_needs_and_nothing_else() -> None:
    backend, messages = provider(sdk_message())
    response = backend.create(REQUEST)
    (sent,) = messages.calls
    assert set(sent) == {"model", "max_tokens", "system", "messages", "output_config"}
    for forbidden in ("tools", "tool_choice", "temperature", "top_p", "top_k", "mcp_servers"):
        assert forbidden not in sent
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["max_tokens"] == 200
    assert sent["messages"] == [{"role": "user", "content": "A synthetic item."}]
    assert sent["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": Verdict.model_json_schema()},
    }
    assert FAKE_KEY not in json.dumps(sent)
    # Only text blocks are the answer. Thinking is not.
    assert response.text == '{"relevant": true, "reason": "ok"}'
    assert response.usage == Usage(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=3, cache_creation_input_tokens=0
    )


def test_a_provider_refusal_is_passed_on_with_its_explanation() -> None:
    backend, _ = provider(
        sdk_message(
            content=[],
            stop_reason="refusal",
            stop_details=SimpleNamespace(category=None, explanation="Declined."),
        )
    )
    response = backend.create(REQUEST)
    assert (response.stop_reason, response.text) == ("refusal", "")
    assert response.refusal_explanation == "Declined."


def test_a_provider_error_keeps_its_kind_and_none_of_its_text() -> None:
    backend, _ = provider(anthropic.AnthropicError(f"bad request echoing {REQUEST.user}"))
    with pytest.raises(BackendError) as raised:
        backend.create(REQUEST)
    assert raised.value.error_class == "AnthropicError"
    assert REQUEST.user not in str(raised.value)
    assert FAKE_KEY not in str(raised.value)


def test_the_sdk_client_is_built_with_the_key_the_version_and_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, Any] = {}

    def fake_client(**kwargs: Any) -> SimpleNamespace:
        built.update(kwargs)
        return SimpleNamespace(messages=FakeMessages(sdk_message()))

    monkeypatch.setattr(anthropic, "Anthropic", fake_client)
    AnthropicBackend(ApiKey(FAKE_KEY), api_version="2026-10-21")
    assert built["api_key"] == FAKE_KEY
    assert built["default_headers"] == {"anthropic-version": "2026-10-21"}
    assert built["max_retries"] == 2
    assert built["timeout"] == 120.0


def test_a_recorded_call_never_holds_the_key(
    engine: Engine, config: ModelsConfig, job_run_id: int
) -> None:
    backend, _ = provider(sdk_message())
    client = ModelClient(engine=engine, config=config, backend=backend, clock=lambda: NOW)
    result = client.call(
        task=ModelTask.SCREENING,
        job_run_id=job_run_id,
        prompt_id="screening",
        system=SYSTEM,
        user="A synthetic item.",
        output_type=Verdict,
        max_output_tokens=200,
    )
    assert result.status is LLMCallStatus.SUCCEEDED
    with engine.connect() as connection:
        everything = connection.execute(select(schema.llm_calls)).all()
        count = connection.execute(select(func.count()).select_from(schema.llm_calls)).scalar_one()
    assert count == 1
    assert FAKE_KEY not in repr(everything)


# --- One retry when the answer is not the asked shape (ADR-009) ---------------------------------


class SequenceBackend:
    """Gives its responses in turn. Stands in for a model that answers differently twice."""

    def __init__(self, *responses: ModelResponse) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    def create(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


BAD = ModelResponse('{"relevant": "maybe"}', "end_turn", Usage(input_tokens=1000, output_tokens=40))
GOOD = ModelResponse(
    '{"relevant": true, "reason": "ok"}', "end_turn", Usage(input_tokens=1000, output_tokens=50)
)


def sequence_client(
    engine: Engine, config: ModelsConfig, *responses: ModelResponse
) -> tuple[ModelClient, SequenceBackend]:
    backend = SequenceBackend(*responses)
    return ModelClient(engine=engine, config=config, backend=backend, clock=lambda: NOW), backend


def test_an_answer_in_the_wrong_shape_is_asked_for_once_more(
    engine: Engine, config: ModelsConfig, job_run_id: int
) -> None:
    client, backend = sequence_client(engine, config, BAD, GOOD)
    result = ask(client, job_run_id, "relevant")
    assert result.status is LLMCallStatus.SUCCEEDED
    assert result.output == Verdict(relevant=True, reason="ok")
    assert len(backend.requests) == 2
    assert backend.requests[0] == backend.requests[1]  # the same request, sent again
    # Both requests cost money, and both are on record.
    recorded = rows(engine)
    assert [(r["status"], r["error_class"]) for r in recorded] == [
        ("failed", "InvalidOutput"),
        ("succeeded", None),
    ]
    assert month_to_date(engine, NOW) == Decimal("0.00012") + Decimal("0.000125")
    assert result.call.id == recorded[1]["id"]


def test_the_retry_is_bounded_at_one(engine: Engine, config: ModelsConfig, job_run_id: int) -> None:
    client, backend = sequence_client(engine, config, BAD, BAD, GOOD)
    result = ask(client, job_run_id, "relevant")
    assert result.status is LLMCallStatus.FAILED
    assert result.reason == "InvalidOutput"
    assert len(backend.requests) == 2  # the third response is never asked for
    assert len(rows(engine)) == 2


def worst_case(config: ModelsConfig, user: str, max_output_tokens: int) -> Decimal:
    """The figure the client's budget check uses for a screening call with this text."""
    _, spec, _ = config.for_task(ModelTask.SCREENING)
    ceiling = prompt_token_ceiling(SYSTEM, user, json.dumps(Verdict.model_json_schema()))
    return worst_case_cost(spec, ceiling, max_output_tokens)


def test_the_retry_has_its_own_budget_check(
    engine: Engine, config: ModelsConfig, job_run_id: int
) -> None:
    # Today has room for exactly one worst-case call. The first answer is the wrong shape
    # and costs something, so the retry no longer fits and is refused, not sent.
    worst = worst_case(config, USER["relevant"], MAX_OUTPUT_TOKENS)
    allowance = daily_allowance(config.budget, Decimal(0), NOW)
    already = allowance - worst - Decimal("0.00001")
    spend(engine, job_run_id, str(already), at=NOW.replace(hour=1))
    client, backend = sequence_client(engine, config, BAD, GOOD)
    result = ask(client, job_run_id, "relevant")
    assert result.status is LLMCallStatus.BUDGET_REFUSED
    assert len(backend.requests) == 1
    assert [r["status"] for r in rows(engine)][-2:] == ["failed", "budget_refused"]


def test_a_refusal_a_cut_off_answer_and_a_provider_error_are_not_retried(
    engine: Engine, config: ModelsConfig, job_run_id: int
) -> None:
    refusal = ModelResponse("", "refusal", Usage(input_tokens=10, output_tokens=1))
    cut_off = ModelResponse(
        '{"relevant": tr', "max_tokens", Usage(input_tokens=10, output_tokens=200)
    )
    for first in (refusal, cut_off):
        client, backend = sequence_client(engine, config, first, GOOD)
        assert ask(client, job_run_id, "relevant").status is not LLMCallStatus.SUCCEEDED
        assert len(backend.requests) == 1


# --- The day's allowance (RFC 7.2) ---------------------------------------------------------------


def test_the_days_allowance_is_what_is_left_of_the_month_over_the_days_left(
    config: ModelsConfig,
) -> None:
    budget = config.budget
    # On the 19th of a 30-day month, 12 days remain, today included.
    assert daily_allowance(budget, Decimal(0), NOW) == Decimal("1.25")
    assert daily_allowance(budget, Decimal("9"), NOW) == Decimal("0.5")
    first = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    last = datetime(2026, 11, 30, 23, 59, tzinfo=UTC)
    assert daily_allowance(budget, Decimal(0), first) == Decimal("0.5")
    assert daily_allowance(budget, Decimal("14"), last) == Decimal("1")  # the last day: the rest
    assert daily_allowance(budget, Decimal("20"), NOW) == 0  # overspent: nothing, never negative
    february = datetime(2028, 2, 29, 12, 0, tzinfo=UTC)
    assert daily_allowance(budget, Decimal("14"), february) == Decimal("1")


def test_a_fixed_daily_allowance_in_the_configuration_is_used(config: ModelsConfig) -> None:
    fixed = config.budget.model_copy(update={"daily_allowance": Decimal("0.40")})
    assert daily_allowance(fixed, Decimal(0), NOW) == Decimal("0.40")
    assert daily_allowance(fixed, Decimal("14"), NOW) == Decimal("0.40")
    assert config.budget.daily_allowance is None  # the committed file does not set one


def test_a_call_is_refused_when_today_is_spent_although_the_month_has_room(
    client: ModelClient, engine: Engine, job_run_id: int, backend: CountingBackend
) -> None:
    # $1.25 may be spent today. $1.2499 already has been, and the month is at a twelfth
    # of its cap.
    spend(engine, job_run_id, "1.2499", at=NOW.replace(hour=1))
    result = ask(client, job_run_id, "relevant")
    assert result.status is LLMCallStatus.BUDGET_REFUSED
    assert "allowance for the day" in (result.reason or "")
    assert backend.requests == []
    refused = rows(engine)[-1]
    assert (refused["status"], refused["error_class"]) == ("budget_refused", DAILY)
    assert Decimal(refused["estimated_cost_usd"]) == 0
    assert month_to_date(engine, NOW) == Decimal("1.2499")


def test_yesterdays_spend_does_not_count_against_today(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    yesterday = datetime(2026, 11, 18, 23, 59, 59, tzinfo=UTC)
    spend(engine, job_run_id, "1.2499", at=yesterday)
    now_spend = current_spend(engine, client._config.budget, NOW)
    assert now_spend.today == 0
    assert now_spend.month_to_date == Decimal("1.2499")
    # What is left of the month, shared over the twelve days that remain.
    assert now_spend.daily_allowance == (Decimal("15") - Decimal("1.2499")) / 12
    assert ask(client, job_run_id, "relevant").status is LLMCallStatus.SUCCEEDED


def test_the_monthly_cap_is_reported_when_both_limits_would_be_passed(
    client: ModelClient, engine: Engine, job_run_id: int
) -> None:
    spend(engine, job_run_id, "15", at=NOW.replace(hour=1))
    result = ask(client, job_run_id, "relevant")
    assert rows(engine)[-1]["error_class"] == MONTHLY
    assert "monthly budget" in (result.reason or "")


def test_one_busy_day_cannot_use_up_the_month(
    engine: Engine, config: ModelsConfig, job_run_id: int
) -> None:
    # A two-cent day. Each call has a 40,000-byte prompt: at most 41,000-odd tokens, in
    # fact 10,000. Calls go through until a worst case would pass the allowance; the day
    # then stops, and the month has hardly been touched.
    two_cents = config.model_copy(
        update={"budget": config.budget.model_copy(update={"daily_allowance": Decimal("0.02")})}
    )
    prompt = "word " * 8_000
    answer = ModelResponse(
        '{"relevant": false, "reason": "no"}',
        "end_turn",
        Usage(input_tokens=10_000, output_tokens=100),
    )
    client, backend = sequence_client(engine, two_cents, *([answer] * 40))
    statuses = [ask(client, job_run_id, "relevant", user=prompt).status for _ in range(40)]
    made = statuses.count(LLMCallStatus.SUCCEEDED)
    assert made == 16  # 16 x $0.00105 = $0.0168, and a 17th could reach $0.0211
    assert set(statuses[made:]) == {LLMCallStatus.BUDGET_REFUSED}
    assert len(backend.requests) == made
    assert month_to_date(engine, NOW) == Decimal("0.0168")
    assert month_to_date(engine, NOW) <= Decimal("0.02")  # never over the day's allowance
    assert {r["error_class"] for r in rows(engine)[made:]} == {DAILY}
    assert current_spend(engine, two_cents.budget, NOW).left_this_month > Decimal("14.98")


def test_actual_cost_never_exceeds_the_worst_case_that_was_checked(config: ModelsConfig) -> None:
    # The byte count bounds the tokens, so a call that passed the check cannot cost more
    # than the check allowed for. That is what makes the limits hold.
    _, spec, _ = config.for_task(ModelTask.SCREENING)
    for text in ("short", "word " * 8_000, "\u65e5\u672c\u8a9e " * 5_000, "x" * 400_000):
        ceiling = prompt_token_ceiling(SYSTEM, text, json.dumps(Verdict.model_json_schema()))
        worst = worst_case(config, text, MAX_OUTPUT_TOKENS)
        # The most a real response could report: every bounded token, all uncached.
        extreme = Usage(input_tokens=ceiling, output_tokens=MAX_OUTPUT_TOKENS)
        assert cost(spec, extreme) == worst
        cheaper = Usage(input_tokens=ceiling // 4, output_tokens=MAX_OUTPUT_TOKENS // 2)
        assert cost(spec, cheaper) <= worst
