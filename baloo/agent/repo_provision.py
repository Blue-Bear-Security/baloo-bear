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
import base64
import logging
import os
import shutil
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from baloo.config.settings import get_settings

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


# --- Git command builders + auth --------------------------------------------
def auth_header(token: str) -> str:
    """Build the ``AUTHORIZATION: basic ...`` header value for a GitHub token.

    Passed to git via ``-c http.extraHeader=<this>`` so the credential is never
    written to the stored remote URL (which git would persist in .git/config).
    """
    raw = f"x-access-token:{token}".encode()
    return "AUTHORIZATION: basic " + base64.b64encode(raw).decode()


def _auth_args(token: str | None) -> list[str]:
    if not token:
        return []
    return ["-c", f"http.extraHeader={auth_header(token)}"]


def build_clone_cmd(token: str | None, remote_url: str, dest: str | os.PathLike) -> list[str]:
    return [
        "git",
        *_auth_args(token),
        "clone",
        "--filter=blob:none",
        "--bare",
        remote_url,
        str(dest),
    ]


def build_fetch_cmd(
    token: str | None, cache_dir_path: str | os.PathLike, head_sha: str
) -> list[str]:
    return [
        "git",
        *_auth_args(token),
        "-C",
        str(cache_dir_path),
        "fetch",
        "--filter=blob:none",
        "origin",
        head_sha,
    ]


def build_worktree_add_cmd(
    cache_dir_path: str | os.PathLike, wt_dir: str | os.PathLike, head_sha: str
) -> list[str]:
    return [
        "git",
        "-C",
        str(cache_dir_path),
        "worktree",
        "add",
        "--detach",
        str(wt_dir),
        head_sha,
    ]


def build_worktree_remove_cmd(
    cache_dir_path: str | os.PathLike, wt_dir: str | os.PathLike
) -> list[str]:
    return [
        "git",
        "-C",
        str(cache_dir_path),
        "worktree",
        "remove",
        "--force",
        str(wt_dir),
    ]


def build_worktree_prune_cmd(cache_dir_path: str | os.PathLike) -> list[str]:
    return ["git", "-C", str(cache_dir_path), "worktree", "prune"]


