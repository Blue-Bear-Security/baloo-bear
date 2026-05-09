"""Prompt templates for code review agent."""

from __future__ import annotations

from typing import Any

from baloo.github.models import PRContext

REVIEW_JSON_RESPONSE_SCHEMA = """## Output Schema
Your response will be parsed as JSON automatically.  Return an object with:
- "findings": list of objects with keys: file, line, severity (CRITICAL|HIGH|MEDIUM|LOW),
  category (Security|Bugs|Silent Failures|Guidelines|Performance|Quality), title, description, impact, recommendation, code_example
- "summary": object with keys: total_issues, critical, high, medium, low,
  files_examined, patterns_searched (list), positive_observations (list)
"""

REVIEW_SEVERITY_GUIDELINES = """## Severity Guidelines
- **CRITICAL**: Reserve for confirmed exploitable vulnerabilities or certain catastrophic data loss only
- **HIGH**: Security concerns, serious bugs, silent failure patterns, or clear guidelines violations
- **MEDIUM**: Quality, maintainability, or performance issues
- **LOW**: Style or minor polish improvements
"""

REVIEW_SYSTEM_PROMPT = f"""You are Baloo, expert code reviewer. Use read/grep/find/ls tools proactively.

## Scope
Flag only issues **introduced or made worse by this PR's changes**. Pre-existing issues in unchanged code are out of scope — the diff is your boundary. Read full files for context, but anchor every finding to a changed line.

## Workflow
1. Read changed files (full context with read tool) 2. grep for security patterns 3. find/ls for tests/configs

## Critical Rules to Prevent False Positives
- **ALWAYS use read tool** before claiming code is missing/undefined
- **NEVER flag code as missing** without verifying the entire file
- **Check diff context carefully**: Code outside diff hunks still exists
- **Verify your findings**: If unsure, use grep to search for the identifier
- **Cross-file verification (MANDATORY)**: A PR spans multiple files. Before flagging:
  - **AttributeError / missing field**: grep for the class definition (`grep -rn "class ClassName"`) and read the file that defines it. The attribute may be added in another file in the same PR.
  - **Missing implementation**: read the file that should contain the implementation before claiming it doesn't exist. A test for `foo()` is not evidence that `foo()` is missing — read the source file.
  - **Rule**: if the attribute/method/field could be defined in a file not yet read, read that file first.

## Priority: Security > Bugs > Silent Failures > Performance > Quality
- **Security (HIGH)**: SQL injection (string concat), XSS, secrets exposure, command injection, auth/authz — use CRITICAL only when impact is clearly exploitable or catastrophic
- **Bugs (HIGH/MEDIUM)**: Logic errors, null refs, leaks, race conditions, error handling
- **Silent Failures (HIGH)**: Swallowed errors, missing input ignored, silent exception handling. Flag patterns such as:
  - Bare `except:` or `except Exception:` that don't re-raise or log the error
  - `try/except` blocks with `pass`, empty bodies, or only comments
  - Catching exceptions and returning default/fallback values without logging
  - Using `.get()` with default values or `or ""` / `or []` / `or {{}}` to silently replace **required** inputs (not optional ones with documented defaults)
  - `if x is not None` / `if x` guards that skip critical logic without logging why
  - `continue` or `return` inside exception handlers without logging the error
  - Any pattern where an error condition is detected but execution continues silently
  Treat as HIGH unless tied to security, data corruption, or guaranteed wrong financial/identity outcomes.
- **Performance (MEDIUM)**: Algorithm efficiency, N+1 queries, blocking ops
- **Quality (MEDIUM/LOW)**: DRY, complexity, naming, tests

## Project Guidelines Compliance (HIGH)
You MUST read `AGENTS.md` and `CONTRIBUTING.md` at the repo root before checking for violations.
Changes that contradict what those files say are HIGH findings. Common examples include:
- Branch names that don't follow the naming convention documented in the guidelines
- Commit messages that don't follow the required format or are missing required ticket references
- Code that violates architectural decisions or tooling choices stated in AGENTS.md
- Dependency management that contradicts the conventions in the guidelines
Only flag a violation if the target repo's guidelines explicitly require a different convention.

## Dependency Reviews
1. Check existing patterns (Glob other dep files)
2. Consider deployment: Binary packages need wheels for target Python version
3. Balance pinning (security) vs ranges (compatibility) - ranges OK for binaries in Lambda/containers
4. Respect context: If PR fixes a build/compatibility issue, acknowledge the constraint
5. **NEVER state unverified version numbers/dates** - say "check PyPI" instead

{REVIEW_JSON_RESPONSE_SCHEMA}

{REVIEW_SEVERITY_GUIDELINES}
Be specific (file:line) and constructive.

## Exhaustive Reporting
Report **ALL** findings in a single pass — never self-limit for brevity. After compiling, do a completeness check and verify you haven't omitted anything noticed during file reads or grep searches.

You MUST return ONLY valid JSON matching the Output Schema above. No markdown fences, no commentary — just the raw JSON object.

REMINDER: Your final message MUST be ONLY the JSON object. Do not include any reasoning, analysis, or text before or after the JSON."""


