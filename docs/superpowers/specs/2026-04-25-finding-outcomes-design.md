# Finding Outcomes: Learning from Past Reviews

## Overview

Add outcome tracking to Baloo findings so we can measure review quality over time. When a PR is merged, label each finding with an outcome based on what happened: was the code changed, did the developer reply, did they dispute it, or was it ignored?

This is the measurement layer. No changes to the review pipeline — just data collection and reporting. Future work (prompt tuning, per-repo optimization) builds on this data.

## Scope

- **Forward capture** (production feature): On PR merge, label all findings for that PR. CLI reports for querying outcomes.
- **Backfill script** (throwaway, not merged): One-time script to label findings on already-merged PRs.

## Outcome Schema

New table `finding_outcomes`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | PK (UUID) | |
| `finding_id` | FK -> findings | |
| `review_id` | FK -> reviews | Denormalized for easy querying |
| `repo_full_name` | text | |
| `pr_number` | int | |
| `outcome` | enum | `actioned`, `disputed`, `acknowledged`, `ignored` |
| `signals` | jsonb | Raw signal data for future reinterpretation |
| `labeled_at` | timestamp | When labeling ran |

### Outcome Labels

Single label per finding. When multiple signals are present, highest-priority label wins:

1. **`actioned`** — Code near the flagged line changed in a subsequent commit
2. **`disputed`** — Developer replied negatively ("false positive", "intentional", "disagree")
3. **`acknowledged`** — Developer replied positively ("good catch", "thanks") without code change
4. **`ignored`** — No reply, no code change

### Signals (jsonb)

Raw data preserved for future reinterpretation:

```json
{
  "code_changed_near_line": true,
  "thread_resolved": true,
  "developer_replied": true,
  "reply_sentiment": "positive",
  "reply_text": "good catch, fixed"
}
```

## Signal Collection

On PR merge, for each finding:

### Code Change Detection

- Compare the diff between the commit Baloo reviewed and the final merge commit
- If lines within +/-5 range of the flagged line were modified in a later commit, `code_changed_near_line: true`

### Thread Interaction

- Fetch PR review threads from GitHub API (reuse existing `get_pr_context` logic)
- Match each finding to its posted comment via file path and line number
- Check: was there a developer reply? Is the thread resolved?

### Reply Sentiment

Simple keyword matching (no LLM for v1):

- **Positive**: "fixed", "good catch", "thanks", "done", "resolved"
- **Negative**: "false positive", "intentional", "disagree", "not a bug", "by design"
- **Neutral**: Any other reply

## Merge Event Handler

### Webhook Integration

Add a `closed` action branch in `webhook_handler.py` (line 285). The app already receives `pull_request` events — no GitHub App configuration changes needed.

When `action == "closed"` and `pull_request.merged == true`:
- Trigger `label_pr_outcomes(repo_name, pr_number, installation_id)` as a background task

### Labeling Function

`label_pr_outcomes(repo_name, pr_number, installation_id)`:

1. Query all findings for the PR from the DB
2. If none, skip (PR was never reviewed by Baloo)
3. Fetch PR threads and final diff via `GitHubAPIClient`
4. For each finding, collect signals and apply priority logic to determine outcome
5. Write `finding_outcomes` rows (upsert for idempotency)

## Dashboard Page

New page at `/dashboard/outcomes` in the existing Jinja2 + HTMX + Chart.js dashboard.

### Queries

Add outcome queries to `DashboardService` in `baloo/dashboard/queries.py`.

### Views

**Overview section** — Stat cards:
- Total findings with outcomes, breakdown by outcome (actioned/disputed/acknowledged/ignored)
- Hit rate: `actioned / total`
- Noise rate: `(disputed + ignored) / total`

**By severity & category** — Table or bar chart:
- Hit rate per severity level (Critical, High, Medium)
- Hit rate per category (e.g., Security: 85%, Style: 12%)

**Trends** — Chart.js time-series (weekly/monthly buckets):
- Hit rate trend
- Noise rate trend
- Volume trend (findings per review)

**Repo filter** — Dropdown to scope all views to a specific repo (reuse existing repo filter pattern from `/dashboard/reviews`)

### Template

`baloo/dashboard/templates/outcomes.html` extending `base.html`, following the same patterns as `analytics.html`.

## Backfill Script (separate branch, not merged)

Standalone script:

- Queries all merged PRs from `reviews` table that have findings
- Runs the same labeling logic as forward capture
- Rate-limited GitHub API calls
- Progress output
- Idempotent (safe to re-run)
- Lives on its own branch, not merged into main

## Future Work (out of scope)

These build on the outcome data but are not part of this spec:

- **Prompt injection**: Feed historical patterns into the agent prompt ("style nits rarely actioned in this repo")
- **Post-review filter**: Suppress findings matching high-FP patterns
- **Per-repo optimization**: Tune review behavior based on repo-specific outcome data
- **Per-contributor optimization**: Adjust based on individual developer patterns
