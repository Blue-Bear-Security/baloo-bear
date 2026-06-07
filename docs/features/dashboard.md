# Dashboard

Baloo includes an optional review history dashboard backed by PostgreSQL. It provides visibility into review activity, costs, and findings across all repositories.

## What It Shows

- **Review history** — Every review with status, duration, model used, and cost
- **Findings** — Individual findings per review with severity, category, file, and line
- **Cost tracking** — Token usage and dollar cost per review and in aggregate
- **Fidelity scores** — When fidelity analysis is enabled
- **Settings** — A read-only view of the instance's effective runtime configuration

## Requirements

The dashboard requires:

1. **PostgreSQL** — For storing review data
2. **Database enabled** — `DATABASE_ENABLED=true`
3. **Dashboard enabled** — `DASHBOARD_ENABLED=true`
4. **Credentials** — `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`

The default `docker-compose.yml` includes a PostgreSQL container, so no external database setup is needed for local use.

## Access

The dashboard is served at `/dashboard/` and protected by HTTP Basic Auth.

```
http://localhost:8000/dashboard/
```

## Settings Page

The dashboard includes a read-only **Settings** page at `/dashboard/settings` showing the effective runtime configuration loaded for this Baloo instance, grouped by category (GitHub App, Agent, Review Behavior, Repo Provisioning, etc.). Each row lists the environment variable, its current value, its default, and a description.

Secrets are never exposed: sensitive settings (API keys, private keys, passwords, webhook secrets) render as `Configured (redacted)` or `Not configured`, and `DATABASE_URL` is shown with its credentials stripped. The page is for inspection only — it cannot change configuration.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_ENABLED` | `false` | Enable PostgreSQL persistence |
| `DATABASE_URL` | — | PostgreSQL connection URL (auto-set in docker-compose) |
| `DASHBOARD_ENABLED` | `true` | Enable the dashboard UI (requires `DATABASE_ENABLED=true` + credentials to be useful) |
| `DASHBOARD_USERNAME` | — | Basic auth username |
| `DASHBOARD_PASSWORD` | — | Basic auth password |

## Without the Dashboard

If you don't need review history, leave `DATABASE_ENABLED=false`. Baloo works fine without a database — it just won't persist review data between restarts.
