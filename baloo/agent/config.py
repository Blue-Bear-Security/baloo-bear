"""Agent configuration for PI runtime."""

import logging

from baloo.agent.pi_runtime import PIAgentOptions
from baloo.agent.prompts import AST_TOOLS_PROMPT_SECTION, REVIEW_SYSTEM_PROMPT
from baloo.config.settings import settings

logger = logging.getLogger(__name__)

# Model registry: short name -> (provider, model_id, max_turns)
# Organized by tier: economy → standard → premium
MODEL_REGISTRY: dict[str, tuple[str, str, int]] = {
    # Economy tier — bulk reviews, simple PRs (docs, deps, configs)
    "flash": ("google", "gemini-2.5-flash", 10),
    "haiku": ("anthropic", "claude-haiku-4-5-20251001", 10),
    # Standard tier — default code reviews
    "gemini-pro": ("google", "gemini-2.5-pro", 20),
    "sonnet": ("anthropic", "claude-sonnet-4-6", 20),
    # Premium tier — complex/security-sensitive reviews
    "opus": ("anthropic", "claude-opus-4-6", 30),
}

# Backward-compat aliases
MODEL_MAP = {name: spec[1] for name, spec in MODEL_REGISTRY.items()}
MAX_TURNS = {name: spec[2] for name, spec in MODEL_REGISTRY.items()}


def _build_system_prompt() -> str:
    """Build the system prompt, conditionally including the AST tools section."""
    prompt = REVIEW_SYSTEM_PROMPT
    if settings.ast_tools_enabled:
        prompt += AST_TOOLS_PROMPT_SECTION
    return prompt


def get_agent_options(model: str = None, thinking_level: str | None = None) -> PIAgentOptions:
    """
    Get PI agent configuration options.

    Args:
        model: Override model selection (default from settings).
               Accepts short names ("flash", "haiku", "sonnet", "gemini-pro", "opus")
               or full "provider/model" strings (e.g. "google/gemini-2.5-flash").
        thinking_level: Thinking level (off, minimal, low, medium, high).
                        Defaults to settings.pi_thinking_level.

    Returns:
        PIAgentOptions configured for read-only code review
    """
    level = thinking_level or settings.pi_thinking_level
    system_prompt = _build_system_prompt()

    # 1. Short name lookup
    if model and model in MODEL_REGISTRY:
        provider, model_id, max_turns = MODEL_REGISTRY[model]
        return PIAgentOptions(
            model=model_id,
            provider=provider,
            system_prompt=system_prompt,
            thinking_level=level,
            max_turns=max_turns,
        )

    # 2. Explicit "provider/model" string
    if model and "/" in model:
        provider, model_id = model.split("/", 1)
        return PIAgentOptions(
            model=model_id,
            provider=provider,
            system_prompt=system_prompt,
            thinking_level=level,
            max_turns=20,
        )

    # 3. Full model name passthrough (assume anthropic)
    if model:
        return PIAgentOptions(
            model=model,
            provider="anthropic",
            system_prompt=system_prompt,
            thinking_level=level,
            max_turns=20,
        )

    # 4. Default from settings — resolve short names first
    default_model = settings.agent_model
    if default_model in MODEL_REGISTRY:
        provider, model_id, max_turns = MODEL_REGISTRY[default_model]
        return PIAgentOptions(
            model=model_id,
            provider=provider,
            system_prompt=system_prompt,
            thinking_level=level,
            max_turns=max_turns,
        )

    return PIAgentOptions(
        model=default_model,
        provider=settings.agent_provider,
        system_prompt=system_prompt,
        thinking_level=level,
        max_turns=20,
    )
