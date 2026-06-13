"""Prompts for PR-time documentation drift analysis."""

from __future__ import annotations

import json

from baloo.documentation.models import DocumentationWorkItem
from baloo.github.models import PRContext

DOCUMENTATION_DRIFT_SYSTEM_PROMPT = """You are Baloo's documentation drift reviewer.

You run during pull request review. Your job is to decide whether implementation
changes make existing documentation stale, and whether documentation already
changed in the same PR is sufficient.

Use only read-only tools such as read, grep, find, and ls in the checked-out
repository. Do not edit files. Do not create branches. Do not open pull
requests. Return JSON only.
"""


def build_documentation_drift_prompt(
    *,
    pr_context: PRContext,
    work_item: DocumentationWorkItem,
    catalog_path: str,
) -> str:
    """Build the user prompt for documentation drift analysis."""
    work_item_json = json.dumps(work_item.model_dump(), indent=2, sort_keys=True)
    changed_files_json = json.dumps(
        [
            {
                "filename": file.filename,
                "status": file.status,
                "additions": file.additions,
                "deletions": file.deletions,
                "changes": file.changes,
                "patch": file.patch,
            }
            for file in pr_context.files_changed
        ],
        indent=2,
        sort_keys=True,
    )

    return f"""Review this pull request for documentation drift.

Repository: {pr_context.repo_full_name}
PR: #{pr_context.pr_number}
Title: {pr_context.title}
Catalog: {catalog_path}

Instructions:
- Inspect implementation files and documentation files using read/grep/find/ls in the repo checkout.
- Evaluate every docs_to_review path.
- Inspect every docs_already_changed path and decide whether they are sufficient for this PR.
- Do not recommend docs that are already sufficiently updated in this PR.
- Report unmapped_files as catalog gaps separately from documentation update findings.
- Do not edit files.
- Do not create branches.
- Return JSON only. Do not wrap it in markdown.

Use these verdicts for findings:
- "required": documentation is stale or missing and should be updated in this PR.
- "optional": documentation could be improved but merge should not wait on it.
- "not_needed": a mapped doc was inspected and does not need updates.

Return this JSON shape:
{{
  "summary": "short summary",
  "required_updates": [
    {{
      "doc_path": "docs/path.md",
      "verdict": "required",
      "rationale": "why the doc is stale",
      "evidence": ["changed file or doc path"],
      "suggested_update": "specific update to make"
    }}
  ],
  "optional_updates": [],
  "not_needed": [],
  "catalog_gaps": ["changed implementation path or glob that has no catalog rule"]
}}

Documentation work item:
{work_item_json}

Changed files:
{changed_files_json}

PR diff:
```diff
{pr_context.diff}
```
"""
