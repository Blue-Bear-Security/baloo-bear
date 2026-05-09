# Thread Conversation Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight thread-reply agent that responds to developer comments on Baloo findings, with per-repo feedback signals injected into future reviews.

**Architecture:** Webhook handler re-enables `pull_request_review_comment` events and filters to Baloo-thread replies. A new ThreadAgent (cheap model, no tools) classifies the developer's response and optionally replies. Concessions write feedback signals to the DB, which are injected as LLM context in future review prompts.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy (async), Alembic, PI runtime (RPC subprocess), Pydantic

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `baloo/agent/thread_prompts.py` | System prompt and prompt builder for the thread agent |
| Create | `baloo/agent/thread_agent.py` | ThreadAgent class — runs PI with narrow context, parses classification |
| Create | `baloo/db/feedback_service.py` | CRUD for `feedback_signals` table |
| Create | `baloo/db/migrations/versions/005_add_feedback_signals.py` | Alembic migration |
| Create | `tests/agent/test_thread_prompts.py` | Tests for thread prompt building |
| Create | `tests/agent/test_thread_agent.py` | Tests for ThreadAgent classification and reply logic |
| Create | `tests/db/test_feedback_service.py` | Tests for feedback signal CRUD |
| Create | `tests/github/test_thread_webhook.py` | Tests for webhook handler thread-reply flow |
| Modify | `baloo/config/settings.py` | Add thread agent + feedback signal settings |
| Modify | `baloo/db/models.py` | Add `FeedbackSignal` ORM model |
| Modify | `baloo/github/webhook_handler.py` | Handle `pull_request_review_comment` events |
| Modify | `baloo/agent/prompts.py` | Add `_feedback_signals_section()` to review prompt |

---

### Task 1: Configuration Settings

**Files:**
- Modify: `baloo/config/settings.py:93-109` (after FP verification settings)
- Test: `tests/agent/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agent/test_config.py — append to existing file

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_config.py::test_thread_agent_settings_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'thread_agent_enabled'`

- [ ] **Step 3: Add settings to Settings class**

Add after the FP verification section (line ~109) in `baloo/config/settings.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_config.py::test_thread_agent_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add baloo/config/settings.py tests/agent/test_config.py
git commit -m "feat(thread-agent): add configuration settings for thread agent and feedback signals"
```

---

### Task 2: FeedbackSignal ORM Model + Migration

**Files:**
- Modify: `baloo/db/models.py:132` (after FindingOutcome class)
- Create: `baloo/db/migrations/versions/005_add_feedback_signals.py`
- Test: `tests/db/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_models.py — append to existing file

def test_feedback_signal_model_exists():
    """FeedbackSignal model is importable and has expected columns."""
    from baloo.db.models import FeedbackSignal

    assert FeedbackSignal.__tablename__ == "feedback_signals"
    columns = {c.name for c in FeedbackSignal.__table__.columns}
    assert columns == {
        "id", "repo", "pattern", "category", "file_glob",
        "developer", "thread_url", "pr_number",
        "created_at", "last_matched_at", "times_matched",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/db/test_models.py::test_feedback_signal_model_exists -v`
Expected: FAIL — `ImportError: cannot import name 'FeedbackSignal'`

- [ ] **Step 3: Add FeedbackSignal model**

Append to `baloo/db/models.py` after the `FindingOutcome` class:

```python
class FeedbackSignal(Base):
    __tablename__ = "feedback_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo: Mapped[str] = mapped_column(Text, nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    file_glob: Mapped[str | None] = mapped_column(Text, nullable=True)
    developer: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    times_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_feedback_signals_repo", "repo"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/db/test_models.py::test_feedback_signal_model_exists -v`
Expected: PASS

- [ ] **Step 5: Create Alembic migration**

Create `baloo/db/migrations/versions/005_add_feedback_signals.py`:

```python
"""Add feedback_signals table for thread agent memory.

Revision ID: 005
Revises: 004
Create Date: 2026-05-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "feedback_signals" not in existing_tables:
        op.create_table(
            "feedback_signals",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("repo", sa.Text, nullable=False),
            sa.Column("pattern", sa.Text, nullable=False),
            sa.Column("category", sa.String(50), nullable=False),
            sa.Column("file_glob", sa.Text, nullable=True),
            sa.Column("developer", sa.String(255), nullable=False),
            sa.Column("thread_url", sa.Text, nullable=True),
            sa.Column("pr_number", sa.Integer, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_matched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("times_matched", sa.Integer, nullable=False, server_default="0"),
        )
        op.create_index("ix_feedback_signals_repo", "feedback_signals", ["repo"])


def downgrade() -> None:
    op.drop_index("ix_feedback_signals_repo", table_name="feedback_signals")
    op.drop_table("feedback_signals")
```

- [ ] **Step 6: Run all model tests**

Run: `uv run pytest tests/db/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add baloo/db/models.py baloo/db/migrations/versions/005_add_feedback_signals.py tests/db/test_models.py
git commit -m "feat(thread-agent): add FeedbackSignal model and migration"
```

---

### Task 3: Feedback Signal Service

**Files:**
- Create: `baloo/db/feedback_service.py`
- Create: `tests/db/test_feedback_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/db/test_feedback_service.py`:

