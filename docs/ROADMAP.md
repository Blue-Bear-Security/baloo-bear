# Roadmap

## 1. Multi-model review with judge
Orchestrate reviews across two models (e.g. Sonnet + Gemini Pro) and use a
third model as a judge to reconcile disagreements.  The judge sees both sets
of findings and produces a single merged review, keeping findings both models
agree on and adjudicating conflicts.  Goal: higher recall without more false
positives.

## 2. False-positive reduction pass
After the agent produces findings, run a second lightweight pass that
re-examines each finding in isolation: read the flagged code, check the
claim, and decide "real issue" vs "false positive".  Drop FPs before
posting.  This can use a cheaper model (Flash/Haiku) since each check is
scoped to a single finding + file context.

## 3. Conversational thread agent
When a developer replies to a Baloo inline comment (`pull_request_review_comment`
event), don't re-review the whole PR.  Instead, run a lightweight
thread-reply agent that:
- Sees only the specific thread (Baloo's finding + developer's response)
- Decides: acknowledge, clarify, or concede
- Posts a targeted reply in the same thread

Also use this as a **feedback loop**: if the developer says "this is a false
positive" or "this is intentional", log it and use the signal to improve
prompts and the FP-reduction pass over time.

> Comment-triggered events (`issue_comment`, `pull_request_review_comment`,
> `pull_request_review`) are currently disabled in the webhook handler.
> Re-enable selectively when implementing this feature.

## 4. AST-enriched context for the review agent
Before the PI agent reviews a PR, parse changed files into ASTs and provide
structural context alongside the raw diff.  This gives the agent:
- Function/class boundaries for each hunk ("this change is inside `AuthService.validate_token`")
- Call-graph snippets (callers/callees of changed functions)
- Symbol cross-references (where else is this function/variable used?)

Inspired by GitNexus-style semantic analysis.  Implementation path:
1. Run a lightweight AST parser (tree-sitter) on the changed files
2. Extract scope info, symbol table, and call edges
3. Inject a structured summary into the agent prompt as additional context
4. Optionally expose as a PI tool so the agent can query the AST on demand

Language support: start with Python + TypeScript, expand based on repo usage.
