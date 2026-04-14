# Baloo

Baloo is a FastAPI-based GitHub App that reviews pull requests with Anthropic models. It fetches full pull request context, reads repository guidelines from `AGENTS.md` and `CONTRIBUTING.md`, and posts review comments, approvals, and optional dashboard or fidelity output back to GitHub.

## Features

- Agentic pull request review for opened, reopened, and updated PRs
- Severity-based routing for inline comments, review summaries, and Checks API annotations
- Repository-specific guideline enforcement from the target repository's `AGENTS.md` and `CONTRIBUTING.md`
- Optional fidelity analysis against plan documents
- Optional PostgreSQL-backed review history dashboard

## Architecture

```text
GitHub webhook -> FastAPI handler -> Claude agent -> findings processor -> GitHub review/checks APIs
```

Key modules:

- `baloo/github/`: webhook handling, GitHub API access, review thread parsing
- `baloo/agent/`: prompt construction, Claude runtime, structured review output
- `baloo/processor/`: filtering, routing, approval decisions, formatting
- `baloo/fidelity/`: optional plan-vs-implementation analysis
- `baloo/db/` and `baloo/dashboard/`: optional persistence and review history UI

## Prerequisites

- A GitHub App with pull request and contents access
- An Anthropic API key
- A public HTTPS endpoint for GitHub webhooks in non-local environments

## Quick Start

The fastest path is the end-to-end guide in [docs/getting-started.md](docs/getting-started.md).

## Docker

Baloo ships with a local-friendly `docker-compose.yml` that builds the application image from this repository.

```bash
cp .env.docker .env
docker compose up --build
```

If you keep the GitHub App private key as a file, place it under `.secrets/` and set `GITHUB_PRIVATE_KEY=.secrets/<your-key>.pem` in `.env`.

`GITHUB_APP_ID` must be the numeric GitHub App ID, not the Client ID.

If you want to use an alternate env file without copying over `.env`, run:

```bash
BALOO_ENV_FILE=.env.local docker compose up --build
```

Useful endpoints:

- Health check: `http://localhost:8000/health`
- Dashboard: `http://localhost:8000/dashboard/` when `DASHBOARD_ENABLED=true`

See [DOCKER.md](DOCKER.md) for container details and deployment notes.

## Container Publishing

The repository includes a GitHub Actions workflow at [.github/workflows/deploy.yml](.github/workflows/deploy.yml) that builds and publishes a container image to GitHub Container Registry on pushes to `main`. If you use a different registry or deploy process, adapt that workflow before relying on it.

## Configuration

Baloo is configured through environment variables. Common settings:

| Variable | Default | Description |
| --- | --- | --- |
| `GITHUB_APP_ID` | - | Numeric GitHub App ID |
| `GITHUB_PRIVATE_KEY` | - | Path to a PEM file, typically under `.secrets/`, or inline PEM contents |
| `GITHUB_WEBHOOK_SECRET` | - | GitHub webhook secret |
| `ANTHROPIC_API_KEY` | - | Anthropic API key |
| `APP_HOST` | `0.0.0.0` | Bind host |
| `APP_PORT` | `8000` | Bind port |
| `LOG_LEVEL` | `INFO` | Log level |
| `MAX_CONCURRENT_REVIEWS` | `3` | Maximum reviews processed at once |
| `AGENT_MODEL` | `claude-sonnet-4-6` | Anthropic model to use |
| `REVIEW_AUTO_APPROVE` | `true` | Auto-approve PRs with no blocking findings |
| `REVIEW_MIN_SEVERITY` | `MEDIUM` | Minimum severity to report |
| `DATABASE_ENABLED` | `false` | Persist review history to PostgreSQL |
| `DASHBOARD_ENABLED` | `true` | Serve the dashboard UI |
| `FIDELITY_ENABLED` | `true` | Compare PRs against plan documents |

## Development

For contributor setup, direct local execution, tests, and hooks, see [docs/development.md](docs/development.md).

### Common commands

```bash
uv sync
npm install
uv run python main.py
uv run pytest
uv run pytest --cov=baloo --cov-report=term-missing
uv run ruff check baloo tests
uv run black --check baloo tests
```

### Git hooks

The repository uses Husky for local Git hooks and `gitleaks` for staged secret scanning on `pre-commit`.

Hook setup:

```bash
brew install gitleaks
npm install
```

The installed pre-commit hook runs:

```bash
gitleaks git --staged --pre-commit --no-banner --redact
```

### Project structure

```text
baloo/
├── baloo/
│   ├── agent/
│   ├── config/
│   ├── db/
│   ├── fidelity/
│   ├── github/
│   └── processor/
├── tests/
├── main.py
└── pyproject.toml
```

## How It Works

1. GitHub sends a `pull_request` webhook when a PR is opened or updated.
2. Baloo verifies the webhook signature and loads PR metadata, diffs, and discussion context.
3. Baloo fetches `AGENTS.md` and `CONTRIBUTING.md` from the reviewed repository when present.
4. The Claude agent performs a structured review and emits findings.
5. Findings are filtered, routed, and posted back to GitHub as review comments, summaries, and checks.

## Retrieving Review Comments

You can query Baloo's review comments with the GitHub CLI:

```bash
gh api /repos/{owner}/{repo}/pulls/{pr_number}/comments \
  --jq '.[] | select(.user.login=="baloo-code-reviewer[bot]") | {path, line, body, created_at}'
```

## Troubleshooting

### Webhook not receiving events

- Verify the GitHub App webhook URL is correct and publicly reachable.
- Verify `GITHUB_WEBHOOK_SECRET` matches your GitHub App configuration.
- Check webhook delivery logs in GitHub.

### Authentication errors

- Verify the app ID and private key belong to the same GitHub App.
- Ensure the app has been installed on the target repository.
- Confirm required GitHub App permissions are granted.

### Agent failures

- Verify `ANTHROPIC_API_KEY` is valid in the running environment.
- Check application logs with `LOG_LEVEL=DEBUG`.
- Confirm the configured model is available to your Anthropic account.

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [AGENTS.md](AGENTS.md) for repository-specific guidance for coding agents.

## Security

Please read [SECURITY.md](SECURITY.md) before reporting vulnerabilities.

## License

Baloo is released under the MIT license. See [LICENSE](LICENSE).
