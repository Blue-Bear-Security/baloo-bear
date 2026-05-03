"""Run a Baloo review locally without posting to GitHub."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlparse

from baloo.agent.client import BalooAgent
from baloo.github.models import FileChange, PRContext, PRDiscussionContext, PRMetadata, ReviewResult

logger = logging.getLogger(__name__)

GitRunner = Callable[[Sequence[str], str | None, bool], str]


def run_git(args: Sequence[str], cwd: str | None = None, check: bool = True) -> str:
    """Run a git command and return stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with exit {proc.returncode}: {proc.stderr.strip()}"
        )
    return proc.stdout.rstrip("\n")


def _git_start_path(git_workdir: str | Path | None) -> Path:
    """Directory used to resolve the git repo root (repo or any path inside it)."""
    if git_workdir is not None:
        start = Path(git_workdir).expanduser().resolve()
    else:
        start = Path.cwd()
    if not start.exists():
        raise RuntimeError(f"Git workdir does not exist: {start}")
    return start


def build_local_pr_context(
    *,
    base: str,
    head: str,
    title: str,
    description: str,
    author: str,
    repo_full_name: str | None = None,
    git_workdir: str | Path | None = None,
    git: GitRunner = run_git,
) -> PRContext:
    """Build a synthetic PRContext from local git diff data.

    Args:
        git_workdir: Filesystem path to the repository (or a path inside it) whose
            ``git diff base...head`` should be reviewed. When omitted, ``Path.cwd()``
            is used — set this when running via ``uv run --directory …`` so the
            process cwd is not the repo under review.
    """
    start = _git_start_path(git_workdir)
    try:
        repo_root = git(["rev-parse", "--show-toplevel"], str(start), True)
    except RuntimeError as exc:
        raise RuntimeError(
            f"Not a git repository (failed rev-parse --show-toplevel from {start})"
        ) from exc
    head_branch = git(["rev-parse", "--abbrev-ref", head], repo_root, True)
    head_sha = git(["rev-parse", head], repo_root, True)
    diff_range = f"{base}...{head}"
    diff = git(["diff", diff_range], repo_root, True)

    if not diff.strip():
        raise RuntimeError(f"No diff found for {diff_range}")

    repo = repo_full_name or _infer_repo_full_name(repo_root, git)
    files_changed = _build_file_changes(
        numstat=git(["diff", "--numstat", diff_range], repo_root, True),
        name_status=git(["diff", "--name-status", diff_range], repo_root, True),
    )
    repo_guidelines = _load_repo_guidelines(head, repo_root, git)

    return PRContext(
        metadata=PRMetadata(
            repo_full_name=repo,
            pr_number=0,
            title=title,
            description=description,
            author=author,
            base_branch=base,
            head_branch=head_branch,
            head_sha=head_sha,
            files_changed=files_changed,
            repo_guidelines=repo_guidelines,
        ),
        discussion=PRDiscussionContext(
            digest="**Open Baloo threads awaiting response:** 0\n"
            "**Recent inline discussions:**\n"
            "- No inline review threads yet.",
            awaiting_response_count=0,
        ),
        diff=diff,
    )


async def run_local_review(
    *,
    context: PRContext,
    agent: BalooAgent,
    model: str | None,
    output_json: bool,
    fail_on_blocking: bool,
) -> int:
    """Run BalooAgent against a synthetic context and print the dry-run result."""
    if model:
        result = await agent.review_pr(context, model_override=model)
    else:
        result = await agent.review_pr(context)

    if output_json:
        print(json.dumps(_result_to_json(result), indent=2))
    else:
        _print_markdown_result(result)

    if fail_on_blocking and _has_blocking_findings(result):
        return 1
    return 0