async def _run_git(cmd: list[str], timeout: float = 300.0) -> tuple[int, str]:
    """Run a git command; return (returncode, combined-output-text)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode(errors="replace")


# --- LRU eviction ------------------------------------------------------------
def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            total += p.stat(follow_symlinks=False).st_size
        except OSError:
            pass
    return total


def _evict_over_cap_sync(root: str | os.PathLike, max_bytes: int) -> None:
    """Synchronous LRU eviction body (heavy filesystem I/O).

    Never removes a cache with a live worktree (its normalized path is in
    ``_active``). Run off the event loop via ``_evict_if_over_cap``.
    """
    root = Path(root)
    if not root.exists():
        return
    caches = [p for p in root.glob("*/*.git") if p.is_dir()]
    total = sum(_dir_size(c) for c in caches)
    if total <= max_bytes:
        return
    for cache in sorted(caches, key=lambda c: c.stat().st_mtime):
        if _active.get(_norm(cache), 0) > 0:
            continue
        size = _dir_size(cache)
        shutil.rmtree(cache, ignore_errors=True)
        total -= size
        logger.info("Evicted repo cache %s (~%d bytes)", cache, size)
        if total <= max_bytes:
            break


async def _evict_if_over_cap(root: str | os.PathLike, max_bytes: int) -> None:
    """Evict LRU caches over ``max_bytes``, holding the global evict lock.

    The recursive scan + rmtree can take seconds on a multi-GB cache, so it runs
    in a worker thread to avoid stalling the event loop (and concurrent reviews).
    The lock still serializes eviction against concurrent provisions.
    """
    async with _evict_lock:
        await asyncio.to_thread(_evict_over_cap_sync, root, max_bytes)


# --- GitHub seams (monkeypatched in tests to use a local file:// remote) -----
def _remote_url(repo_full_name: str) -> str:
    """Clean remote URL (no credential). Token is injected via header per call."""
    return f"https://github.com/{repo_full_name}"


_auth_singleton = None
_auth_lock = threading.Lock()  # guards lazy init (called from to_thread workers)


def _get_token(installation_id: int | str) -> str:
    """Return an installation token (never persisted to disk).

    Synchronous (``httpx.post`` under the hood); callers run it via
    ``asyncio.to_thread`` so the blocking HTTP round-trip does not stall the event
    loop. A module-level ``GitHubAuth`` preserves its expiry-aware token cache
    across reviews, so back-to-back reviews of the same installation reuse the
    token instead of re-minting one each time. The lazy init is lock-guarded
    because it runs in worker threads (concurrent reviews).
    """
    global _auth_singleton
    with _auth_lock:
        if _auth_singleton is None:
            from baloo.github.auth import GitHubAuth

            _auth_singleton = GitHubAuth()
    return _auth_singleton.get_installation_token(int(installation_id))


# --- Public entry point ------------------------------------------------------
@asynccontextmanager
async def provision_repo(
    installation_id: int | str,
    repo_full_name: str,
    head_sha: str,
    review_id: int | None = None,
) -> AsyncIterator[Checkout]:
    """Yield a ``Checkout`` for ``repo_full_name`` at ``head_sha``.

    On success, ``Checkout.path`` is a per-review detached worktree; on the
    master switch being off, a missing head SHA, or ANY failure, yields an
    unavailable Checkout so the caller falls back to diff-only.
    """
    s = get_settings()
    if not s.repo_cache_enabled or not head_sha:
        yield Checkout(path=None, available=False)
        return

    root = s.repo_cache_root
    cdir = cache_dir(root, installation_id, repo_full_name)
    ckey = _norm(cdir)
    max_bytes = int(s.repo_cache_max_disk_gb) * 1024**3
    unique = str(review_id) if review_id is not None else uuid.uuid4().hex[:8]
    wt = worktree_dir(root, installation_id, repo_full_name, unique, head_sha)

    checkout = Checkout(path=None, available=False)
    wt_created = False

    # --- Provisioning (may raise; no yield here) ---
    try:
        token = await asyncio.to_thread(_get_token, installation_id)
        remote = _remote_url(repo_full_name)
        cdir.parent.mkdir(parents=True, exist_ok=True)
        wt.parent.mkdir(parents=True, exist_ok=True)

        await _evict_if_over_cap(root, max_bytes)

        async with _get_lock(ckey):
            if not (cdir / "HEAD").exists():
                rc, out = await _run_git(build_clone_cmd(token, remote, cdir))
                if rc != 0:
                    raise RuntimeError(f"clone failed (rc={rc}): {out[-500:]}")
            rc, out = await _run_git(build_fetch_cmd(token, cdir, head_sha))
            if rc != 0:
                raise RuntimeError(f"fetch failed (rc={rc}): {out[-500:]}")
            # Clear stale worktree admin metadata left by crashed reviews.
            await _run_git(build_worktree_prune_cmd(cdir))
            rc, out = await _run_git(build_worktree_add_cmd(cdir, wt, head_sha))
            if rc != 0:
                raise RuntimeError(f"worktree add failed (rc={rc}): {out[-500:]}")
            _active[ckey] = _active.get(ckey, 0) + 1
            wt_created = True

        os.utime(cdir, None)  # touch last_used for LRU
        await _evict_if_over_cap(root, max_bytes)
        checkout = Checkout(path=str(wt), available=True)
    except Exception as exc:  # noqa: BLE001 — any failure => diff-only
        logger.warning(
            "provision_repo failed for %s@%s: %s — falling back to diff-only",
            repo_full_name,
            head_sha[:12],
            exc,
        )
        checkout = Checkout(path=None, available=False)

    # --- Single yield + guaranteed cleanup ---
    try:
        yield checkout
    finally:
        if wt_created:
            async with _get_lock(ckey):
                try:
                    await _run_git(build_worktree_remove_cmd(cdir, wt))
                    await _run_git(build_worktree_prune_cmd(cdir))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("worktree cleanup failed for %s: %s", wt, exc)
                finally:
                    _active[ckey] = max(0, _active.get(ckey, 1) - 1)
