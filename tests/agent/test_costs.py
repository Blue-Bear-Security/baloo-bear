"""Tests for model usage normalization and cost estimation."""

import logging

import pytest

from baloo.agent.costs import _usage_int, normalize_usage


def test_estimates_anthropic_cost_from_billing_usage_fields():
    """Anthropic cache tokens should be priced separately from regular input."""
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_creation_input_tokens": 10_000,
        "cache_read_input_tokens": 20_000,
        "cost": {"total": 999.0},
    }

    normalized = normalize_usage(
        usage,
        provider="anthropic",
        model="claude-sonnet-4-6",
    )

    assert normalized.input_tokens == 1_000_000
    assert normalized.output_tokens == 100_000
    assert normalized.cache_write_tokens == 10_000
    assert normalized.cache_read_tokens == 20_000
    assert normalized.cost_usd == pytest.approx(4.5435)


def test_uses_pi_camel_case_usage_fields():
    usage = {
        "input": 2_000,
        "output": 500,
        "cacheWrite": 200,
        "cacheRead": 1_000,
        "cost": {"total": 0.10},
    }

    normalized = normalize_usage(
        usage,
        provider="anthropic",
        model="claude-sonnet-4-6",
    )

    assert normalized.input_tokens == 2_000
    assert normalized.output_tokens == 500
    assert normalized.cache_write_tokens == 200
    assert normalized.cache_read_tokens == 1_000
    assert normalized.cost_usd == pytest.approx(0.01455)


def test_bills_separately_reported_thinking_tokens_as_output():
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "thinking_tokens": 50_000,
    }

    normalized = normalize_usage(
        usage,
        provider="anthropic",
        model="claude-sonnet-4-6",
    )

    assert normalized.thinking_tokens == 50_000
    assert normalized.cost_usd == pytest.approx(5.25)


def test_usage_int_logs_debug_when_aliases_missing(caplog):
    """Missing usage aliases should emit debug signal instead of failing silently."""
    caplog.set_level(logging.DEBUG)
    assert _usage_int({"unknown_metric": 5}, "input", "input_tokens") == 0
    assert "_usage_int" in caplog.text


def test_falls_back_to_provider_reported_cost_for_unknown_pricing():
    normalized = normalize_usage(
        {"input": 2_000, "output": 500, "cost": {"total": 0.10}},
        provider="google",
        model="gemini-2.5-flash",
    )

    assert normalized.cost_usd == 0.10
