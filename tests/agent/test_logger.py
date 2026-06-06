"""Tests for ReviewLogger."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from baloo.agent.logger import ReviewLogger


class TestReviewLoggerNoOp:
    """When review_id is None, logger is a no-op."""

    @pytest.mark.asyncio
    async def test_noop_does_not_write(self):
        logger = ReviewLogger(review_id=None)
        # Should not raise
        await logger.agent_started(model="test", thinking_level="medium")
        await logger.turn_completed(turn_number=1, tokens_in=100, tokens_out=50)
        await logger.json_parse_failed(raw_text="bad", char_count=3)
        await logger.agent_error(error_message="boom", error_category="test")


class TestReviewLoggerEvents:
    """Test that events produce correct ReviewLog rows."""

    @pytest.mark.asyncio
    async def test_agent_started_creates_log(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        logger = ReviewLogger(review_id=42, session=mock_session)
        await logger.agent_started(model="claude-sonnet-4-6", thinking_level="medium")

        mock_session.add.assert_called_once()
        log_row = mock_session.add.call_args[0][0]
        assert log_row.review_id == 42
        assert log_row.event_type == "agent_started"
        assert "claude-sonnet-4-6" in log_row.message
        assert log_row.raw_text is None

        meta = json.loads(log_row.metadata_json)
        assert meta["model"] == "claude-sonnet-4-6"
        assert meta["thinking_level"] == "medium"

    @pytest.mark.asyncio
    async def test_json_parse_failed_stores_raw_text(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        logger = ReviewLogger(review_id=42, session=mock_session)
        await logger.json_parse_failed(raw_text="some bad text", char_count=13)

        log_row = mock_session.add.call_args[0][0]
        assert log_row.event_type == "json_parse_failed"
        assert log_row.raw_text == "some bad text"

    @pytest.mark.asyncio
    async def test_agent_completed_metadata(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        logger = ReviewLogger(review_id=42, session=mock_session)
        await logger.agent_completed(tokens_in=1000, tokens_out=500, cost=0.05, duration=12.3)

        log_row = mock_session.add.call_args[0][0]
        assert log_row.event_type == "agent_completed"
        meta = json.loads(log_row.metadata_json)
        assert meta["tokens_in"] == 1000
        assert meta["cost"] == 0.05
        assert meta["duration"] == 12.3

    @pytest.mark.asyncio
    async def test_tool_use_records_success(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        logger = ReviewLogger(review_id=42, session=mock_session)
        await logger.tool_use(tool_name="read", file_path="src/foo.py", success=True)

        log_row = mock_session.add.call_args[0][0]
        assert log_row.event_type == "tool_use"
        meta = json.loads(log_row.metadata_json)
        assert meta["tool_name"] == "read"
        assert meta["file_path"] == "src/foo.py"
        assert meta["success"] is True

    @pytest.mark.asyncio
    async def test_tool_use_records_failure_in_message_and_metadata(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        logger = ReviewLogger(review_id=42, session=mock_session)
        await logger.tool_use(tool_name="read", file_path="src/missing.py", success=False)

        log_row = mock_session.add.call_args[0][0]
        meta = json.loads(log_row.metadata_json)
        assert meta["success"] is False
        assert "failed" in log_row.message.lower()

    @pytest.mark.asyncio
    async def test_log_exception_is_swallowed(self):
        """Logger errors must not crash the review."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock(side_effect=Exception("DB down"))

        logger = ReviewLogger(review_id=42, session=mock_session)
        # Should not raise
        await logger.agent_started(model="test", thinking_level="off")


@pytest.mark.asyncio
async def test_review_logger_sets_installation_id_on_rows():
    """ReviewLogger populates installation_id on ReviewLog rows."""
    logged_rows = []
    mock_session = MagicMock()
    mock_session.add = lambda row: logged_rows.append(row)
    mock_session.flush = AsyncMock()

    rl = ReviewLogger(review_id=1, session=mock_session, installation_id="inst_log")
    await rl.agent_started(model="claude", thinking_level="medium")

    assert len(logged_rows) == 1
    assert logged_rows[0].installation_id == "inst_log"


@pytest.mark.asyncio
async def test_review_logger_installation_id_none_by_default():
    logged_rows = []
    mock_session = MagicMock()
    mock_session.add = lambda row: logged_rows.append(row)
    mock_session.flush = AsyncMock()

    rl = ReviewLogger(review_id=1, session=mock_session)
    await rl.agent_started(model="claude", thinking_level="medium")

    assert logged_rows[0].installation_id is None


@pytest.mark.asyncio
async def test_tool_use_includes_agent_label():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    logger = ReviewLogger(review_id=42, session=mock_session, agent_label="fidelity")
    await logger.tool_use(tool_name="read", file_path="a.py", success=True)

    row = mock_session.add.call_args[0][0]
    meta = json.loads(row.metadata_json)
    assert meta["agent"] == "fidelity"


@pytest.mark.asyncio
async def test_default_agent_label_is_review():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    logger = ReviewLogger(review_id=42, session=mock_session)
    await logger.tool_use(tool_name="read", file_path="a.py", success=True)

    row = mock_session.add.call_args[0][0]
    meta = json.loads(row.metadata_json)
    assert meta["agent"] == "review"
