# False-Positive Verification

An optional second LLM pass that re-examines each finding before posting, dropping false positives to improve developer trust.

## How It Works

1. The main review agent produces findings
2. Each finding is independently sent to a **cheap/fast model** (Haiku or Flash)
3. The verifier sees: the finding description + the actual code context (diff hunk)
4. It classifies each finding as **real issue** or **false positive**
5. False positives are dropped before posting

## Why a Separate Pass?

The review agent optimizes for **recall** (finding all issues). The verification pass optimizes for **precision** (only keeping real ones). Separating these concerns gives better results than asking one model to do both.

## Fail-Open Design

If verification errors (model timeout, parse failure), the finding is **kept**. It's better to over-report than to silently drop a real bug.

## Audit Log

Every verdict is logged to a JSONL file for offline review and prompt tuning:

```json
{
  "timestamp": "2026-04-14T13:00:00Z",
  "repo": "org/repo",
  "pr_number": 42,
  "finding": {
    "file": "src/auth.py",
    "line": 55,
    "severity": "HIGH",
    "category": "Security",
    "title": "SQL injection risk"
  },
  "verdict": "fp",
  "reason": "The query uses parameterized bindings, not string concat",
  "model": "claude-haiku-4-5-20251001",
  "cost_usd": 0.0003
}
```

Use this log to:
- Review rejected findings and confirm they're actually FPs
- Identify patterns in false positives to improve the review prompt
- Track FP reduction effectiveness over time

## Cost

Per finding verification:
- Haiku: ~$0.0003
- Flash: ~$0.0001

Typical review with 5 findings: **$0.0005–$0.0015** extra. Negligible compared to the main review cost.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `FP_VERIFICATION_ENABLED` | `false` | Enable the verification pass |
| `FP_VERIFICATION_MODEL` | `haiku` | Model for verification (short name or provider/model) |
| `FP_VERIFICATION_MAX_CONCURRENT` | `5` | Max parallel verification calls |
| `FP_AUDIT_LOG_PATH` | `/var/log/baloo/fp-audit.jsonl` | Audit log path. Empty to disable logging |

## Enabling

```bash
FP_VERIFICATION_ENABLED=true
FP_VERIFICATION_MODEL=haiku
FP_AUDIT_LOG_PATH=/var/log/baloo/fp-audit.jsonl
```

Start with verification enabled on a staging environment. Review the audit log to confirm it's dropping actual false positives before enabling in production.
