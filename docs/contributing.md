# Contributing to Baloo

## Before You Start

- For bugs, feature requests, and design discussions, prefer opening a GitHub issue first unless you already have maintainer guidance.
- Keep pull requests scoped to one logical change.
- For sensitive security issues, follow [SECURITY.md](https://github.com/Blue-Bear-Security/baloo-bear/blob/main/SECURITY.md) instead of opening a public issue.

## Development Setup

```bash
uv sync
cp .env.example .env
uv run python main.py
```

To enable local git hooks:

```bash
npm install
```

Common checks before opening a pull request:

```bash
uv run pytest
uv run ruff check baloo tests
uv run black --check baloo tests
```

## Commit Convention

Semantic commits are recommended:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `ci`: CI/CD changes

### Examples

```bash
feat(agent): add self-awareness check for PR context

fix(webhook): handle 422 errors with fallback to issue comments

docs: update deployment instructions for Docker

chore(deps): update claude-sdk to 0.1.4
```

### Footers

```bash
# Reference GitHub issues
Refs: #123

# Breaking changes
BREAKING CHANGE: renamed config parameter MAX_REVIEWS to MAX_CONCURRENT_REVIEWS

# Co-authored commits
Co-Authored-By: Claude <noreply@anthropic.com>
```

## Development Workflow

1. Create or identify the GitHub issue for the change when appropriate.
2. Create a descriptive branch such as `feat/review-guidelines` or `fix/webhook-fallback`.
3. Make the smallest change that fully addresses the problem.
4. Add or update tests when behavior changes.
5. Run the relevant checks locally before opening a PR.
6. Open a pull request with context, risk notes, and any follow-up work.

## Pull Requests

- Use a clear title that describes the change.
- Link the related issue when one exists, for example `Closes #123`.
- Include test coverage notes or explain why tests were not added.
- Ensure CI passes before requesting review.
- Address review comments explicitly in follow-up commits or replies.

## Questions?

- Open a GitHub issue for product or implementation questions.
- Open a GitHub Discussion if you want feedback before writing code.
