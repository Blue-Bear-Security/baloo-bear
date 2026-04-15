# Guidelines Enforcement

Baloo reads convention files from the repository being reviewed and uses them to enforce project-specific rules.

## How It Works

When reviewing a PR, Baloo fetches these files from the target repository (if they exist):

- **`AGENTS.md`** — Repository guidance for coding agents (architecture, conventions, tooling)
- **`CONTRIBUTING.md`** — Contributor guidelines (commit format, branch naming, workflow)

The contents are injected into the review agent's prompt. The agent then flags any PR changes that contradict the documented conventions.

## What Gets Flagged

Guidelines violations are reported as **CRITICAL** severity with category **"Guidelines"**. Examples:

- Branch name doesn't follow the naming convention (e.g., `fix/thing` when repo requires `fix(scope): thing`)
- Commit messages missing required ticket references
- Code that violates architectural decisions stated in AGENTS.md
- Dependency management that contradicts documented conventions
- Using a tool or pattern explicitly discouraged by the guidelines

## Setting Up Your Repository

### AGENTS.md

This file tells Baloo (and other coding agents) how your project works:

```markdown
# AGENTS.md

## Architecture
- Backend: Python 3.11, FastAPI
- All database access goes through the repository pattern in `app/repos/`

## Conventions
- Branch names: `feat/description` or `fix/description`
- Semantic commits required
- All new endpoints need tests in `tests/api/`

## Common Commands
- `uv run pytest` — run tests
- `uv run ruff check` — lint
```

### CONTRIBUTING.md

Standard contributor guidelines. Baloo reads this alongside AGENTS.md:

```markdown
# Contributing

## Commit Format
<type>(<scope>): <subject>

Types: feat, fix, docs, refactor, test, chore

## Pull Requests
- Link the related issue
- Include test coverage
- Run lint before opening
```

## No Guidelines? No Problem

If neither file exists in the repository, Baloo skips the guidelines compliance check entirely. It won't invent rules that aren't documented.

## Configuration

Guidelines enforcement is always on when the files exist. There is no separate toggle — if you don't want it, simply don't include `AGENTS.md` or `CONTRIBUTING.md` in your repository.
