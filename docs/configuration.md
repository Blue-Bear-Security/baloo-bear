# Configuration Reference

All Baloo settings are environment variables. Set them in `.env`, pass them via `docker-compose.yml`, or export them directly.

## GitHub App

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_APP_ID` | ✅ | — | Numeric GitHub App ID (not the Client ID) |
| `GITHUB_PRIVATE_KEY` | ✅ | — | Path to `.pem` file (e.g., `.secrets/app.pem`) or inline PEM contents |
| `GITHUB_WEBHOOK_SECRET` | ✅ | — | Webhook signature verification secret |

## LLM API Keys

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key (for Claude models) |
| `GEMINI_API_KEY` | — | — | Google Gemini API key (for fallback / Gemini models) |

## Application

| Variable | Default | Description |
|---|---|---|
| `APP_ENVIRONMENT` | `development` | `development` or `production`. Production disables API docs |
| `APP_HOST` | `0.0.0.0` | Bind host |
| `APP_PORT` | `8000` | Bind port |
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `MAX_CONCURRENT_REVIEWS` | `3` | Max PRs reviewed simultaneously |

## Agent

| Variable | Default | Description |
|---|---|---|
| `AGENT_PROVIDER` | `anthropic` | LLM provider: `anthropic`, `google` |
| `AGENT_MODEL` | `sonnet` | Model short name or `provider/model` string. See [Models](features/models.md) |
| `AGENT_FALLBACK_MODEL` | `google/gemini-2.5-flash` | Fallback model (`provider/model`). Empty to disable |
| `AGENT_MAX_TOKENS` | `4096` | Max output tokens |
| `AGENT_TEMPERATURE` | `0.2` | Generation temperature |
| `PI_BINARY_PATH` | `pi` | Path to PI binary |
| `PI_THINKING_LEVEL` | `medium` | Thinking depth: `off`, `minimal`, `low`, `medium`, `high` |

## Review Behavior

| Variable | Default | Description |
|---|---|---|
| `REVIEW_AUTO_APPROVE` | `true` | Auto-approve PRs with no CRITICAL/HIGH findings |
| `REVIEW_MIN_SEVERITY` | `MEDIUM` | Minimum severity to post: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `REVIEW_USE_CHECKS_API` | `true` | Post MEDIUM findings to Checks API instead of review comments |

## FP Verification

| Variable | Default | Description |
|---|---|---|
| `FP_VERIFICATION_ENABLED` | `false` | Enable LLM false-positive verification pass |
| `FP_VERIFICATION_MODEL` | `haiku` | Model for verification |
| `FP_VERIFICATION_MAX_CONCURRENT` | `5` | Max parallel verification calls |
| `FP_AUDIT_LOG_PATH` | `/var/log/baloo/fp-audit.jsonl` | Audit log path. Empty to disable |

## Fidelity Analysis

| Variable | Default | Description |
|---|---|---|
| `FIDELITY_ENABLED` | `true` | Compare PRs against design plan documents |
| `FIDELITY_PLAN_PATH_PATTERN` | `docs/plans/{ticket_id}.md` | Path pattern with `{ticket_id}` placeholder |
| `FIDELITY_APPROVAL_THRESHOLD` | `90` | Min fidelity score (0–100) for auto-approval boost |
| `TICKET_ID_PREFIX` | `PROJ` | Ticket ID prefix for extraction (e.g., `PROJ` → `PROJ-123`) |

## Database & Dashboard

| Variable | Default | Description |
|---|---|---|
| `DATABASE_ENABLED` | `false` | Enable PostgreSQL persistence |
| `DATABASE_URL` | — | PostgreSQL connection URL. Auto-set in docker-compose |
| `DASHBOARD_ENABLED` | `false` | Enable review history dashboard |
| `DASHBOARD_USERNAME` | — | Dashboard basic auth username |
| `DASHBOARD_PASSWORD` | — | Dashboard basic auth password |
