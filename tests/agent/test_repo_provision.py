"""Tests for the agent repo-provisioning module."""

from __future__ import annotations

import asyncio
from pathlib import Path

from baloo.agent import repo_provision as rp


def test_repo_slug_splits_owner_and_repo():
    assert rp._slug("octocat/Hello-World") == "octocat__Hello-World"


def test_cache_dir_partitions_by_installation_then_slug():
    d = rp.cache_dir("/cache", 12345, "octocat/Hello-World")
    assert d == Path("/cache/12345/octocat__Hello-World.git")


def test_worktree_dir_is_unique_per_review_and_sha():
    a = rp.worktree_dir("/cache", 1, "o/r", "rev7", "abcdef1234567890")
    b = rp.worktree_dir("/cache", 1, "o/r", "rev8", "abcdef1234567890")
    assert a != b
    assert a.parent == Path("/cache/1/worktrees")
    assert "rev7" in a.name and "abcdef123456" in a.name


def test_get_lock_returns_same_lock_for_same_key():
    rp._locks.clear()
    a = rp._get_lock("k1")
    b = rp._get_lock("k1")
    c = rp._get_lock("k2")
    assert a is b
    assert a is not c
    assert isinstance(a, asyncio.Lock)
