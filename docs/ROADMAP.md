# Roadmap

This roadmap focuses on improvements that make Baloo easier to trust, operate, and evaluate as an open source AI code review agent.

## Security and Supply Chain

- Keep CodeQL coverage active for Python, GitHub Actions, JavaScript, and TypeScript.
- Publish OpenSSF Scorecard results and keep the score visible from the README.
- Keep Dependabot enabled for uv, npm, GitHub Actions, Docker, and Docker Compose.
- Add signed container provenance and release attestations for published images.
- Review GitHub branch protection after each workflow change and require passing CI before merge.

## Review Quality

- Improve false-positive verification for security findings and edge-case logic findings.
- Expand Dependabot-aware review behavior for high-risk package updates.
- Improve thread follow-up quality when maintainers ask Baloo to explain or re-check a finding.
- Add more fixtures for real pull request shapes, including large refactors and generated files.

## Operations

- Keep local Docker defaults safe for development while documenting production hardening clearly.
- Improve dashboard authentication and deployment guidance for production operators.
- Add clearer observability examples for latency, cost, queue depth, and review outcomes.

## Discoverability

- Maintain concise docs pages that answer common operator and evaluator questions directly.
- Keep the GitHub repository description, topics, social preview, and README aligned around self-hosted AI code review.
- Publish an LLM-readable index at `llms.txt` so AI assistants can find the canonical setup, configuration, and security pages.