```python
"""Tests for the feedback signal service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.db.feedback_service import FeedbackService


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock()
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    factory = MagicMock(return_value=mock_session)
    return factory


@pytest.mark.asyncio
async def test_write_signal_calls_session_add(mock_session, mock_session_factory):
    """write_signal adds a FeedbackSignal row to the session."""
    with patch("baloo.db.feedback_service.get_session_factory", return_value=mock_session_factory):
        with patch("baloo.db.feedback_service.get_settings") as mock_settings:
            mock_settings.return_value.database_url = "postgresql+asyncpg://localhost/test"
            mock_settings.return_value.database_enabled = True
            mock_settings.return_value.feedback_signals_enabled = True

            await FeedbackService.write_signal(
                repo="org/repo",
                pattern="except pass in retry loops is intentional",
                category="Silent Failures",
                developer="alice",
                file_glob="app/retry/*.py",
                thread_url="https://github.com/org/repo/pull/1#discussion_r123",
                pr_number=1,
            )

            mock_session.add.assert_called_once()
            added = mock_session.add.call_args[0][0]
            assert added.repo == "org/repo"
            assert added.pattern == "except pass in retry loops is intentional"
            assert added.category == "Silent Failures"
            assert added.developer == "alice"
            assert added.file_glob == "app/retry/*.py"


@pytest.mark.asyncio
async def test_write_signal_skipped_when_disabled(mock_session, mock_session_factory):
    """write_signal is a no-op when feedback signals are disabled."""
    with patch("baloo.db.feedback_service.get_settings") as mock_settings:
        mock_settings.return_value.feedback_signals_enabled = False

        await FeedbackService.write_signal(
            repo="org/repo",
            pattern="test",
            category="Bugs",
            developer="bob",
        )

        mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_write_signal_skipped_when_db_disabled(mock_session, mock_session_factory):
    """write_signal is a no-op when database is disabled."""
    with patch("baloo.db.feedback_service.get_settings") as mock_settings:
        mock_settings.return_value.feedback_signals_enabled = True
        mock_settings.return_value.database_enabled = False

        await FeedbackService.write_signal(
            repo="org/repo",
            pattern="test",
            category="Bugs",
            developer="bob",
        )

        mock_session.add.assert_not_called()


def test_format_signals_for_prompt_empty():
    """Empty signal list produces empty string."""
    assert FeedbackService.format_signals_for_prompt([]) == ""


def test_format_signals_for_prompt_formats_correctly():
    """Signals are formatted as a readable prompt section."""
    signals = [
        MagicMock(
            category="Silent Failures",
            file_glob="app/retry/*.py",
            pattern="except pass in retry loops is intentional",
            developer="alice",
            created_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        ),
        MagicMock(
            category="Security",
            file_glob=None,
            pattern="shell=True is acceptable in dev scripts",
            developer="bob",
            created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        ),
    ]
    result = FeedbackService.format_signals_for_prompt(signals)
    assert "Silent Failures" in result
    assert "app/retry/*.py" in result
    assert "except pass in retry loops is intentional" in result
    assert "@alice" in result
    assert "Security" in result
    assert "shell=True" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/db/test_feedback_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'baloo.db.feedback_service'`

- [ ] **Step 3: Implement FeedbackService**

Create `baloo/db/feedback_service.py`:

```python
"""CRUD service for feedback signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import FeedbackSignal

logger = logging.getLogger(__name__)


class FeedbackService:
    """Service for reading and writing per-repo feedback signals."""

    @staticmethod
    async def write_signal(
        *,
        repo: str,
        pattern: str,
        category: str,
        developer: str,
        file_glob: str | None = None,
        thread_url: str | None = None,
        pr_number: int | None = None,
    ) -> None:
        """Write a feedback signal to the database.

        No-op if feedback signals or the database are disabled.
        """
        settings = get_settings()
        if not settings.feedback_signals_enabled or not settings.database_enabled:
            return

        session_factory = get_session_factory(settings.database_url)
        async with session_factory() as session:
            async with session.begin():
                signal = FeedbackSignal(
                    repo=repo,
                    pattern=pattern,
                    category=category,
                    file_glob=file_glob,
                    developer=developer,
                    thread_url=thread_url,
                    pr_number=pr_number,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(signal)

        logger.info(
            "Wrote feedback signal for %s: [%s] %s (by @%s)",
            repo, category, pattern[:80], developer,
        )

    @staticmethod
    async def get_signals_for_repo(repo: str) -> list[FeedbackSignal]:
        """Fetch active (non-expired) feedback signals for a repo.

        Returns an empty list if feedback signals or the database are disabled.
        """
        settings = get_settings()
        if not settings.feedback_signals_enabled or not settings.database_enabled:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.feedback_signals_ttl_days)

        session_factory = get_session_factory(settings.database_url)
        async with session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(FeedbackSignal)
                .where(FeedbackSignal.repo == repo)
                .where(FeedbackSignal.created_at > cutoff)
                .order_by(FeedbackSignal.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    def format_signals_for_prompt(signals: list) -> str:
        """Format feedback signals as a prompt section for the review agent.

        Args:
            signals: List of FeedbackSignal objects.

        Returns:
            Formatted string to inject into the review prompt, or empty string.
        """
        if not signals:
            return ""

        lines = []
        for signal in signals:
            scope = f" in `{signal.file_glob}`" if signal.file_glob else ""
            date_str = signal.created_at.strftime("%Y-%m-%d")
            lines.append(
                f"- {signal.category}{scope}: "
                f'"{signal.pattern}" '
                f"(@{signal.developer}, {date_str})"
            )

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/db/test_feedback_service.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add baloo/db/feedback_service.py tests/db/test_feedback_service.py
git commit -m "feat(thread-agent): add FeedbackService for reading/writing feedback signals"
```

---

### Task 4: Thread Prompts

**Files:**
- Create: `baloo/agent/thread_prompts.py`
- Create: `tests/agent/test_thread_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_thread_prompts.py`:

