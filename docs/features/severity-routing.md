# Severity Routing

Baloo routes findings to different GitHub surfaces based on severity, so developers see critical issues prominently while non-blocking suggestions stay out of the way.

## Routing Rules

| Severity | Where It Goes | Blocks PR? |
|---|---|---|
| **CRITICAL** | Inline review comment + "Request Changes" | ✅ Yes |
| **HIGH** | Inline review comment + "Request Changes" | ✅ Yes |
| **MEDIUM** | GitHub Checks API annotation | ❌ No |
| **LOW** | Filtered out (not posted) | ❌ No |

## How It Looks

### CRITICAL / HIGH → Review Comments

Posted as inline comments on the exact file and line. The PR review is submitted with "Request Changes" status, which blocks merge (if branch protection requires it).

### MEDIUM → Checks API

Posted as annotations on a GitHub Check called "Baloo Code Quality". These appear in the Checks tab and as non-blocking annotations on the PR diff, but don't block merge.

If the Checks API fails (e.g., missing permissions), MEDIUM findings fall back to regular issue comments.

### LOW → Filtered

Findings below the minimum severity threshold are not posted. This reduces noise for developers.

## Severity Guidelines

The agent assigns severity based on these guidelines:

- **CRITICAL** — Security vulnerabilities, data loss, silent failures, guidelines violations
- **HIGH** — Bugs or logic errors that can break functionality
- **MEDIUM** — Quality, maintainability, or performance issues
- **LOW** — Style or minor polish

## Configuration

| Variable | Default | Description |
|---|---|---|
| `REVIEW_MIN_SEVERITY` | `MEDIUM` | Minimum severity to post. Set to `LOW` to see everything, `HIGH` to reduce noise |
| `REVIEW_USE_CHECKS_API` | `true` | Post MEDIUM findings to Checks API. When `false`, MEDIUM findings go to review comments |
| `REVIEW_AUTO_APPROVE` | `true` | Auto-approve PRs with no CRITICAL/HIGH findings |

## Approval Decision Logic

```
CRITICAL or HIGH found  →  Request Changes
No blocking issues + high fidelity score  →  Approve
No blocking issues + auto-approve enabled  →  Approve
Otherwise  →  Comment only (no approval or rejection)
```
