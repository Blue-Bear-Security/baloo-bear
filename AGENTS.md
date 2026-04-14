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

## Roadmap / TODO

### 1. Multi-model review with judge
Orchestrate reviews across two models (e.g. Sonnet + Gemini Pro) and use a
third model as a judge to reconcile disagreements.  The judge sees both sets
of findings and produces a single merged review, keeping findings both models
agree on and adjudicating conflicts.  Goal: higher recall without more false
positives.

### 2. False-positive reduction pass
After the agent produces findings, run a second lightweight pass that
re-examines each finding in isolation: read the flagged code, check the
claim, and decide "real issue" vs "false positive".  Drop FPs before
posting.  This can use a cheaper model (Flash/Haiku) since each check is
scoped to a single finding + file context.

### 3. Conversational thread agent
When a developer replies to a Baloo inline comment (`pull_request_review_comment`
event), don't re-review the whole PR.  Instead, run a lightweight
thread-reply agent that:
- Sees only the specific thread (Baloo's finding + developer's response)
- Decides: acknowledge, clarify, or concede
- Posts a targeted reply in the same thread

Also use this as a **feedback loop**: if the developer says "this is a false
positive" or "this is intentional", log it and use the signal to improve
prompts and the FP-reduction pass over time.

> Comment-triggered events (`issue_comment`, `pull_request_review_comment`,
> `pull_request_review`) are currently disabled in the webhook handler.
> Re-enable selectively when implementing this feature.

## Workflow Guidelines

- Prefer linking larger changes to a GitHub issue or pull request discussion.
- Keep changes scoped and easy to review.
- Use descriptive branch names such as `feat/review-routing` or `fix/checks-api-fallback`.
- Semantic commits are preferred when practical.
- Before pushing, address open review comments explicitly: fix, decline with reasoning, or explain the tradeoff.