```python
"""Tests for thread agent prompt building."""

from __future__ import annotations

from datetime import datetime, timezone

from baloo.agent.thread_prompts import (
    THREAD_AGENT_SYSTEM_PROMPT,
    build_thread_prompt,
)
from baloo.github.models import DiscussionComment


def _make_comment(author: str, body: str, is_baloo: bool = False) -> DiscussionComment:
    now = datetime.now(timezone.utc)
    return DiscussionComment(
        id=1, author=author, body=body, created_at=now, updated_at=now,
        source="review_comment", is_baloo=is_baloo,
    )


def test_system_prompt_contains_classification_instructions():
    assert "acknowledged" in THREAD_AGENT_SYSTEM_PROMPT
    assert "disagreed_valid" in THREAD_AGENT_SYSTEM_PROMPT
    assert "disagreed_invalid" in THREAD_AGENT_SYSTEM_PROMPT
    assert "question" in THREAD_AGENT_SYSTEM_PROMPT
    assert "unclear" in THREAD_AGENT_SYSTEM_PROMPT


def test_build_thread_prompt_includes_thread_history():
    thread_comments = [
        _make_comment("baloo[bot]", "**[HIGH] Security** - SQL injection risk", is_baloo=True),
        _make_comment("alice", "This uses parameterized queries, not string concat"),
    ]
    result = build_thread_prompt(
        thread_comments=thread_comments,
        code_context="def query(user_id):\n    return db.execute(stmt, [user_id])",
        file_path="src/auth.py",
        line_number=42,
    )
    assert "SQL injection risk" in result
    assert "parameterized queries" in result
    assert "src/auth.py" in result
    assert "42" in result


def test_build_thread_prompt_includes_code_context():
    thread_comments = [
        _make_comment("baloo[bot]", "Finding body", is_baloo=True),
        _make_comment("dev", "Why?"),
    ]
    code = "try:\n    result = fetch()\nexcept Exception:\n    pass"
    result = build_thread_prompt(
        thread_comments=thread_comments,
        code_context=code,
        file_path="app/retry.py",
        line_number=10,
    )
    assert "fetch()" in result
    assert "except Exception" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_thread_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'baloo.agent.thread_prompts'`

- [ ] **Step 3: Implement thread prompts**

Create `baloo/agent/thread_prompts.py`:

```python
"""Prompt templates for the thread conversation agent."""

from __future__ import annotations

from baloo.github.models import DiscussionComment

THREAD_AGENT_SYSTEM_PROMPT = """You are Baloo, responding to a developer's reply on one of your code review findings.

## Your Task

Classify the developer's response and decide how to reply.

## Classifications

- **acknowledged**: Developer fixed or accepted the issue ("fixed", "done", "updated", pushed a fix). No reply needed.
- **disagreed_valid**: Developer explains why the flagged pattern is intentional and their reasoning is sound. Concede gracefully.
- **disagreed_invalid**: Developer disagrees but their reasoning doesn't hold (e.g., the risk is real despite their claim). Explain once with evidence.
- **question**: Developer asks for clarification or help understanding the issue. Explain clearly and suggest a concrete fix.
- **unclear**: Ambiguous or unrelated reply. No reply needed.

## Rules

- Be concise and conversational. No severity badges, no formatted finding blocks.
- If conceding: acknowledge their reasoning specifically, don't just say "you're right".
- If explaining: cite specific code behavior or risk, not abstract principles.
- If answering a question: include a concrete code example for the fix when possible.
- NEVER repeat your original finding verbatim. The developer already read it.
- You are having a conversation, not issuing a report.

## Output

Return ONLY a JSON object:

```json
{
  "classification": "acknowledged | disagreed_valid | disagreed_invalid | question | unclear",
  "reply": "your reply text, or null if no reply needed",
  "reasoning": "1-2 sentence internal reasoning for your classification",
  "feedback_signal": {
    "pattern": "natural language description of the accepted pattern",
    "category": "finding category",
    "file_glob": "optional file glob or null"
  }
}
```

The `feedback_signal` field should ONLY be present when classification is `disagreed_valid`.
For all other classifications, set `feedback_signal` to null.

IMPORTANT: Return ONLY the JSON object. No markdown fences, no extra text."""


def build_thread_prompt(
    *,
    thread_comments: list[DiscussionComment],
    code_context: str,
    file_path: str,
    line_number: int,
) -> str:
    """Build the user prompt for the thread agent.

    Args:
        thread_comments: Full thread history in chronological order.
        code_context: Current code around the finding location.
        file_path: Path to the file containing the finding.
        line_number: Line number of the finding.

    Returns:
        Formatted prompt string.
    """
    # Format thread history
    thread_lines = []
    for comment in thread_comments:
        role = "Baloo" if comment.is_baloo else f"@{comment.author}"
        thread_lines.append(f"**{role}:**\n{comment.body}")

    thread_history = "\n\n---\n\n".join(thread_lines)

    return f"""## Thread on {file_path}:{line_number}

{thread_history}

## Current Code at {file_path}:{line_number}

```
{code_context}
```

Classify the developer's latest response and decide whether to reply."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_thread_prompts.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add baloo/agent/thread_prompts.py tests/agent/test_thread_prompts.py
git commit -m "feat(thread-agent): add thread agent system prompt and prompt builder"
```

---

### Task 5: ThreadAgent

**Files:**
- Create: `baloo/agent/thread_agent.py`
- Create: `tests/agent/test_thread_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_thread_agent.py`:

