"""The one path by which the application calls a model (ADR-009, RFC §7).

Every call goes through :meth:`ModelClient.call`, which in order:

1. works out the most the call could cost, and refuses it if that would pass the monthly
   cap or the day's allowance;
2. sends the request, with no tools and no sampling parameters;
3. validates the answer against the caller's schema before returning it. An answer that
   is not that shape is asked for once more, as a new request with its own budget check;
4. records every request, whatever happened: answered, refused by the model, refused by
   the budget check, or failed.

The record is committed at once, on its own, so it survives whatever the job does next.
A refusal or a failure is returned as a result, not raised: one bad call must not fail a
run. Nothing here can be used to call a model without the budget check or the record.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine

from ai_briefing.domain.enums import LLMCallStatus, ModelTask
from ai_briefing.domain.records import LLMCall
from ai_briefing.llm.backends import (
    MAX_TOKENS,
    REFUSAL,
    Backend,
    BackendError,
    ModelRequest,
    ModelResponse,
)
from ai_briefing.llm.budget import MONTHLY, current_spend
from ai_briefing.llm.config import ModelsConfig
from ai_briefing.llm.pricing import Usage, cost, prompt_token_ceiling, worst_case_cost
from ai_briefing.storage import repositories

T = TypeVar("T", bound=BaseModel)


# How many times an answer that fails validation is asked for again.
VALIDATION_RETRIES = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ModelResult[T: BaseModel]:
    """What came of a call. ``output`` is set only when the status is ``succeeded``."""

    status: LLMCallStatus
    call: LLMCall
    output: T | None = None
    reason: str | None = None  # why there is no output, in a few words


class ModelClient:
    def __init__(
        self,
        *,
        engine: Engine,
        config: ModelsConfig,
        backend: Backend,
        clock: Callable[[], datetime] = utc_now,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._config = config
        self._backend = backend
        self._clock = clock
        self._timer = timer

    def call(
        self,
        *,
        task: ModelTask,
        job_run_id: int,
        prompt_id: str,
        system: str,
        user: str,
        output_type: type[T],
        max_output_tokens: int,
    ) -> ModelResult[T]:
        """Make one model call for ``task`` and return its validated output, or why not.

        Call this from a job's ``prepare`` step, where no database transaction is open:
        the record of the call is committed here, at once.
        """
        model_id, spec, effort = self._config.for_task(task)
        if not 0 < max_output_tokens <= spec.max_output_tokens:
            raise ValueError(f"max_output_tokens must be between 1 and {spec.max_output_tokens}")
        output_schema = output_type.model_json_schema()
        request = ModelRequest(
            model=model_id,
            system=system,
            user=user,
            output_schema=output_schema,
            max_tokens=max_output_tokens,
            effort=effort,
        )
        request_payload = json.dumps(request.canonical(), sort_keys=True, ensure_ascii=False)

        def record(
            status: LLMCallStatus,
            *,
            usage: Usage | None = None,
            error_class: str | None = None,
            latency_ms: int | None = None,
            response_text: str | None = None,
        ) -> LLMCall:
            used = usage or Usage()
            call = LLMCall(
                job_run_id=job_run_id,
                purpose=task,
                prompt_id=prompt_id,
                prompt_hash=hashlib.sha256(system.encode("utf-8")).hexdigest(),
                provider=self._config.provider.name,
                model_id=model_id,
                tokens_in=used.prompt_tokens,
                tokens_out=used.output_tokens,
                estimated_cost_usd=cost(spec, used),
                price_table_version=self._config.price_table.version,
                latency_ms=latency_ms,
                status=status,
                error_class=error_class,
                request_ref=request.digest(),
            )
            return repositories.record_model_call(
                self._engine,
                call,
                now=self._clock,
                # A request that was never sent holds no text that left the machine, but
                # it is kept all the same: it shows what the budget check stopped.
                request_payload=request_payload,
                response_payload=response_text,
            )

        ceiling = prompt_token_ceiling(system, user, json.dumps(output_schema))
        worst = worst_case_cost(spec, ceiling, max_output_tokens)
        budget = self._config.budget
        result: ModelResult[T] | None = None
        # One request, and at most one more if the answer is not the asked shape (ADR-009).
        for _attempt in range(1 + VALIDATION_RETRIES):
            # 1. The budget check, before anything is sent. Made afresh for a retry.
            spend = current_spend(self._engine, budget, self._clock())
            refusal = spend.refusal(worst)
            if refusal is not None:
                call = record(LLMCallStatus.BUDGET_REFUSED, error_class=refusal)
                limit, spent = (
                    (f"monthly budget of {spend.monthly_limit}", spend.month_to_date)
                    if refusal == MONTHLY
                    else (f"allowance for the day of {spend.daily_allowance:.4f}", spend.today)
                )
                return ModelResult(
                    LLMCallStatus.BUDGET_REFUSED,
                    call,
                    reason=(
                        f"the {limit} {budget.currency} would be passed: "
                        f"{spent} spent, up to {worst} more for this call"
                    ),
                )

            # 2. The call.
            started = self._timer()
            try:
                response = self._backend.create(request)
            except BackendError as error:
                latency = int((self._timer() - started) * 1000)
                call = record(
                    LLMCallStatus.FAILED, error_class=error.error_class, latency_ms=latency
                )
                return ModelResult(LLMCallStatus.FAILED, call, reason=error.error_class)
            latency = int((self._timer() - started) * 1000)

            def outcome(
                status: LLMCallStatus,
                *,
                error_class: str | None = None,
                reason: str | None = None,
                response: ModelResponse = response,
                latency: int = latency,
            ) -> ModelResult[T]:
                call = record(
                    status,
                    usage=response.usage,
                    error_class=error_class,
                    latency_ms=latency,
                    response_text=response.text,
                )
                return ModelResult(status, call, reason=reason or error_class)

            # 3. The answer, checked before anything can use it.
            if response.stop_reason == REFUSAL:
                # A refusal is a normal outcome. It is recorded, with what it cost.
                return outcome(
                    LLMCallStatus.REFUSED,
                    reason=response.refusal_explanation or "the model declined",
                )
            if response.stop_reason == MAX_TOKENS:
                # Asking again with the same limit would be cut off again.
                return outcome(LLMCallStatus.FAILED, error_class="OutputTruncated")
            output = _validated(response, output_type)
            if output is not None:
                call = record(
                    LLMCallStatus.SUCCEEDED,
                    usage=response.usage,
                    latency_ms=latency,
                    response_text=response.text,
                )
                return ModelResult(LLMCallStatus.SUCCEEDED, call, output=output)
            # Not the asked shape. This request is recorded as failed; the loop asks once
            # more, and a second failure is the result.
            result = outcome(LLMCallStatus.FAILED, error_class="InvalidOutput")
        if result is None:  # pragma: no cover - the loop always runs at least once
            raise RuntimeError("no model request was made")
        return result


def _validated[T: BaseModel](response: ModelResponse, output_type: type[T]) -> T | None:
    """The response as ``output_type``, or ``None`` if it is not exactly that shape."""
    try:
        return output_type.model_validate_json(response.text, strict=True)
    except ValidationError:
        return None
