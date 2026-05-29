"""Repository checkout and instruction context helpers for PR reviews."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import base64
from pathlib import Path, PurePosixPath

from baloo.config.settings import settings
from baloo.github.auth import GitHubAuth
from baloo.github.models import PRContext

logger = logging.getLogger(__name__)

_MAX_GUIDELINES_CHARS = 120_000


def materialize_repository(
    repo_full_name: str,
    head_sha: str,
    installation_id: int,
) -> Path | None:
    """Create a read-only checkout of the PR head SHA for PI file tools."""
    if not settings.repo_checkout_enabled:
        return None

    root = Path(settings.repo_checkout_root)
    root.mkdir(parents=True, exist_ok=True)
    safe_repo = repo_full_name.replace("/", "-")
    checkout_dir = Path(
        tempfile.mkdtemp(prefix=f"{safe_repo}-{head_sha[:8]}-", dir=str(root))
    )

    token = GitHubAuth().get_installation_token(installation_id)
    basic_token = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    extra_header = f"http.extraHeader=Authorization: Basic {basic_token}"
    clone_url = f"https://github.com/{repo_full_name}.git"

    try:
        subprocess.run(
            [
                "git",
                "-c",
                extra_header,
                "clone",
                "--no-checkout",
                "--depth=1",
                clone_url,
                str(checkout_dir),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        subprocess.run(
            [
                "git",
                "-c",
                extra_header,
                "-C",
                str(checkout_dir),
                "fetch",
                "--depth=1",
                "origin",
                head_sha,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        subprocess.run(
            ["git", "-C", str(checkout_dir), "checkout", "--detach", head_sha],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Failed to materialize %s@%s: git command timed out", repo_full_name, head_sha[:12])
        cleanup_repository(checkout_dir)
        return None
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip().splitlines()[-1:] or ["git command failed"]
        logger.warning(
            "Failed to materialize %s@%s: %s",
            repo_full_name,
            head_sha[:12],
            stderr[0],
        )
        cleanup_repository(checkout_dir)
        return None

    return checkout_dir


def cleanup_repository(checkout_dir: Path | None) -> None:
    """Remove a temporary checkout."""
    if checkout_dir is None:
        return
    try:
        shutil.rmtree(checkout_dir, ignore_errors=True)
    except Exception as exc:
        logger.debug("Failed to clean checkout %s: %s", checkout_dir, exc)


def collect_repository_guidelines(
    repo_dir: Path | str,
    changed_files: list[str],
    existing_guidelines: str | None = None,
) -> str | None:
    """Collect root and closest path-local instruction files for changed files."""
    root = Path(repo_dir)
    paths: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            paths.append(path)

    add(root / "AGENTS.md")
    add(root / "CONTRIBUTING.md")

    for changed in changed_files:
        rel = PurePosixPath(changed)
        current = rel.parent
        ancestors = []
        while str(current) not in ("", "."):
            ancestors.append(current)
            current = current.parent
        for ancestor in reversed(ancestors):
            add(root / Path(str(ancestor)) / "AGENTS.md")

    sections: list[str] = []
    if existing_guidelines:
        sections.append("## Previously fetched root guidelines\n\n" + existing_guidelines.strip())

    for path in paths:
        try:
            rel = path.relative_to(root)
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            logger.debug("Skipping guideline file %s: %s", path, exc)
            continue
        sections.append(f"## {rel.as_posix()}\n\n{content.strip()}")

    if not sections:
        return None

    combined = "\n\n---\n\n".join(sections)
    if len(combined) > _MAX_GUIDELINES_CHARS:
        combined = combined[:_MAX_GUIDELINES_CHARS] + "\n\n[truncated]"
    return combined


def enrich_pr_context_with_repository_guidelines(
    pr_context: PRContext,
    repo_dir: Path | str,
) -> PRContext:
    """Return a PRContext copy with checkout-derived repo guidelines attached."""
    changed_files = [file.filename for file in pr_context.files_changed]
    guidelines = collect_repository_guidelines(
        repo_dir,
        changed_files,
        existing_guidelines=pr_context.repo_guidelines,
    )
    if not guidelines:
        return pr_context
    metadata = pr_context.metadata.model_copy(update={"repo_guidelines": guidelines})
    return pr_context.model_copy(update={"metadata": metadata})
