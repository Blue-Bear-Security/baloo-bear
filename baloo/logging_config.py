"""Centralized logging configuration for the Baloo application.

Every log line — app code, uvicorn, and Alembic — should share one format:

    2026-06-06 15:31:24 UTC INFO  [baloo.agent.pi_runtime] ...

The non-obvious hazard this module guards against: Alembic's ``env.py`` calls
``logging.config.fileConfig(alembic.ini)`` whenever migrations run. ``fileConfig``
clears the root logger's handlers and installs Alembic's own (timestamp-less)
handler *and* raises the root level to WARN — silently dropping every ``baloo.*``
INFO line for the rest of the process. ``configure_logging`` is therefore called
both at startup AND again after migrations (see ``baloo.db.engine``) to restore
the app's handler, format, and level.
"""

from __future__ import annotations

import logging
import time

# Shared by the app, uvicorn, and alembic.ini's formatter — keep all three in sync.
LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S UTC"

# Uvicorn log config — override its default formatters so every line gets a
# timestamp, matching the rest of the application output.
UVICORN_LOG_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": LOG_FORMAT, "datefmt": LOG_DATEFMT},
        "access": {"format": LOG_FORMAT, "datefmt": LOG_DATEFMT},
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


def configure_logging(level: str | int = "INFO") -> None:
    """(Re)apply the canonical root logging configuration.

    Idempotent and safe to call repeatedly: ``force=True`` replaces any existing
    root handlers (including ones Alembic's ``fileConfig`` may have installed) so
    the app's format and level always win.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATEFMT, force=True)
    # Emit all timestamps in UTC (matches the " UTC" suffix in LOG_DATEFMT).
    logging.Formatter.converter = time.gmtime

    # Suppress verbose logs from third-party libraries.
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