def _ctx_get(pr_context: PRContext | dict[str, Any], key: str, default: Any = None) -> Any:
    """Read values from either a PRContext model or legacy dict payload."""
    if hasattr(pr_context, "get"):
        return pr_context.get(key, default)
    return getattr(pr_context, key, default)


def _is_simple_pr(pr_context: PRContext | dict[str, Any]) -> bool:
    """Check if this is a simple PR that doesn't need extensive analysis."""
    changed_files = _ctx_get(pr_context, "changed_file_paths", [])

    if not changed_files:
        return False

    # Check if all files are dependency or config files
    simple_file_patterns = [
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "go.mod",
        "go.sum",
        "Gemfile",
        "Gemfile.lock",
        ".md",
        ".txt",
    ]

    return all(any(f.endswith(pattern) for pattern in simple_file_patterns) for f in changed_files)


# Maximum characters to show in recommendation summary fallback
_MAX_RECOMMENDATION_SUMMARY_LENGTH = 200


def _extract_baloo_recommendations(threads: list) -> str:
    """Extract previous Baloo recommendations from discussion threads."""
    recommendations = []

    for thread in threads:
        if not _ctx_get(thread, "is_baloo_thread", False):
            continue

        path = _ctx_get(thread, "path")
        line = _ctx_get(thread, "line")
        if not path or not line:
            continue

        # Get all Baloo comments in this thread
        baloo_comments = [
            comment
            for comment in _ctx_get(thread, "comments", [])
            if _ctx_get(comment, "is_baloo", False)
        ]

        if not baloo_comments:
            continue

        location = f"{path}:{line}"
        status = (
            "⏳ Awaiting response"
            if _ctx_get(thread, "awaiting_response", False)
            else "💬 Active discussion"
        )

        # Extract recommendation from most recent Baloo comment
        latest_baloo = baloo_comments[-1]
        body = _ctx_get(latest_baloo, "body", "")

        # Try to extract recommendation section
        rec_marker = "**Recommendation:**"
        parts = body.split(rec_marker)

        if len(parts) > 1 and parts[1].strip():
            # Extract first few lines after recommendation marker
            rec_lines = parts[1].split("\n")[0:3]  # Get first 3 lines
            rec_summary = "\n".join(rec_lines).strip()

            # Fallback if extraction resulted in empty string
            if not rec_summary:
                rec_summary = body[:_MAX_RECOMMENDATION_SUMMARY_LENGTH].strip()
                if len(body) > _MAX_RECOMMENDATION_SUMMARY_LENGTH:
                    rec_summary += "..."
        else:
            # Fallback: use first N chars of body
            rec_summary = body[:_MAX_RECOMMENDATION_SUMMARY_LENGTH].strip()
            if len(body) > _MAX_RECOMMENDATION_SUMMARY_LENGTH:
                rec_summary += "..."

        recommendations.append(f"- **{location}** ({status}):\n  {rec_summary}")

    if not recommendations:
        return ""

    return "\n".join(recommendations)


def _discussion_section(pr_context: PRContext | dict[str, Any]) -> str:
    """Format a prior discussion section if digest data is available."""
    digest = _ctx_get(pr_context, "discussion_digest")
    threads = _ctx_get(pr_context, "discussion_threads", [])

    if not digest and not threads:
        return ""

    awaiting = _ctx_get(pr_context, "awaiting_discussions")
    awaiting_line = ""
    if isinstance(awaiting, int) and awaiting > 0:
        awaiting_line = f"\nBaloo is still waiting on **{awaiting}** thread(s) to be addressed.\n"

    # Extract Baloo's previous recommendations
    baloo_recs = _extract_baloo_recommendations(threads)
    baloo_section = ""
    if baloo_recs:
        baloo_section = f"""
### Previous Baloo Recommendations

**IMPORTANT**: The following are Baloo's previous recommendations on this PR. When reviewing the same code locations:

**FIRST - Check if recommendations were addressed**:
1. **Read the current code** at each location using the Read tool
2. **Verify if the recommendation was followed** - compare current code to what was recommended
3. **If the issue is fixed**: DO NOT re-flag it. The developer addressed your feedback - move on.
4. **If still unfixed**: You may follow up, but check if there's a valid reason (constraint, different approach, etc.)

**Consistency rules**:
- **DO NOT contradict** previous recommendations unless code changed significantly
- **DO NOT flip-flop** between different valid approaches
- If you previously recommended approach A, don't now recommend approach B (the opposite)
- Only post a new finding if there's a **genuinely new issue** discovered

{baloo_recs}

"""

    return f"""## Prior Discussion Context

{digest}
{awaiting_line}
{baloo_section}
"""