```python
"""Tests for the ThreadAgent."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from baloo.agent.thread_agent import ThreadAgent, ThreadAgentResult
from baloo.github.models import DiscussionComment


def _make_comment(author: str, body: str, is_baloo: bool = False) -> DiscussionComment:
    now = datetime.now(timezone.utc)
    return DiscussionComment(
        id=1, author=author, body=body, created_at=now, updated_at=now,
        source="review_comment", is_baloo=is_baloo,
    )


@pytest.mark.asyncio
async def test_thread_agent_concede():
    """ThreadAgent returns disagreed_valid with reply and feedback signal."""
    agent = ThreadAgent()

    mock_response = {
        "classification": "disagreed_valid",
        "reply": "Got it, makes sense for retry loops.",
        "reasoning": "Developer explained retry semantics.",
        "feedback_signal": {
            "pattern": "except pass in retry loops is intentional",
            "category": "Silent Failures",
            "file_glob": "app/retry/*.py",
        },
    }

    with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (mock_response, {"cost_usd": 0.001, "model": "claude-haiku-4-5-20251001"})

        result = await agent.classify(
            thread_comments=[
                _make_comment("baloo[bot]", "**[HIGH] Silent Failures** - except pass", is_baloo=True),
                _make_comment("alice", "This is intentional for retry loops"),
            ],
            code_context="try:\n    op()\nexcept Exception:\n    pass",
            file_path="app/retry/handler.py",
            line_number=15,
        )

    assert isinstance(result, ThreadAgentResult)
    assert result.classification == "disagreed_valid"
    assert result.reply == "Got it, makes sense for retry loops."
    assert result.feedback_signal is not None
    assert result.feedback_signal["pattern"] == "except pass in retry loops is intentional"


@pytest.mark.asyncio
async def test_thread_agent_acknowledged():
    """ThreadAgent returns acknowledged with no reply."""
    agent = ThreadAgent()

    mock_response = {
        "classification": "acknowledged",
        "reply": None,
        "reasoning": "Developer says they fixed it.",
        "feedback_signal": None,
    }

    with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (mock_response, {"cost_usd": 0.0005})

        result = await agent.classify(
            thread_comments=[
                _make_comment("baloo[bot]", "Finding", is_baloo=True),
                _make_comment("dev", "Fixed in latest commit"),
            ],
            code_context="fixed code",
            file_path="src/foo.py",
            line_number=10,
        )

    assert result.classification == "acknowledged"
    assert result.reply is None
    assert result.feedback_signal is None


@pytest.mark.asyncio
async def test_thread_agent_parse_failure_returns_unclear():
    """Unparseable response defaults to unclear with no reply."""
    agent = ThreadAgent()

    with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (None, {"cost_usd": 0.0})

        result = await agent.classify(
            thread_comments=[
                _make_comment("baloo[bot]", "Finding", is_baloo=True),
                _make_comment("dev", "hmm"),
            ],
            code_context="code",
            file_path="f.py",
            line_number=1,
        )

    assert result.classification == "unclear"
    assert result.reply is None


@pytest.mark.asyncio
async def test_thread_agent_exception_returns_unclear():
    """Agent exceptions are caught and return unclear."""
    agent = ThreadAgent()

    with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("PI crashed")

        result = await agent.classify(
            thread_comments=[
                _make_comment("baloo[bot]", "Finding", is_baloo=True),
                _make_comment("dev", "why?"),
            ],
            code_context="code",
            file_path="f.py",
            line_number=1,
        )

    assert result.classification == "unclear"
    assert result.reply is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_thread_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'baloo.agent.thread_agent'`

- [ ] **Step 3: Implement ThreadAgent**

Create `baloo/agent/thread_agent.py`:

```python
"""Thread conversation agent — classifies developer replies and generates responses."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from baloo.agent.config import get_agent_options
from baloo.agent.pi_runtime import PIAgentBase, PIAgentOptions
from baloo.agent.thread_prompts import THREAD_AGENT_SYSTEM_PROMPT, build_thread_prompt
from baloo.config.settings import get_settings
from baloo.github.models import DiscussionComment

logger = logging.getLogger(__name__)

VALID_CLASSIFICATIONS = {
    "acknowledged", "disagreed_valid", "disagreed_invalid", "question", "unclear",
}


@dataclass
class ThreadAgentResult:
    """Result of a thread agent classification."""

    classification: str = "unclear"
    reply: str | None = None
    reasoning: str = ""
    feedback_signal: dict | None = None
    cost_usd: float = 0.0
    model: str = ""


class ThreadAgent:
    """Classify developer replies to Baloo findings and generate responses.

    Uses a cheap/fast model with no tools. Fail-safe: returns ``unclear``
    on any error so the thread is left open without a reply.
    """

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model = model or settings.thread_agent_model

    async def classify(
        self,
        *,
        thread_comments: list[DiscussionComment],
        code_context: str,
        file_path: str,
        line_number: int,
    ) -> ThreadAgentResult:
        """Classify a developer's reply and generate a response.

        Args:
            thread_comments: Full thread history in chronological order.
            code_context: Current code around the finding location.
            file_path: Path to the file containing the finding.
            line_number: Line number of the finding.

        Returns:
            ThreadAgentResult with classification, optional reply, and optional feedback signal.
        """
        prompt = build_thread_prompt(
            thread_comments=thread_comments,
            code_context=code_context,
            file_path=file_path,
            line_number=line_number,
        )

        try:
            structured, metadata = await self._run_query(prompt)
        except Exception as exc:
            logger.warning("Thread agent failed: %s", exc)
            return ThreadAgentResult(classification="unclear")

        if not structured or not isinstance(structured, dict):
            logger.warning("Thread agent returned unparseable response")
            return ThreadAgentResult(classification="unclear")

        classification = structured.get("classification", "unclear")
        if classification not in VALID_CLASSIFICATIONS:
            classification = "unclear"

        reply = structured.get("reply")
        if reply and not isinstance(reply, str):
            reply = None

        feedback_signal = None
        if classification == "disagreed_valid":
            raw_signal = structured.get("feedback_signal")
            if isinstance(raw_signal, dict) and raw_signal.get("pattern"):
                feedback_signal = {
                    "pattern": raw_signal["pattern"],
                    "category": raw_signal.get("category", ""),
                    "file_glob": raw_signal.get("file_glob"),
                }

        return ThreadAgentResult(
            classification=classification,
            reply=reply,
            reasoning=structured.get("reasoning", ""),
            feedback_signal=feedback_signal,
            cost_usd=metadata.get("cost_usd", 0.0),
            model=metadata.get("model", self.model),
        )

    async def _run_query(self, prompt: str) -> tuple[dict | None, dict]:
        """Run the PI agent query. Separated for testability."""
        options = get_agent_options(
            model=self.model,
            thinking_level="off",
        )
        options.system_prompt = THREAD_AGENT_SYSTEM_PROMPT
        options.no_tools = True
        options.max_turns = 2

        agent = PIAgentBase(options)
        return await agent.run_query(prompt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_thread_agent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add baloo/agent/thread_agent.py tests/agent/test_thread_agent.py
git commit -m "feat(thread-agent): add ThreadAgent with classification and reply generation"
```

---

### Task 6: Feedback Signals in Review Prompts

**Files:**
- Modify: `baloo/agent/prompts.py:225-226` (after `_discussion_section`)
- Test: `tests/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prompts.py`:

