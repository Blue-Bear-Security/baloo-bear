"""Configuration settings for Baloo using Pydantic."""

import logging
import os

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=os.getenv("BALOO_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    # GitHub App Configuration
    github_app_id: str = Field(default="", description="GitHub App ID")
    github_private_key: str = Field(default="", description="GitHub App private key (PEM format)")
    github_webhook_secret: str = Field(
        default="", description="GitHub webhook secret for signature validation"
    )
    webhook_pre_verified: bool = Field(
        default=False,
        description="Skip webhook signature verification (set True when behind a trusted proxy)",
    )

    # Anthropic Configuration
    anthropic_api_key: str = Field(default="", description="Anthropic API key for Claude")

    # Application Configuration
    app_environment: str = Field(
        default="development", description="Application environment (development, production)"
    )
    app_host: str = Field(default="0.0.0.0", description="Application host")
    app_port: int = Field(default=8000, description="Application port")
    log_level: str = Field(default="INFO", description="Logging level")
    max_concurrent_reviews: int = Field(
        default=3,
        description="Maximum number of PR reviews to process concurrently",
    )
    review_stale_timeout_minutes: int = Field(
        default=30,
        description="Minutes after which an in-progress review is considered stale and can be superseded",
    )

    # Agent Configuration
    agent_provider: str = Field(
        default="anthropic", description="LLM provider (anthropic, google, openai)"
    )
    agent_model: str = Field(default="claude-sonnet-4-6", description="Model to use for reviews")
    agent_fallback_model: str = Field(
        default="google/gemini-2.5-flash",
        description="Fallback model (provider/model) if the primary fails. Empty to disable.",
    )
    agent_max_tokens: int = Field(default=4096, description="Max tokens for agent responses")
    agent_temperature: float = Field(default=0.2, description="Temperature for agent responses")
    pi_binary_path: str = Field(
        default="pi",
        description="Path to the pi binary (or just 'pi' if on PATH)",
    )
    pi_thinking_level: str = Field(
        default="medium",
        description="PI thinking level: off, minimal, low, medium, high",
    )

    # Review Configuration
    ticket_id_prefix: str = Field(
        default="PROJ",
        description="Prefix for ticket IDs (e.g., 'PROJ' for PROJ-123)",
    )
    review_auto_approve: bool = Field(
        default=True,
        description="Auto-approve PRs with no critical/high issues",
    )
    review_min_severity: str = Field(
        default="MEDIUM",
        description="Minimum severity to report (LOW, MEDIUM, HIGH, CRITICAL)",
    )
    review_use_checks_api: bool = Field(
        default=True,
        description="Use GitHub Checks API for MEDIUM severity issues",
    )

    # Database Configuration
    database_url: str = Field(default="", description="PostgreSQL connection URL")
    database_enabled: bool = Field(
        default=False, description="Enable database persistence for review data"
    )

    # Multi-Tenant Configuration
    installation_id: str | None = Field(
        default=None,
        description="GitHub installation ID for tenant scoping (required in shared-DB deployments)",
    )

    @field_validator("installation_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    installation_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Comma-separated list of GitHub installation IDs this broker serves. "
            "Empty = serve all installations. "
            "Backfilled from INSTALLATION_ID if unset."
        ),
    )

    @field_validator("installation_ids", mode="before")
    @classmethod
    def parse_installation_ids(cls, v: object) -> list[str]:
        if not v:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return [x.strip() for x in str(v).split(",") if x.strip()]

    @model_validator(mode="after")
    def backfill_installation_ids(self) -> "Settings":
        if not self.installation_ids and self.installation_id:
            self.installation_ids = [self.installation_id]
        return self

    # Dashboard Configuration
    dashboard_enabled: bool = Field(default=True, description="Enable the review history dashboard")
    dashboard_username: str = Field(default="", description="Dashboard basic auth username")
    dashboard_password: str = Field(default="", description="Dashboard basic auth password")
    log_retention_days: int = Field(
        default=30, description="Days to retain execution logs (0 to disable cleanup)"
    )

    # FP Verification Configuration
    fp_verification_enabled: bool = Field(
        default=True,
        description="Enable LLM-powered false-positive verification pass",
    )
    fp_verification_model: str = Field(
        default="haiku",
        description="Model for FP verification (short name or provider/model)",
    )
    fp_verification_max_concurrent: int = Field(
        default=5,
        description="Max concurrent FP verification calls",
    )
    fp_audit_log_path: str = Field(
        default="/var/log/baloo/fp-audit.jsonl",
        description="Path for FP verification audit log (JSONL). Empty to disable.",
    )

    # Thread Agent Configuration
    thread_agent_enabled: bool = Field(
        default=False,
        description="Enable the thread conversation agent for PR comment replies",
    )
    thread_agent_model: str = Field(
        default="haiku",
        description="Model for thread replies (short name or provider/model)",
    )
    thread_agent_max_replies: int = Field(
        default=3,
        description="Max total Baloo messages per thread (original + replies) before escalation",
    )
    thread_agent_max_concurrent: int = Field(
        default=3,
        description="Max parallel thread agent calls",
    )

    # Feedback Signals Configuration
    feedback_signals_enabled: bool = Field(
        default=True,
        description="Write and read feedback signals (requires DATABASE_ENABLED)",
    )
    feedback_signals_ttl_days: int = Field(
        default=180,
        description="Days before unmatched feedback signals expire",
    )

    # AST Tools Configuration
    ast_tools_enabled: bool = Field(
        default=True,
        description="Enable AST analysis tools (outline, grep, symbols) for the review agent",
    )

    # Fidelity Report Configuration
    fidelity_enabled: bool = Field(
        default=True,
        description="Enable fidelity report comparing PR changes against design plan",
    )
    fidelity_plan_path_pattern: str = Field(
        default="docs/plans/{ticket_id}.md",
        description="Path pattern for plan files, with {ticket_id} placeholder",
    )
    fidelity_approval_threshold: int = Field(
        default=90,
        description="Minimum fidelity score (0-100) required for auto-approval with clean review",
    )

    @property
    def github_private_key_bytes(self) -> bytes:
        """Get GitHub private key as bytes."""
        # Handle both inline key and file path
        if self.github_private_key.startswith("-----BEGIN"):
            return self.github_private_key.encode("utf-8")
        else:
            # Assume it's a file path
            with open(self.github_private_key, "rb") as f:
                return f.read()


# Global settings instance (lazy-loaded to avoid import errors)
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        if _settings.webhook_pre_verified:
            logger.warning(
                "WEBHOOK_PRE_VERIFIED is enabled — webhook signature verification is DISABLED. "
                "Only use this when running behind a trusted proxy."
            )
    return _settings


def reset_settings() -> None:
    """Reset the global settings instance (useful for tests)."""
    global _settings
    _settings = None


# For backward compatibility - but note: this will be evaluated on import
# For testing, use get_settings() function instead
def __getattr__(name: str):
    """Lazy load settings attribute."""
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
