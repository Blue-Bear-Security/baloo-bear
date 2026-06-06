"""Main entry point for Baloo application."""

import logging

import uvicorn

from baloo.config.settings import settings
from baloo.github.webhook_handler import app
from baloo.logging_config import UVICORN_LOG_CONFIG, configure_logging
from baloo.version import BUILD_DATE, COMMIT_SHA, VERSION, get_version_info

# Configure root logger (covers all non-uvicorn loggers). Re-applied after DB
# migrations run — see baloo.logging_config for why.
configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Baloo webhook server."""
    # Format commit SHA for display (only truncate if it's a real SHA)
    commit_display = (
        COMMIT_SHA[:8]
        if COMMIT_SHA not in ("unknown", "dev", "") and len(COMMIT_SHA) >= 8
        else COMMIT_SHA
    )

    logger.info("=" * 80)
    logger.info(get_version_info())
    logger.info(f"Version: {VERSION} | Commit: {commit_display} | Build Date: {BUILD_DATE}")
    logger.info("=" * 80)
    logger.info(f"Starting Baloo on {settings.app_host}:{settings.app_port}")
    logger.info(f"Using model: {settings.agent_model}")

    uvicorn.run(
        app,
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        log_config=UVICORN_LOG_CONFIG,
    )


if __name__ == "__main__":
    main()
