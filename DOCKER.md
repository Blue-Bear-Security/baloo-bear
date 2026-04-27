# Docker Deployment Guide

## Quick Start

### Local development with Docker Compose

```bash
cp .env.docker .env
docker compose up --build
```

If you use a file-based GitHub App key, put it under `.secrets/` and set `GITHUB_PRIVATE_KEY=.secrets/<your-key>.pem` in `.env`.

`GITHUB_APP_ID` must be the numeric GitHub App ID, not the Client ID.

To use a different env file directly:

```bash
BALOO_ENV_FILE=.env.local docker compose up --build
```

Useful commands:

```bash
docker compose logs -f baloo
docker compose down
curl http://localhost:8000/health
```

The default compose file starts:

- `baloo` on `http://localhost:8000`
- `postgres` as an internal Docker service named `db`

Database-backed features are disabled by default. Enable them in `.env` if you want persistence or the dashboard.

The default stack does not publish PostgreSQL to the host. Baloo connects to it internally at `db:5432`, which avoids conflicts with an existing local PostgreSQL instance. If you need host access for debugging, add a temporary port mapping in your local compose override.

## Run with Docker CLI

```bash
docker build -t baloo:latest .

docker run -d \
  --name baloo \
  -p 8000:8000 \
  -v "$(pwd)/.secrets:/app/.secrets:ro" \
  --env-file .env \
  baloo:latest
```

## Image Details

- Base image: `python:3.11-slim`
- Includes Node.js and Claude Code CLI for agent execution
- Exposes port `8000`
- Runs as a non-root user inside the container

## Environment Variables

Required:

- `GITHUB_APP_ID`
- `GITHUB_PRIVATE_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `ANTHROPIC_API_KEY`

Common optional settings:

- `APP_PORT=8000`
- `LOG_LEVEL=INFO`
- `MAX_CONCURRENT_REVIEWS=3`
- `AGENT_MODEL=claude-sonnet-4-6`
- `DATABASE_ENABLED=false`
- `DASHBOARD_ENABLED=false`

See `.env.docker` for an example.

## Private Key Options

Recommended:

- Keep the PEM file under `.secrets/`
- Set `GITHUB_PRIVATE_KEY=.secrets/<your-key>.pem`
- The compose stack mounts `.secrets/` into `/app/.secrets` read-only

You can still inline the PEM contents directly through `GITHUB_PRIVATE_KEY` if you prefer.

## Publishing Images

To publish to a registry manually:

```bash
docker build -t baloo:latest .
docker tag baloo:latest ghcr.io/blue-bear-security/baloo-bear:latest
docker push ghcr.io/blue-bear-security/baloo-bear:latest
```

The repository workflow in `.github/workflows/deploy.yml` uses GHCR as the default publishing target.

## Production Notes

- Put Baloo behind HTTPS before registering the webhook with GitHub.
- Use immutable image tags for production deployments.
- Store secrets in your deployment platform's secret manager rather than committing `.env` files.
- Size the host based on expected PR concurrency and Claude runtime memory usage.

## Troubleshooting

### The container starts but the webhook fails

- Check that the GitHub App credentials are valid.
- Verify the webhook secret matches the GitHub App configuration.
- Confirm the GitHub App is installed on the target repository.

### The dashboard does not load

- Set `DATABASE_ENABLED=true`
- Set `DASHBOARD_ENABLED=true`
- Provide `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`

### PostgreSQL is not needed

- Leave `DATABASE_ENABLED=false`
- Ignore the `db` service or remove it from your own compose override
