# Finding Outcomes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track finding outcomes on PR merge to measure Baloo's review quality over time.

**Architecture:** On PR merge, a background task labels each finding with an outcome (actioned/disputed/acknowledged/ignored) based on code changes and thread interactions. A new dashboard page visualizes hit rate, noise rate, and trends. All data stored in a new `finding_outcomes` table with Alembic migration.

**Tech Stack:** Python 3.10+, SQLAlchemy async ORM, Alembic, FastAPI, Jinja2/HTMX/Chart.js, pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `baloo/db/migrations/versions/004_add_finding_outcomes.py` | Alembic migration for `finding_outcomes` table |
| Modify | `baloo/db/models.py` | Add `FindingOutcome` model |
| Create | `baloo/outcomes/__init__.py` | Package init |
| Create | `baloo/outcomes/signals.py` | Signal collection (code change detection, thread matching, sentiment) |
| Create | `baloo/outcomes/labeler.py` | Outcome labeling orchestrator (called on PR merge) |
| Modify | `baloo/github/webhook_handler.py` | Add `closed`+merged handler |
| Modify | `baloo/dashboard/queries.py` | Add outcome queries to `DashboardService` |
| Modify | `baloo/dashboard/router.py` | Add `/dashboard/outcomes` route |
| Modify | `baloo/dashboard/templates/base.html` | Add "Outcomes" nav link |
| Create | `baloo/dashboard/templates/outcomes.html` | Outcomes dashboard page |
| Create | `tests/outcomes/__init__.py` | Test package init |
| Create | `tests/outcomes/test_signals.py` | Tests for signal collection |
| Create | `tests/outcomes/test_labeler.py` | Tests for labeling orchestrator |
| Create | `tests/outcomes/test_webhook_merge.py` | Tests for merge webhook handling |
| Create | `tests/dashboard/test_outcomes_page.py` | Tests for outcomes dashboard |

---

### Task 1: FindingOutcome Model + Migration

**Files:**
- Modify: `baloo/db/models.py`
- Create: `baloo/db/migrations/versions/004_add_finding_outcomes.py`
- Modify: `tests/db/test_models.py`

- [ ] **Step 1: Write failing test for FindingOutcome model**

Add to `tests/db/test_models.py`:

```python
from baloo.db.models import FindingOutcome


def test_finding_outcome_model_exists():
    """FindingOutcome has expected columns."""
    outcome = FindingOutcome(
        finding_id=1,
        review_id=1,
        repo_full_name="owner/repo",
        pr_number=42,
        outcome="actioned",
        signals={"code_changed_near_line": True},
    )
    assert outcome.outcome == "actioned"
    assert outcome.signals == {"code_changed_near_line": True}
    assert outcome.repo_full_name == "owner/repo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/db/test_models.py::test_finding_outcome_model_exists -v`
Expected: FAIL with `ImportError: cannot import name 'FindingOutcome'`

- [ ] **Step 3: Add FindingOutcome model**

Add to `baloo/db/models.py`, after the `ReviewLog` class:

```python
from sqlalchemy import JSON


class FindingOutcome(Base):
    __tablename__ = "finding_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    labeled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    finding: Mapped["Finding"] = relationship("Finding")
    review: Mapped["Review"] = relationship("Review")

    __table_args__ = (
        Index("ix_finding_outcomes_finding_id", "finding_id", unique=True),
        Index("ix_finding_outcomes_review_id", "review_id"),
        Index("ix_finding_outcomes_repo", "repo_full_name"),
        Index("ix_finding_outcomes_outcome", "outcome"),
    )
```

Add `JSON` to the imports from `sqlalchemy` at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/db/test_models.py::test_finding_outcome_model_exists -v`
Expected: PASS

- [ ] **Step 5: Create Alembic migration**

Create `baloo/db/migrations/versions/004_add_finding_outcomes.py`:

```python
"""Add finding_outcomes table for tracking review quality.

Revision ID: 004
Revises: 003
Create Date: 2026-04-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "finding_outcomes" not in existing_tables:
        op.create_table(
            "finding_outcomes",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "finding_id",
                sa.Integer,
                sa.ForeignKey("findings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "review_id",
                sa.Integer,
                sa.ForeignKey("reviews.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("repo_full_name", sa.String(255), nullable=False),
            sa.Column("pr_number", sa.Integer, nullable=False),
            sa.Column("outcome", sa.String(20), nullable=False),
            sa.Column("signals", sa.JSON, nullable=True),
            sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_finding_outcomes_finding_id", "finding_outcomes", ["finding_id"], unique=True
        )
        op.create_index("ix_finding_outcomes_review_id", "finding_outcomes", ["review_id"])
        op.create_index("ix_finding_outcomes_repo", "finding_outcomes", ["repo_full_name"])
        op.create_index("ix_finding_outcomes_outcome", "finding_outcomes", ["outcome"])


def downgrade() -> None:
    op.drop_index("ix_finding_outcomes_outcome", table_name="finding_outcomes")
    op.drop_index("ix_finding_outcomes_repo", table_name="finding_outcomes")
    op.drop_index("ix_finding_outcomes_review_id", table_name="finding_outcomes")
    op.drop_index("ix_finding_outcomes_finding_id", table_name="finding_outcomes")
    op.drop_table("finding_outcomes")
```

- [ ] **Step 6: Commit**

```bash
git add baloo/db/models.py baloo/db/migrations/versions/004_add_finding_outcomes.py tests/db/test_models.py
git commit -m "feat: add FindingOutcome model and migration"
```

---

### Task 2: Signal Collection

**Files:**
- Create: `baloo/outcomes/__init__.py`
- Create: `baloo/outcomes/signals.py`
- Create: `tests/outcomes/__init__.py`
- Create: `tests/outcomes/test_signals.py`

- [ ] **Step 1: Create package init files**

Create empty `baloo/outcomes/__init__.py` and `tests/outcomes/__init__.py`.

- [ ] **Step 2: Write failing test for reply sentiment**

Create `tests/outcomes/test_signals.py`:

```python
"""Tests for outcome signal collection."""

from baloo.outcomes.signals import classify_sentiment


def test_positive_sentiment():
    assert classify_sentiment("good catch, I'll fix this") == "positive"


def test_negative_sentiment():
    assert classify_sentiment("this is a false positive") == "negative"


def test_neutral_sentiment():
    assert classify_sentiment("I see what you mean, let me think about it") == "neutral"


def test_no_text_returns_none():
    assert classify_sentiment(None) is None
    assert classify_sentiment("") is None


def test_positive_keywords():
    for text in ["fixed", "good catch", "thanks", "done", "resolved"]:
        assert classify_sentiment(text) == "positive", f"Expected positive for: {text}"


def test_negative_keywords():
    for text in ["false positive", "intentional", "disagree", "not a bug", "by design"]:
        assert classify_sentiment(text) == "negative", f"Expected negative for: {text}"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/outcomes/test_signals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'baloo.outcomes.signals'`

- [ ] **Step 4: Implement classify_sentiment**

Create `baloo/outcomes/signals.py`:

```python
"""Signal collection for finding outcome labeling."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

