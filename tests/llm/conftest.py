"""Fixtures for model-client tests. No test here uses the network or an API key: answers
come from the hand-written, synthetic recordings in ``recorded/``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, insert

from ai_briefing.domain.enums import LLMCallStatus, ModelTask
from ai_briefing.domain.records import LLMCall
from ai_briefing.llm.backends import ModelRequest, ModelResponse, ReplayBackend
from ai_briefing.llm.client import ModelClient
from ai_briefing.llm.config import ModelsConfig, load_models_config
from ai_briefing.storage import database, repositories, schema

RECORDED = Path(__file__).parent / "recorded"
NOW = datetime(2026, 11, 19, 11, 15, tzinfo=UTC)
HASH = "a" * 64
SYSTEM = "You screen synthetic items for a test. Answer in the given shape."
MAX_OUTPUT_TOKENS = 200


class Verdict(BaseModel):
    """The shape these tests ask the model for."""

    model_config = ConfigDict(extra="forbid")

    relevant: bool
    reason: str


# The user text of each recording in recorded/. Each scenario has its own text, so each
# request has its own digest.
USER = {
    "relevant": "Item 1: a synthetic paper about evaluation methods.",
    "refusal": "Item 2: a synthetic item the model declines to assess.",
    "invalid": "Item 3: a synthetic item answered in the wrong shape.",
    "truncated": "Item 4: a synthetic item whose answer is cut off.",
    "error": "Item 5: a synthetic item for which the provider fails.",
    "long": "Item 6: a synthetic item sent with a very long prompt.",
    "cached": "Item 7: a synthetic item with part of its prompt cached.",
    "extra_field": "Item 8: a synthetic item answered with an extra field.",
}


@pytest.fixture(scope="session")
def config() -> ModelsConfig:
    return load_models_config()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    path = tmp_path / "data" / "test.sqlite3"
    path.parent.mkdir(parents=True)
    engine = database.create_database_engine(path)
    database.upgrade(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def job_run_id(engine: Engine) -> int:
    with engine.begin() as connection:
        created: int = connection.execute(
            insert(schema.job_runs)
            .values(
                job="test",
                idempotency_key="test:llm",
                started_at=NOW,
                status="running",
                counts="{}",
                application_version="0.0.0",
                configuration_hash=HASH,
            )
            .returning(schema.job_runs.c.id)
        ).scalar_one()
    return created


class CountingBackend:
    """Wraps a backend and counts what reaches it."""

    def __init__(self, inner: ReplayBackend) -> None:
        self.inner = inner
        self.requests: list[ModelRequest] = []

    def create(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.inner.create(request)


@pytest.fixture
def backend() -> CountingBackend:
    return CountingBackend(ReplayBackend(RECORDED))


@pytest.fixture
def client(engine: Engine, config: ModelsConfig, backend: CountingBackend) -> ModelClient:
    return ModelClient(
        engine=engine, config=config, backend=backend, clock=lambda: NOW, timer=lambda: 0.0
    )


def spend(engine: Engine, job_run_id: int, amount: str, *, at: datetime = NOW) -> None:
    """Record an earlier call that cost ``amount`` dollars."""
    repositories.record_model_call(
        engine,
        LLMCall(
            job_run_id=job_run_id,
            purpose=ModelTask.ASSESSMENT,
            prompt_id="earlier",
            prompt_hash=HASH,
            provider="anthropic",
            model_id="claude-haiku-5-5",
            tokens_in=1,
            tokens_out=1,
            estimated_cost_usd=Decimal(amount),
            price_table_version="2026-11-21",
            status=LLMCallStatus.SUCCEEDED,
        ),
        now=lambda: at,
    )