```python
from unittest.mock import MagicMock
from datetime import datetime, timezone


def test_feedback_signals_section_empty():
    """No signals produces empty section."""
    from baloo.agent.prompts import _feedback_signals_section
    assert _feedback_signals_section([]) == ""


def test_feedback_signals_section_formats_signals():
    """Signals are formatted into a prompt section with header."""
    from baloo.agent.prompts import _feedback_signals_section

    signals = [
        MagicMock(
            category="Silent Failures",
            file_glob="app/retry/*.py",
            pattern="except pass in retry loops is intentional",
            developer="alice",
            created_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        ),
    ]
    result = _feedback_signals_section(signals)
    assert "Team Feedback Signals" in result
    assert "Silent Failures" in result
    assert "app/retry/*.py" in result
    assert "except pass in retry loops" in result
    assert "@alice" in result
    assert "avoid re-flagging" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py::test_feedback_signals_section_empty tests/test_prompts.py::test_feedback_signals_section_formats_signals -v`
Expected: FAIL — `ImportError: cannot import name '_feedback_signals_section'`

- [ ] **Step 3: Add _feedback_signals_section to prompts.py**

Add to `baloo/agent/prompts.py` after the `_discussion_section` function (after line ~225):

```python
def _feedback_signals_section(signals: list) -> str:
    """Format feedback signals as a review prompt section.

    Args:
        signals: List of FeedbackSignal objects (or mocks with same attributes).

    Returns:
        Formatted prompt section, or empty string if no signals.
    """
    from baloo.db.feedback_service import FeedbackService

    formatted = FeedbackService.format_signals_for_prompt(signals)
    if not formatted:
        return ""

    return f"""## Team Feedback Signals

The following patterns have been previously reviewed and accepted by this team.
Consider these when assigning severity. You may still flag if the specific
instance is genuinely dangerous, but avoid re-flagging patterns the team has
explicitly accepted.

{formatted}

"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompts.py::test_feedback_signals_section_empty tests/test_prompts.py::test_feedback_signals_section_formats_signals -v`
Expected: All PASS

- [ ] **Step 5: Wire feedback signals into `build_pr_review_prompt`**

In `baloo/agent/prompts.py`, modify the `build_pr_review_prompt` function. After the `_discussion_section(pr_context)` call in the full review prompt template (around line 436), add the feedback signals section. The prompt template f-string should include `{feedback_signals_text}`:

At the top of `build_pr_review_prompt`, after building `guidelines_section`, add:

```python
    # Build feedback signals section
    feedback_signals = _ctx_get(pr_context, "feedback_signals", [])
    feedback_signals_text = _feedback_signals_section(feedback_signals)
```

Then in the f-string template, add `{feedback_signals_text}` after `{_discussion_section(pr_context)}` (both in the full prompt and the simple prompt).

