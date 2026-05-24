# Guidelines Enforcement

Baloo reads convention files from the repository being reviewed and uses them to enforce project-specific rules.

## How It Works

When reviewing a PR, Baloo fetches these files from the target repository (if they exist):

- **`AGENTS.md`** — Repository guidance for coding agents (architecture, conventions, tooling)
- **`CONTRIBUTING.md`** — Contributor guidelines (commit format, branch naming, workflow)

The contents are injected into the review agent's prompt. The agent then flags any PR changes that contradict the documented conventions.

## What Gets Flagged

Guidelines violations are reported as **CRITICAL** severity with category **"Guidelines"**. Examples:

- Branch name missing required ticket ID (e.g., `fix/thing` when the repo requires `fix/PROJ-123/thing`)
- Commit messages missing required ticket references
- Dependency versions not pinned exactly (e.g., `^1.2.3` when exact pinning is required)
- Code that violates architectural decisions stated in AGENTS.md
- Using a tool or pattern explicitly discouraged by the guidelines
- Missing integration tests when AGENTS.md mandates TDD

## Setting Up Your Repository

### AGENTS.md

This file tells Baloo (and other coding agents) how your project works. Rules should be concrete and actionable — Baloo can only enforce what's written down.

```markdown
# AGENTS.md

## Architecture
- Backend: Python 3.11, FastAPI
- All database access goes through the repository pattern in `app/repos/`

## Conventions
- Every PR must be tied to a ticket; branch name must include the ticket ID
- Branch format: `feat/PROJ-123/short-description` or `fix/PROJ-456/short-description`
- Commit format: `feat(scope): [PROJ-123] subject`
- Pin all dependency versions exactly — no ^ or ~ ranges

## Testing
- Every PR must include integration tests
- Work TDD: write failing tests before implementation

## Common Commands
- `uv run pytest` — run tests
- `uv run ruff check` — lint
```

### CONTRIBUTING.md

Standard contributor guidelines. Baloo reads this alongside AGENTS.md:

```markdown
# Contributing

## Branching Strategy

All branch names must include the ticket ID. Examples:
- feat/PROJ-123/add-auth
- fix/PROJ-456/fix-pagination

## Commit Format
<type>(<scope>): [<ticket-id>] <subject>

Examples:
  feat(auth): [PROJ-123] implement password hashing
  fix(api): [PROJ-456] correct pagination query parameter

## Dependency Management
- All versions must be pinned exactly — no ^, ~, or >= ranges
- Verify new packages before adding them

## Pull Requests
- Link the related ticket in the PR description
- Include test coverage
- Run lint before opening
```

## No Guidelines? No Problem

If neither file exists in the repository, Baloo skips the guidelines compliance check entirely. It won't invent rules that aren't documented.

## Configuration

Guidelines enforcement is always on when the files exist. There is no separate toggle — if you don't want it, simply don't include `AGENTS.md` or `CONTRIBUTING.md` in your repository.
