"""Provision the PR repository for the agent's file tools (Phase 1).

A per-(installation_id, repo) blobless bare clone is cached and reused across
reviews; each review gets its own detached worktree checked out at the PR head
SHA. The agent's ``cwd`` is pointed at that worktree so its read/grep/find/ls
tools operate on the real PR code instead of baloo's own filesystem.

Security / auth:
- The GitHub installation token is injected per git invocation via
  ``-c http.extraHeader=...`` and is NEVER written into the stored remote URL.
  Tokens expire in ~1h but a warm cache lives for days; a token baked into
  ``.git/config`` would pin the cache to a stale token and silently break every
  later fetch. A fresh token is minted per provision.
- Caches are namespaced by installation_id and never shared across
  installations, even for the same public repo.

All failures degrade to diff-only review (the context manager yields an
unavailable ``Checkout``); provisioning never blocks a review.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Checkout:
    """Outcome of a provisioning attempt.

    ``available`` is True only when a worktree was checked out; ``path`` is the
    worktree directory in that case, else None (caller falls back to diff-only).
    """

    path: str | None
    available: bool


# --- Process-global coordination state --------------------------------------
# One asyncio.Lock per cache dir, guarding ref/object-mutating git operations.
_locks: dict[str, asyncio.Lock] = {}
# Separate global lock for the LRU evictor (never nested inside a per-key lock).
_evict_lock: asyncio.Lock = asyncio.Lock()
# Normalized cache-dir path -> count of live worktrees. The evictor must never
# delete a cache whose count is > 0.
_active: dict[str, int] = {}


def _get_lock(key: str) -> asyncio.Lock:
    """Return the per-key lock, creating it on first use.

    Safe without a guard lock: there is no ``await`` between the read and the
    write, so within a single event loop this cannot interleave with another
    coroutine.
    """
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


# --- Pure path helpers (no IO) ----------------------------------------------
def _slug(repo_full_name: str) -> str:
    owner, _, repo = repo_full_name.partition("/")
    return f"{owner}__{repo}"


def _norm(path: str | os.PathLike) -> str:
    """Normalized absolute string for a path (works on non-existent paths)."""
    return str(Path(path).resolve())


def cache_key(installation_id: int | str, repo_full_name: str) -> str:
    return f"{installation_id}/{repo_full_name}"


def cache_dir(root: str, installation_id: int | str, repo_full_name: str) -> Path:
    return Path(root) / str(installation_id) / f"{_slug(repo_full_name)}.git"


def worktree_dir(
    root: str,
    installation_id: int | str,
    repo_full_name: str,
    unique_id: str,
    head_sha: str,
) -> Path:
    short = head_sha[:12]
    name = f"{_slug(repo_full_name)}-{unique_id}-{short}"
    return Path(root) / str(installation_id) / "worktrees" / name
