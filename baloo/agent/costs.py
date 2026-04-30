"""Normalize model usage and estimate token costs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizedUsage:
    """Provider-neutral usage counters for one model response."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class ModelPricing:
    """Per-million-token prices for a model family."""

    input_per_mtok: float
    output_per_mtok: float
    cache_write_per_mtok: float
    cache_read_per_mtok: float


# Anthropic public API prices per million tokens. Cache write uses the standard
# 5-minute cache creation price; 1-hour cache writes require request-level TTL
# details that PI does not currently expose.
ANTHROPIC_PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-6": ModelPricing(3.0, 15.0, 3.75, 0.30),
    "claude-haiku-4-5-20251001": ModelPricing(1.0, 5.0, 1.25, 0.10),
    "claude-opus-4-6": ModelPricing(5.0, 25.0, 6.25, 0.50),
    "claude-opus-4-7": ModelPricing(5.0, 25.0, 6.25, 0.50),
}


def normalize_usage(usage: dict[str, Any], *, provider: str, model: str) -> NormalizedUsage:
    """Normalize PI/provider usage payloads and estimate billable cost."""
    input_tokens = _usage_int(usage, "input", "input_tokens", "inputTokens")
    output_tokens = _usage_int(usage, "output", "output_tokens", "outputTokens")
    cache_read_tokens = _usage_int(
        usage,
        "cacheRead",
        "cache_read_input_tokens",
        "cacheReadInputTokens",
    )
    cache_write_tokens = _usage_int(
        usage,
        "cacheWrite",
        "cache_creation_input_tokens",
        "cacheCreationInputTokens",
    )
    thinking_tokens = _usage_int(usage, "thinking", "thinking_tokens", "thinkingTokens")

    estimated_cost = _estimate_cost(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_tokens=thinking_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )
    cost_usd = estimated_cost if estimated_cost is not None else _provider_reported_cost(usage)

    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        thinking_tokens=thinking_tokens,
        cost_usd=cost_usd,
    )


def _estimate_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float | None:
    if provider != "anthropic":
        return None

    pricing = ANTHROPIC_PRICING.get(model)
    if pricing is None:
        return None

    return (
        (input_tokens / 1_000_000) * pricing.input_per_mtok
        + ((output_tokens + thinking_tokens) / 1_000_000) * pricing.output_per_mtok
        + (cache_write_tokens / 1_000_000) * pricing.cache_write_per_mtok
        + (cache_read_tokens / 1_000_000) * pricing.cache_read_per_mtok
    )


def _provider_reported_cost(usage: dict[str, Any]) -> float:
    cost = usage.get("cost", {})
    if isinstance(cost, dict):
        total = cost.get("total")
        if isinstance(total, int | float):
            return float(total)
    if isinstance(cost, int | float):
        return float(cost)
    return 0.0


def _usage_int(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    if usage:
        logger.debug(
            "_usage_int: none of %s present in usage keys %s",
            keys,
            list(usage.keys()),
        )
    return 0
