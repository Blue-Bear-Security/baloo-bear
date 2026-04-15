# FP Reduction Pass — Design Plan

## Problem

Baloo produces false positives that erode developer trust. The current
`FindingsFilter` uses regex heuristics (hedging language, short comments,
severity threshold) but can't reason about whether a finding is actually
correct. We need an LLM-powered verification step.

## Approach

After the review agent produces findings, run a **second lightweight pass**
that re-examines each finding in isolation. A cheap/fast model (Haiku or
Flash) reads:
- The finding (title, description, severity, recommendation)
- The actual file content around the flagged line (±30 lines of context)
- The diff hunk for that file

It then classifies: **real issue** vs **false positive**, with a one-line
reason. False positives are dropped before posting.

## Architecture

```
review_pr()
  │
  ▼
raw findings (N comments)
  │
  ▼
┌─────────────────────────┐
│  FPVerifier.verify()    │  ← NEW
│  For each finding:      │
│   • build small prompt  │
│   • call cheap model    │
│   • classify real/fp    │
│  Return filtered list   │
└─────────────────────────┘
  │
  ▼
FindingsFilter (existing severity/heuristic filter)
  │
  ▼
post to GitHub
```

## Components

### 1. `baloo/processor/fp_verifier.py` (new)

```python
class FPVerifier:
    """LLM-powered false-positive verification."""

    def __init__(self, model: str = "haiku", max_concurrent: int = 5):
        ...

    async def verify(
        self,
        comments: list[ReviewComment],
        pr_context: PRContext,
    ) -> FPVerificationResult:
        ...
```

**Key decisions:**
- Uses `PIAgentBase` with read-only tools (same RPC subprocess pattern)
- Runs verifications concurrently with `asyncio.gather` (bounded by semaphore)
- Each verification is a single-turn prompt — no tool use needed, just reasoning
- System prompt is minimal: "You are a code review verifier..."
- Uses `thinking_level="off"` for speed

**Verification prompt per finding:**
```
Finding: [title] ([severity])
File: path/to/file.py, line 42
Description: [description]
Recommendation: [recommendation]

File context (lines 12-72):
[actual file content from pr_context or diff]

Diff hunk:
[relevant diff section]

Is this finding a real issue or a false positive?
Respond with JSON: {"verdict": "real"|"fp", "reason": "one line explanation"}
```

**Return type:**
```python
@dataclass
class FPVerificationResult:
    verified: list[ReviewComment]     # kept findings
    rejected: list[FPRejection]       # dropped findings + reasons
    stats: FPStats                    # counts, cost, duration
```

### 2. `baloo/processor/fp_prompts.py` (new)

Prompt templates for the verification pass, kept separate from review prompts.

### 3. Settings additions (`settings.py`)

```python
# FP Verification
fp_verification_enabled: bool = True
fp_verification_model: str = "haiku"       # cheap model short name
fp_verification_max_concurrent: int = 5    # parallel verifications
```

### 4. Integration point (`webhook_handler.py`)

In `process_pr_review()`, between `agent.review_pr()` and `FindingsFilter`:

```python
# FP verification pass (before heuristic filter)
if settings.fp_verification_enabled and review_result.comments:
    from baloo.processor.fp_verifier import FPVerifier
    verifier = FPVerifier(model=settings.fp_verification_model)
    fp_result = await verifier.verify(review_result.comments, pr_context)
    review_result.comments = fp_result.verified
    # Log rejected findings
    for r in fp_result.rejected:
        logger.info("FP rejected: %s:%s - %s", r.path, r.line, r.reason)
```

### 5. DB tracking (optional, if dashboard enabled)

Add `fp_rejected_count` and `fp_verification_cost_usd` to the review
completion data so the dashboard can show FP reduction effectiveness.

## Cost estimate

Per finding verification:
- Haiku: ~500 input tokens + ~50 output tokens ≈ $0.0003
- Flash: ~500 input tokens + ~50 output tokens ≈ $0.0001

Typical review with 5 findings: **$0.0005–$0.0015** extra.
Negligible compared to the $0.02–$0.10 main review cost.

## Testing

- `tests/test_fp_verifier.py` — unit tests with mocked PI responses
- `tests/test_fp_prompts.py` — prompt construction tests
- `tests/test_fp_integration.py` — end-to-end with mock webhook

Key test cases:
1. Real bug survives verification
2. Obvious FP (flagging code that exists elsewhere) gets dropped
3. Verification timeout/error → finding is kept (fail-open)
4. Empty findings list → no verification calls
5. Cost/stats are tracked correctly

## Rollout

1. Ship behind `fp_verification_enabled=false`
2. Enable on staging, compare before/after on real PRs
3. Log all rejections to tune the verification prompt
4. Enable in production once rejection accuracy is validated

## Open questions

- **Fail-open vs fail-closed**: If verification errors, keep or drop the
  finding? Plan: **fail-open** (keep the finding) — better to over-report
  than miss a real issue.
- **Batch vs individual**: Could batch all findings into one prompt to save
  on per-call overhead. Tradeoff: individual is more reliable (no
  cross-contamination), batch is cheaper. Start with individual, optimize
  later if cost matters.
- **Context source**: Use raw diff hunks or fetch full file content? Diff
  hunks are already in `pr_context.diff`. For more context, the verifier
  could use PI's `read` tool — but that adds latency. Start with diff
  context, add file reads if accuracy needs it.