- [ ] **Step 6: Run full prompts test suite**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add baloo/agent/prompts.py tests/test_prompts.py
git commit -m "feat(thread-agent): inject feedback signals into review prompts"
```

---

### Task 7: Webhook Handler — Thread Reply Flow

**Files:**
- Modify: `baloo/github/webhook_handler.py:640-652`
- Create: `tests/github/test_thread_webhook.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/github/test_thread_webhook.py`:

```python
"""Tests for the thread reply webhook handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from baloo.github.webhook_handler import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _make_review_comment_payload(
    *,
    comment_body: str = "This uses parameterized queries",
    comment_author: str = "alice",
    in_reply_to_id: int = 100,
    comment_id: int = 200,
    path: str = "src/auth.py",
    line: int = 42,
    pr_number: int = 1,
    repo: str = "org/repo",
    installation_id: int = 1,
) -> dict:
    return {
        "action": "created",
        "comment": {
            "id": comment_id,
            "body": comment_body,
            "user": {"login": comment_author, "id": 1, "avatar_url": "", "html_url": ""},
            "in_reply_to_id": in_reply_to_id,
            "path": path,
            "line": line,
            "original_line": line,
            "html_url": f"https://github.com/{repo}/pull/{pr_number}#discussion_r{comment_id}",
            "created_at": "2026-05-09T12:00:00Z",
        },
        "pull_request": {
            "number": pr_number,
            "title": "Test PR",
            "body": "",
            "state": "open",
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "user": {"login": "dev", "id": 2, "avatar_url": "", "html_url": ""},
            "head": {"sha": "abc123", "ref": "feat/test"},
            "base": {"ref": "main"},
            "merged": False,
            "draft": False,
        },
        "repository": {
            "id": 1,
            "name": "repo",
            "full_name": repo,
            "owner": {"login": "org", "id": 1, "avatar_url": "", "html_url": ""},
            "html_url": f"https://github.com/{repo}",
            "default_branch": "main",
        },
        "installation": {"id": installation_id},
        "sender": {"login": comment_author, "id": 1, "avatar_url": "", "html_url": ""},
    }


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.settings")
def test_thread_comment_ignored_when_disabled(mock_settings, mock_verify, client):
    """Thread comments are ignored when thread agent is disabled."""
    mock_settings.thread_agent_enabled = False

    response = client.post(
        "/webhook",
        json=_make_review_comment_payload(),
        headers={"X-GitHub-Event": "pull_request_review_comment", "X-Hub-Signature-256": "sha256=fake"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.settings")
def test_thread_comment_ignored_when_no_reply_to(mock_settings, mock_verify, client):
    """Comments that are not replies to an existing comment are ignored."""
    mock_settings.thread_agent_enabled = True

    payload = _make_review_comment_payload()
    payload["comment"]["in_reply_to_id"] = None

    response = client.post(
        "/webhook",
        json=payload,
        headers={"X-GitHub-Event": "pull_request_review_comment", "X-Hub-Signature-256": "sha256=fake"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.settings")
def test_thread_comment_ignored_when_author_is_baloo(mock_settings, mock_verify, client):
    """Baloo's own comments are ignored (no self-replies)."""
    mock_settings.thread_agent_enabled = True

    payload = _make_review_comment_payload(comment_author="baloo-bear[bot]")

    response = client.post(
        "/webhook",
        json=payload,
        headers={"X-GitHub-Event": "pull_request_review_comment", "X-Hub-Signature-256": "sha256=fake"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/github/test_thread_webhook.py -v`
Expected: FAIL — tests fail because the handler currently ignores all `pull_request_review_comment` events

- [ ] **Step 3: Implement the webhook handler for thread replies**

Replace the `pull_request_review_comment` block in `webhook_handler.py` (lines ~640-652). Keep `issue_comment` and `pull_request_review` ignored. The new handler:

```python
    elif event == "pull_request_review_comment":
        payload = await request.json()
        action = payload.get("action")

        # Only handle new comments (not edits or deletions)
        if action != "created":
            return {"status": "ignored", "event": event, "reason": f"action={action}"}

        if not settings.thread_agent_enabled:
            return {"status": "ignored", "event": event, "reason": "thread agent disabled"}

        comment_data = payload.get("comment", {})
        in_reply_to_id = comment_data.get("in_reply_to_id")
        comment_author = (comment_data.get("user") or {}).get("login", "")
        comment_body = comment_data.get("body", "")

        # Must be a reply to an existing comment
        if not in_reply_to_id:
            return {"status": "ignored", "event": event, "reason": "not a reply"}

        # Ignore Baloo's own comments
        from baloo.github.discussions import is_baloo_actor
        if is_baloo_actor(comment_author, comment_body):
            return {"status": "ignored", "event": event, "reason": "self-reply"}

        pr_data = payload.get("pull_request", {})
        repo_data = payload.get("repository", {})
        installation_id = payload.get("installation", {}).get("id")

        repo_full_name = repo_data.get("full_name", "")
        pr_number = pr_data.get("number", 0)

        logger.info(
            "Thread reply on %s#%s by @%s (reply_to=%s)",
            repo_full_name, pr_number, comment_author, in_reply_to_id,
        )

        # Process thread reply in background
        background_tasks.add_task(
            _process_thread_reply,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            installation_id=installation_id,
            comment_data=comment_data,
            in_reply_to_id=in_reply_to_id,
            head_sha=pr_data.get("head", {}).get("sha", ""),
        )

        return {"status": "queued", "event": event, "action": "thread_reply"}

    elif event in ("issue_comment", "pull_request_review"):
        logger.debug("Ignoring %s event — reviews trigger only on new code", event)
        return {"status": "ignored", "event": event, "reason": "comment events disabled"}
```

- [ ] **Step 4: Implement `_process_thread_reply` function**

Add this function to `webhook_handler.py`:

```python
async def _process_thread_reply(
    *,
    repo_full_name: str,
    pr_number: int,
    installation_id: int,
    comment_data: dict,
    in_reply_to_id: int,
    head_sha: str,
) -> None:
    """Process a developer's reply to a Baloo thread comment.

    Fetches thread context, runs the ThreadAgent, posts a reply if needed,
    and writes a feedback signal on concession.
    """
    from baloo.agent.thread_agent import ThreadAgent
    from baloo.db.feedback_service import FeedbackService
    from baloo.github.discussions import build_discussion_comment, is_baloo_actor

    try:
        github_client = GitHubAPIClient(installation_id)

        # Fetch the full thread: get all comments replying to the same root
        all_review_comments = await github_client.fetch_review_comments(
            repo_full_name, pr_number
        )

        # Build the thread: find all comments in this thread chain
        thread_comments_raw = []
        for c in all_review_comments:
            root_id = c.get("in_reply_to_id") or c.get("id")
            if root_id == in_reply_to_id or c.get("id") == in_reply_to_id:
                thread_comments_raw.append(c)

        # Sort by creation time
        thread_comments_raw.sort(key=lambda c: c.get("created_at", ""))

        # Check if this is actually a Baloo thread
        thread_comments = [
            build_discussion_comment(c, source="review_comment",
                                     path=c.get("path"), line=c.get("line") or c.get("original_line"))
            for c in thread_comments_raw
        ]

        if not any(c.is_baloo for c in thread_comments):
            logger.info("Thread %s is not a Baloo thread, skipping", in_reply_to_id)
            return

        # Check escalation cap
        baloo_message_count = sum(1 for c in thread_comments if c.is_baloo)
        if baloo_message_count >= settings.thread_agent_max_replies:
            logger.info(
                "Thread %s hit escalation cap (%d Baloo messages), skipping",
                in_reply_to_id, baloo_message_count,
            )
            return

        # Fetch code context around the finding location
        file_path = comment_data.get("path", "")
        line_number = comment_data.get("line") or comment_data.get("original_line") or 0

        code_context = ""
        if file_path and head_sha:
            file_content = await github_client.get_file_content(
                repo_full_name, file_path, ref=head_sha
            )
            if file_content:
                lines = file_content.splitlines()
                start = max(0, line_number - 31)
                end = min(len(lines), line_number + 30)
                code_context = "\n".join(
                    f"{i+1}: {line}" for i, line in enumerate(lines[start:end], start=start)
                )

        # Run the thread agent
        agent = ThreadAgent()
        result = await agent.classify(
            thread_comments=thread_comments,
            code_context=code_context,
            file_path=file_path,
            line_number=line_number,
        )

        logger.info(
            "Thread agent result for %s#%s thread %s: %s (reply=%s)",
            repo_full_name, pr_number, in_reply_to_id,
            result.classification, bool(result.reply),
        )

        # Post reply if needed
        if result.reply:
            await github_client.reply_to_review_comment(
                repo_full_name,
                in_reply_to_id,
                result.reply,
            )

        # Write feedback signal on concession
        if result.classification == "disagreed_valid" and result.feedback_signal:
            comment_url = comment_data.get("html_url", "")
            await FeedbackService.write_signal(
                repo=repo_full_name,
                pattern=result.feedback_signal["pattern"],
                category=result.feedback_signal.get("category", ""),
                developer=(comment_data.get("user") or {}).get("login", "unknown"),
                file_glob=result.feedback_signal.get("file_glob"),
                thread_url=comment_url,
                pr_number=pr_number,
            )

    except Exception as exc:
        logger.error(
            "Error processing thread reply for %s#%s: %s",
            repo_full_name, pr_number, exc, exc_info=True,
        )
```

- [ ] **Step 5: Check if `fetch_review_comments` exists on GitHubAPIClient**

Search for the method. If it doesn't exist, add it to `api_client.py`:

```python
    async def fetch_review_comments(
        self, repo_full_name: str, pr_number: int
    ) -> list[dict]:
        """Fetch all review comments on a PR.

        Args:
            repo_full_name: Repository full name (owner/repo)
            pr_number: Pull request number

        Returns:
            List of raw comment dicts from the GitHub API
        """
        comments = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments"
                response = await client.get(
                    url,
                    headers=self._get_headers(),
                    params={"per_page": 100, "page": page},
                )
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    break
                comments.extend(batch)
                page += 1
        return comments
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/github/test_thread_webhook.py -v`
Expected: All PASS

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS (existing tests not broken)

- [ ] **Step 8: Commit**

```bash
git add baloo/github/webhook_handler.py baloo/github/api_client.py tests/github/test_thread_webhook.py
git commit -m "feat(thread-agent): handle pull_request_review_comment events with thread agent"
```

---

### Task 8: Wire Feedback Signals into Full Review Pipeline

**Files:**
- Modify: `baloo/github/webhook_handler.py` (in `process_pr_review`, before building review prompt)
- Test: `tests/github/test_webhook_handler.py`

- [ ] **Step 1: Write the failing test**

Append to an existing webhook handler test or create a targeted test:

```python
# In tests/github/test_webhook_handler.py or a new test file

@pytest.mark.asyncio
async def test_feedback_signals_fetched_during_review():
    """Feedback signals are fetched and attached to PR context during review."""
    from baloo.db.feedback_service import FeedbackService

    with patch.object(FeedbackService, "get_signals_for_repo", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = []
        # Trigger a review and verify get_signals_for_repo was called
        # (The exact setup depends on existing test patterns in the file)
```

- [ ] **Step 2: Add feedback signal fetching to `process_pr_review`**

In `webhook_handler.py`, inside `process_pr_review`, after `pr_context` is fetched (around line 776) and before the agent review starts, add:

```python
            # Fetch feedback signals for this repo
            feedback_signals = []
            if settings.feedback_signals_enabled and settings.database_enabled:
                try:
                    from baloo.db.feedback_service import FeedbackService
                    feedback_signals = await FeedbackService.get_signals_for_repo(repo_full_name)
                    if feedback_signals:
                        logger.info(
                            "Loaded %d feedback signal(s) for %s",
                            len(feedback_signals), repo_full_name,
                        )
                except Exception as exc:
                    logger.warning("Failed to load feedback signals: %s", exc)
```

Then pass `feedback_signals` to the PR context so the prompt builder can access them. The cleanest approach is to store them on `review_context` as an attribute accessible via `.get("feedback_signals")`. Since `PRContext` uses `get()` for backward compat, add `feedback_signals` as an optional field on `PRContext`:

In `baloo/github/models.py`, add to `PRContext`:

```python
    feedback_signals: list = Field(default_factory=list)
```

Then after fetching signals:

```python
            if feedback_signals:
                review_context = review_context.model_copy(
                    update={"feedback_signals": feedback_signals}
                )
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add baloo/github/webhook_handler.py baloo/github/models.py
git commit -m "feat(thread-agent): wire feedback signals into review pipeline"
```

---

### Task 9: Integration Test — End-to-End Thread Flow

**Files:**
- Create: `tests/agent/test_thread_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/agent/test_thread_integration.py`:

```python
"""Integration test for the full thread reply flow."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.webhook_handler import _process_thread_reply


@pytest.mark.asyncio
async def test_process_thread_reply_concede_writes_signal():
    """Full flow: developer disagrees validly -> Baloo concedes -> feedback signal written."""
    mock_client = AsyncMock()

    # Mock fetch_review_comments: return a Baloo finding + developer reply
    mock_client.fetch_review_comments.return_value = [
        {
            "id": 100,
            "body": "**[HIGH] Silent Failures** - except pass swallows errors",
            "user": {"login": "baloo-bear[bot]"},
            "path": "app/retry.py",
            "line": 15,
            "original_line": 15,
            "created_at": "2026-05-09T10:00:00Z",
            "updated_at": "2026-05-09T10:00:00Z",
            "html_url": "https://github.com/org/repo/pull/1#discussion_r100",
        },
        {
            "id": 200,
            "body": "This is intentional - retry loops need to swallow transient errors",
            "user": {"login": "alice"},
            "in_reply_to_id": 100,
            "path": "app/retry.py",
            "line": 15,
            "original_line": 15,
            "created_at": "2026-05-09T11:00:00Z",
            "updated_at": "2026-05-09T11:00:00Z",
            "html_url": "https://github.com/org/repo/pull/1#discussion_r200",
        },
    ]

    # Mock get_file_content: return some code
    mock_client.get_file_content.return_value = (
        "def retry(fn):\n"
        "    for _ in range(3):\n"
        "        try:\n"
        "            return fn()\n"
        "        except Exception:\n"
        "            pass\n"
        "    raise RuntimeError('retries exhausted')\n"
    )

    mock_client.reply_to_review_comment.return_value = True

    # Mock the ThreadAgent to return a concession
    mock_result = MagicMock()
    mock_result.classification = "disagreed_valid"
    mock_result.reply = "Got it, makes sense for retry loops."
    mock_result.feedback_signal = {
        "pattern": "except pass in retry loops is intentional",
        "category": "Silent Failures",
        "file_glob": "app/retry*.py",
    }

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_client),
        patch("baloo.github.webhook_handler.settings") as mock_settings,
        patch("baloo.agent.thread_agent.ThreadAgent.classify", new_callable=AsyncMock, return_value=mock_result),
        patch("baloo.db.feedback_service.FeedbackService.write_signal", new_callable=AsyncMock) as mock_write,
    ):
        mock_settings.thread_agent_max_replies = 3
        mock_settings.feedback_signals_enabled = True
        mock_settings.database_enabled = True

        await _process_thread_reply(
            repo_full_name="org/repo",
            pr_number=1,
            installation_id=1,
            comment_data={
                "id": 200,
                "body": "This is intentional",
                "user": {"login": "alice"},
                "path": "app/retry.py",
                "line": 15,
                "original_line": 15,
                "html_url": "https://github.com/org/repo/pull/1#discussion_r200",
            },
            in_reply_to_id=100,
            head_sha="abc123",
        )

    # Verify reply was posted
    mock_client.reply_to_review_comment.assert_called_once_with(
        "org/repo", 100, "Got it, makes sense for retry loops."
    )

    # Verify feedback signal was written
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["repo"] == "org/repo"
    assert call_kwargs["pattern"] == "except pass in retry loops is intentional"
    assert call_kwargs["category"] == "Silent Failures"
    assert call_kwargs["developer"] == "alice"


@pytest.mark.asyncio
async def test_process_thread_reply_escalation_cap():
    """Thread with too many Baloo messages is skipped (escalation)."""
    mock_client = AsyncMock()

    # 3 Baloo messages already in thread
    mock_client.fetch_review_comments.return_value = [
        {"id": 100, "body": "Finding", "user": {"login": "baloo-bear[bot]"}, "path": "f.py", "line": 1, "original_line": 1, "created_at": "2026-05-09T10:00:00Z", "updated_at": "2026-05-09T10:00:00Z"},
        {"id": 101, "body": "reply1", "user": {"login": "dev"}, "in_reply_to_id": 100, "path": "f.py", "line": 1, "original_line": 1, "created_at": "2026-05-09T10:01:00Z", "updated_at": "2026-05-09T10:01:00Z"},
        {"id": 102, "body": "Baloo reply1", "user": {"login": "baloo-bear[bot]"}, "in_reply_to_id": 100, "path": "f.py", "line": 1, "original_line": 1, "created_at": "2026-05-09T10:02:00Z", "updated_at": "2026-05-09T10:02:00Z"},
        {"id": 103, "body": "reply2", "user": {"login": "dev"}, "in_reply_to_id": 100, "path": "f.py", "line": 1, "original_line": 1, "created_at": "2026-05-09T10:03:00Z", "updated_at": "2026-05-09T10:03:00Z"},
        {"id": 104, "body": "Baloo reply2", "user": {"login": "baloo-bear[bot]"}, "in_reply_to_id": 100, "path": "f.py", "line": 1, "original_line": 1, "created_at": "2026-05-09T10:04:00Z", "updated_at": "2026-05-09T10:04:00Z"},
        {"id": 105, "body": "reply3", "user": {"login": "dev"}, "in_reply_to_id": 100, "path": "f.py", "line": 1, "original_line": 1, "created_at": "2026-05-09T10:05:00Z", "updated_at": "2026-05-09T10:05:00Z"},
    ]

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_client),
        patch("baloo.github.webhook_handler.settings") as mock_settings,
    ):
        mock_settings.thread_agent_max_replies = 3

        await _process_thread_reply(
            repo_full_name="org/repo",
            pr_number=1,
            installation_id=1,
            comment_data={"id": 105, "body": "reply3", "user": {"login": "dev"}, "path": "f.py", "line": 1},
            in_reply_to_id=100,
            head_sha="abc123",
        )

    # No reply should be posted and no agent should run
    mock_client.reply_to_review_comment.assert_not_called()
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/agent/test_thread_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/agent/test_thread_integration.py
git commit -m "test(thread-agent): add integration tests for thread reply flow"
```

---

### Task 10: Documentation

**Files:**
- Create: `docs/features/thread-agent.md`

- [ ] **Step 1: Write feature documentation**

Create `docs/features/thread-agent.md`:

```markdown
# Thread Conversation Agent

When a developer replies to a Baloo inline review comment, a lightweight agent reads the conversation and responds appropriately — explaining, suggesting fixes, or conceding when the developer's reasoning is valid.

## How It Works

1. Developer replies to a Baloo inline comment on a PR
2. Baloo classifies the response: acknowledged, disagreed, question, or unclear
3. Based on classification, Baloo may reply once (explain, concede, or answer)
4. If Baloo concedes, a **feedback signal** is saved for the repo

## Feedback Signals

When Baloo concedes that a flagged pattern is intentional, it stores this as a feedback signal. In future reviews, these signals are injected into the review prompt so Baloo avoids re-flagging the same patterns.

Signals are:
- **Per-repo** — one developer's feedback benefits all future reviews
- **Category-scoped** — e.g., "Silent Failures in retry code"
- **Optionally file-scoped** — can target specific directories
- **Time-limited** — signals expire after 6 months without use

## Escalation Cap

Baloo replies at most twice per thread (original finding + 2 replies = 3 total Baloo messages). After that, the thread is left for human review.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `THREAD_AGENT_ENABLED` | `false` | Enable the thread conversation agent |
| `THREAD_AGENT_MODEL` | `haiku` | Model for thread replies |
| `THREAD_AGENT_MAX_REPLIES` | `3` | Max Baloo messages per thread before escalation |
| `THREAD_AGENT_MAX_CONCURRENT` | `3` | Max parallel thread agent calls |
| `FEEDBACK_SIGNALS_ENABLED` | `true` | Write and read feedback signals (requires DATABASE_ENABLED) |
| `FEEDBACK_SIGNALS_TTL_DAYS` | `180` | Days before unmatched signals expire |

## Cost

Thread agent uses a cheap model (Haiku/Flash). Typical cost: ~$0.001 per thread reply.
```

- [ ] **Step 2: Commit**

```bash
git add docs/features/thread-agent.md
git commit -m "docs: add thread conversation agent feature documentation"
```
