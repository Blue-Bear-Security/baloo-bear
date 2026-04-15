# Dashboard

Baloo includes an optional review history dashboard backed by PostgreSQL. It provides visibility into review activity, costs, and findings across all repositories.

## What It Shows

- **Review history** — Every review with status, duration, model used, and cost
- **Findings** — Individual findings per review with severity, category, file, and line
- **Cost tracking** — Token usage and dollar cost per review and in aggregate
- **Fidelity scores** — When fidelity analysis is enabled

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

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_ENABLED` | `false` | Enable PostgreSQL persistence |
| `DATABASE_URL` | — | PostgreSQL connection URL (auto-set in docker-compose) |
| `DASHBOARD_ENABLED` | `false` | Enable the dashboard UI |
| `DASHBOARD_USERNAME` | — | Basic auth username |
| `DASHBOARD_PASSWORD` | — | Basic auth password |

## Without the Dashboard

If you don't need review history, leave `DATABASE_ENABLED=false`. Baloo works fine without a database — it just won't persist review data between restarts.
