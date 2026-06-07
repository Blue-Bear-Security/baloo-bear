# Configuration Reference

All Baloo settings are environment variables. Set them in `.env`, pass them via `docker-compose.yml`, or export them directly.

## GitHub App

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_APP_ID` | ✅ | — | Numeric GitHub App ID (not the Client ID) |
| `GITHUB_PRIVATE_KEY` | ✅ | — | Path to `.pem` file (e.g., `.secrets/app.pem`) or inline PEM contents |
| `GITHUB_WEBHOOK_SECRET` | ✅ | — | Webhook signature verification secret |
| `WEBHOOK_PRE_VERIFIED` | — | `false` | Skip webhook signature verification (set `true` when behind trusted proxy) |

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
| `REVIEW_STALE_TIMEOUT_MINUTES` | `30` | Minutes after which an in-progress review is considered abandoned and can be superseded by a new one (used with `DATABASE_ENABLED=true`) |

## Agent

| Variable | Default | Description |
|---|---|---|
| `AGENT_PROVIDER` | `anthropic` | LLM provider: `anthropic`, `google` |
| `AGENT_MODEL` | `sonnet` | Model short name or `provider/model` string. See [Models](features/models.md) |
| `AGENT_FALLBACK_MODEL` | `google/gemini-2.5-flash` | Fallback model (`provider/model`). Empty to disable |
| `AGENT_MAX_TOKENS` | `4096` | Max output tokens |
| `AGENT_TEMPERATURE` | `0.2` | Generation temperature |
| `PI_BINARY_PATH` | `pi` | Path to PI binary |
| `PI_THINKING_LEVEL` | `medium` | PI thinking level: `off`, `minimal`, `low`, `medium`, `high` |

## Review Behavior

| Variable | Default | Description |
|---|---|---|
| `REVIEW_AUTO_APPROVE` | `true` | Auto-approve PRs with no CRITICAL/HIGH findings |
| `REVIEW_MIN_SEVERITY` | `MEDIUM` | Minimum severity to post: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `REVIEW_USE_CHECKS_API` | `true` | Post MEDIUM findings to Checks API instead of review comments |

## FP Verification

| Variable | Default | Description |
|---|---|---|
| `FP_VERIFICATION_ENABLED` | `true` | Enable LLM false-positive verification pass |
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
| `POSTGRES_USER` | `baloo` | Local Docker Compose PostgreSQL user |
| `POSTGRES_PASSWORD` | — | Local Docker Compose PostgreSQL password. Set explicitly before running Compose |
| `POSTGRES_DB` | `baloo` | Local Docker Compose PostgreSQL database name |
| `INSTALLATION_ID` | — | GitHub installation ID for this broker. If set, broker only processes webhooks for this installation and scopes all DB queries to this tenant. Unset = serve all installations |
| `DASHBOARD_ENABLED` | `true` | Enable review history dashboard (still requires `DATABASE_ENABLED=true` and credentials to be useful) |
| `DASHBOARD_USERNAME` | — | Dashboard basic auth username |
| `DASHBOARD_PASSWORD` | — | Dashboard basic auth password |
| `LOG_RETENTION_DAYS` | `30` | Days to retain execution logs (0 to disable cleanup) |

## Thread Agent

| Variable | Default | Description |
|---|---|---|
| `THREAD_AGENT_ENABLED` | `false` | Enable conversational thread replies to PR comments |
| `THREAD_AGENT_MODEL` | `haiku` | Model for thread replies (short name or `provider/model`) |
| `THREAD_AGENT_MAX_REPLIES` | `3` | Max Baloo messages per thread before escalation |
| `THREAD_AGENT_MAX_CONCURRENT` | `3` | Max parallel thread agent calls |

## Feedback Signals

| Variable | Default | Description |
|---|---|---|
| `FEEDBACK_SIGNALS_ENABLED` | `true` | Write and read feedback signals (requires `DATABASE_ENABLED`) |
| `FEEDBACK_SIGNALS_TTL_DAYS` | `180` | Days before unmatched feedback signals expire |

## AST Tools

| Variable | Default | Description |
|---|---|---|
| `AST_TOOLS_ENABLED` | `true` | Enable AST analysis tools (outline, grep, symbols) for the review agent |

## Repo Provisioning

| Variable | Default | Description |
|---|---|---|
| `REPO_CACHE_ENABLED` | `true` | Check out the PR repo at its head SHA so the agent's file tools read real code. Off = diff-only review. |
| `REPO_CACHE_ROOT` | `/tmp/baloo-repo-cache` | Ephemeral root for cached bare clones + per-review worktrees (lost on redeploy). |
| `REPO_CACHE_MAX_DISK_GB` | `10` | Total cache disk cap (GB). Least-recently-used caches are evicted above this. |
| `REPO_SANDBOX_MODE` | `bwrap` | Filesystem sandbox for the agent subprocess (`bwrap` binds only the review worktree read-only; `off` disables). Requires bubblewrap + unprivileged user namespaces; falls back to `off` automatically when unavailable. |

## Multi-Broker Deployment

Baloo supports running multiple broker instances against a shared database for high availability and horizontal scale.

### Shared Model (recommended for HA)

All brokers handle any installation. A load balancer distributes incoming webhooks. If two brokers race on a GitHub retry, the duplicate-review unique index discards the second silently.

```
GitHub → Load Balancer → Broker A  (INSTALLATION_ID unset)
                       → Broker B  (INSTALLATION_ID unset)
                       → Broker C  (INSTALLATION_ID unset)
         (all share one database)
```

**Minimal nginx upstream config:**
```nginx
upstream baloo {
    server broker-a:8000;
    server broker-b:8000;
    server broker-c:8000;
}
```

### Dedicated Mode

Each broker is scoped to one installation via `INSTALLATION_ID`. Webhooks for other installations are silently acknowledged and dropped.

```
GitHub → Load Balancer → Broker A  (INSTALLATION_ID=111)
                       → Broker B  (INSTALLATION_ID=222)
```

Each broker only sees its own installation's data in the database.

### Health Checks

Each broker exposes `GET /health`:

```json
{ "status": "ok" }
```

Use this endpoint for load balancer health probes.

### Webhook Security

Every webhook is validated before processing:
1. HMAC-SHA256 signature verification (confirms payload is from GitHub)
2. `installation_id` present in payload
3. Installation filter — if `INSTALLATION_ID` is set, drop webhooks for other installations
4. Installation token fetch — confirms installation is active and Baloo has valid auth
5. Repository access check — confirms the repo in the payload belongs to this installation (prevents cross-tenant payloads)
