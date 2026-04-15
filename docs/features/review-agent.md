# Review Agent

Baloo uses [PI](https://github.com/mariozechner/pi-coding-agent) as its agentic runtime. When a PR is opened or updated, Baloo spawns a PI agent process that actively explores the repository to produce a thorough review.

## How It Works

1. **Webhook arrives** — GitHub sends a `pull_request` event
2. **Context assembly** — Baloo fetches the PR diff, file list, metadata, and any prior discussion threads
3. **Agent spawns** — A PI process starts in RPC mode with **read-only tools**: `read`, `grep`, `find`, `ls`
4. **Agentic review** — The agent reads changed files in full, greps for security patterns, explores project structure, checks for tests and configs
5. **Structured output** — The agent returns a JSON object with findings (file, line, severity, category, description, recommendation)
6. **Post-processing** — Findings go through FP verification (optional), severity filtering, duplicate detection, and severity routing before being posted

## Why Agentic?

Unlike simple "diff-in, comments-out" reviewers, Baloo's agent can:

- **Read full files** — not just the diff, but the entire file for context
- **Search the codebase** — grep for patterns, find related files, check if tests exist
- **Follow references** — if a function is changed, the agent can check where it's called
- **Read project conventions** — examines `AGENTS.md` and `CONTRIBUTING.md` for repo-specific rules

## Read-Only Guarantee

The agent has **no write access**. It cannot execute commands, modify files, or make API calls. All mutations (posting comments, updating GitHub) happen in the deterministic Python code after the agent returns its findings.

## Tools Available

| Tool | Purpose |
|---|---|
| `read` | Read file contents (full or by line range) |
| `grep` | Search for patterns across files |
| `find` | Locate files by name or pattern |
| `ls` | List directory contents |

## What the Agent Reviews

The system prompt instructs the agent to check, in priority order:

1. **Security** — SQL injection, XSS, secrets exposure, command injection, auth/authz issues
2. **Bugs** — Logic errors, null refs, race conditions, error handling gaps
3. **Silent failures** — Swallowed exceptions, missing error logging, silent default substitution
4. **Guidelines** — Violations of conventions in `AGENTS.md` / `CONTRIBUTING.md`
5. **Performance** — N+1 queries, blocking operations, algorithm efficiency
6. **Quality** — DRY, complexity, naming, test coverage

## Configuration

| Variable | Default | Description |
|---|---|---|
| `AGENT_MODEL` | `sonnet` | Model to use (see [Models](models.md)) |
| `AGENT_FALLBACK_MODEL` | `google/gemini-2.5-flash` | Fallback if primary fails |
| `AGENT_MAX_TOKENS` | `4096` | Max output tokens |
| `AGENT_TEMPERATURE` | `0.2` | Temperature for generation |
| `PI_THINKING_LEVEL` | `medium` | Thinking depth: off, minimal, low, medium, high |
