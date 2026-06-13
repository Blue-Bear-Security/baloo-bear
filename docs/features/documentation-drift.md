# Documentation Drift Review

Documentation drift review is an optional PR-time side analysis that checks whether implementation changes make repository documentation stale.

It runs during the normal Baloo review when enabled, reads a repo-owned catalog from the PR head, and posts at most one PR-level comment asking the author to update affected docs in the same PR.

## Why PR-Time?

Post-merge documentation fixes separate ownership from the code change that made the docs stale. Documentation drift review keeps the request in the original PR, where the author still has the context and can update code and docs together.

The MVP is non-blocking:

- It does not create inline comments.
- It does not request changes.
- It does not affect auto-approval.
- It does not edit files or open documentation PRs.

## How It Works

1. Baloo provisions the PR checkout at the head SHA.
2. Baloo loads the catalog from `.baloo/documentation-catalog.json` by default.
3. Changed implementation files are matched against catalog rules.
4. Recommended docs are split into docs already changed in the PR and docs still to review.
5. A read-only PI side agent inspects the changed files and mapped docs.
6. Baloo posts or updates one PR-level comment marked with `<!-- baloo:documentation-drift-report -->`.

If no catalog exists, Baloo skips the feature silently. This keeps the feature precise and avoids broad heuristic doc discovery.

## Quick Start

1. Add a catalog file to the repository you want Baloo to review:

   ```text
   .baloo/documentation-catalog.json
   ```

2. Map implementation areas to the docs that describe them:

   ```json
   {
     "schema_version": 1,
     "rules": [
       {
         "area": "Billing workflows",
         "patterns": ["app/billing/**", "app/jobs/invoices/**"],
         "recommended_docs": ["docs/features/billing.md", "README.md"]
       }
     ]
   }
   ```

3. Enable the feature in Baloo:

   ```env
   DOCUMENTATION_DRIFT_ENABLED=true
   DOCUMENTATION_DRIFT_CATALOG_PATH=.baloo/documentation-catalog.json
   DOCUMENTATION_DRIFT_MODEL=sonnet
   ```

4. Open or update a PR that changes a mapped implementation file.

5. If Baloo finds actionable drift, it posts one PR comment. If docs are already updated in the PR, Baloo inspects those docs and may post no comment.

Baloo itself includes `.baloo/documentation-catalog.json` as a working example catalog for this repository.

## Writing a Good Catalog

Start small. Add rules for high-traffic areas where stale docs are expensive, then expand as the reports prove useful.

Good catalog rules are:

- **Specific enough to avoid noise** — map an area to docs that actually describe that area.
- **Broad enough to survive file moves** — prefer `app/billing/**` over every individual billing file.
- **Owned by the repo** — the catalog lives in the reviewed repository, so each repo can choose its own docs contract.
- **Kept in the same PR as code changes** — when a new feature area or doc page is added, update the catalog with it.

Use `read_only: true` when a code area is useful context but should not cause Baloo to request documentation updates:

```json
{
  "area": "Generated API clients",
  "patterns": ["src/generated/**"],
  "recommended_docs": ["docs/api.md"],
  "read_only": true
}
```

## Catalog Schema

Create a catalog in the reviewed repository:

```json
{
  "schema_version": 1,
  "rules": [
    {
      "area": "Review orchestration",
      "patterns": ["baloo/review/**", "baloo/processor/**"],
      "recommended_docs": ["README.md", "docs/features/review-agent.md"]
    },
    {
      "area": "Agent runtime",
      "patterns": ["baloo/agent/**"],
      "recommended_docs": [
        "docs/features/models.md",
        "docs/features/review-agent.md"
      ]
    }
  ]
}
```

Rules support:

| Field              | Description                                                                         |
| ------------------ | ----------------------------------------------------------------------------------- |
| `area`             | Human-readable name for the code area.                                              |
| `patterns`         | Repo-relative implementation file globs.                                            |
| `recommended_docs` | Repo-relative docs that should be reviewed when the patterns match.                 |
| `read_only`        | Optional. When `true`, matched files provide context but do not add docs to review. |

