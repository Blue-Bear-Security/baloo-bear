"""Prompt templates for the false-positive verification pass."""

from __future__ import annotations

from baloo.github.models import ReviewComment

FP_SYSTEM_PROMPT = """\
You are a precise code review verifier. Your job is to check whether a code \
review finding is a real issue or a false positive.

You will receive:
1. A finding (title, severity, description, recommendation)
2. The surrounding code context (diff hunk and/or file content)

Rules:
- A finding is a FALSE POSITIVE if:
  - The flagged code doesn't actually have the described problem
  - The issue is already handled elsewhere in the visible context
  - The finding misreads the code (e.g., claims string concat SQL but it's parameterized)
  - The finding flags something that doesn't exist in the actual code
  - The description contradicts what the code actually does

- A finding is REAL if:
  - The described problem genuinely exists in the code
  - Even if minor, the finding accurately describes a real concern

Be strict: only mark as false positive if you're confident the finding is wrong.
When in doubt, mark as real.

IMPORTANT: You have NO tools. Do NOT attempt to read files, search, or call \
any tools. All the context you need is provided in the prompt. Analyze the \
provided diff and finding, then respond.

Your response must be ONLY a raw JSON object, nothing else:
{"verdict": "real", "reason": "one concise sentence"}
or
{"verdict": "fp", "reason": "one concise sentence"}

No markdown fences, no explanation before or after — just the JSON object.
"""


def build_verification_prompt(
    comment: ReviewComment,
    diff_context: str,
    file_context: str | None = None,
) -> str:
    """Build a verification prompt for a single finding.

    Args:
        comment: The review finding to verify.
        diff_context: The diff hunk(s) for the file.
        file_context: Optional full file content around the flagged line.

    Returns:
        Prompt string for the verification model.
    """
    parts = [
        "## Finding to verify",
        f"**File**: {comment.path}, line {comment.line}",
        f"**Severity**: {comment.severity.value}",
        f"**Category**: {comment.category.value}",
        "",
        comment.body,
        "",
    ]

    if file_context:
        parts.extend(
            [
                "## File context (around flagged line)",
                "```",
                file_context,
                "```",
                "",
            ]
        )

    parts.extend(
        [
            "## Diff",
            "```diff",
            diff_context,
            "```",
            "",
            'Is this finding real or a false positive? Respond with ONLY a raw JSON object (no markdown, no explanation): {"verdict": "real"|"fp", "reason": "one concise sentence"}',
        ]
    )

    return "\n".join(parts)


def extract_diff_for_file(full_diff: str, file_path: str) -> str:
    """Extract the diff hunk(s) for a specific file from the full PR diff.

    Args:
        full_diff: The complete PR diff.
        file_path: Path of the file to extract.

    Returns:
        Diff section for the file, or empty string if not found.
    """
    lines = full_diff.split("\n")
    result: list[str] = []
    capturing = False

    # Exact-boundary match: diff headers are "diff --git a/<path> b/<path>",
    # so look for the full tokens to avoid suffix-substring false matches
    # (e.g. "lib/auth.py" matching "tests/lib/auth.py").
    a_token = f"a/{file_path}"
    b_token = f"b/{file_path}"

    def _header_is_for_file(header: str) -> bool:
        # Header form: diff --git a/<pathA> b/<pathB>.  For renames, pathA
        # and pathB differ, so match if either side's token is present.
        parts = header.split()
        return a_token in parts or b_token in parts

    for line in lines:
        if line.startswith("diff --git"):
            if capturing:
                break  # We were capturing and hit a new file — done
            capturing = _header_is_for_file(line)
            if capturing:
                result.append(line)
        elif capturing:
            result.append(line)

    return "\n".join(result)
