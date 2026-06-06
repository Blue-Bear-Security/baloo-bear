"""Tests for centralized logging configuration.

The critical regression these guard: Alembic's ``fileConfig`` (run on every
in-app migration) clobbers the root logger — stripping timestamps and raising
the level to WARN, which silently drops every ``baloo.*`` INFO line.
``configure_logging`` must be able to undo that.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

import pytest

from baloo.logging_config import (
    LOG_DATEFMT,
    LOG_FORMAT,
    UVICORN_LOG_CONFIG,
    configure_logging,
)


@pytest.fixture(autouse=True)
def _restore_logging():
    """Leave global logging state as we found it."""
    root = logging.getLogger()
    saved = (root.level, list(root.handlers), logging.Formatter.converter)
    try:
        yield
    finally:
        root.setLevel(saved[0])
        root.handlers[:] = saved[1]
        logging.Formatter.converter = saved[2]


def test_configure_logging_sets_format_and_level():
    configure_logging("INFO")
    root = logging.getLogger()
    assert root.level == logging.INFO
    assert root.handlers, "expected a root handler"
    assert root.handlers[0].formatter._fmt == LOG_FORMAT


def test_configure_logging_restores_after_alembic_fileconfig():
    """fileConfig strips the timestamp and raises root to WARN; re-applying
    configure_logging must restore both so baloo INFO lines survive."""
    configure_logging("INFO")
    fileConfig("alembic.ini", disable_existing_loggers=False)

    # Sanity: alembic really did raise the root level to WARN (alembic.ini's
    # [logger_root] level) — otherwise this test would be vacuous. This is the
    # hazard that silently drops baloo.* INFO lines.
    assert logging.getLogger().level == logging.WARNING

    configure_logging("INFO")

    root = logging.getLogger()
    assert root.level == logging.INFO
    assert root.handlers[0].formatter._fmt == LOG_FORMAT
    assert logging.getLogger("baloo.agent.repo_provision").isEnabledFor(logging.INFO)


def test_alembic_ini_format_matches_app_format():
    """Standalone `alembic` CLI output should match the app's format."""
    import configparser

    parser = configparser.ConfigParser(interpolation=None)
    parser.read("alembic.ini")
    assert parser.get("formatter_generic", "format") == LOG_FORMAT
    assert parser.get("formatter_generic", "datefmt") == LOG_DATEFMT


def test_uvicorn_log_config_uses_shared_format():
    for name in ("default", "access"):
        assert UVICORN_LOG_CONFIG["formatters"][name]["format"] == LOG_FORMAT
        assert UVICORN_LOG_CONFIG["formatters"][name]["datefmt"] == LOG_DATEFMT
