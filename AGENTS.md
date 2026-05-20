# AGENTS.md

This file provides guidance to coding agents working in this repository. `CLAUDE.md` and `GEMINI.md` point here as compatibility symlinks.

## Project Overview

Baloo is a GitHub application that provides automated code reviews for pull requests. It analyzes PRs submitted to selected repositories, provides feedback as comments, and can accept or reject changes. The agent runs on every new commit to a PR and uses PI (pi-coding-agent) as the agentic runtime, with Anthropic models for code analysis.

## Development Environment

- **Language**: Python 3.10+
- **Package Manager**: uv
- **Key Dependencies**: pi-coding-agent (Node.js, RPC subprocess), FastAPI, PyGithub

## Common Commands

```bash
# Install dependencies
uv sync
npm install

# Run the server
uv run python main.py

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=baloo

# Lint
uv run ruff check baloo tests

# Format
uv run black baloo tests
```

## Architecture

GitHub App that:
1. Listens for PR events via GitHub webhooks
2. Analyzes code changes using Anthropic's Claude models
3. Generates review comments and feedback
4. Posts results back to the PR as comments
5. Provides approval/rejection decisions

**Components:**
- `baloo/github/` - GitHub integration (webhooks, API client, auth)
- `baloo/agent/` - PI agent runtime (prompts, config, review logic via RPC subprocess)
- `baloo/processor/` - Review processing (filtering, formatting, decisions)
- `baloo/config/` - Configuration management

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for planned features.

## Workflow Guidelines

- Prefer linking larger changes to a GitHub issue or pull request discussion.
- Keep changes scoped and easy to review.
- Use descriptive branch names such as `feat/review-routing` or `fix/checks-api-fallback`.
- Semantic commits are preferred when practical.
- Before pushing, address open review comments explicitly: fix, decline with reasoning, or explain the tradeoff.

## Adding Environment Variables

When adding a new setting to `baloo/config/settings.py`, always update all four of these in the same change:

1. `.env.example` — add the variable with its default value
2. `docker-compose.yml` — add `VAR_NAME: ${VAR_NAME:-default}`
3. `docs/configuration.md` — add a row to the relevant table with variable, default, and description
4. Alembic migration (if the setting affects the database schema)
