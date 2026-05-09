# Thread Conversation Agent with Feedback Memory

## Overview

A lightweight agent that responds to developer replies on Baloo's inline review comments, combined with a per-repo feedback memory system that improves review quality over time.

## Goals

1. When a developer replies to a Baloo thread, understand the response and act on it (explain, suggest a fix, concede)
2. Feed thread outcomes back into future reviews so Baloo stops re-flagging patterns the team has explicitly accepted
3. Prevent endless comment loops — hard cap on replies per thread

## Non-Goals

- Replacing the full review pipeline
- Multi-turn open-ended conversation (max one reply per developer message)
- Auto-pushing fix commits
- Per-developer feedback profiles (feedback is per-repo, developer stored as metadata only)

---

## 1. Trigger & Entry Point

### Webhook Handler

Re-enable `pull_request_review_comment` events in `webhook_handler.py` (currently ignored at line ~646). Filter conditions:

- **Accept**: comment where `in_reply_to_id` points to a Baloo comment
- **Reject**: comments authored by Baloo (no self-replies)
- **Reject**: comments on resolved threads
- **Reject**: comments on threads that already have 3+ Baloo messages (escalation cap)

The handler spawns a **ThreadAgent** — a separate flow from the full review pipeline. No semaphore contention with full reviews. Uses a dedicated (smaller) concurrency limit.

### Payload

From the webhook payload, extract:
- `comment.in_reply_to_id` — identifies the root Baloo comment
- `comment.body` — the developer's reply
- `comment.path` and `comment.line` / `comment.original_line` — file location
- `pull_request.number`, `repository.full_name`, `installation.id` — PR context

---

## 2. ThreadAgent

### Model

Cheap/fast model (Haiku or Flash) — same tier as the FP verifier. The thread agent sees a narrow context window and does not need tool access.

### Input Context

