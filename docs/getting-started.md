# Getting Started

This guide is for running Baloo as a service and getting a real pull request review end to end.

It is the operator path, not the contributor path.

It uses the root `docker-compose.yml` and a local PostgreSQL container. This is the setup to use if you want to prove Baloo works against a real GitHub App before doing any code changes.

By the end of this guide, you will have:

- a GitHub App configured for Baloo
- a local Baloo stack running with Docker Compose
- a public webhook URL using `ngrok`
- Baloo installed on one canary repository
- a successful PR review

## 1. Prerequisites

You need:

- Docker
- Docker Compose
- `ngrok`
- an Anthropic API key

You do not need a Python development environment just to try Baloo as a service.

## 2. Clone the Repository

```bash
git clone https://github.com/your-org/baloo.git
cd baloo
```

## 3. Create the GitHub App

In GitHub:

1. Open `Settings -> Developer settings -> GitHub Apps -> New GitHub App`
2. Choose an app name
3. Set the homepage URL to the Baloo repository URL
4. Set a placeholder webhook URL for now if you do not have one yet
5. Generate a webhook secret
6. Create the app
7. Generate a private key for the app

You can update the webhook URL after Baloo is running behind `ngrok`.

Important:

- `GITHUB_APP_ID` must be the numeric App ID
- do not use the GitHub App Client ID

## 4. Configure GitHub App Permissions

Set these repository permissions:

- `Pull requests: Read and write`
- `Contents: Read-only`
- `Issues: Read and write`
- `Checks: Read and write`

These are needed because Baloo:

- reads PRs and posts review comments
- reads repository files such as `AGENTS.md` and `CONTRIBUTING.md`
- posts general PR comments
- posts medium-severity findings to the Checks tab

## 5. Subscribe to GitHub Events

Enable these events:

- `Pull request`
- `Issue comment`
- `Pull request review`
- `Pull request review comment`

Baloo currently reacts to:

- PR opened, synchronized, reopened, and ready-for-review transitions
- PR comments
- PR review comments
- submitted human reviews in `commented` and `changes_requested` states

## 6. Configure Baloo

Copy the Docker environment template:

```bash
cp .env.docker .env
```

Edit `.env` and fill in at least:

```text
GITHUB_APP_ID=...
GITHUB_PRIVATE_KEY=.secrets/your-github-app.private-key.pem
GITHUB_WEBHOOK_SECRET=...
ANTHROPIC_API_KEY=...
```

Create the `.secrets` directory in the repo root and place the GitHub App private key file there:

```bash
mkdir -p .secrets
mv /path/to/your-private-key.pem .secrets/
```

For a more complete local stack, also set:

```text
DATABASE_ENABLED=true
DASHBOARD_ENABLED=true
DASHBOARD_USERNAME=baloo
DASHBOARD_PASSWORD=choose-a-password
```

Notes:

- the default compose stack mounts `.secrets/` into the container, so `GITHUB_PRIVATE_KEY=.secrets/<file>.pem` works both locally and in Docker
- you do not need to set `DATABASE_URL` when using the default compose stack, because `docker-compose.yml` already injects the local PostgreSQL connection string
- the default compose stack does not publish PostgreSQL to your host, so it should not conflict with a local Postgres instance
- if you keep multiple env files, you can run compose with `BALOO_ENV_FILE=<your-file> docker compose up --build` instead of copying over `.env`

## 7. Start Baloo With Docker Compose

```bash
docker compose up --build
```

Expected local endpoints:

- `http://localhost:8000/health`
- `http://localhost:8000/`
- `http://localhost:8000/dashboard/` if dashboard is enabled

Quick health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"healthy"}
```

If you enabled the dashboard, verify both of these:

- `GET /dashboard/` returns `401` before login
- after basic auth with `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`, the dashboard renders

## 8. Expose the Webhook With ngrok

In another terminal:

```bash
ngrok http 8000
```

Copy the public HTTPS URL from `ngrok` and update the GitHub App webhook URL to:

```text
https://your-ngrok-subdomain.ngrok.app/webhook
```

After updating the webhook URL, use GitHub's webhook delivery UI to send a ping or redeliver a recent event. A valid delivery should return `200`.

## 9. Install the App on One Canary Repository

Install the GitHub App on exactly one repository first.

Do not install it broadly yet. Baloo does not currently enforce a repository allowlist in application code, so installation scope matters.

## 10. Open a Test PR

Create a small test PR in the canary repository.

A simple smoke test:

1. Open a PR
2. Wait for Baloo to review it
3. Push another commit to the same PR
4. Add a PR comment

Expected results:

- GitHub webhook deliveries return `200`
- Baloo may receive `check_suite` events and ignore them; that is normal
- Baloo posts a progress comment
- Baloo posts review output
- medium findings appear in the Checks tab when present
- the second push triggers another review

## 11. Optional Repository Conventions

Baloo becomes more useful when the reviewed repository contains:

- `AGENTS.md`
- `CONTRIBUTING.md`

Baloo reads those files from the target repository and uses them as review guidance.

If fidelity analysis is enabled, the reviewed repository can also include plan files such as:

```text
docs/plans/TICKET-123-some-feature.md
```

## 12. Common Problems

### Webhook deliveries fail

- Check that the webhook URL points to `/webhook`
- Check that the `ngrok` tunnel is still running
- Check that `GITHUB_WEBHOOK_SECRET` matches the GitHub App webhook secret

### Baloo cannot authenticate to GitHub

- Check that `GITHUB_APP_ID` is the numeric App ID, not the Client ID
- Check that the private key belongs to the same GitHub App
- Check that the app is installed on the repository you are testing

### Baloo posts comments but no Checks appear

- Verify the app has `Checks: Read and write`
- Verify `REVIEW_USE_CHECKS_API` is not disabled

### The dashboard does not load

- Set `DATABASE_ENABLED=true`
- Set `DASHBOARD_ENABLED=true`
- Set `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`

### Baloo reviews the wrong repositories

- Reduce the GitHub App installation scope
- Use one canary repository first

## 13. Next Steps

After the canary repository works:

1. verify the review quality on a few real PRs
2. decide whether to keep the dashboard and fidelity features enabled
3. expand installation to more repositories

For direct code-level development and test commands, see [docs/development.md](development.md).

For more container details, see [DOCKER.md](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/DOCKER.md).
