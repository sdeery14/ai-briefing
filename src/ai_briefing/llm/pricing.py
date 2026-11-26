"""What a model call costs, and the most it could cost (RFC §7.1, §7.2).

A request whose prompt is over a model's long-prompt threshold is billed *entirely* at
the long-prompt prices, input and output alike. Both functions here apply that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ai_briefing.llm.config import TOKENS_PER_PRICE_UNIT, ModelSpec, Prices

# Tokens the provider adds around a request that the text does not account for: message
# framing and the instructions that enforce the output schema. Deliberately generous.
REQUEST_OVERHEAD_TOKENS = 1_000


@dataclass(frozen=True)
class Usage:
    """Tokens as the provider reports them. The three input figures do not overlap."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Every token sent: uncached, read from cache and written to cache."""
        return self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens


def prices_for(spec: ModelSpec, prompt_tokens: int) -> Prices:
    threshold = spec.long_prompt_threshold_tokens
    if threshold is not None and spec.prices.long_prompt is not None and prompt_tokens > threshold:
        return spec.prices.long_prompt
    return spec.prices.standard


def cost(spec: ModelSpec, usage: Usage) -> Decimal:
    """The cost of a call in US dollars, exactly."""
    prices = prices_for(spec, usage.prompt_tokens)
    total = (
        usage.input_tokens * prices.input
        + usage.output_tokens * prices.output
        + usage.cache_read_input_tokens * prices.cache_read
        + usage.cache_creation_input_tokens * prices.cache_write_5m
    )
    return total / TOKENS_PER_PRICE_UNIT


def prompt_token_ceiling(*texts: str) -> int:
    """An upper bound on the tokens a request's text can come to.

    A token is at least one byte of UTF-8, so the byte count cannot be exceeded. It is
    usually three or four times too high, which is the safe direction for a budget check
    that must not let a call through on an optimistic guess.
    """
    return sum(len(text.encode("utf-8")) for text in texts) + REQUEST_OVERHEAD_TOKENS


def worst_case_cost(spec: ModelSpec, prompt_tokens: int, max_output_tokens: int) -> Decimal:
    """The most a call can cost: the whole prompt uncached, and the full output limit used."""
    worst = Usage(input_tokens=prompt_tokens, output_tokens=max_output_tokens)
    return cost(spec, worst)
