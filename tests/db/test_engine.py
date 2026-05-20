"""Tests for _run_alembic_migrations advisory lock behaviour."""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch


def _run_with_mocks(database_url: str, *, lock_raises: bool = False):
    """Exercise _run_alembic_migrations with all external dependencies mocked."""
    mock_conn = MagicMock()
    if lock_raises:

        def _selective_execute(*args, **_kwargs):
            if args and "pg_advisory_lock" in str(args[0]):
                raise Exception("lock error")
            return MagicMock()

        mock_conn.execute.side_effect = _selective_execute

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = lambda _: mock_conn
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = []

    with ExitStack() as stack:
        mock_upgrade = stack.enter_context(patch("alembic.command.upgrade"))
        stack.enter_context(patch("alembic.command.stamp"))
        stack.enter_context(patch("alembic.config.Config"))
        stack.enter_context(patch("pathlib.Path.exists", return_value=True))
        stack.enter_context(patch("sqlalchemy.create_engine", return_value=mock_engine))
        stack.enter_context(patch("sqlalchemy.inspect", return_value=mock_inspector))

        from baloo.db.engine import _run_alembic_migrations

        result = _run_alembic_migrations(database_url)

    executed_texts = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    return result, mock_upgrade, executed_texts


def test_advisory_lock_acquired_for_postgres():
    result, mock_upgrade, executed_texts = _run_with_mocks("postgresql://localhost/test")

    assert result is True
    assert any("pg_advisory_lock" in t for t in executed_texts)
    mock_upgrade.assert_called_once()


def test_advisory_lock_skipped_for_sqlite():
    result, mock_upgrade, executed_texts = _run_with_mocks("sqlite:///test.db")

    assert result is True
    assert not any("pg_advisory_lock" in t for t in executed_texts)
    mock_upgrade.assert_called_once()


def test_advisory_lock_failure_does_not_block_migrations():
    result, mock_upgrade, _ = _run_with_mocks("postgresql://localhost/test", lock_raises=True)

    assert result is True
    mock_upgrade.assert_called_once()
