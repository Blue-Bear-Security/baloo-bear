"""Tests for the agent repo-provisioning module."""

from __future__ import annotations

import asyncio
import base64 as _b64
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


def test_auth_header_is_basic_b64_of_x_access_token():
    header = rp.auth_header("TOK123")
    assert header.startswith("AUTHORIZATION: basic ")
    encoded = header.split("basic ", 1)[1]
    assert _b64.b64decode(encoded).decode() == "x-access-token:TOK123"


def test_clone_cmd_injects_token_via_header_not_url():
    cmd = rp.build_clone_cmd("TOK123", "https://github.com/o/r", "/cache/o__r.git")
    assert "TOK123@" not in " ".join(cmd)
    assert "https://github.com/o/r" in cmd
    assert "-c" in cmd
    assert any(a.startswith("http.extraHeader=AUTHORIZATION: basic ") for a in cmd)
    assert "--filter=blob:none" in cmd
    assert "--bare" in cmd


def test_builders_omit_auth_when_token_empty():
    cmd = rp.build_clone_cmd("", "file:///tmp/remote.git", "/cache/x.git")
    assert "-c" not in cmd
    assert not any("http.extraHeader" in a for a in cmd)


def test_fetch_cmd_targets_cache_and_sha():
    cmd = rp.build_fetch_cmd("TOK", "/cache/x.git", "deadbeef")
    assert cmd[:1] == ["git"]
    assert "-C" in cmd and "/cache/x.git" in cmd
    assert "fetch" in cmd and "origin" in cmd and "deadbeef" in cmd


def test_worktree_add_cmd_is_detached_at_sha():
    cmd = rp.build_worktree_add_cmd("/cache/x.git", "/cache/wt", "deadbeef")
    assert cmd == [
        "git",
        "-C",
        "/cache/x.git",
        "worktree",
        "add",
        "--detach",
        "/cache/wt",
        "deadbeef",
    ]


def test_worktree_remove_and_prune_cmds():
    assert rp.build_worktree_remove_cmd("/cache/x.git", "/cache/wt") == [
        "git",
        "-C",
        "/cache/x.git",
        "worktree",
        "remove",
        "--force",
        "/cache/wt",
    ]
    assert rp.build_worktree_prune_cmd("/cache/x.git") == [
        "git",
        "-C",
        "/cache/x.git",
        "worktree",
        "prune",
    ]