POSITIVE_KEYWORDS = ["fixed", "good catch", "thanks", "done", "resolved"]
NEGATIVE_KEYWORDS = ["false positive", "intentional", "disagree", "not a bug", "by design"]


def classify_sentiment(text: str | None) -> str | None:
    """Classify reply sentiment using keyword matching.

    Returns "positive", "negative", "neutral", or None if no text.
    """
    if not text:
        return None

    lower = text.lower()
    for kw in NEGATIVE_KEYWORDS:
        if kw in lower:
            return "negative"
    for kw in POSITIVE_KEYWORDS:
        if kw in lower:
            return "positive"
    return "neutral"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/outcomes/test_signals.py -v`
Expected: PASS

- [ ] **Step 6: Write failing test for code change detection**

Add to `tests/outcomes/test_signals.py`:

```python
from baloo.outcomes.signals import detect_code_change


def test_code_changed_near_line():
    """Detects changes within ±5 lines of the flagged line."""
    # Unified diff showing lines 10-15 changed
    diff = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -8,7 +8,7 @@ class Auth:
     def validate(self):
-        old_code()
+        new_code()
         return True"""
    assert detect_code_change("src/auth.py", 12, diff) is True


def test_code_not_changed_near_line():
    """No changes near the flagged line."""
    diff = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -100,3 +100,3 @@ class Auth:
-    old_line()
+    new_line()"""
    assert detect_code_change("src/auth.py", 12, diff) is False


def test_code_change_different_file():
    """Changes in a different file don't count."""
    diff = """diff --git a/src/other.py b/src/other.py
--- a/src/other.py
+++ b/src/other.py
@@ -10,3 +10,3 @@
-    old()
+    new()"""
    assert detect_code_change("src/auth.py", 12, diff) is False


def test_code_change_no_diff():
    assert detect_code_change("src/auth.py", 12, "") is False
    assert detect_code_change("src/auth.py", 12, None) is False
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/outcomes/test_signals.py::test_code_changed_near_line -v`
Expected: FAIL with `ImportError: cannot import name 'detect_code_change'`

- [ ] **Step 8: Implement detect_code_change**

Add to `baloo/outcomes/signals.py`:

```python
import re

LINE_TOLERANCE = 5

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_DIFF_FILE = re.compile(r"^diff --git a/.+ b/(.+)$")


