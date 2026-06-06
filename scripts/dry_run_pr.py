"""Dry-run a Baloo review against a real, checked-out repository.

Unlike ``scripts/local_review.py``, this harness points the agent's working
directory at the repo under review so its file tools (read/grep/find/ls)
actually operate on that repo's files. It also injects a console logger that
reports the success/failure of every tool call, so you can see whether the
agent's tools work.

Examples:
    # Review a checked-out repo (base...HEAD), tools enabled against the repo:
    uv run python -m scripts.dry_run_pr --repo /path/to/repo --base origin/main

    # Reproduce the production bug (cwd NOT set -> tools hit baloo, not the PR):
    uv run python -m scripts.dry_run_pr --repo /path/to/repo --reproduce-bug

Requires PI credentials, e.g. `export ANTHROPIC_API_KEY=...` (or `pi` login).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from baloo.agent.client import BalooAgent
from scripts.local_review import build_local_pr_context

logger = logging.getLogger(__name__)


class ToolOutcomeLogger:
    """Duck-typed ReviewLogger that records tool-call outcomes to memory.

    run_query calls several logger methods (agent_started, turn_completed, ...);
    everything except tool_use is a no-op via __getattr__.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, bool | None]] = []

    async def tool_use(
        self, tool_name: str, file_path: str | None = None, success: bool | None = None
    ) -> None:
        self.calls.append((tool_name, file_path, success))
        marker = "ok " if success else "ERR" if success is False else "?  "
        target = f" {file_path}" if file_path else ""
        print(f"  [tool {marker}] {tool_name}{target}", file=sys.stderr)

    def __getattr__(self, _name: str) -> Any:
        async def _noop(*args: Any, **kwargs: Any) -> None:
            return None

        return _noop


def _print_outcome_summary(collector: ToolOutcomeLogger) -> None:
    print("\n=== Tool call outcomes ===")
    if not collector.calls:
        print("(no tool calls were made)")
        return

    by_tool: Counter[str] = Counter()
    fails: Counter[str] = Counter()
    for name, _path, success in collector.calls:
        by_tool[name] += 1
        if success is False:
            fails[name] += 1

    total = len(collector.calls)
    total_fail = sum(fails.values())
    print(f"total: {total}  |  succeeded: {total - total_fail}  |  failed: {total_fail}")
    for name in sorted(by_tool):
        print(f"  {name}: {by_tool[name]} calls, {fails.get(name, 0)} failed")

    if total_fail:
        print("\nFailed calls:")
        for name, path, success in collector.calls:
            if success is False:
                print(f"  - {name} {path or ''}".rstrip())


async def async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the checked-out repo under review")
    parser.add_argument("--base", default="origin/main", help="Base ref for the diff")
    parser.add_argument("--head", default="HEAD", help="Head ref for the diff")
    parser.add_argument("--model", help="Optional Baloo model override")
    parser.add_argument(
        "--reproduce-bug",
        action="store_true",
        help="Do NOT set the agent cwd (reproduces the production behavior where "
        "file tools run against baloo's own filesystem, not the PR repo)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("baloo.agent.pi_runtime").setLevel(logging.DEBUG)

    repo = str(Path(args.repo).expanduser().resolve())

    context = build_local_pr_context(
        base=args.base,
        head=args.head,
        title="Baloo dry run",
        description="",
        author="dry-run",
        git_workdir=repo,
    )

    agent = BalooAgent(model_override=args.model) if args.model else BalooAgent()
    bug_dir: tempfile.TemporaryDirectory | None = None
    if args.reproduce_bug:
        # Simulate production: the agent's cwd is NOT the PR repo. In production it
        # is baloo's own tree (/app); here we use an empty dir so the absence of the
        # PR's files is unambiguous (no coincidental path overlap with baloo).
        bug_dir = tempfile.TemporaryDirectory(prefix="baloo-wrong-cwd-")
        agent.options.cwd = bug_dir.name
        print(
            f"[cwd] set to an EMPTY dir ({bug_dir.name}) — simulates production, "
            "where cwd is not the PR repo",
            file=sys.stderr,
        )
    else:
        agent.options.cwd = repo
        print(f"[cwd] set to repo under review: {repo}", file=sys.stderr)

    collector = ToolOutcomeLogger()
    result = await agent.review_pr(context, review_logger=collector)

    print("\n=== Review summary ===")
    print(result.summary)
    if result.comments:
        print("\n=== Findings ===")
        for c in result.comments:
            sev = c.severity.value if hasattr(c.severity, "value") else c.severity
            print(f"[{sev}] {c.path}:{c.line}")

    _print_outcome_summary(collector)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
