# Fidelity Analysis

Fidelity analysis compares a PR's actual changes against a design plan document, scoring how closely the implementation matches the plan.

## Why Fidelity?

When teams write design docs or implementation plans before coding, fidelity analysis closes the loop:

- Did the PR implement what was planned?
- Are there planned items missing from the PR?
- Did the PR add scope beyond the plan?

This is especially useful for teams that use ticket-linked plan files as part of their workflow.

## How It Works

1. **Extract ticket ID** — Baloo looks for a ticket ID in the PR branch name, title, or description (e.g., `PROJ-123` from branch `feat/PROJ-123-add-auth`)
2. **Fetch plan file** — Looks for a plan document at a configurable path (default: `docs/plans/{ticket_id}.md`) in the PR branch
3. **Analyze** — An LLM compares the plan against the PR diff
4. **Score** — Produces a fidelity score (0–100) and a breakdown of matched/missing/extra items
5. **Report** — Posts the fidelity report as a separate PR comment

## Example Output

```
📋 Fidelity Report — PROJ-123

Score: 85/100

✅ Implemented:
- Add JWT token validation middleware
- Create /api/auth/refresh endpoint
- Add rate limiting to auth endpoints

❌ Missing:
- Add integration tests for token refresh flow

➕ Extra (not in plan):
- Added logout endpoint (not planned but reasonable)
```

## Plan File Format

Plan files are freeform markdown. Baloo works best when the plan lists concrete deliverables:

```markdown
# PROJ-123 — Add Authentication

## Planned Changes
- Add JWT middleware in `app/middleware/auth.py`
- Create `/api/auth/login` and `/api/auth/refresh` endpoints
- Add rate limiting (10 req/min) to all auth endpoints
- Write integration tests in `tests/api/test_auth.py`

## Out of Scope
- OAuth2 provider integration (separate ticket)
```

## Impact on Approval

Fidelity score affects the approval decision:

- **Score ≥ threshold** (default 90) + no CRITICAL/HIGH findings → **auto-approve**
- **Score < threshold** → approval requires clean review findings only (fidelity doesn't block, but doesn't help)

This means a high-fidelity PR with only MEDIUM issues can still be auto-approved.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `FIDELITY_ENABLED` | `true` | Enable fidelity analysis |
| `FIDELITY_PLAN_PATH_PATTERN` | `docs/plans/{ticket_id}.md` | Path pattern for plan files |
| `FIDELITY_APPROVAL_THRESHOLD` | `90` | Minimum score for auto-approval boost |
| `TICKET_ID_PREFIX` | `PROJ` | Prefix for ticket extraction (e.g., `PROJ` matches `PROJ-123`) |

## No Plan? No Report

If Baloo can't find a ticket ID or plan file, fidelity analysis is silently skipped. It never blocks a review.