## Path Matching

Documentation drift uses GitHub-style glob behavior:

- `*` matches one path segment.
- `**` matches recursively across path segments.

Examples:

| Pattern          | Matches                                                | Does Not Match                  |
| ---------------- | ------------------------------------------------------ | ------------------------------- |
| `baloo/agent/*`  | `baloo/agent/client.py`                                | `baloo/agent/tools/client.py`   |
| `baloo/agent/**` | `baloo/agent/client.py`, `baloo/agent/tools/client.py` | `baloo/review/orchestrator.py`  |
| `baloo/**/*.py`  | `baloo/review/orchestrator.py`                         | `docs/features/review-agent.md` |

Baloo treats `.md`, `.mdx`, `.rst`, and `.csv` files as documentation paths.

## Report Behavior

Baloo posts at most one documentation drift report per PR. The report is an issue comment, not an inline review comment, because the stale documentation may be outside the PR diff.

Baloo uses the stable sentinel `<!-- baloo:documentation-drift-report -->` to find its previous report:

- If actionable drift is found and no previous report exists, Baloo posts a new report.
- If a previous report exists, Baloo edits it with the latest result.
- If no drift is found and no previous report exists, Baloo stays silent.
- If no drift is found and a previous report exists, Baloo edits it to say no drift was detected.

Catalog gaps are actionable. If an implementation file changed but did not match any catalog rule, Baloo reports it under `Catalog Gaps` so maintainers can decide whether to add a new rule.

## Example Comment

```markdown
<!-- baloo:documentation-drift-report -->

## Documentation Drift Review

This PR appears to change behavior or workflows that are documented elsewhere.

### Required Updates

- `docs/features/review-agent.md`
  - Update the review lifecycle section to mention documentation drift analysis.
  - Rationale: The PR adds a new review-side analysis step.
  - Evidence: `baloo/review/orchestrator.py`

### Catalog Gaps

- `baloo/documentation/analyzer.py` is not mapped in the documentation drift catalog.
```

If a previous drift comment exists and the latest review finds no drift, Baloo edits that same comment to a short no-drift message. If no previous drift comment exists and no drift is found, Baloo posts nothing.

## Configuration

| Variable                           | Default                             | Description                                   |
| ---------------------------------- | ----------------------------------- | --------------------------------------------- |
| `DOCUMENTATION_DRIFT_ENABLED`      | `false`                             | Enable PR-time documentation drift analysis.  |
| `DOCUMENTATION_DRIFT_CATALOG_PATH` | `.baloo/documentation-catalog.json` | Repo-relative catalog path.                   |
| `DOCUMENTATION_DRIFT_MODEL`        | `sonnet`                            | Model for the documentation drift side agent. |

## Troubleshooting

### No comment appeared

Check these first:

- `DOCUMENTATION_DRIFT_ENABLED=true` is set in the running Baloo service.
- The reviewed PR head contains the catalog file.
- The changed files match at least one catalog rule, or there are unmapped implementation files that should be reported as catalog gaps.
- The PR only changed docs. Docs-only PRs skip analysis unless implementation files changed too.

### The report says there is a catalog gap

Add or update a rule in `.baloo/documentation-catalog.json` so the changed implementation path maps to the docs that describe it. If the path should never request documentation updates, add a `read_only: true` rule.

### The wrong docs are recommended

Tighten the matching rule or split it into multiple narrower rules. For example, separate `app/billing/**` and `app/auth/**` if they are currently grouped under a broad `app/**` rule.

### A docs update was already included but Baloo still reported drift

Baloo inspects docs already changed in the PR and decides whether they are sufficient. If it still reports drift, update the mentioned doc section more directly or narrow the catalog rule if that doc should not be tied to the changed implementation area.
