# Thread Auto-Resolution Design

**Date:** 2026-05-04
**Status:** Approved

## Problem

When Baloo flags an issue on a PR and the developer fixes it in a follow-up commit, Baloo silently stops re-filing the finding but never acknowledges the fix. The GitHub thread stays open, `awaiting_response=True`, and the decision engine keeps setting `request_changes=True` even when the latest review finds zero new issues. The PR is stuck.

Observed on PR #30: 4 reviews, 3 findings fixed across 3 commits, final review found 0 issues — yet the PR was still marked `changes_requested` and all 3 threads left unresolved at merge.

The `finding_outcomes` signals confirm this: `code_changed_near_line=true`, `thread_resolved=false` on all findings.

## Out of scope (deferred)

Human responses on Baloo threads (developer replies to a finding) — will be designed after gathering real examples of how developers actually respond.

## Design

### 1. Data model: `DiscussionThread.node_id`

Add one field to `DiscussionThread`:

```python
node_id: str | None = None  # GraphQL thread node ID for resolveReviewThread mutation
```

This is the GraphQL `id` on the `PullRequestReviewThread` node, distinct from the REST `databaseId` used today.

### 2. GraphQL query update

`fetch_resolved_thread_ids` in `api_client.py` adds `id` to the thread nodes:

```graphql
nodes {
  id          # NEW — thread node ID for mutation
  isResolved
  isOutdated
  comments(first: 1) {
    nodes { databaseId }
  }
}
```

`_apply_resolved_thread_state` is extended to write `node_id` onto each matched thread alongside the existing `resolved`/`outdated` flags.

### 3. New API method: `resolve_review_thread`

```python
async def resolve_review_thread(self, thread_node_id: str) -> bool
```

Calls the GraphQL mutation:

```graphql
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
```

Returns `True` on success. On error: logs a warning and returns `False` — a failed resolve is not fatal, the reply comment was already posted.

### 4. Re-verification pass

After the existing thread-matching loop in `webhook_handler.py`, collect threads eligible for re-verification:

- `is_baloo_thread=True`
- `awaiting_response=True`
- Not matched to any new finding (i.e., the review agent did not re-file this finding)
- `node_id` is set (needed to resolve)
- Not already `resolved` or `outdated`

Reconstruct a `ReviewComment` from each thread's root comment (`body`, `path`, `line`, `severity`, `category`). Pass the batch to `FPVerifier.verify()` — the existing verifier, same Haiku model, same prompt, but with the new diff as context.

`fp` verdict = issue no longer present in current code = fixed.
`real` verdict = issue still present = leave thread open.

The re-verification batch runs **concurrently** with the new-findings FP verifier pass (they are independent).

### 5. Actions on `fp` verdict

For each thread where re-verification returns `fp`:

1. `reply_to_review_comment(root_comment_id, "Looks like this was addressed in the latest commit. Resolving.")`
2. `resolve_review_thread(node_id)`
3. Update `finding_outcomes` row for this finding: set `thread_resolved=True` in signals (if row exists)
4. Remove thread from the `awaiting_response` count fed to the decision engine

Step 4 prevents the `if awaiting_threads and not request_changes and not decision_comments: request_changes = True` block from firing when all previously open threads are now resolved.

### 6. Pipeline position

```
review agent runs
        |
thread matching (existing)
  fresh / duplicate / resolved / responded / outdated
        |
        +---> FP verifier: new findings     (existing, concurrent)
        |
        +---> FP verifier: awaiting threads (new, concurrent)
                    |
                  fp -> reply + resolve + update outcome
                  real -> leave open
        |
post new findings
resolve fixed threads
        |
decision engine
```

## Edge cases

**Thread has no `node_id`** (GraphQL fetch failed): skip re-verification for that thread. Logged as a warning. PR behaviour unchanged from today.

**`reply_to_review_comment` returns `False`** (thread outdated/404): still attempt `resolve_review_thread`. If that also fails, log and move on — don't block the review.

**Re-verification returns `real` but developer already fixed it** (false negative from verifier): thread stays open. Harmless — developer can manually resolve, or next push will re-verify.

**New finding matches the same location as an awaiting thread**: existing dedup logic handles this (`skipped_duplicates`). Thread is not eligible for re-verification.

## Testing

- Unit: `test_resolve_review_thread` — mock GraphQL mutation, verify correct node ID sent
- Unit: `test_thread_reverification_fp_verdict` — mock FPVerifier returning fp, assert reply + resolve called
- Unit: `test_thread_reverification_real_verdict` — assert no reply/resolve called
- Unit: `test_awaiting_count_excludes_resolved_threads` — verify decision engine sees 0 awaiting after resolution
- Integration: reconstruct `ReviewComment` from a `DiscussionThread` root comment — verify fields round-trip correctly
