"""Main entry point for Baloo application."""

import logging

import uvicorn

from baloo.config.settings import settings
from baloo.github.webhook_handler import app
from baloo.version import BUILD_DATE, COMMIT_SHA, VERSION, get_version_info

# Logging format shared by the app and uvicorn
LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"

# Configure root logger (covers all non-uvicorn loggers)
logging.basicConfig(level=settings.log_level, format=LOG_FORMAT)

# Uvicorn log config — override its default formatters so every line
# gets a timestamp, matching the rest of the application output.
UVICORN_LOG_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": LOG_FORMAT},
        "access": {"format": LOG_FORMAT},
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}

# Suppress verbose logs from third-party libraries
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

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
