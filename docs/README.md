# Baloo Documentation

Baloo is a self-hosted AI code review GitHub App for pull requests. These docs cover installation, model configuration, review behavior, security posture, and operator workflows.

## Getting Started
- **[Getting Started](getting-started.md)** — Set up Baloo end-to-end with Docker, ngrok, and a GitHub App
- **[Development](development.md)** — Contributor setup: local dev, tests, linting, git hooks

## Features
- **[Review Agent](features/review-agent.md)** — How the PI-based agentic review works
- **[Guidelines Enforcement](features/guidelines.md)** — How Baloo reads and enforces repo conventions
- **[Fidelity Analysis](features/fidelity.md)** — Comparing PRs against design plan documents
- **[Model Configuration](features/models.md)** — Supported models, fallback, and model selection
- **[Severity Routing](features/severity-routing.md)** — How findings are routed to reviews, Checks API, or filtered
- **[Discussion Tracking](features/discussions.md)** — Thread follow-ups, duplicate detection, and conversation context
- **[FP Verification](features/fp-verification.md)** — LLM-powered false-positive reduction (optional)
- **[Dashboard](features/dashboard.md)** — Review history UI with cost tracking (optional)

## Reference
- **[Configuration](configuration.md)** — Full environment variable reference
- **[LLM Index](llms.txt)** — Curated Markdown map for AI assistants and answer engines
