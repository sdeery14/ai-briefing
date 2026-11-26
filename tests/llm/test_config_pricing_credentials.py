"""The model configuration, what a call costs, and where the API key comes from
(RFC §7, §11). No test here reads the real environment's key or the real env file.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from ai_briefing.domain.enums import Effort, ModelTask, ModelTier
from ai_briefing.llm import credentials
from ai_briefing.llm.config import (
    CONFIG_ENV,
    ModelsConfig,
    ModelsConfigError,
    load_models_config,
)
from ai_briefing.llm.credentials import ApiKey, MissingApiKey, load_api_key
from ai_briefing.llm.pricing import (
    REQUEST_OVERHEAD_TOKENS,
    Usage,
    cost,
    prompt_token_ceiling,
    worst_case_cost,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))

# --- Configuration ----------------------------------------------------------------------------


def test_the_committed_configuration_loads_with_exact_prices(config: ModelsConfig) -> None:
    assert config.provider.name == "anthropic"
    assert config.provider.api_version == "2026-10-21"
    assert config.provider.api_key_env == "ANTHROPIC_API_KEY"
    haiku = config.models["claude-haiku-5-5"]
    assert haiku.tier is ModelTier.INEXPENSIVE
    # Exactly a tenth, not the nearest binary fraction to it.
    assert haiku.prices.standard.input == Decimal("0.10")
    assert str(haiku.prices.standard.input) == "0.1"
    assert haiku.prices.standard.cache_write_5m == Decimal("0.125")
    assert haiku.prices.long_prompt is not None
    assert haiku.prices.long_prompt.output == Decimal("2.50")
    assert haiku.long_prompt_threshold_tokens == 100_000
    sonnet = config.models["claude-sonnet-5-5"]
    assert sonnet.prices.standard.output == Decimal("10.00")
    assert sonnet.prices.long_prompt is None
    assert config.budget.monthly_limit == Decimal("15.00")
    assert config.price_table.version == "2026-11-21"


def test_every_task_has_a_model_and_an_effort(config: ModelsConfig) -> None:
    for task in ModelTask:
        model_id, spec, effort = config.for_task(task)
        assert model_id in config.models
        assert spec.structured_output is True
        assert isinstance(effort, Effort)
    assert config.for_task(ModelTask.SCREENING)[0] == "claude-haiku-5-5"
    assert config.for_task(ModelTask.SCREENING)[2] is Effort.LOW
    assert config.for_task(ModelTask.ESCALATED_ASSESSMENT)[0] == "claude-sonnet-5-5"


def changed(**changes: object) -> dict[str, object]:
    data: dict[str, object] = yaml.safe_load(
        (REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8")
    )
    for dotted, value in changes.items():
        node: Any = data
        *path, last = dotted.split("__")
        for key in path:
            node = node[key]
        if value is None:
            del node[last]
        else:
            node[last] = value
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "models.v2"}, "expected schema"),
        ({"provider__name": "another"}, "anthropic"),
        ({"budget__currency": "EUR"}, "USD"),
        ({"budget__monthly_limit": -1}, "monthly_limit"),
        ({"tasks__screening__model": "claude-unknown"}, "unknown model"),
        ({"tasks__screening": None}, "no model is configured for: screening"),
        ({"tasks__screening__effort": "maximum"}, "effort"),
        ({"models__claude-haiku-5-5__long_prompt_threshold_tokens": None}, "come together"),
        ({"models__claude-haiku-5-5__prices__standard__input": -0.1}, "input"),
        ({"models__claude-haiku-5-5__structured_output": False}, "structured output"),
        ({"provider__api_key": "sk-ant-not-a-real-key"}, "api_key"),
        ({"temperature": 0.2}, "temperature"),
    ],
)
def test_an_inconsistent_configuration_does_not_load(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(changed(**change)), encoding="utf-8")
    with pytest.raises(ModelsConfigError, match=message):
        load_models_config(path)


def test_a_missing_or_malformed_file_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ModelsConfigError, match="cannot read"):
        load_models_config(tmp_path / "absent.yaml")
    (tmp_path / "models.yaml").write_text("- a list\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path))
    with pytest.raises(ModelsConfigError, match="expected a mapping"):
        load_models_config()


# --- Cost -------------------------------------------------------------------------------------


def test_cost_matches_a_hand_computed_figure_below_the_threshold(config: ModelsConfig) -> None:
    haiku = config.models["claude-haiku-5-5"]
    # 1,200 x $0.10 + 300 x $0.50, per million: $0.00012 + $0.00015
    assert cost(haiku, Usage(input_tokens=1200, output_tokens=300)) == Decimal("0.00027")


def test_cost_above_the_threshold_uses_long_prompt_prices_for_everything(
    config: ModelsConfig,
) -> None:
    haiku = config.models["claude-haiku-5-5"]
    # 150,000 x $0.50 + 1,000 x $2.50, per million: $0.075 + $0.0025
    assert cost(haiku, Usage(input_tokens=150_000, output_tokens=1_000)) == Decimal("0.0775")
    # Five times the standard figure for the same tokens, not a blend.
    standard = (150_000 * Decimal("0.10") + 1_000 * Decimal("0.50")) / 1_000_000
    assert cost(haiku, Usage(input_tokens=150_000, output_tokens=1_000)) == standard * 5


def test_the_threshold_is_exclusive_and_counts_cached_tokens(config: ModelsConfig) -> None:
    haiku = config.models["claude-haiku-5-5"]
    at = Usage(input_tokens=100_000, output_tokens=0)
    over = Usage(input_tokens=100_001, output_tokens=0)
    assert cost(haiku, at) == Decimal("0.01")  # exactly at the threshold: standard
    assert cost(haiku, over) == Decimal("100001") * Decimal("0.50") / 1_000_000
    # 60,000 uncached and 50,000 from cache is a 110,000-token prompt: long-prompt prices.
    mixed = Usage(input_tokens=60_000, cache_read_input_tokens=50_000)
    assert mixed.prompt_tokens == 110_000
    assert cost(haiku, mixed) == (60_000 * Decimal("0.50") + 50_000 * Decimal("0.05")) / 1_000_000


def test_cached_tokens_are_priced_at_their_own_rates(config: ModelsConfig) -> None:
    haiku = config.models["claude-haiku-5-5"]
    usage = Usage(
        input_tokens=2_000,
        output_tokens=100,
        cache_read_input_tokens=50_000,
        cache_creation_input_tokens=10_000,
    )
    # $0.0002 + $0.00005 + 50,000 x $0.01 ($0.0005) + 10,000 x $0.125 ($0.00125)
    assert cost(haiku, usage) == Decimal("0.002")


def test_a_model_without_a_threshold_is_always_at_standard_prices(config: ModelsConfig) -> None:
    sonnet = config.models["claude-sonnet-5-5"]
    assert cost(sonnet, Usage(input_tokens=500_000, output_tokens=1_000)) == Decimal("1.01")
    assert cost(sonnet, Usage()) == 0


def test_the_token_ceiling_is_never_below_the_true_count() -> None:
    # A token is at least one byte, so the byte count is a bound for any text.
    assert prompt_token_ceiling("") == REQUEST_OVERHEAD_TOKENS
    assert prompt_token_ceiling("abcd") == 4 + REQUEST_OVERHEAD_TOKENS
    assert prompt_token_ceiling("café", "日本") == 5 + 6 + REQUEST_OVERHEAD_TOKENS
    assert prompt_token_ceiling("a" * 1000, "b" * 500) == 1500 + REQUEST_OVERHEAD_TOKENS


def test_the_worst_case_includes_the_output_limit_and_the_long_prompt_price(
    config: ModelsConfig,
) -> None:
    haiku = config.models["claude-haiku-5-5"]
    # 10,000 in and the whole 2,000-token output limit used.
    assert worst_case_cost(haiku, 10_000, 2_000) == Decimal("0.002")
    # A prompt that could be over the threshold is costed at the higher prices.
    assert worst_case_cost(haiku, 200_000, 2_000) == Decimal("0.105")
    assert worst_case_cost(haiku, 200_000, 2_000) > worst_case_cost(haiku, 100_000, 2_000) * 5


# --- The API key ------------------------------------------------------------------------------

VARIABLE = "ANTHROPIC_API_KEY"
FAKE = "sk-ant-test-0000-not-a-real-key"


def env_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".config" / "ai-briefing" / ".env"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_environment_variable_is_used_when_set(tmp_path: Path) -> None:
    env_file(tmp_path, f"{VARIABLE}=from-the-file\n")
    key = load_api_key(VARIABLE, environ={VARIABLE: FAKE}, home=tmp_path)
    assert key.reveal() == FAKE


def test_the_env_file_under_the_home_directory_is_the_fallback(tmp_path: Path) -> None:
    env_file(tmp_path, f"# local secrets\n\n{VARIABLE}={FAKE}\nOTHER=x\n")
    assert load_api_key(VARIABLE, environ={}, home=tmp_path).reveal() == FAKE
    assert load_api_key(VARIABLE, environ={VARIABLE: "  "}, home=tmp_path).reveal() == FAKE


def test_the_env_file_path_can_be_set(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.env"
    elsewhere.write_text(f"{VARIABLE}={FAKE}\n", encoding="utf-8")
    environ = {credentials.ENV_FILE_ENV: str(elsewhere)}
    assert load_api_key(VARIABLE, environ=environ, home=tmp_path / "unused").reveal() == FAKE


@pytest.mark.parametrize(
    "line",
    [
        f"{VARIABLE}={FAKE}",
        f'{VARIABLE}="{FAKE}"',
        f"{VARIABLE}='{FAKE}'",
        f"  {VARIABLE} = {FAKE}  ",
        f"export {VARIABLE}={FAKE}",
        f"﻿{VARIABLE}={FAKE}",  # a byte-order mark, as some editors on Windows add
    ],
)
def test_the_env_file_is_read_tolerantly(tmp_path: Path, line: str) -> None:
    env_file(tmp_path, line + "\n")
    assert load_api_key(VARIABLE, environ={}, home=tmp_path).reveal() == FAKE


@pytest.mark.parametrize("text", ["", f"{VARIABLE}=\n", "OTHER=value\n", "# nothing here\n"])
def test_a_missing_key_is_reported_without_any_value(tmp_path: Path, text: str) -> None:
    path = env_file(tmp_path, text)
    with pytest.raises(MissingApiKey) as raised:
        load_api_key(VARIABLE, environ={"OTHER_SECRET": "do-not-print-me"}, home=tmp_path)
    message = str(raised.value)
    assert VARIABLE in message
    assert str(path) in message
    assert "do-not-print-me" not in message


def test_no_env_file_at_all_is_a_missing_key(tmp_path: Path) -> None:
    with pytest.raises(MissingApiKey):
        load_api_key(VARIABLE, environ={}, home=tmp_path)


def test_a_key_does_not_reveal_itself(caplog: pytest.LogCaptureFixture) -> None:
    key = ApiKey(FAKE)
    assert repr(key) == str(key) == f"{key}" == "ApiKey(***)"
    assert FAKE not in f"{key!r} {key!s} {[key]} {{'k': {key}}}"
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("using %s", key)
    assert FAKE not in caplog.text
    assert not hasattr(key, "__dict__")  # nothing to dump
    assert key == ApiKey(FAKE)
    assert key != ApiKey("other")


def test_the_tests_never_reach_for_the_real_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_home() -> Path:
        raise AssertionError("a test looked up the real home directory")

    monkeypatch.setattr(Path, "home", no_home)
    env_file(tmp_path, f"{VARIABLE}={FAKE}\n")
    assert load_api_key(VARIABLE, environ={}, home=tmp_path).reveal() == FAKE
    assert load_api_key(VARIABLE, environ={VARIABLE: FAKE}).reveal() == FAKE


def test_the_committed_configuration_holds_no_key() -> None:
    assert "api_key" not in RAW["provider"]
    text = (REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8")
    assert "sk-ant-" not in text
