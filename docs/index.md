<p align="center">
  <img src="assets/baloo-banner.png" alt="Baloo — AI Code Review Agent" width="600">
</p>

<p align="center">
  <strong>AI-powered code reviews for every pull request</strong>
</p>

<p align="center">
  <a href="https://github.com/Blue-Bear-Security/baloo-bear/actions/workflows/ci.yml"><img src="https://github.com/Blue-Bear-Security/baloo-bear/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
</p>

---

Baloo is a **GitHub App** that automatically reviews pull requests using LLMs. It installs on your repos, reads every PR diff, and posts actionable review comments — catching bugs, security issues, and guideline violations before humans look at the code.

## Why Baloo?

- **Catches what linters can't** — logic errors, silent failures, security antipatterns, missing error handling
- **Respects your conventions** — reads `AGENTS.md` and `CONTRIBUTING.md` from your repo and enforces them
- **Posts like a teammate** — inline comments on specific lines, severity labels, approval/request-changes decisions
- **Runs on every push** — new commits get reviewed automatically, with discussion thread tracking across iterations
- **Self-hosted & private** — your code never leaves your infrastructure; bring your own API keys

## What It Looks Like

When a PR is opened or updated, Baloo posts a review:

```
🐻 Baloo review completed in 45s.
Found 2 issue(s): 0 critical, 1 high, 1 medium, 0 low.
```

Inline comments appear on the exact lines:

> **[HIGH] Security** — `src/auth.py:55`
>
> SQL query uses string concatenation instead of parameterized bindings.
> This is vulnerable to SQL injection.
>
> **Recommendation:** Use parameterized queries: `cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))`

## Features

| Feature | Description |
|---|---|
| **Agentic review** | Uses [PI](https://github.com/mariozechner/pi-coding-agent) to read files, grep patterns, and explore the repo — not just the diff |
| **Multi-model** | Supports Claude (Sonnet, Haiku, Opus) and Gemini (Flash, Pro) with automatic fallback |
| **Severity routing** | CRITICAL/HIGH → request changes; MEDIUM → Checks API annotations; LOW → filtered |
| **Guideline enforcement** | Reads repo-level `AGENTS.md` / `CONTRIBUTING.md` and flags violations |
| **Discussion tracking** | Follows up on existing threads, skips duplicates, detects addressed feedback |
| **Fidelity analysis** | Optionally compares PR against design plan documents |
| **FP reduction** | Optional second LLM pass to verify findings and drop false positives |
| **Dashboard** | Optional PostgreSQL-backed review history UI with cost tracking |
| **Dependabot-aware** | Specialized review logic for dependency update PRs |

## Quick Start

### 1. Create a GitHub App

Go to **GitHub Settings → Developer settings → GitHub Apps → New GitHub App**:
- **Webhook URL**: Your public HTTPS endpoint (e.g. `https://baloo.example.com/webhook`)
- **Permissions**: Pull requests (read/write), Contents (read), Checks (read/write)
- **Events**: Pull request
- Download the private key `.pem` file

### 2. Deploy with Docker

```bash
git clone https://github.com/Blue-Bear-Security/baloo-bear.git
cd baloo-bear
cp .env.example .env
# Edit .env with your GitHub App ID, private key path, webhook secret, and API keys
```

```bash
docker compose up --build
```

### 3. Install the App

Install the GitHub App on your repositories. Open a PR — Baloo will review it automatically.

📖 **Full setup guide**: [getting-started.md](getting-started.md)

## Architecture

```text
┌──────────────┐     webhook      ┌──────────────────┐
│   GitHub      │ ───────────────→ │   FastAPI         │
│   (PR event)  │                  │   webhook_handler │
└──────────────┘                  └────────┬─────────┘
                                           │
                                  ┌────────▼─────────┐
                                  │   PI Agent (RPC)  │
                                  │   read / grep /   │
                                  │   find / ls       │
                                  └────────┬─────────┘
                                           │
                                  ┌────────▼─────────┐
                                  │   Processor       │
                                  │   filter → route  │
                                  │   → decide        │
                                  └────────┬─────────┘
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                        ┌──────────┐ ┌──────────┐ ┌──────────┐
                        │ Review   │ │ Checks   │ │ Dashboard│
                        │ comments │ │ API      │ │ (opt.)   │
                        └──────────┘ └──────────┘ └──────────┘
```

```text
baloo/
├── agent/       # PI runtime, prompts, structured output parsing
├── config/      # Environment-based settings
├── db/          # PostgreSQL models + migrations (optional)
├── dashboard/   # Review history UI (optional)
├── fidelity/    # Plan-vs-implementation analysis (optional)
├── github/      # Webhooks, API client, auth, Checks API
└── processor/   # Findings filter, severity routing, decisions, FP verification
```

## Configuration

All settings are environment variables. Key ones:

| Variable | Default | Description |
|---|---|---|
| `GITHUB_APP_ID` | — | Numeric GitHub App ID |
| `GITHUB_PRIVATE_KEY` | — | Path to `.pem` file or inline PEM |
| `GITHUB_WEBHOOK_SECRET` | — | Webhook signature secret |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `GEMINI_API_KEY` | — | Google Gemini API key (for fallback/multi-model) |
| `AGENT_MODEL` | `sonnet` | Model short name: `flash`, `haiku`, `sonnet`, `gemini-pro`, `opus` |
| `AGENT_FALLBACK_MODEL` | `google/gemini-2.5-flash` | Fallback on primary failure |
| `REVIEW_AUTO_APPROVE` | `true` | Auto-approve PRs with no blocking findings |
| `REVIEW_MIN_SEVERITY` | `MEDIUM` | Minimum severity to post |
| `FP_VERIFICATION_ENABLED` | `false` | Enable LLM false-positive verification |
| `DATABASE_ENABLED` | `false` | Enable PostgreSQL review history |
| `DASHBOARD_ENABLED` | `false` | Enable review dashboard UI |
| `FIDELITY_ENABLED` | `true` | Compare PRs against plan docs |

Full reference: [configuration.md](configuration.md)

## Documentation

📖 **[Full documentation](./)** — Feature guides, configuration reference, and more

Feature guides:
- [Review Agent](features/review-agent.md) — How the agentic review works
- [Guidelines Enforcement](features/guidelines.md) — Repo convention checking
- [Fidelity Analysis](features/fidelity.md) — Plan-vs-implementation scoring
- [Models](features/models.md) — Supported models and fallback
- [Severity Routing](features/severity-routing.md) — How findings reach developers
- [Discussion Tracking](features/discussions.md) — Thread follow-ups across iterations
- [FP Verification](features/fp-verification.md) — False-positive reduction
- [Dashboard](features/dashboard.md) — Review history UI

## Development

```bash
uv sync && npm install     # install deps
uv run python main.py      # run locally
uv run pytest              # test
uv run ruff check baloo    # lint
uv run black --check baloo # format check
```

See [development.md](development.md) for the full contributor guide.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features including multi-model review with judge, conversational thread replies, and AST-enriched context.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](contributing.md) for workflow and conventions, and [AGENTS.md](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/AGENTS.md) for AI-agent-specific guidance.

## Security

Please read [SECURITY.md](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/SECURITY.md) before reporting vulnerabilities.

## License

MIT — see [LICENSE](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/LICENSE).