async def async_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "When using `uv run --directory /path/to/baloo-bear`, the process cwd is "
            "that project — pass `--git-workdir /path/to/repo-under-review` so diffs "
            "and guidelines load from the correct repository."
        ),
    )
    parser.add_argument("--base", default="origin/main", help="Base ref for the comparison")
    parser.add_argument("--head", default="HEAD", help="Head ref for the comparison")
    parser.add_argument(
        "--git-workdir",
        metavar="PATH",
        help=(
            "Git repository root (or any path inside it) for diff/refs; "
            "defaults to current working directory"
        ),
    )
    parser.add_argument("--title", default="Local Baloo review", help="Synthetic PR title")
    parser.add_argument("--description", default="", help="Synthetic PR description")
    parser.add_argument("--author", default="local", help="Synthetic PR author")
    parser.add_argument("--repo-full-name", help="Override inferred owner/repo name")
    parser.add_argument("--model", help="Optional Baloo model override")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--fail-on-blocking",
        action="store_true",
        help="Exit 1 when CRITICAL/HIGH findings are present",
    )
    args = parser.parse_args(argv)

    try:
        context = build_local_pr_context(
            base=args.base,
            head=args.head,
            title=args.title,
            description=args.description,
            author=args.author,
            repo_full_name=args.repo_full_name,
            git_workdir=args.git_workdir,
        )
        return await run_local_review(
            context=context,
            agent=BalooAgent(),
            model=args.model,
            output_json=args.json,
            fail_on_blocking=args.fail_on_blocking,
        )
    except Exception as exc:
        print(f"local review failed: {exc}", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


def _build_file_changes(*, numstat: str, name_status: str) -> list[FileChange]:
    stats = _parse_numstat(numstat)
    changes: list[FileChange] = []

    for raw_line in name_status.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        status_code = parts[0]
        filename = parts[-1]
        additions, deletions = stats.get(filename, (0, 0))
        changes.append(
            FileChange(
                filename=filename,
                status=_status_name(status_code),
                additions=additions,
                deletions=deletions,
                changes=additions + deletions,
            )
        )

    return changes


def _parse_numstat(output: str) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t", 2)
        if len(parts) < 3:
            logger.warning("Unexpected numstat line (skipping): %r", raw_line)
            continue
        additions_raw, deletions_raw, filename = parts
        additions = 0 if additions_raw == "-" else int(additions_raw)
        deletions = 0 if deletions_raw == "-" else int(deletions_raw)
        stats[filename] = (additions, deletions)
    return stats


def _status_name(status_code: str) -> str:
    status = status_code[0]
    return {
        "A": "added",
        "C": "copied",
        "D": "removed",
        "M": "modified",
        "R": "renamed",
        "T": "modified",
        "U": "modified",
    }.get(status, "modified")


def _load_repo_guidelines(head: str, repo_root: str, git: GitRunner) -> str | None:
    guideline_parts: list[str] = []
    for path in ("AGENTS.md", "CONTRIBUTING.md"):
        content = git(["show", f"{head}:{path}"], repo_root, False).strip()
        if content:
            guideline_parts.append(content)
    return "\n\n---\n\n".join(guideline_parts) if guideline_parts else None


def _infer_repo_full_name(repo_root: str, git: GitRunner) -> str:
    remote = git(["config", "--get", "remote.origin.url"], repo_root, False).strip()
    parsed = _parse_github_remote(remote)
    if parsed:
        return parsed
    return f"local/{Path(repo_root).name}"


def _parse_github_remote(remote: str) -> str | None:
    if not remote:
        return None

    if remote.startswith("git@"):
        path = remote.split(":", 1)[-1]
    else:
        parsed = urlparse(remote)
        path = parsed.path.lstrip("/")

    if path.endswith(".git"):
        path = path[:-4]

    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return None


def _print_markdown_result(result: ReviewResult) -> None:
    print(result.summary)
    if not result.comments:
        return

    print("\n## Findings")
    for comment in result.comments:
        severity = _value(comment.severity)
        category = _value(comment.category)
        print(f"\n### [{severity}] {category} - {comment.path}:{comment.line}")
        print(comment.body)


def _result_to_json(result: ReviewResult) -> dict:
    return {
        "summary": result.summary,
        "approve": result.approve,
        "request_changes": result.request_changes,
        "findings": [
            {
                "path": comment.path,
                "line": comment.line,
                "severity": _value(comment.severity),
                "category": _value(comment.category),
                "body": comment.body,
            }
            for comment in result.comments
        ],
    }


def _has_blocking_findings(result: ReviewResult) -> bool:
    return any(_value(comment.severity) in {"CRITICAL", "HIGH"} for comment in result.comments)


def _value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
