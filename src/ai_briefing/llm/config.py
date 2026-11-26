"""Loading ``config/models.yaml``: the provider, models, prices, tasks and budget (RFC §7).

Money is held as exact decimals. A price in the file such as ``0.10`` is read from its
written form, not from a binary float.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from ai_briefing.domain.enums import Effort, ModelTask, ModelTier

SCHEMA = "models.v1"
CONFIG_ENV = "AI_BRIEFING_CONFIG"
TOKENS_PER_PRICE_UNIT = 1_000_000  # prices are per million tokens


class ModelsConfigError(ValueError):
    """``models.yaml`` is missing, malformed, or inconsistent."""


def _exact(value: Any) -> Any:
    # YAML reads 0.10 as a float. Its shortest decimal form is the number that was written.
    return Decimal(repr(value)) if isinstance(value, float) else value


Money = Annotated[Decimal, BeforeValidator(_exact), Field(ge=0)]


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Prices(_Config):
    """US dollars per million tokens."""

    input: Money
    output: Money
    cache_read: Money
    cache_write_5m: Money


class ModelPrices(_Config):
    standard: Prices
    long_prompt: Prices | None = None


class ModelSpec(_Config):
    tier: ModelTier
    context_window_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    default_effort: Effort
    structured_output: bool
    # A request whose prompt is over this many tokens is billed entirely at the
    # long-prompt prices.
    long_prompt_threshold_tokens: int | None = Field(default=None, gt=0)
    prices: ModelPrices

    @model_validator(mode="after")
    def _threshold_and_long_prices_come_together(self) -> Self:
        if (self.long_prompt_threshold_tokens is None) != (self.prices.long_prompt is None):
            raise ValueError("a long-prompt threshold and long-prompt prices come together")
        return self


class Provider(_Config):
    name: str
    api: str
    api_version: str
    api_key_env: str


class PriceTable(_Config):
    version: str
    verified_on: date
    sources: tuple[str, ...]


class TaskSpec(_Config):
    model: str
    effort: Effort


class Budget(_Config):
    currency: str
    monthly_limit: Money
    provisional: bool
    shed_order: tuple[str, ...]
    # A fixed amount per day. When it is not set, the day's allowance is what is left of
    # the month shared equally over the days that remain (see ai_briefing.llm.budget).
    daily_allowance: Money | None = None


class ModelsConfig(_Config):
    schema_: str = Field(alias="schema")
    provider: Provider
    price_table: PriceTable
    models: dict[str, ModelSpec]
    tasks: dict[ModelTask, TaskSpec]
    budget: Budget

    @model_validator(mode="after")
    def _is_consistent(self) -> Self:
        if self.schema_ != SCHEMA:
            raise ValueError(f"expected schema {SCHEMA!r}")
        if self.provider.name != "anthropic":
            raise ValueError("the one supported provider is anthropic (ADR-009)")
        if self.budget.currency != "USD":
            raise ValueError("prices and the budget are in USD")
        missing = sorted(t.value for t in ModelTask if t not in self.tasks)
        if missing:
            raise ValueError(f"no model is configured for: {', '.join(missing)}")
        for task, spec in self.tasks.items():
            if spec.model not in self.models:
                raise ValueError(f"task {task.value} names an unknown model {spec.model!r}")
            if not self.models[spec.model].structured_output:
                raise ValueError(f"task {task.value} needs a model with structured output")
        return self

    def for_task(self, task: ModelTask) -> tuple[str, ModelSpec, Effort]:
        """The model identifier, its specification and the effort for a task."""
        spec = self.tasks[task]
        return spec.model, self.models[spec.model], spec.effort


def config_directory() -> Path:
    """``AI_BRIEFING_CONFIG``, else ``config/`` in the source checkout (RFC §3.4)."""
    override = os.environ.get(CONFIG_ENV)
    return Path(override) if override else Path(__file__).resolve().parents[3] / "config"


def load_models_config(path: str | os.PathLike[str] | None = None) -> ModelsConfig:
    target = Path(path) if path is not None else config_directory() / "models.yaml"
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ModelsConfigError(f"cannot read the model configuration {target}: {error}") from error
    if not isinstance(data, dict):
        raise ModelsConfigError(f"{target.name}: expected a mapping")
    try:
        return ModelsConfig.model_validate(data)
    except ValidationError as error:
        raise ModelsConfigError(f"{target.name} is not valid: {error}") from error