The agent receives:
1. **Full thread history** — Baloo's original finding + all subsequent replies, in order
2. **Current code at the location** — fetch the file at `comment.path` from the PR head SHA, extract a window around `comment.line` (roughly +/-30 lines for context)
3. **Original finding metadata** — severity, category, title (parsed from Baloo's formatted comment body)

### Classification

The agent classifies the developer's response:

| Classification | Signal | Baloo's Action |
|---|---|---|
| `acknowledged` | "fixed", "done", "updated", pushed a fix | No reply. Log outcome as `resolved`. |
| `disagreed_valid` | Developer explains why the pattern is intentional and reasoning is sound | Short concede reply ("Got it, makes sense in this context."). Log as `conceded`. Write a `feedback_signal`. |
| `disagreed_invalid` | Developer disagrees but reasoning doesn't hold | One explanation with evidence from the code. Log as `explained`. |
| `question` | Developer asks for clarification or help | Provide explanation + concrete fix suggestion if applicable. Log as `explained`. |
| `unclear` | Ambiguous or unrelated reply | No reply. Thread stays open. Log as `unclear`. |

### Output Schema

```json
{
  "classification": "acknowledged | disagreed_valid | disagreed_invalid | question | unclear",
  "reply": "string or null — the reply to post, null if no reply needed",
  "reasoning": "short internal reasoning for the classification",
  "feedback_signal": {
    "pattern": "natural language description of the accepted pattern",
    "category": "finding category (e.g. Silent Failures, Security)",
    "file_glob": "optional file glob where this pattern applies, or null"
  }
}
```

The `feedback_signal` field is only populated when classification is `disagreed_valid`.

### Escalation Cap

If the thread already contains 3+ Baloo messages (original finding + 2 replies), Baloo stops responding. The outcome is logged as `escalated` — this signals that a human reviewer should look at this thread. No reply is posted.

### Reply Format

Replies are short and conversational. No severity badges, no formatted finding blocks. Examples:
- Concede: "Got it — makes sense given the retry semantics here. I'll keep this in mind for future reviews."
- Explain: "The concern is that if `fetch_config()` raises here, the default empty dict silently replaces the real config, and downstream code won't know it's operating on defaults. Consider logging a warning at minimum."
- Answer: "This is flagged because `shell=True` with string concatenation allows command injection if `filename` contains shell metacharacters. You can fix this with `subprocess.run(['cmd', filename])` instead."

---

## 3. Feedback Memory

### Storage

New `feedback_signals` table in the existing PostgreSQL database.

```sql
CREATE TABLE feedback_signals (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    file_glob TEXT,
    developer TEXT NOT NULL,
    thread_url TEXT,
    pr_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_matched_at TIMESTAMPTZ,
    times_matched INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_feedback_signals_repo ON feedback_signals(repo);
```

### Writing Signals

When the ThreadAgent classifies a response as `disagreed_valid`, the handler writes a row to `feedback_signals` with the pattern, category, optional file glob, and developer identity.

### Reading Signals (Review Prompt Injection)

During a full PR review, before building the review prompt:

1. Query `feedback_signals WHERE repo = ? AND created_at > NOW() - INTERVAL '6 months'`
2. Format as a prompt section injected into the review agent's context (in `prompts.py`, similar to how `_discussion_section` works)

Prompt injection format:

```
## Team Feedback Signals

The following patterns have been previously reviewed and accepted by this team.
Consider these when assigning severity. You may still flag if the specific
instance is genuinely dangerous, but avoid re-flagging patterns the team has
explicitly accepted.

- Silent Failures in `app/retry/*.py`: "except Exception: pass in retry loops
  is intentional" (@alice, 2026-05-07)
- Security in `scripts/`: "shell=True is acceptable in local dev scripts that
  are not deployed" (@bob, 2026-04-20)
```

The LLM decides how to weight these — no hardcoded severity demotion logic. This handles nuance naturally (e.g., "this pattern is fine in retry loops but not in auth code").

### Staleness

Signals older than 6 months without a `last_matched_at` update are auto-expired (excluded from query results). When the review agent sees a signal and acts on it (doesn't flag a matching pattern), the `last_matched_at` and `times_matched` are updated — but this is a v2 optimization, not required for initial implementation.

### Graceful Degradation

If the database is disabled (`DATABASE_ENABLED=false`), feedback signals are simply not written or read. The thread agent still works — it just doesn't persist learnings. Same fail-open pattern as the rest of Baloo.

---

## 4. Integration with Existing Systems

### What Changes

| Component | Change |
|---|---|
| `webhook_handler.py` | Re-enable `pull_request_review_comment` with Baloo-reply filter, spawn ThreadAgent |
| `prompts.py` | New `_feedback_signals_section()` injected into review prompt |
| `db/models.py` | New `FeedbackSignal` model |
| `db/migrations/` | New migration for `feedback_signals` table |
| New: `baloo/agent/thread_agent.py` | ThreadAgent class with system prompt and narrow context builder |
| New: `baloo/agent/thread_prompts.py` | Thread-specific prompt templates |
| New: `baloo/db/feedback_service.py` | CRUD for feedback signals |

### What Doesn't Change

- Full review pipeline (`process_pr_review`)
- FP verifier
- Discussion tracking and dedup logic
- Severity routing
- Decision engine
- Fidelity analysis

### Thread State Integration

When the ThreadAgent processes a reply:
- `conceded` and `acknowledged` outcomes: the thread is treated as resolved in subsequent full reviews (the existing dedup logic in `_match_thread` already skips resolved threads)
- `explained` outcomes: thread goes back to `awaiting_response` — Baloo already skips these during dedup
- The existing `discussions.py` `determine_resolution_state` may need a small update to recognize Baloo concession replies as resolution signals

---

## 5. Configuration

| Variable | Default | Description |
|---|---|---|
| `THREAD_AGENT_ENABLED` | `false` | Enable the thread conversation agent |
| `THREAD_AGENT_MODEL` | `haiku` | Model for thread replies (short name or provider/model) |
| `THREAD_AGENT_MAX_REPLIES` | `3` | Max total Baloo messages per thread (original + replies) before escalation |
| `THREAD_AGENT_MAX_CONCURRENT` | `3` | Max parallel thread agent calls |
| `FEEDBACK_SIGNALS_ENABLED` | `true` | Write and read feedback signals (requires DATABASE_ENABLED) |
| `FEEDBACK_SIGNALS_TTL_DAYS` | `180` | Days before unmatched signals expire |

---

## 6. Cost

Thread agent calls are cheap — narrow context, fast model:
- Haiku: ~$0.001 per thread reply
- Flash: ~$0.0003 per thread reply

Typical PR with 2-3 developer replies: **$0.001-$0.003** extra. Negligible.

---

## 7. Future Extensions (Not in Scope)

- **FP verifier integration**: Use feedback signals as an additional input to the FP verification pass
- **Feedback signal matching tracking**: Update `times_matched` when the review agent acts on a signal
- **Dashboard visibility**: Show feedback signals and thread outcomes in the dashboard
- **Auto-resolve**: If Baloo's finding matches a strong feedback signal (3+ matches), skip posting entirely instead of letting the LLM decide
- **Fix suggestions**: ThreadAgent could suggest code changes as GitHub suggestion blocks
