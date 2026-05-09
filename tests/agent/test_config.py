"""Tests for PI agent configuration helpers."""

from baloo.agent.config import get_agent_options


class TestGetAgentOptions:
    """Tests for get_agent_options function."""

    # --- Anthropic short names ---

    def test_get_options_with_haiku_short_name(self):
        options = get_agent_options("haiku")
        assert options.model == "claude-haiku-4-5-20251001"
        assert options.provider == "anthropic"
        assert options.max_turns == 10

    def test_get_options_with_sonnet_short_name(self):
        options = get_agent_options("sonnet")
        assert options.model == "claude-sonnet-4-6"
        assert options.provider == "anthropic"
        assert options.max_turns == 20

    def test_get_options_with_opus_short_name(self):
        options = get_agent_options("opus")
        assert options.model == "claude-opus-4-6"
        assert options.provider == "anthropic"
        assert options.max_turns == 30

    # --- Google short names ---

    def test_get_options_with_flash_short_name(self):
        options = get_agent_options("flash")
        assert options.model == "gemini-2.5-flash"
        assert options.provider == "google"
        assert options.max_turns == 10

    def test_get_options_with_gemini_pro_short_name(self):
        options = get_agent_options("gemini-pro")
        assert options.model == "gemini-2.5-pro"
        assert options.provider == "google"
        assert options.max_turns == 20

    # --- Explicit provider/model ---

    def test_get_options_with_provider_slash_model(self):
        options = get_agent_options("google/gemini-2.5-flash")
        assert options.model == "gemini-2.5-flash"
        assert options.provider == "google"

    def test_get_options_with_anthropic_slash_model(self):
        options = get_agent_options("anthropic/claude-opus-4-6")
        assert options.model == "claude-opus-4-6"
        assert options.provider == "anthropic"

    # --- Full model name passthrough ---

    def test_get_options_with_full_model_name(self):
        full_model = "claude-opus-4-6"
        options = get_agent_options(full_model)
        assert options.model == full_model
        assert options.provider == "anthropic"  # default for passthrough

    # --- Defaults ---

    def test_get_options_with_default_model(self):
        options = get_agent_options()
        assert options.model is not None
        assert options.system_prompt is not None

    def test_thinking_level_override(self):
        options = get_agent_options("opus", thinking_level="high")
        assert options.thinking_level == "high"

    def test_default_thinking_level(self):
        options = get_agent_options("sonnet")
        assert options.thinking_level == "medium"

    def test_system_prompt_is_set(self):
        options = get_agent_options("sonnet")
        assert options.system_prompt is not None
        assert "Baloo" in options.system_prompt


def test_thread_agent_settings_defaults():
    """Thread agent settings have correct defaults."""
    from baloo.config.settings import Settings

    s = Settings()
    assert s.thread_agent_enabled is False
    assert s.thread_agent_model == "haiku"
    assert s.thread_agent_max_replies == 3
    assert s.thread_agent_max_concurrent == 3
    assert s.feedback_signals_enabled is True
    assert s.feedback_signals_ttl_days == 180
