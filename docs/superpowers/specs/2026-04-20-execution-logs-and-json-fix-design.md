# Execution Logs & JSON Parsing Fix

## Problem

1. **JSON parsing failures**: The agent model sometimes emits a long reasoning preamble before the JSON output. The current 3-strategy extractor fails on mixed text+JSON (14K+ chars), and the retry subprocess also fails. Different models have different compliance levels with output format instructions — we can't rely on prompting alone.

2. **No visibility into task execution**: Diagnosing failures requires reading Docker logs, which is noisy and inconvenient. There's no way to see what happened during a review from the dashboard.

## Solution

Structured execution logging per review stored in the database and surfaced in the dashboard, combined with improved JSON extraction and prompt reinforcement.

## Database Schema

New `review_log` table:

| Column      | Type                | Notes                                              |
|-------------|---------------------|----------------------------------------------------|
| id          | UUID                | Primary key                                        |
| review_id   | UUID                | FK → reviews.id, CASCADE delete                    |
| created_at  | timestamp           | Indexed for retention cleanup                      |
| event_type  | varchar             | One of the known event types below                 |
| message     | text                | Human-readable summary                             |
| raw_text    | text, nullable      | Full assistant response — populated only on failure |
| metadata    | jsonb, nullable     | Structured extras (tokens, turn number, model)     |

**Indexes:**
- `(review_id, created_at)` — fast per-review timeline queries
- `(created_at)` — retention cleanup

**Event types:**
- `agent_started` — review kicked off (model name in metadata)
- `turn_completed` — one agent turn finished (turn number, tokens in metadata)
- `tool_use` — agent invoked a tool (tool name, file path in metadata)
- `json_parse_failed` — extraction failed, raw_text populated
- `json_retry_started` — retry subprocess spawned
- `json_retry_failed` — retry also failed, raw_text populated
- `fallback_triggered` — switching to fallback model
- `agent_completed` — finished successfully (total tokens, cost, duration in metadata)
- `agent_error` — unrecoverable error (exception message)

**Retention:** `DELETE FROM review_log WHERE created_at < NOW() - INTERVAL '30 days'` — configurable via `LOG_RETENTION_DAYS` setting. Runs on app startup.

## ReviewLogger

A class that the runtime uses to emit events during execution.

```
ReviewLogger
├── __init__(review_id, db_session)
├── async log(event_type, message, raw_text=None, metadata=None)
│   └── Inserts a ReviewLog row immediately (no buffering — crash-safe)
├── async agent_started(model, thinking_level)
├── async turn_completed(turn_number, tokens_in, tokens_out)
├── async tool_use(tool_name, file_path=None)
├── async json_parse_failed(raw_text, char_count)
├── async json_retry_started()
├── async json_retry_failed(raw_text)
├── async fallback_triggered(primary_model, fallback_model, error)
├── async agent_completed(tokens_in, tokens_out, cost, duration)
├── async agent_error(error_message, error_category)
```

**When DB is disabled:** ReviewLogger becomes a no-op (methods return immediately).

### Runtime Integration Points

In `pi_runtime.py`:
- `run_query()` — receives a `ReviewLogger`, calls `agent_started` at top
- `_drive_session()` — calls `turn_completed` after each `turn_end` event, `tool_use` on tool events
- After `_extract_json_from_text()` fails — calls `json_parse_failed` with raw text
- `_retry_json()` — calls `json_retry_started`/`json_retry_failed`
- `run_query()` exit — calls `agent_completed` or `agent_error`

In `client.py`:
- `_run_with_fallback()` — calls `fallback_triggered` when switching models
- Creates the `ReviewLogger` and passes it down to the runtime

## JSON Extraction Improvements

### New reverse-scan strategy

The model consistently puts JSON at the end after reasoning. Scan backwards from the end of the text to find the last `}`, then walk backwards counting brace depth (respecting string literals) to find its matching `{`. Parse that substring.

### Updated strategy order

1. **Direct JSON parse** — entire text is valid JSON
2. **Markdown fence extraction** — ```json ... ``` blocks
3. **Reverse-scan** (new) — find the last complete JSON object from the tail
4. **Outermost braces** (demoted) — first `{` to last `}`, last-resort fallback

### Prompt reinforcement

Add closing instruction to the system prompt, after tool definitions:

```
REMINDER: Your final message MUST be ONLY the JSON object.
Do not include any text before or after the JSON.
```

## Dashboard UI

New "Execution Log" section on the review detail page (`review_detail.html`).

### Layout

- Sits below the existing findings table
- Vertical timeline: each event shows timestamp, color-coded event type badge, and message
- `json_parse_failed` and `json_retry_failed` events get an expandable "Show raw response" toggle revealing raw_text in a scrollable `<pre>` block
- Error events in red, warnings in amber, info in neutral

### New endpoint

```
GET /dashboard/reviews/{review_id}/logs
```

Returns partial HTML (HTMX-compatible) of the log timeline. Loaded asynchronously so the main detail page isn't slowed by large log sets.

### New query

```python
DashboardService.get_review_logs(review_id) → list[ReviewLog]
```

## Files to Create/Modify

**New files:**
- `baloo/db/migrations/003_add_review_logs.py` — Alembic migration
- `baloo/agent/logger.py` — ReviewLogger class

**Modified files:**
- `baloo/db/models.py` — ReviewLog model
- `baloo/agent/pi_runtime.py` — emit log events, add reverse-scan extraction strategy
- `baloo/agent/client.py` — create ReviewLogger, pass to runtime, emit fallback events
- `baloo/agent/prompts.py` — add JSON reminder to system prompt
- `baloo/config/settings.py` — add `LOG_RETENTION_DAYS` setting
- `baloo/dashboard/router.py` — add logs endpoint
- `baloo/dashboard/queries.py` — add `get_review_logs` query
- `baloo/dashboard/templates/review_detail.html` — add execution log section
- `baloo/dashboard/templates/partials/review_logs.html` — log timeline partial
- `tests/agent/test_runtime.py` — tests for reverse-scan extraction
- `tests/agent/test_logger.py` — tests for ReviewLogger