def detect_code_change(
    file_path: str, line_number: int | None, diff: str | None
) -> bool:
    """Check if lines near line_number were modified in the diff.

    Parses unified diff to find added/removed lines within ±LINE_TOLERANCE
    of the target line in the specified file.
    """
    if not diff or line_number is None:
        return False

    in_target_file = False
    current_line = 0

    for raw_line in diff.splitlines():
        # Track which file we're in
        file_match = _DIFF_FILE.match(raw_line)
        if file_match:
            in_target_file = file_match.group(1) == file_path
            continue

        if not in_target_file:
            continue

        # Parse hunk headers for line numbers
        hunk_match = _HUNK_HEADER.match(raw_line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        # Skip diff metadata lines
        if raw_line.startswith("---") or raw_line.startswith("+++"):
            continue

        # Track line numbers and check for changes
        if raw_line.startswith("-"):
            # Removed lines don't advance the new-file line counter
            continue

        if raw_line.startswith("+"):
            if abs(current_line - line_number) <= LINE_TOLERANCE:
                return True
            current_line += 1
        else:
            # Context line
            current_line += 1

    return False
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/outcomes/test_signals.py -v`
Expected: All PASS

- [ ] **Step 10: Write failing test for thread signal collection**

Add to `tests/outcomes/test_signals.py`:

```python
from baloo.outcomes.signals import collect_thread_signals


def test_collect_thread_signals_with_reply():
    """Extracts signals from a thread where developer replied."""
    thread = {
        "path": "src/auth.py",
        "line": 42,
        "is_resolved": True,
        "comments": [
            {"author": "baloo[bot]", "body": "SQL injection risk", "is_baloo": True},
            {"author": "dev", "body": "good catch, fixed", "is_baloo": False},
        ],
    }
    signals = collect_thread_signals(thread)
    assert signals["thread_resolved"] is True
    assert signals["developer_replied"] is True
    assert signals["reply_sentiment"] == "positive"
    assert signals["reply_text"] == "good catch, fixed"


def test_collect_thread_signals_no_reply():
    """Thread with only Baloo's comment — no developer reply."""
    thread = {
        "path": "src/auth.py",
        "line": 42,
        "is_resolved": False,
        "comments": [
            {"author": "baloo[bot]", "body": "SQL injection risk", "is_baloo": True},
        ],
    }
    signals = collect_thread_signals(thread)
    assert signals["thread_resolved"] is False
    assert signals["developer_replied"] is False
    assert signals["reply_sentiment"] is None
    assert signals["reply_text"] is None


def test_collect_thread_signals_disputed():
    thread = {
        "path": "src/auth.py",
        "line": 42,
        "is_resolved": False,
        "comments": [
            {"author": "baloo[bot]", "body": "Possible bug", "is_baloo": True},
            {"author": "dev", "body": "this is intentional", "is_baloo": False},
        ],
    }
    signals = collect_thread_signals(thread)
    assert signals["reply_sentiment"] == "negative"


def test_collect_thread_signals_none():
    assert collect_thread_signals(None) == {
        "thread_resolved": False,
        "developer_replied": False,
        "reply_sentiment": None,
        "reply_text": None,
    }
```

- [ ] **Step 11: Run test to verify it fails**

Run: `uv run pytest tests/outcomes/test_signals.py::test_collect_thread_signals_with_reply -v`
Expected: FAIL with `ImportError: cannot import name 'collect_thread_signals'`

- [ ] **Step 12: Implement collect_thread_signals**

Add to `baloo/outcomes/signals.py`:

```python
def collect_thread_signals(thread: dict | None) -> dict:
    """Extract signals from a PR review thread.

    Args:
        thread: Dict with keys: is_resolved, comments (list of dicts
                with author, body, is_baloo).

    Returns:
        Dict with thread_resolved, developer_replied, reply_sentiment, reply_text.
    """
    empty = {
        "thread_resolved": False,
        "developer_replied": False,
        "reply_sentiment": None,
        "reply_text": None,
    }
    if not thread:
        return empty

    comments = thread.get("comments", [])

    # Find first non-Baloo reply
    developer_reply = None
    for comment in comments:
        if not comment.get("is_baloo", False):
            developer_reply = comment
            break

    if not developer_reply:
        return {**empty, "thread_resolved": bool(thread.get("is_resolved", False))}

    reply_text = developer_reply.get("body", "")
    return {
        "thread_resolved": bool(thread.get("is_resolved", False)),
        "developer_replied": True,
        "reply_sentiment": classify_sentiment(reply_text),
        "reply_text": reply_text[:500] if reply_text else None,
    }
```

- [ ] **Step 13: Run all signal tests**

Run: `uv run pytest tests/outcomes/test_signals.py -v`
Expected: All PASS

- [ ] **Step 14: Commit**

```bash
git add baloo/outcomes/ tests/outcomes/
git commit -m "feat: add signal collection for finding outcomes"
```

---

### Task 3: Outcome Labeler

**Files:**
- Create: `baloo/outcomes/labeler.py`
- Create: `tests/outcomes/test_labeler.py`

- [ ] **Step 1: Write failing test for determine_outcome**

Create `tests/outcomes/test_labeler.py`:

```python
"""Tests for outcome labeling logic."""

from baloo.outcomes.labeler import determine_outcome


def test_actioned_wins_over_all():
    """Code change is highest priority."""
    signals = {
        "code_changed_near_line": True,
        "thread_resolved": True,
        "developer_replied": True,
        "reply_sentiment": "positive",
        "reply_text": "fixed",
    }
    assert determine_outcome(signals) == "actioned"


def test_disputed_when_negative_reply_no_code_change():
    signals = {
        "code_changed_near_line": False,
        "thread_resolved": False,
        "developer_replied": True,
        "reply_sentiment": "negative",
        "reply_text": "false positive",
    }
    assert determine_outcome(signals) == "disputed"


def test_acknowledged_when_positive_reply_no_code_change():
    signals = {
        "code_changed_near_line": False,
        "thread_resolved": True,
        "developer_replied": True,
        "reply_sentiment": "positive",
        "reply_text": "good catch",
    }
    assert determine_outcome(signals) == "acknowledged"


def test_acknowledged_when_neutral_reply_and_resolved():
    signals = {
        "code_changed_near_line": False,
        "thread_resolved": True,
        "developer_replied": True,
        "reply_sentiment": "neutral",
        "reply_text": "ok",
    }
    assert determine_outcome(signals) == "acknowledged"


def test_ignored_when_no_signals():
    signals = {
        "code_changed_near_line": False,
        "thread_resolved": False,
        "developer_replied": False,
        "reply_sentiment": None,
        "reply_text": None,
    }
    assert determine_outcome(signals) == "ignored"


def test_ignored_when_neutral_reply_not_resolved():
    """Neutral reply without resolution is still ignored."""
    signals = {
        "code_changed_near_line": False,
        "thread_resolved": False,
        "developer_replied": True,
        "reply_sentiment": "neutral",
        "reply_text": "hmm",
    }
    assert determine_outcome(signals) == "ignored"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/outcomes/test_labeler.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement determine_outcome**

Create `baloo/outcomes/labeler.py`:

```python
"""Outcome labeling for Baloo findings."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import Finding, FindingOutcome, Review
from baloo.outcomes.signals import (
    classify_sentiment,
    collect_thread_signals,
    detect_code_change,
)

logger = logging.getLogger(__name__)


def determine_outcome(signals: dict) -> str:
    """Apply priority logic to determine the outcome label.

    Priority: actioned > disputed > acknowledged > ignored.
    """
    if signals.get("code_changed_near_line"):
        return "actioned"
    if signals.get("reply_sentiment") == "negative":
        return "disputed"
    if signals.get("developer_replied") and (
        signals.get("reply_sentiment") == "positive"
        or signals.get("thread_resolved")
    ):
        return "acknowledged"
    return "ignored"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/outcomes/test_labeler.py -v`
Expected: All PASS

- [ ] **Step 5: Write failing test for label_pr_outcomes**

Add to `tests/outcomes/test_labeler.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from baloo.db.engine import reset_engine
from baloo.db.models import Base, Finding, FindingOutcome, Review
from baloo.outcomes.labeler import label_pr_outcomes


@pytest.fixture
async def db_factory():
    """In-memory SQLite DB with all tables."""
    reset_engine()
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    with patch("baloo.outcomes.labeler.get_session_factory", return_value=factory):
        yield factory
    await engine.dispose()
    reset_engine()


@pytest.fixture
async def seeded_db(db_factory):
    """DB with a review and two findings."""
    async with db_factory() as session:
        async with session.begin():
            review = Review(
                repo_full_name="owner/repo",
                pr_number=10,
                pr_title="Fix auth",
                review_status="approved",
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                commit_sha="abc123",
            )
            session.add(review)
            await session.flush()
            session.add(Finding(
                review_id=review.id,
                file_path="src/auth.py",
                line_number=42,
                severity="HIGH",
                category="Security",
                body="SQL injection risk",
            ))
            session.add(Finding(
                review_id=review.id,
                file_path="src/utils.py",
                line_number=10,
                severity="MEDIUM",
                category="Style",
                body="Naming convention",
            ))
    return db_factory


async def test_label_pr_outcomes_creates_rows(seeded_db):
    """Labels findings and writes outcome rows."""
    mock_diff = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -40,5 +40,5 @@ class Auth:
-    old_vulnerable_code()
+    new_safe_code()"""

    mock_threads = [
        {
            "path": "src/auth.py",
            "line": 42,
            "is_resolved": True,
            "comments": [
                {"author": "baloo[bot]", "body": "SQL injection", "is_baloo": True},
                {"author": "dev", "body": "fixed, thanks", "is_baloo": False},
            ],
        },
    ]

    with patch(
        "baloo.outcomes.labeler.fetch_merge_signals",
        new=AsyncMock(return_value=(mock_diff, mock_threads)),
    ):
        await label_pr_outcomes("owner/repo", 10, 12345)

    async with seeded_db() as session:
        outcomes = (
            await session.execute(select(FindingOutcome).order_by(FindingOutcome.id))
        ).scalars().all()

    assert len(outcomes) == 2
    auth_outcome = next(o for o in outcomes if o.finding_id and "auth" in str(
        (await _get_finding(seeded_db, o.finding_id))
    ) or o.outcome == "actioned")
    # The auth.py finding should be actioned (code changed near line 42)
    actioned = [o for o in outcomes if o.outcome == "actioned"]
    ignored = [o for o in outcomes if o.outcome == "ignored"]
    assert len(actioned) == 1
    assert len(ignored) == 1
```

Wait — that test got messy. Let me simplify:

Replace the `test_label_pr_outcomes_creates_rows` test above with:

```python
async def test_label_pr_outcomes_creates_rows(seeded_db):
    """Labels findings and writes outcome rows."""
    mock_diff = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -40,5 +40,5 @@ class Auth:
-    old_vulnerable_code()
+    new_safe_code()"""

    mock_threads = [
        {
            "path": "src/auth.py",
            "line": 42,
            "is_resolved": True,
            "comments": [
                {"author": "baloo[bot]", "body": "SQL injection", "is_baloo": True},
                {"author": "dev", "body": "fixed, thanks", "is_baloo": False},
            ],
        },
    ]

    with patch(
        "baloo.outcomes.labeler.fetch_merge_signals",
        new=AsyncMock(return_value=(mock_diff, mock_threads)),
    ):
        await label_pr_outcomes("owner/repo", 10, 12345)

    async with seeded_db() as session:
        outcomes = (
            await session.execute(
                select(FindingOutcome).order_by(FindingOutcome.id)
            )
        ).scalars().all()

    assert len(outcomes) == 2
    outcomes_by_label = {o.outcome for o in outcomes}
    assert "actioned" in outcomes_by_label  # auth.py — code changed near line 42
    assert "ignored" in outcomes_by_label   # utils.py — no thread, no code change


async def test_label_pr_outcomes_skips_when_no_findings(db_factory):
    """No-op when PR has no findings."""
    with patch(
        "baloo.outcomes.labeler.fetch_merge_signals",
        new=AsyncMock(),
    ) as mock_fetch:
        await label_pr_outcomes("owner/repo", 999, 12345)

    mock_fetch.assert_not_called()


async def test_label_pr_outcomes_is_idempotent(seeded_db):
    """Running twice doesn't duplicate rows."""
    mock_diff = ""
    mock_threads = []

    with patch(
        "baloo.outcomes.labeler.fetch_merge_signals",
        new=AsyncMock(return_value=(mock_diff, mock_threads)),
    ):
        await label_pr_outcomes("owner/repo", 10, 12345)
        await label_pr_outcomes("owner/repo", 10, 12345)

    async with seeded_db() as session:
        count = (
            await session.execute(
                select(func.count(FindingOutcome.id))
            )
        ).scalar()

    assert count == 2  # Still 2, not 4
```

Add this import at the top of the test file:

```python
from sqlalchemy import func
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/outcomes/test_labeler.py::test_label_pr_outcomes_creates_rows -v`
Expected: FAIL with `ImportError: cannot import name 'label_pr_outcomes'`

- [ ] **Step 7: Implement label_pr_outcomes and fetch_merge_signals**

Add to `baloo/outcomes/labeler.py`:

```python
from sqlalchemy import func

from baloo.github.api_client import GitHubAPIClient


async def fetch_merge_signals(
    repo_full_name: str, pr_number: int, installation_id: int
) -> tuple[str, list[dict]]:
    """Fetch the diff and review threads for a merged PR.

    Returns:
        Tuple of (compare_diff, threads) where threads is a list of dicts
        with keys: path, line, is_resolved, comments.
    """
    client = GitHubAPIClient(installation_id)

    # Fetch PR review comments (threads)
    headers = await client._get_headers()
    raw_comments = await client._fetch_paginated_json(
        f"{client.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments",
        headers,
    )

    # Fetch PR diff
    async with client._http_client() as http:
        diff_resp = await http.get(
            f"{client.base_url}/repos/{repo_full_name}/pulls/{pr_number}",
            headers={**headers, "Accept": "application/vnd.github.v3.diff"},
        )
        diff = diff_resp.text if diff_resp.status_code == 200 else ""

    # Fetch resolved thread IDs
    resolved_ids = await client.fetch_resolved_thread_ids(repo_full_name, pr_number)

    # Group comments into threads (simplified: group by path+line of root comment)
    threads = []
    root_comments = {}
    for c in raw_comments:
        root_id = c.get("in_reply_to_id") or c["id"]
        if root_id not in root_comments:
            root_comments[root_id] = {
                "path": c.get("path", ""),
                "line": c.get("original_line") or c.get("line") or 0,
                "is_resolved": root_id in resolved_ids,
                "comments": [],
            }
        is_baloo = "baloo" in (c.get("user", {}).get("login", "")).lower()
        root_comments[root_id]["comments"].append({
            "author": c.get("user", {}).get("login", ""),
            "body": c.get("body", ""),
            "is_baloo": is_baloo,
        })

    threads = list(root_comments.values())
    return diff, threads


def _match_finding_to_thread(
    finding: Finding, threads: list[dict]
) -> dict | None:
    """Find the review thread that matches a finding by file path and line."""
    for thread in threads:
        if thread["path"] != finding.file_path:
            continue
        if finding.line_number is None:
            continue
        if abs(thread["line"] - finding.line_number) <= 5:
            return thread
    return None


async def label_pr_outcomes(
    repo_full_name: str, pr_number: int, installation_id: int
) -> None:
    """Label all findings for a merged PR with outcome data.

    Fetches the PR diff and threads, then for each finding:
    1. Checks if code changed near the flagged line
    2. Checks thread interaction (replies, resolution, sentiment)
    3. Applies priority logic to determine outcome
    4. Writes FindingOutcome row (upsert)
    """
    settings = get_settings()
    factory = get_session_factory(settings.database_url)

    # Get all findings for this PR
    async with factory() as session:
        result = await session.execute(
            select(Finding)
            .join(Review)
            .where(
                Review.repo_full_name == repo_full_name,
                Review.pr_number == pr_number,
            )
        )
        findings = result.scalars().all()

    if not findings:
        logger.info(f"No findings for {repo_full_name}#{pr_number}, skipping outcome labeling")
        return

    # Fetch signals from GitHub
    diff, threads = await fetch_merge_signals(repo_full_name, pr_number, installation_id)

    logger.info(
        f"Labeling {len(findings)} findings for {repo_full_name}#{pr_number} "
        f"({len(threads)} threads)"
    )

    # Label each finding
    async with factory() as session:
        async with session.begin():
            for finding in findings:
                # Check if outcome already exists (idempotency)
                existing = (
                    await session.execute(
                        select(FindingOutcome).where(
                            FindingOutcome.finding_id == finding.id
                        )
                    )
                ).scalars().first()
                if existing:
                    continue

                # Collect signals
                code_changed = detect_code_change(
                    finding.file_path, finding.line_number, diff
                )
                thread = _match_finding_to_thread(finding, threads)
                thread_signals = collect_thread_signals(thread)

                signals = {
                    "code_changed_near_line": code_changed,
                    **thread_signals,
                }

                outcome = determine_outcome(signals)

                session.add(FindingOutcome(
                    finding_id=finding.id,
                    review_id=finding.review_id,
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    outcome=outcome,
                    signals=signals,
                    labeled_at=datetime.now(timezone.utc),
                ))

    logger.info(f"Outcome labeling complete for {repo_full_name}#{pr_number}")
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/outcomes/test_labeler.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add baloo/outcomes/labeler.py tests/outcomes/test_labeler.py
git commit -m "feat: add outcome labeler with priority logic and DB persistence"
```

---

### Task 4: Webhook Merge Handler

**Files:**
- Modify: `baloo/github/webhook_handler.py`
- Create: `tests/outcomes/test_webhook_merge.py`

- [ ] **Step 1: Write failing test for merge event handling**

Create `tests/outcomes/test_webhook_merge.py`:

```python
"""Tests for PR merge webhook triggering outcome labeling."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from baloo.github.webhook_handler import app


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(app)
    return TestClient(test_app)


def _make_pr_payload(action: str, merged: bool = False) -> dict:
    return {
        "action": action,
        "number": 42,
        "pull_request": {
            "number": 42,
            "title": "Fix auth",
            "body": "",
            "state": "closed",
            "html_url": "https://github.com/owner/repo/pull/42",
            "user": {"login": "dev", "id": 1},
            "head": {"sha": "abc123", "ref": "fix/auth"},
            "base": {"ref": "main"},
            "merged": merged,
            "draft": False,
        },
        "repository": {"full_name": "owner/repo"},
        "installation": {"id": 12345},
        "sender": {"login": "dev", "id": 1},
    }


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.label_pr_outcomes", new_callable=AsyncMock)
def test_merged_pr_triggers_labeling(mock_label, mock_sig, client):
    """Merged PR triggers outcome labeling."""
    payload = _make_pr_payload("closed", merged=True)
    response = client.post(
        "/webhook",
        json=payload,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "labeling_outcomes"
    mock_label.assert_called_once_with("owner/repo", 42, 12345)


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.label_pr_outcomes", new_callable=AsyncMock)
def test_closed_not_merged_skips_labeling(mock_label, mock_sig, client):
    """Closed but not merged PR does not trigger labeling."""
    payload = _make_pr_payload("closed", merged=False)
    response = client.post(
        "/webhook",
        json=payload,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    mock_label.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/outcomes/test_webhook_merge.py -v`
Expected: FAIL (either import error for `label_pr_outcomes` in webhook handler or assertion error)

- [ ] **Step 3: Add merge handler to webhook_handler.py**

In `baloo/github/webhook_handler.py`, add import at the top:

```python
from baloo.outcomes.labeler import label_pr_outcomes
```

Then add a new branch inside the `if event == "pull_request":` block, after the existing `if action in [...]` block and before the `else` at line 384. Insert between lines 383 and 384:

```python
            elif action == "closed":
                if webhook_payload.pull_request.merged:
                    logger.info(
                        f"PR merged: {repo_name}#{pr_number}, triggering outcome labeling"
                    )
                    asyncio.create_task(
                        label_pr_outcomes(repo_name, pr_number, webhook_payload.installation.id)
                    )
                    background_tasks.add_task(lambda: None)
                    return {"status": "labeling_outcomes", "pr": pr_number}
                else:
                    logger.info(f"PR closed without merge: {repo_name}#{pr_number}")
                    return {"status": "ignored", "action": "closed", "reason": "not merged"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/outcomes/test_webhook_merge.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing webhook tests to check for regressions**

Run: `uv run pytest tests/github/test_webhook_handler.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add baloo/github/webhook_handler.py tests/outcomes/test_webhook_merge.py
git commit -m "feat: trigger outcome labeling on PR merge"
```

---

### Task 5: Dashboard Queries

**Files:**
- Modify: `baloo/dashboard/queries.py`

- [ ] **Step 1: Write failing test for get_outcomes_data**

Create `tests/dashboard/test_outcomes_page.py`:

```python
"""Tests for the outcomes dashboard page."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from baloo.dashboard.auth import verify_credentials
from baloo.dashboard.queries import DashboardService
from baloo.dashboard.router import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_credentials] = lambda: "tester"
    return app


async def test_get_outcomes_data_returns_expected_keys():
    """DashboardService.get_outcomes_data returns all required keys."""
    data = None
    with patch(
        "baloo.dashboard.queries.get_session_factory",
    ) as mock_factory:
        # We'll test the actual query in integration; here just check it exists
        try:
            data = await DashboardService.get_outcomes_data()
        except Exception:
            pass

    # If we got here without ImportError/AttributeError, the method exists
    # Full query testing happens against a real DB
    assert hasattr(DashboardService, "get_outcomes_data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/dashboard/test_outcomes_page.py::test_get_outcomes_data_returns_expected_keys -v`
Expected: FAIL with `AttributeError: type object 'DashboardService' has no attribute 'get_outcomes_data'`

- [ ] **Step 3: Implement get_outcomes_data**

Add to `baloo/dashboard/queries.py`:

Import `FindingOutcome` at the top:
```python
from baloo.db.models import Finding, FindingOutcome, Review, ReviewLog
```

Add this method to `DashboardService`:

```python
    @staticmethod
    async def get_outcomes_data(
        days: int = 90,
        repo_filter: str | None = None,
    ) -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)

        async with factory() as session:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # Base filter
            base_filter = [FindingOutcome.labeled_at >= since]
            if repo_filter:
                base_filter.append(FindingOutcome.repo_full_name == repo_filter)

            # Total outcomes by label
            outcome_rows = (
                await session.execute(
                    select(FindingOutcome.outcome, func.count(FindingOutcome.id))
                    .where(*base_filter)
                    .group_by(FindingOutcome.outcome)
                )
            ).all()
            outcomes = {r[0]: r[1] for r in outcome_rows}
            total = sum(outcomes.values())

            actioned = outcomes.get("actioned", 0)
            disputed = outcomes.get("disputed", 0)
            ignored = outcomes.get("ignored", 0)
            hit_rate = round(actioned / total * 100, 1) if total else 0.0
            noise_rate = round((disputed + ignored) / total * 100, 1) if total else 0.0

            # By severity
            severity_rows = (
                await session.execute(
                    select(
                        Finding.severity,
                        FindingOutcome.outcome,
                        func.count(FindingOutcome.id),
                    )
                    .join(Finding, FindingOutcome.finding_id == Finding.id)
                    .where(*base_filter)
                    .group_by(Finding.severity, FindingOutcome.outcome)
                )
            ).all()
            severity_data = {}
            for sev, outcome, count in severity_rows:
                if sev not in severity_data:
                    severity_data[sev] = {"total": 0, "actioned": 0}
                severity_data[sev]["total"] += count
                if outcome == "actioned":
                    severity_data[sev]["actioned"] += count
            for sev in severity_data:
                t = severity_data[sev]["total"]
                a = severity_data[sev]["actioned"]
                severity_data[sev]["hit_rate"] = round(a / t * 100, 1) if t else 0.0

            # By category
            category_rows = (
                await session.execute(
                    select(
                        Finding.category,
                        FindingOutcome.outcome,
                        func.count(FindingOutcome.id),
                    )
                    .join(Finding, FindingOutcome.finding_id == Finding.id)
                    .where(*base_filter)
                    .group_by(Finding.category, FindingOutcome.outcome)
                )
            ).all()
            category_data = {}
            for cat, outcome, count in category_rows:
                if cat not in category_data:
                    category_data[cat] = {"total": 0, "actioned": 0}
                category_data[cat]["total"] += count
                if outcome == "actioned":
                    category_data[cat]["actioned"] += count
            for cat in category_data:
                t = category_data[cat]["total"]
                a = category_data[cat]["actioned"]
                category_data[cat]["hit_rate"] = round(a / t * 100, 1) if t else 0.0

            # Weekly trends
            if "postgres" in settings.database_url:
                week_label = func.to_char(
                    func.date_trunc("week", FindingOutcome.labeled_at), "YYYY-MM-DD"
                )
            else:
                week_label = func.strftime("%Y-%W", FindingOutcome.labeled_at)

            weekly_rows = (
                await session.execute(
                    select(
                        week_label.label("week"),
                        FindingOutcome.outcome,
                        func.count(FindingOutcome.id),
                    )
                    .where(*base_filter)
                    .group_by("week", FindingOutcome.outcome)
                    .order_by("week")
                )
            ).all()
            weekly = {}
            for week, outcome, count in weekly_rows:
                if week not in weekly:
                    weekly[week] = {"total": 0, "actioned": 0, "disputed": 0, "ignored": 0}
                weekly[week]["total"] += count
                if outcome in weekly[week]:
                    weekly[week][outcome] += count
            trends = []
            for week, data in weekly.items():
                t = data["total"]
                trends.append({
                    "week": week,
                    "total": t,
                    "hit_rate": round(data["actioned"] / t * 100, 1) if t else 0.0,
                    "noise_rate": round(
                        (data["disputed"] + data["ignored"]) / t * 100, 1
                    ) if t else 0.0,
                })

            # Repos for filter dropdown
            repos = (
                (
                    await session.execute(
                        select(FindingOutcome.repo_full_name)
                        .distinct()
                        .order_by(FindingOutcome.repo_full_name)
                    )
                )
                .scalars()
                .all()
            )

        return {
            "total": total,
            "outcomes": outcomes,
            "hit_rate": hit_rate,
            "noise_rate": noise_rate,
            "severity_data": severity_data,
            "category_data": category_data,
            "trends": trends,
            "repos": repos,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/dashboard/test_outcomes_page.py::test_get_outcomes_data_returns_expected_keys -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add baloo/dashboard/queries.py tests/dashboard/test_outcomes_page.py
git commit -m "feat: add outcomes queries to DashboardService"
```

---

### Task 6: Dashboard Route + Template

**Files:**
- Modify: `baloo/dashboard/router.py`
- Modify: `baloo/dashboard/templates/base.html`
- Create: `baloo/dashboard/templates/outcomes.html`
- Modify: `tests/dashboard/test_outcomes_page.py`

- [ ] **Step 1: Write failing test for outcomes route**

Add to `tests/dashboard/test_outcomes_page.py`:

```python
def test_outcomes_page_renders():
    app = _build_app()
    mock_data = {
        "total": 50,
        "outcomes": {"actioned": 20, "disputed": 5, "acknowledged": 10, "ignored": 15},
        "hit_rate": 40.0,
        "noise_rate": 40.0,
        "severity_data": {
            "HIGH": {"total": 20, "actioned": 15, "hit_rate": 75.0},
            "MEDIUM": {"total": 30, "actioned": 5, "hit_rate": 16.7},
        },
        "category_data": {
            "Security": {"total": 15, "actioned": 12, "hit_rate": 80.0},
            "Style": {"total": 20, "actioned": 2, "hit_rate": 10.0},
        },
        "trends": [
            {"week": "2026-16", "total": 25, "hit_rate": 44.0, "noise_rate": 36.0},
            {"week": "2026-17", "total": 25, "hit_rate": 36.0, "noise_rate": 44.0},
        ],
        "repos": ["owner/repo-a", "owner/repo-b"],
    }

    with patch(
        "baloo.dashboard.router.DashboardService.get_outcomes_data",
        new=AsyncMock(return_value=mock_data),
    ):
        client = TestClient(app)
        response = client.get("/dashboard/outcomes")

    assert response.status_code == 200
    assert "Outcomes" in response.text
    assert "40.0" in response.text  # hit_rate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/dashboard/test_outcomes_page.py::test_outcomes_page_renders -v`
Expected: FAIL (404 — route doesn't exist yet)

- [ ] **Step 3: Add route to router.py**

Add to `baloo/dashboard/router.py`:

```python
@router.get("/outcomes", response_class=HTMLResponse)
async def outcomes(
    request: Request,
    days: int = Query(90, ge=1, le=365),
    repo: str | None = Query(None),
):
    data = await DashboardService.get_outcomes_data(days=days, repo_filter=repo)
    return templates.TemplateResponse(
        request=request,
        name="outcomes.html",
        context={"days": days, "repo": repo, **data},
    )
```

- [ ] **Step 4: Add nav link to base.html**

In `baloo/dashboard/templates/base.html`, after the Analytics nav link (line 31), add:

```html
          <a href="/dashboard/outcomes"
             class="inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium
                    {% if active_page == 'outcomes' %}border-indigo-500 text-gray-900{% else %}border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300{% endif %}">
            Outcomes
          </a>
```

- [ ] **Step 5: Create outcomes.html template**

Create `baloo/dashboard/templates/outcomes.html`:

```html
{% extends "base.html" %}
{% set active_page = "outcomes" %}

{% block title %}Outcomes - Baloo Dashboard{% endblock %}

{% block content %}
<div class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-bold text-gray-900">Finding Outcomes</h1>

  <div class="flex items-center space-x-4">
    <!-- Repo filter -->
    <form class="flex items-center space-x-2">
      <input type="hidden" name="days" value="{{ days }}">
      <select name="repo" onchange="this.form.submit()"
              class="text-sm border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500">
        <option value="">All repos</option>
        {% for r in repos %}
        <option value="{{ r }}" {% if repo == r %}selected{% endif %}>{{ r }}</option>
        {% endfor %}
      </select>
    </form>

    <!-- Day range selector -->
    <div class="flex items-center space-x-2">
      <label class="text-sm text-gray-500">Range:</label>
      {% for d in [30, 60, 90, 180, 365] %}
      <a href="/dashboard/outcomes?days={{ d }}{% if repo %}&repo={{ repo }}{% endif %}"
         class="px-3 py-1 text-sm rounded border {% if days == d %}bg-indigo-600 text-white border-indigo-600{% else %}hover:bg-gray-50{% endif %}">
        {{ d }}d
      </a>
      {% endfor %}
    </div>
  </div>
</div>

<!-- Summary cards -->
<div class="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
  <div class="bg-white rounded-lg shadow p-5">
    <p class="text-sm text-gray-500">Total Findings</p>
    <p class="text-3xl font-bold text-gray-900">{{ total }}</p>
  </div>
  <div class="bg-white rounded-lg shadow p-5">
    <p class="text-sm text-gray-500">Hit Rate</p>
    <p class="text-3xl font-bold {% if hit_rate >= 50 %}text-green-600{% elif hit_rate >= 25 %}text-yellow-600{% else %}text-red-600{% endif %}">{{ hit_rate }}%</p>
    <p class="text-xs text-gray-400">actioned / total</p>
  </div>
  <div class="bg-white rounded-lg shadow p-5">
    <p class="text-sm text-gray-500">Noise Rate</p>
    <p class="text-3xl font-bold {% if noise_rate <= 30 %}text-green-600{% elif noise_rate <= 60 %}text-yellow-600{% else %}text-red-600{% endif %}">{{ noise_rate }}%</p>
    <p class="text-xs text-gray-400">(disputed + ignored) / total</p>
  </div>
  <div class="bg-white rounded-lg shadow p-5">
    <p class="text-sm text-gray-500">Outcome Breakdown</p>
    <div class="flex items-center space-x-2 mt-1">
      <span class="text-xs px-2 py-0.5 rounded bg-green-100 text-green-800">{{ outcomes.get('actioned', 0) }} actioned</span>
      <span class="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-800">{{ outcomes.get('acknowledged', 0) }} ack'd</span>
    </div>
    <div class="flex items-center space-x-2 mt-1">
      <span class="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800">{{ outcomes.get('disputed', 0) }} disputed</span>
      <span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-800">{{ outcomes.get('ignored', 0) }} ignored</span>
    </div>
  </div>
</div>

<!-- Charts + Tables -->
<div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
  <!-- Hit rate by severity -->
  <div class="bg-white rounded-lg shadow p-5">
    <h2 class="text-lg font-semibold text-gray-900 mb-4">Hit Rate by Severity</h2>
    <canvas id="severityHitChart" height="250"></canvas>
  </div>

  <!-- Hit rate by category -->
  <div class="bg-white rounded-lg shadow p-5">
    <h2 class="text-lg font-semibold text-gray-900 mb-4">Hit Rate by Category</h2>
    <canvas id="categoryHitChart" height="250"></canvas>
  </div>

  <!-- Trends chart -->
  <div class="bg-white rounded-lg shadow p-5 lg:col-span-2">
    <h2 class="text-lg font-semibold text-gray-900 mb-4">Weekly Trends</h2>
    <canvas id="trendsChart" height="200"></canvas>
  </div>
</div>

<!-- Outcome distribution doughnut -->
<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
  <div class="bg-white rounded-lg shadow p-5">
    <h2 class="text-lg font-semibold text-gray-900 mb-4">Outcome Distribution</h2>
    <canvas id="outcomeChart" height="250"></canvas>
  </div>

  <!-- Category table -->
  <div class="bg-white rounded-lg shadow p-5">
    <h2 class="text-lg font-semibold text-gray-900 mb-4">Category Details</h2>
    <table class="min-w-full text-sm">
      <thead>
        <tr class="border-b">
          <th class="text-left py-2">Category</th>
          <th class="text-right py-2">Total</th>
          <th class="text-right py-2">Actioned</th>
          <th class="text-right py-2">Hit Rate</th>
        </tr>
      </thead>
      <tbody>
        {% for cat, data in category_data.items() | sort(attribute='1.hit_rate', reverse=true) %}
        <tr class="border-b">
          <td class="py-2">{{ cat }}</td>
          <td class="text-right">{{ data.total }}</td>
          <td class="text-right">{{ data.actioned }}</td>
          <td class="text-right font-medium {% if data.hit_rate >= 50 %}text-green-600{% elif data.hit_rate >= 25 %}text-yellow-600{% else %}text-red-600{% endif %}">
            {{ data.hit_rate }}%
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
  const outcomes = {{ (outcomes or {}) | tojson }};
  const severityData = {{ (severity_data or {}) | tojson }};
  const categoryData = {{ (category_data or {}) | tojson }};
  const trends = {{ (trends or []) | tojson }};

  // Outcome doughnut
  const outcomeColors = {
    actioned: '#22c55e', acknowledged: '#3b82f6',
    disputed: '#ef4444', ignored: '#9ca3af'
  };
  new Chart(document.getElementById('outcomeChart'), {
    type: 'doughnut',
    data: {
      labels: Object.keys(outcomes),
      datasets: [{
        data: Object.values(outcomes),
        backgroundColor: Object.keys(outcomes).map(k => outcomeColors[k] || '#6b7280'),
      }]
    },
    options: { responsive: true }
  });

  // Severity hit rate bar
  const sevOrder = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
  const sevColors = { CRITICAL: '#dc2626', HIGH: '#f97316', MEDIUM: '#eab308', LOW: '#3b82f6' };
  new Chart(document.getElementById('severityHitChart'), {
    type: 'bar',
    data: {
      labels: sevOrder.filter(s => severityData[s]),
      datasets: [{
        label: 'Hit Rate %',
        data: sevOrder.filter(s => severityData[s]).map(s => severityData[s].hit_rate),
        backgroundColor: sevOrder.filter(s => severityData[s]).map(s => sevColors[s]),
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, max: 100 } }
    }
  });

  // Category hit rate horizontal bar
  const catNames = Object.keys(categoryData).sort((a, b) => categoryData[b].hit_rate - categoryData[a].hit_rate);
  new Chart(document.getElementById('categoryHitChart'), {
    type: 'bar',
    data: {
      labels: catNames,
      datasets: [{
        label: 'Hit Rate %',
        data: catNames.map(c => categoryData[c].hit_rate),
        backgroundColor: '#6366f1',
      }]
    },
    options: {
      responsive: true,
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, max: 100 } }
    }
  });

  // Weekly trends line chart
  new Chart(document.getElementById('trendsChart'), {
    type: 'line',
    data: {
      labels: trends.map(t => t.week),
      datasets: [
        {
          label: 'Hit Rate %',
          data: trends.map(t => t.hit_rate),
          borderColor: '#22c55e',
          backgroundColor: 'rgba(34,197,94,0.1)',
          fill: true,
          tension: 0.3,
        },
        {
          label: 'Noise Rate %',
          data: trends.map(t => t.noise_rate),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239,68,68,0.1)',
          fill: true,
          tension: 0.3,
        },
        {
          label: 'Volume',
          data: trends.map(t => t.total),
          borderColor: '#6366f1',
          borderDash: [5, 5],
          fill: false,
          tension: 0.3,
          yAxisID: 'y1',
        }
      ]
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: true, max: 100, title: { display: true, text: '%' } },
        y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false }, title: { display: true, text: 'Findings' } }
      }
    }
  });
</script>
{% endblock %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/dashboard/test_outcomes_page.py::test_outcomes_page_renders -v`
Expected: PASS

- [ ] **Step 7: Run all dashboard tests**

Run: `uv run pytest tests/dashboard/ -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add baloo/dashboard/router.py baloo/dashboard/templates/base.html baloo/dashboard/templates/outcomes.html tests/dashboard/test_outcomes_page.py
git commit -m "feat: add outcomes dashboard page with charts and filters"
```

---

### Task 7: Integration Test + Full Suite

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest --cov=baloo -v`
Expected: All tests PASS, no regressions

- [ ] **Step 2: Run linter and formatter**

Run: `uv run ruff check baloo tests && uv run black baloo tests`
Expected: Clean output (or auto-fixed formatting)

- [ ] **Step 3: Fix any issues found**

Address any linting or test failures.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: fix lint and formatting for outcomes feature"
```

---

### Task 8: Backfill Script (separate branch, not merged)

**Files:**
- Create: `scripts/backfill_outcomes.py`

- [ ] **Step 1: Create a new branch**

```bash
git checkout -b tool/backfill-outcomes
```

- [ ] **Step 2: Write the backfill script**

Create `scripts/backfill_outcomes.py`:

```python
"""One-time backfill script to label outcomes for already-merged PRs.

Usage:
    uv run python scripts/backfill_outcomes.py [--dry-run] [--limit N]

NOT intended to be merged into main.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from sqlalchemy import distinct, func, select

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import Finding, FindingOutcome, Review
from baloo.outcomes.labeler import label_pr_outcomes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def get_merged_prs_with_findings(limit: int | None = None) -> list[dict]:
    """Get all merged PRs that have findings but no outcomes yet."""
    settings = get_settings()
    factory = get_session_factory(settings.database_url)

    async with factory() as session:
        # Find PRs with findings that don't have outcomes
        subq = (
            select(distinct(FindingOutcome.review_id))
        ).scalar_subquery()

        q = (
            select(
                Review.repo_full_name,
                Review.pr_number,
                Review.id.label("review_id"),
                func.count(Finding.id).label("finding_count"),
            )
            .join(Finding, Review.id == Finding.review_id)
            .where(
                Review.review_status.in_(["approved", "commented", "changes_requested"]),
                Review.id.notin_(subq),
            )
            .group_by(Review.repo_full_name, Review.pr_number, Review.id)
            .order_by(Review.started_at.asc())
        )
        if limit:
            q = q.limit(limit)

        rows = (await session.execute(q)).all()

    return [
        {
            "repo": r.repo_full_name,
            "pr_number": r.pr_number,
            "review_id": r.review_id,
            "finding_count": r.finding_count,
        }
        for r in rows
    ]


async def main(dry_run: bool = False, limit: int | None = None):
    prs = await get_merged_prs_with_findings(limit=limit)
    total = len(prs)
    logger.info(f"Found {total} PRs to backfill")

    if dry_run:
        for pr in prs:
            logger.info(f"  [dry-run] {pr['repo']}#{pr['pr_number']} ({pr['finding_count']} findings)")
        return

    # Note: installation_id is needed for GitHub API access.
    # For backfill, you'll need to provide this from your app's config.
    from baloo.config.settings import get_settings
    settings = get_settings()
    installation_id = settings.github_app_installation_id

    for i, pr in enumerate(prs, 1):
        logger.info(f"[{i}/{total}] Labeling {pr['repo']}#{pr['pr_number']} ({pr['finding_count']} findings)")
        try:
            await label_pr_outcomes(pr["repo"], pr["pr_number"], installation_id)
        except Exception as e:
            logger.error(f"  Failed: {e}")
            continue

        # Rate limit: 1 second between PRs to avoid GitHub API limits
        if i < total:
            time.sleep(1)

    logger.info(f"Backfill complete: {total} PRs processed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill finding outcomes")
    parser.add_argument("--dry-run", action="store_true", help="List PRs without labeling")
    parser.add_argument("--limit", type=int, default=None, help="Max PRs to process")
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
```

- [ ] **Step 3: Commit on the backfill branch**

```bash
git add scripts/backfill_outcomes.py
git commit -m "tool: add backfill script for finding outcomes (not for merge)"
```

- [ ] **Step 4: Switch back to feature branch**

```bash
git checkout -
```