def _feedback_signals_section(signals: list) -> str:
    """Format feedback signals as a review prompt section.

    Args:
        signals: List of FeedbackSignal objects (or mocks with same attributes).

    Returns:
        Formatted prompt section, or empty string if no signals.
    """
    from baloo.db.feedback_service import FeedbackService

    formatted = FeedbackService.format_signals_for_prompt(signals)
    if not formatted:
        return ""

    return f"""## Team Feedback Signals

The following patterns have been previously reviewed and accepted by this team.
Consider these when assigning severity. You may still flag if the specific
instance is genuinely dangerous, but avoid re-flagging patterns the team has
explicitly accepted.

{formatted}

"""


def _is_dependabot_pr(pr_context: PRContext | dict[str, Any]) -> bool:
    """Check if this PR is from Dependabot or similar dependency update bots."""
    author = (_ctx_get(pr_context, "author", "") or "").lower()
    title = (_ctx_get(pr_context, "title", "") or "").lower()
    description = (_ctx_get(pr_context, "description", "") or "").lower()

    # Explicit Dependabot detection
    if "dependabot" in author or "dependabot" in title or "dependabot" in description:
        return True

    # Known dependency update bots (whitelist)
    dependency_bots = ["renovate[bot]", "dependabot[bot]", "dependabot-preview[bot]"]
    if author in dependency_bots:
        return True

    # Bot with dependency-specific keywords (stricter check)
    if author.endswith("[bot]"):
        # More specific dependency-related keywords
        dependency_keywords = ["bump", "upgrade"]
        if any(kw in title for kw in dependency_keywords):
            # Additional check: verify dependency files are being changed
            changed_files = _ctx_get(pr_context, "changed_file_paths", [])
            dep_file_patterns = [
                "requirements.txt",
                "package.json",
                "package-lock.json",
                "go.mod",
                "go.sum",
                "Gemfile",
                "Gemfile.lock",
                "pom.xml",
                "build.gradle",
                "yarn.lock",
                "Cargo.toml",
                "Cargo.lock",
            ]
            if any(
                any(f.endswith(pattern) for pattern in dep_file_patterns) for f in changed_files
            ):
                return True

    return False


def _is_security_patch(pr_context: PRContext | dict[str, Any]) -> bool:
    """Check if this PR is a security patch."""
    title = (_ctx_get(pr_context, "title", "") or "").lower()
    description = (_ctx_get(pr_context, "description", "") or "").lower()

    return (
        "security" in title
        or "security" in description
        or "vulnerability" in title
        or "vulnerability" in description
        or "cve" in title
        or "cve" in description
    )


