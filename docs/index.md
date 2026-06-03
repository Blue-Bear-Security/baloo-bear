# Baloo: self-hosted AI code review for GitHub pull requests

<p align="center">
  <a href="https://github.com/Blue-Bear-Security/baloo-bear/actions/workflows/ci.yml"><img src="https://github.com/Blue-Bear-Security/baloo-bear/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Blue-Bear-Security/baloo-bear/actions/workflows/codeql-python.yml"><img src="https://github.com/Blue-Bear-Security/baloo-bear/actions/workflows/codeql-python.yml/badge.svg" alt="CodeQL Python"></a>
  <a href="https://api.scorecard.dev/projects/github.com/Blue-Bear-Security/baloo-bear"><img src="https://api.scorecard.dev/projects/github.com/Blue-Bear-Security/baloo-bear/badge" alt="OpenSSF Scorecard"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
</p>

---

Baloo is an open source **GitHub App for AI pull request review**. It installs on your repositories, reads PR diffs and relevant project context, and posts actionable review comments that catch bugs, security issues, missing error handling, and repository guideline violations before humans review the code.

Baloo is built for teams that want a **self-hosted AI code review agent** instead of a hosted SaaS reviewer. You run the service, control the GitHub App installation scope, and provide your own model API keys for Claude or Gemini.

Website: [BlueBear Security](https://www.bluebear.io)

## Why Baloo?

- **Catches what linters can't** — logic errors, silent failures, security antipatterns, missing error handling
- **Respects your conventions** — reads `AGENTS.md` and `CONTRIBUTING.md` from your repo and enforces them
- **Posts like a teammate** — inline comments on specific lines, severity labels, approval/request-changes decisions
- **Runs on every push** — new commits get reviewed automatically, with discussion thread tracking across iterations
- **Self-hosted & private** — your code never leaves your infrastructure; bring your own API keys

## Use Cases

- **AI code review for GitHub pull requests** — review opened, reopened, synchronized, and ready-for-review PRs
- **Security review assistance** — flag injection risks, unsafe auth patterns, secret handling mistakes, and missing validation
- **Repository guideline enforcement** — apply project-specific rules from `AGENTS.md` and `CONTRIBUTING.md`
- **Dependency update review** — use Dependabot-aware prompts for dependency PRs
- **Plan fidelity checks** — compare an implementation against plan documents before approval
- **Local review before opening a PR** — run the same review pipeline against a local git diff

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
| **Local dry-run** | Run [`scripts/local_review.py`](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/scripts/local_review.py) against a local git diff — no GitHub webhook or posted comments |

## Baloo Compared

| Need | Baloo's fit |
|---|---|
| Hosted AI reviewer alternative | Self-host Baloo as your own GitHub App and choose the model credentials |
| Static analysis complement | Baloo reviews intent, behavior, edge cases, and repo-specific conventions that linters may not express |
| GitHub Copilot review complement | Baloo runs automatically as an app on every PR update and can route findings to reviews or Checks |
| Security review workflow | Baloo combines LLM review with severity routing, false-positive verification, and GitHub-native comments |

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
┌──────────────┐     webhook      ┌───────────────────┐
│   GitHub     │ ───────────────→ │   FastAPI         │
│   (PR event) │                  │   webhook_handler │
└──────────────┘                  └────────┬──────────┘
                                           │
                                  ┌────────▼──────────┐
                                  │   PI Agent (RPC)  │
                                  │   read / grep /   │
                                  │   find / ls       │
                                  └────────┬──────────┘
                                           │
                                  ┌────────▼──────────┐
                                  │   Processor       │
                                  │   filter → route  │
                                  │   → decide        │
                                  └────────┬──────────┘
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
| `FP_VERIFICATION_ENABLED` | `true` | Enable LLM false-positive verification |
| `DATABASE_ENABLED` | `false` | Enable PostgreSQL review history |
| `DASHBOARD_ENABLED` | `false` | Enable review dashboard UI |
| `FIDELITY_ENABLED` | `true` | Compare PRs against plan docs |

Full reference: [configuration.md](configuration.md)

## Documentation

📖 **[Full documentation](getting-started.md)** — Feature guides, configuration reference, and more

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

### Local review (dry run)

You can run the same review pipeline against your working tree before opening a PR. The script builds a synthetic pull request from a git diff (`base...head`), loads `AGENTS.md` / `CONTRIBUTING.md` from the head ref when present, and prints findings to stdout — nothing is posted to GitHub.

Requires the same LLM credentials as production (for example `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` in your environment).

```bash
uv run python scripts/local_review.py
uv run python scripts/local_review.py --base origin/main --head HEAD
uv run python scripts/local_review.py --json
uv run python scripts/local_review.py --fail-on-blocking   # exit 1 if CRITICAL/HIGH findings
# Review another clone while cwd is baloo-bear (e.g. uv --directory this repo):
uv run python scripts/local_review.py --git-workdir /path/to/other-repo --base origin/main --head HEAD
```

See [development.md](development.md) for the full contributor guide.

## FAQ

### Is Baloo self-hosted?

Yes. Baloo runs as your own service and GitHub App. You control deployment, repository installation scope, database persistence, and model credentials.

### Does Baloo send code to a hosted Baloo service?

No. Baloo does not require a Baloo-hosted backend. The running service reads repository content through your GitHub App installation and sends review context to the LLM provider you configure.

### Which models does Baloo support?

Baloo supports Claude models through Anthropic and Gemini models through Google, including fallback model configuration. See [features/models.md](features/models.md).

### Is Baloo a replacement for CodeQL, Semgrep, Ruff, or other static analysis tools?

No. Baloo is a review agent that complements static analysis. Keep deterministic scanners for known patterns and use Baloo for reasoning-heavy findings, project conventions, and PR-level review context.

### Can I try Baloo without posting comments to GitHub?

Yes. Use [`scripts/local_review.py`](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/scripts/local_review.py) to run a dry review against a local git diff.

## Support

- **Issues & Bug Reports**: [GitHub Issues](https://github.com/Blue-Bear-Security/baloo-bear/issues)
- **Feature Requests**: [GitHub Issues](https://github.com/Blue-Bear-Security/baloo-bear/issues)
- **Questions**: Open a [GitHub Discussion](https://github.com/Blue-Bear-Security/baloo-bear/discussions) or file an issue

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](contributing.md) for workflow and conventions, and [AGENTS.md](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/AGENTS.md) for AI-agent-specific guidance.

## Security

Please read [SECURITY.md](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/SECURITY.md) before reporting vulnerabilities.

## License

MIT — see [LICENSE](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/LICENSE).
