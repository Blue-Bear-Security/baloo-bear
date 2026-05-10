"""Tests for AST tools integration with PI runtime."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from baloo.agent.pi_runtime import PIAgentBase, PIAgentOptions


def _make_mock_settings(**overrides):
    """Create a mock settings object with sensible defaults."""
    mock = MagicMock()
    mock.ast_tools_enabled = overrides.get("ast_tools_enabled", False)
    mock.pi_binary_path = overrides.get("pi_binary_path", None)
    return mock


def test_extension_flag_added_when_ast_tools_enabled():
    """PI command includes --extension flag when ast_tools_enabled is True."""
    options = PIAgentOptions(
        model="claude-haiku-4-5-20251001",
        provider="anthropic",
        system_prompt="test",
    )
    agent = PIAgentBase(options)

    with patch(
        "baloo.agent.pi_runtime.get_settings",
        return_value=_make_mock_settings(ast_tools_enabled=True),
    ):
        cmd = agent._build_pi_command()

    assert "--extension" in cmd
    ext_idx = cmd.index("--extension")
    ext_path = cmd[ext_idx + 1]
    assert ext_path.endswith("baloo-ast-tools.ts")


def test_extension_flag_omitted_when_ast_tools_disabled():
    """PI command has no --extension flag when ast_tools_enabled is False."""
    options = PIAgentOptions(
        model="claude-haiku-4-5-20251001",
        provider="anthropic",
        system_prompt="test",
    )
    agent = PIAgentBase(options)

    with patch(
        "baloo.agent.pi_runtime.get_settings",
        return_value=_make_mock_settings(ast_tools_enabled=False),
    ):
        cmd = agent._build_pi_command()

    assert "--extension" not in cmd


def test_extension_flag_omitted_when_no_tools():
    """PI command has no --extension when no_tools is True (e.g. thread agent)."""
    options = PIAgentOptions(
        model="claude-haiku-4-5-20251001",
        provider="anthropic",
        system_prompt="test",
        no_tools=True,
    )
    agent = PIAgentBase(options)

    with patch(
        "baloo.agent.pi_runtime.get_settings",
        return_value=_make_mock_settings(ast_tools_enabled=True),
    ):
        cmd = agent._build_pi_command()

    assert "--extension" not in cmd
