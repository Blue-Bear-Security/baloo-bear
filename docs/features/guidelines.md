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

## Real-World Example: BlueDen

Here's an excerpt from the [BlueDen](https://github.com/Blue-Bear-Security/blueden) monorepo's guidelines. These rules are enforced on every PR via Baloo.

### AGENTS.md (key rules Baloo enforces)

```markdown
## Every coding task must have a linear ticket.

1. No code without Linear task
2. The task spec is the contract — no additions beyond the spec unless asked
3. Stop on misalignment — spec doesn't match reality or complexity is unexpected?
   Stop, document in Linear, await developer guidance

## Fail Fast Over Fallbacks

We prefer failing fast and loudly over silent fallbacks.

When mandatory fields are missing or data is invalid:
1. FAIL the operation — don't use fallback values
2. LOG an error — use `logger.exception()` for Slack alerts
3. Return an error — make failures visible

Bad: `value = data.get('field') or default_value`
Good: Validate, log error, reject bad data

## Testing Strategy

Every PR MUST include integration tests (excluding console-only changes).
Every bug fix or new feature first introduces the missing tests. Work TDD:
start with failing integration tests, work until they pass.
```

### CONTRIBUTING.md (key rules Baloo enforces)

```markdown
## Branching Strategy

Branch names must include the Linear ticket ID. All of these are valid:

- feat/DEN-123/add-user-login
- fix/DEN-456/resolve-payment-issue
- feature/den-1522-collapse-assets-section-by-default-in-sidebar

## Commit Message Convention

Format: <type>(<scope>): [<linear-ticket-id>] <subject>

Examples:
  feat(auth): [DEN-123] implement password hashing
  fix(api): [DEN-456] correct pagination query parameter

## Supply Chain Security — Dependency Management

1. All versions must be pinned to exact versions — no ^, ~, >=, or ranges
   - npm:    "next": "16.1.6"    not "next": "^16.1.6"
   - Python: boto3==1.35.81      not boto3>=1.34.0
2. 4-week quarantine on new package versions — do not adopt any version
   published less than 4 weeks ago
3. Never run `npm install` without a specific package name
```

When a PR adds `"next": "^16.1.6"` or branches from `add-login` (missing ticket ID), Baloo flags it as **CRITICAL — Guidelines** before a human reviewer sees it.

## Setting Up Your Repository

### AGENTS.md

This file tells Baloo (and other coding agents) how your project works. It works best when rules are concrete and actionable — Baloo can only enforce what's written down.

```markdown
# AGENTS.md

## Architecture
- Backend: Python 3.11, FastAPI
- All database access goes through the repository pattern in `app/repos/`

## Conventions
- Branch names must include the Linear ticket ID: `feat/PROJ-123/description`
- Commit format: `feat(scope): [PROJ-123] subject`
- All new endpoints need tests in `tests/api/`
- Pin all dependency versions exactly — no ^ or ~ ranges

## Testing
- Every PR must include integration tests
- Work TDD: write failing tests before implementation
```

### CONTRIBUTING.md

Standard contributor guidelines. Baloo reads this alongside AGENTS.md:

```markdown
# Contributing

## Commit Format
<type>(<scope>): [<ticket-id>] <subject>

Types: feat, fix, docs, refactor, test, chore

## Pull Requests
- Branch must include the ticket ID (e.g., feat/PROJ-123/description)
- Link the related issue in the PR description
- Include test coverage
- Run lint before opening
```

## No Guidelines? No Problem

If neither file exists in the repository, Baloo skips the guidelines compliance check entirely. It won't invent rules that aren't documented.

## Configuration

Guidelines enforcement is always on when the files exist. There is no separate toggle — if you don't want it, simply don't include `AGENTS.md` or `CONTRIBUTING.md` in your repository.
