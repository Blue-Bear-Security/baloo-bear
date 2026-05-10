# Roadmap

## 1. Multi-model review with judge
Orchestrate reviews across two models (e.g. Sonnet + Gemini Pro) and use a
third model as a judge to reconcile disagreements.  The judge sees both sets
of findings and produces a single merged review, keeping findings both models
agree on and adjudicating conflicts.  Goal: higher recall without more false
positives.

## ~~2. Conversational thread agent~~ ✅ Shipped
Implemented in PR #36. See [docs/features/thread-agent.md](features/thread-agent.md).

## 3. AST-enriched context for the review agent — 🚧 In Progress
PI extension providing structural code analysis tools (ast_outline, ast_grep, ast_symbols)
via `@ast-grep/napi`. The agent can query file structure, search patterns by syntax tree,
and follow symbol definitions/references to improve finding accuracy.

Language support: Python, TypeScript/JavaScript, and Go.
