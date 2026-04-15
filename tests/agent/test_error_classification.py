"""Tests for agent error classification."""

import pytest

from baloo.agent.client import BalooAgent


@pytest.mark.parametrize(
    "error_msg, expected_category",
    [
        (
            "Separator is not found, and chunk exceed the limit",
            "buffer_overflow",
        ),
        (
            "Separator is found, but chunk is longer than limit",
            "buffer_overflow",
        ),
        (
            "Prompt is too long for model context window",
            "prompt_too_long",
        ),
        (
            "JSONDecodeError: Expecting value",
            "json_parse_error",
        ),
        (
            "could not parse JSON from assistant response",
            "json_parse_error",
        ),
        (
            "Request timed out after 300 seconds",
            "timeout",
        ),
        (
            "asyncio.TimeoutError: operation timed out",
            "timeout",
        ),
        (
            "Rate limit exceeded (429)",
            "rate_limited",
        ),
        (
            "HTTP 401 Unauthorized",
            "auth_error",
        ),
        (
            "HTTP 403 Forbidden: invalid API key",
            "auth_error",
        ),
        (
            "Some unexpected error happened",
            "agent_error",
        ),
    ],
)
def test_classify_error(error_msg: str, expected_category: str) -> None:
    assert BalooAgent._classify_error(error_msg) == expected_category