def _build_simple_pr_review_prompt(
    pr_context: PRContext | dict[str, Any], files_list: str, feedback_signals_text: str = ""
) -> str:
    """Build a focused prompt for simple PRs (configs, deps, docs)."""
    is_dependabot = _is_dependabot_pr(pr_context)
    is_security = _is_security_patch(pr_context)

    dependabot_notice = ""
    if is_dependabot and is_security:
        dependabot_notice = """
**🔒 SECURITY PATCH DETECTED**:
This PR is from Dependabot and addresses a security vulnerability.

**Review Protocol**:
1. **Understand upgrade direction**: OLD version has vulnerability → NEW version fixes it
   - Do NOT report the upgrade itself as introducing a vulnerability
   - The vulnerability existed BEFORE this PR

2. **Check for breaking changes**:
   - Major version bumps (1.x → 2.x) may have compatibility issues
   - Review changelog if mentioned in PR description
   - Look for API changes in the diff

3. **Default to APPROVE**:
   - Security fixes are critical and should be merged quickly
   - Only recommend REJECTION if:
     * Package version doesn't exist or is incompatible with runtime
     * Clear evidence the update will immediately break the application
   - If breaking changes detected: Still recommend APPROVAL but note "Needs migration" with specific steps

4. **Be specific and constructive**:
   - Mention the security fix being addressed
   - List any compatibility concerns with mitigation steps
   - Don't create unnecessary blockers for critical security updates

"""
    elif is_dependabot:
        dependabot_notice = """
**🤖 DEPENDABOT PR DETECTED**:
This is an automated dependency update. Focus on:
1. Version changes (are they reasonable?)
2. Breaking changes
3. Compatibility with current codebase
4. Security implications (if any)

Be practical - automated updates usually don't need extensive review unless they involve major version bumps.

"""

    return f"""Review this simple configuration/dependency change:

## Pull Request Information

**Title**: {_ctx_get(pr_context, "title")}
**Author**: {_ctx_get(pr_context, "author")}
**Files Changed**: {len(_ctx_get(pr_context, "files_changed", []))}
{files_list}

**Description**:
{_ctx_get(pr_context, "description", "No description provided.")}

{dependabot_notice}
{_discussion_section(pr_context)}
{feedback_signals_text}
## Changes

```diff
{_ctx_get(pr_context, "diff")}
```

## Task

This is a configuration or dependency file change. Perform a focused review:

**FIRST - Check PR Context**:
Look at the PR description above. Does it mention:
- "Baloo" or "previous review" or "code review"?
- "fixing" or "addresses" a build failure or compatibility issue?
- References to another PR that had review comments?

If YES: This PR may be fixing a constraint or addressing feedback. Understand WHAT problem it's solving before suggesting alternatives. Be practical, not theoretical.

1. **Read** the changed file(s) using the read tool
2. **Check context** (optional): Use find/ls to locate other similar files to understand project patterns
3. Analyze the changes for:
   - Dependency version issues (consider Python version, wheel availability, deployment constraints)
   - Configuration correctness and security
   - Breaking changes or compatibility issues
   - Documentation accuracy

**Important for dependencies**:
- If this PR is fixing a previous issue (especially from a previous review), acknowledge the constraint
- Binary packages need wheels for the target Python/runtime version
- Respect existing versioning patterns in the project
- Don't recommend impossible constraints (e.g., pinning versions that don't support the runtime)
- NEVER state specific version numbers or release dates unless you can verify them

**Keep it focused**: Review only what's relevant to these specific changes.

**Be exhaustive**: Report ALL issues you find in this single pass. Do not hold back findings for brevity.
Before emitting JSON, do a completeness check — re-read your analysis notes and verify you haven't
omitted any issues you noticed. The developer should not discover new pre-existing issues in a follow-up review.

**Output immediately**: After reading and analyzing, provide your findings as JSON matching the schema.
If no issues found, return empty findings array. Be practical and focus on real risks."""


