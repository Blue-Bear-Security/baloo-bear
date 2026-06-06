"""Tests for the agent repo-provisioning module."""

from __future__ import annotations

import asyncio
import base64 as _b64
import os
import subprocess
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
    cmd = rp.build_worktree_add_cmd("TOK123", "/cache/x.git", "/cache/wt", "deadbeef")
    assert cmd == [
        "git",
        "-c",
        f"http.extraHeader={rp.auth_header('TOK123')}",
        "-C",
        "/cache/x.git",
        "worktree",
        "add",
        "--detach",
        "/cache/wt",
        "deadbeef",
    ]


def test_worktree_add_cmd_injects_token_for_lazy_blob_fetch():
    # The bare repo is blobless; `worktree add` checks out the head SHA, which
    # triggers a lazy promisor fetch of the missing file blobs. That fetch must
    # carry the auth header or it fails with "could not read Username".
    cmd = rp.build_worktree_add_cmd("TOK123", "/cache/x.git", "/cache/wt", "deadbeef")
    assert "TOK123@" not in " ".join(cmd)
    assert any(a.startswith("http.extraHeader=AUTHORIZATION: basic ") for a in cmd)


def test_worktree_add_cmd_omits_auth_when_token_empty():
    cmd = rp.build_worktree_add_cmd("", "/cache/x.git", "/cache/wt", "deadbeef")
    assert "-c" not in cmd
    assert not any("http.extraHeader" in a for a in cmd)


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


# --- LRU evictor -------------------------------------------------------------
def _make_cache(root: Path, inst: str, slug: str, *, size: int, mtime: float) -> Path:
    d = root / inst / f"{slug}.git"
    d.mkdir(parents=True)
    (d / "blob").write_bytes(b"x" * size)
    os.utime(d, (mtime, mtime))
    return d


async def test_evictor_noop_under_cap(tmp_path):
    rp._active.clear()
    _make_cache(tmp_path, "1", "o__a", size=100, mtime=1000)
    await rp._evict_if_over_cap(tmp_path, max_bytes=10_000)
    assert (tmp_path / "1" / "o__a.git").exists()


async def test_evictor_removes_lru_first(tmp_path):
    rp._active.clear()
    old = _make_cache(tmp_path, "1", "o__old", size=5_000, mtime=1000)
    new = _make_cache(tmp_path, "1", "o__new", size=5_000, mtime=2000)
    await rp._evict_if_over_cap(tmp_path, max_bytes=6_000)
    assert not old.exists()  # LRU removed
    assert new.exists()  # most-recent kept


async def test_evictor_never_removes_active_cache(tmp_path):
    rp._active.clear()
    old = _make_cache(tmp_path, "1", "o__old", size=5_000, mtime=1000)
    new = _make_cache(tmp_path, "1", "o__new", size=5_000, mtime=2000)
    # Mark the LRU cache as having a live worktree -> must be skipped.
    rp._active[rp._norm(old)] = 1
    await rp._evict_if_over_cap(tmp_path, max_bytes=6_000)
    assert old.exists()  # active -> protected
    assert not new.exists()  # next-oldest non-active removed instead
    rp._active.clear()


# --- provision_repo integration (local file:// remote, no network) -----------
def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _rev(cwd) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(cwd), capture_output=True, text=True
    ).stdout.strip()


def _make_remote(tmp_path: Path):
    """Build a throwaway work repo + bare remote; return (remote, sha1, work)."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "hello.txt").write_text("hi\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "first")
    sha1 = _rev(work)
    remote = tmp_path / "remote.git"
    _git(work, "clone", "-q", "--bare", str(work), str(remote))
    # Allow partial clone + fetch-by-sha over the local protocol.
    _git(remote, "config", "uploadpack.allowFilter", "true")
    _git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    return remote, sha1, work


def _enable_cache(monkeypatch, cache_root: Path, remote: Path):
    from baloo.config.settings import reset_settings

    monkeypatch.setenv("REPO_CACHE_ENABLED", "true")
    monkeypatch.setenv("REPO_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("REPO_CACHE_MAX_DISK_GB", "10")
    reset_settings()
    monkeypatch.setattr(rp, "_remote_url", lambda rfn: f"file://{remote}")
    monkeypatch.setattr(rp, "_get_token", lambda iid: "")


async def test_provision_clone_worktree_read_cleanup(tmp_path, monkeypatch):
    rp._active.clear()
    rp._locks.clear()
    remote, sha1, _ = _make_remote(tmp_path)
    cache_root = tmp_path / "cache"
    _enable_cache(monkeypatch, cache_root, remote)

    wt_path = None
    async with rp.provision_repo("99", "o/r", sha1, review_id=1) as co:
        assert co.available is True
        assert co.path is not None
        wt_path = Path(co.path)
        assert (wt_path / "hello.txt").read_text() == "hi\n"
        # bare cache exists and is reused across reviews
        assert rp.cache_dir(str(cache_root), "99", "o/r").exists()

    # worktree cleaned up at exit
    assert not wt_path.exists()
    assert rp._active.get(rp._norm(rp.cache_dir(str(cache_root), "99", "o/r")), 0) == 0


async def test_provision_disabled_yields_unavailable(tmp_path, monkeypatch):
    from baloo.config.settings import reset_settings

    monkeypatch.setenv("REPO_CACHE_ENABLED", "false")
    reset_settings()
    async with rp.provision_repo("99", "o/r", "abc123", review_id=1) as co:
        assert co.available is False
        assert co.path is None


async def test_provision_failure_falls_back_to_unavailable(tmp_path, monkeypatch):
    rp._active.clear()
    cache_root = tmp_path / "cache"
    from baloo.config.settings import reset_settings

    monkeypatch.setenv("REPO_CACHE_ENABLED", "true")
    monkeypatch.setenv("REPO_CACHE_ROOT", str(cache_root))
    reset_settings()
    # Point at a non-existent remote -> clone fails -> diff-only fallback.
    monkeypatch.setattr(rp, "_remote_url", lambda rfn: f"file://{tmp_path}/nope.git")
    monkeypatch.setattr(rp, "_get_token", lambda iid: "")

    async with rp.provision_repo("99", "o/r", "deadbeef", review_id=1) as co:
        assert co.available is False
        assert co.path is None


async def test_concurrent_worktrees_at_different_shas_coexist(tmp_path, monkeypatch):
    rp._active.clear()
    rp._locks.clear()
    remote, sha1, work = _make_remote(tmp_path)
    # Second commit -> second sha, pushed to the same remote.
    (work / "hello.txt").write_text("bye\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "second")
    sha2 = _rev(work)
    _git(work, "push", "-q", str(remote), "main")
    cache_root = tmp_path / "cache"
    _enable_cache(monkeypatch, cache_root, remote)

    async with (
        rp.provision_repo("99", "o/r", sha1, review_id=1) as a,
        rp.provision_repo("99", "o/r", sha2, review_id=2) as b,
    ):
        assert a.available and b.available
        assert a.path != b.path
        assert (Path(a.path) / "hello.txt").read_text() == "hi\n"
        assert (Path(b.path) / "hello.txt").read_text() == "bye\n"
