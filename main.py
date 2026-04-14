"""Main entry point for Baloo application."""

import logging
import uvicorn
from baloo.config.settings import settings
from baloo.github.webhook_handler import app
from baloo.version import get_version_info, VERSION, COMMIT_SHA, BUILD_DATE

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Suppress verbose logs from third-party libraries
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Baloo webhook server."""
    # Format commit SHA for display (only truncate if it's a real SHA)
    commit_display = COMMIT_SHA[:8] if COMMIT_SHA not in ('unknown', 'dev', '') and len(COMMIT_SHA) >= 8 else COMMIT_SHA

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
    )


if __name__ == "__main__":
    main()