def build_pr_review_prompt(pr_context: PRContext | dict[str, Any]) -> str:
    """
    Build a prompt for reviewing a pull request.

    Args:
        pr_context: Context about the PR

    Returns:
        Formatted prompt string
    """
    # Extract file paths for explicit tool guidance
    changed_files = _ctx_get(pr_context, "changed_file_paths", [])
    files_list = "\n".join([f"  - {file}" for file in changed_files])

    # Build guidelines section from fetched repo guidelines
    repo_guidelines = _ctx_get(pr_context, "repo_guidelines")
    if repo_guidelines:
        guidelines_section = (
            f"The following guidelines were fetched directly from this repository:\n\n"
            f"```\n{repo_guidelines}\n```\n\n"
            f'Flag any violations of the conventions documented above as **HIGH** with category "Guidelines".\n'
            f"Only flag a violation if the guidelines explicitly require a specific convention."
        )
    else:
        guidelines_section = (
            "No `AGENTS.md` or `CONTRIBUTING.md` found in this repository. "
            "Skip guidelines compliance check."
        )

    # Build feedback signals section
    feedback_signals = _ctx_get(pr_context, "feedback_signals", [])
    feedback_signals_text = _feedback_signals_section(feedback_signals)

    # Use simplified prompt for simple PRs (configs, deps, docs)
    if _is_simple_pr(pr_context):
        return _build_simple_pr_review_prompt(pr_context, files_list, feedback_signals_text)

    return f"""Please review the following pull request:

## Pull Request Information

**Title**: {_ctx_get(pr_context, "title")}
**Author**: {_ctx_get(pr_context, "author")}
**Base Branch**: {_ctx_get(pr_context, "base_branch")} ← **Head Branch**: {_ctx_get(pr_context, "head_branch")}

**Description**:
{_ctx_get(pr_context, "description", "No description provided.")}

{_discussion_section(pr_context)}
{feedback_signals_text}
**Files Changed**: {len(_ctx_get(pr_context, "files_changed", []))} files

{files_list}

## Code Changes (Diff Overview)

```diff
{_ctx_get(pr_context, "diff")}
```

## Your Task

Perform a thorough agentic code review following your system prompt guidelines. **You MUST use your tools proactively:**

### Step 0: Understand PR Context (REQUIRED)
**Check the PR description above carefully**. Look for:
- Mentions of "Baloo", "previous review", "code review", "recommended"
- References to fixing build failures or compatibility issues
- Links to other PRs or issues that explain constraints

**If this PR is fixing a problem**: Understand the constraint being addressed before suggesting alternatives. Be practical.

### Step 1: Read Full Context (REQUIRED)
Use the **read** tool to examine each changed file in full context:
{files_list}

**CRITICAL**: Do NOT rely only on the diff. You MUST read the complete files using the read tool to understand:
- Full file context (not just the changed lines)
- Code that exists outside the diff (before/after changed sections)
- Dependencies and imports at the top of files
- Related code that may be referenced in changes

**NEVER flag code as "missing" or "undefined" without first using the read tool to verify it doesn't exist elsewhere in the file.**

**Cross-file verification**: When a changed file accesses an attribute or calls a method on a type defined in another file (e.g. `thread.outdated`, `result.max_turns_reached`), you MUST:
1. Use grep to locate the class/type definition: e.g. `grep -rn "class DiscussionThread"`
2. Read the defining file and verify whether that attribute exists
Do this BEFORE flagging any AttributeError, missing field, or unimplemented method. The attribute may have been added in the same PR in a file you haven't read yet.

### Step 2: Search for Patterns (REQUIRED)
Use the **grep** tool to search for:
- Security-sensitive patterns: `password`, `api_key`, `secret`, `token`, `API_KEY`, `SECRET`
- SQL injection risks: `SELECT.*FROM`, `INSERT INTO`, `UPDATE.*SET`, `DELETE FROM` (look for string concatenation)
- Command injection: `exec\\(`, `eval\\(`, `subprocess`, `os.system`, `shell=True`
- **Silent error swallowing (CRITICAL)**: Search changed files for these patterns:
  - `except.*pass` or `except.*:` followed by `pass` - swallowed exceptions
  - `except.*continue` - silently skipping errors in loops
  - `except.*return None` or `except.*return ""` or `except.*return \\[\\]` - replacing errors with defaults
  - `.get\\(` with default values for required inputs
  - `or ""` / `or []` / `or {{}}` / `or 0` - silent default substitution for missing data
  - `try/except` blocks that do NOT contain `log`, `logger`, `logging`, `raise`, `warn`, or `print`
  For every match, verify if the error is truly being swallowed (no logging, no re-raise, no alerting). If so, flag as HIGH (CRITICAL only if it causes certain data loss or an exploitable security vulnerability).
- Code duplication: Search for function names and patterns similar to changed code
- Test coverage: Search for test files related to changed modules

### Step 3: Check Project Guidelines Compliance (REQUIRED)
{guidelines_section}

### Step 4: Discover Related Files (REQUIRED)
Use the **find** and **ls** tools to locate:
- Configuration files: `.eslintrc*`, `.prettierrc*`, `pyproject.toml`, `setup.cfg`
- Test files: `test_*.py`, `*_test.py`, `tests/`, `__tests__/`
- Documentation: `README.md`, `docs/`

### Step 5: Compile Final Report (REQUIRED)

After completing your analysis, provide your findings as JSON matching the output schema.
You MUST return ONLY valid JSON matching the Output Schema. No markdown fences, no commentary — just the raw JSON object.

For each issue you identify:
1. Specify the exact file path and line number
2. Assign a severity level (CRITICAL, HIGH, MEDIUM, LOW)
3. Explain the problem clearly
4. Suggest a specific fix with code examples

Focus on issues that truly matter for security, correctness, and maintainability. Be thorough but practical.

### Step 6: Completeness Check (REQUIRED)
Before emitting your final JSON, review your analysis:
- Re-read your notes from Steps 1-4. Did you notice any issues that you haven't included in your findings?
- Check every file you read — did you skip any findings because you already had "enough"?
- If you found issues of different severities, make sure ALL of them are included, not just the top few.
- Report everything in this single pass.
"""
