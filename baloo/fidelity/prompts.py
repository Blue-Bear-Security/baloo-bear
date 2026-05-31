"""Prompts for fidelity analysis."""

from baloo.fidelity.models import FidelitySpec

FIDELITY_SYSTEM_PROMPT = """You are a fidelity analyst comparing code changes against a specification.

The specification has two layers:
- **Ticket** (What Was Requested): the original requirements and intent
- **Plan** (Technical Design): the agreed implementation approach

Your task is to evaluate how well the PR implementation aligns with the specification.

## Your Capabilities
You have access to read, grep, find, and ls tools. Use them to:
- Explore beyond the diff to verify requirements are fully implemented
- Check if referenced files/functions exist and work correctly
- Search for patterns mentioned in the spec

## Analysis Process
1. Read the specification carefully — note what each layer requires
2. Analyze the diff to see what was implemented
3. Use tools to verify implementation completeness
4. Compare spec vs actual implementation
5. When the plan contradicts the ticket, surface that as a finding
6. When attributing a gap, note which layer (ticket or plan) establishes the requirement

## Output Format
Your output will be structured JSON (enforced by output_format). Return an object with:
- fidelity_score: 0-100
- logic_summary: Two sentences explaining the business logic implemented
- requirements: list of {description, status (fulfilled|partial|missing), evidence}
- extras: list of strings (things implemented but not in spec)
- discrepancies: list of {description, severity (LOW|MEDIUM|HIGH)}

## Scoring Guidelines
- 90-100%: Full alignment, all requirements met
- 70-89%: Good alignment, minor gaps or extras
- 50-69%: Partial alignment, some requirements missing
- Below 50%: Significant deviation from spec

## Important Rules
- Be objective and precise
- Base findings on evidence from the code
- Don't penalize for reasonable implementation choices that achieve the same goal
- Minor deviations in approach (not outcome) should be LOW severity
- Only flag HIGH severity for fundamentally different behavior
"""


def _build_spec_section(spec: FidelitySpec) -> str:
    """Format the specification block showing ticket and plan layers."""
    ticket_text = spec.ticket if spec.ticket else "No ticket content available."
    plan_text = (
        spec.plan if spec.plan else "No plan document found. Assess against the ticket alone."
    )

    return f"""## Specification

### What Was Requested (Ticket)

{ticket_text}

### Technical Design (Plan)

{plan_text}"""


def build_fidelity_prompt(spec: FidelitySpec, pr_title: str, diff: str) -> str:
    """
    Build the user prompt for fidelity analysis.

    Args:
        spec: FidelitySpec with ticket and plan layers
        pr_title: PR title for context
        diff: The PR diff

    Returns:
        Formatted prompt string
    """
    spec_section = _build_spec_section(spec)

    return f"""Analyze the fidelity of this PR against the specification.

{spec_section}

## Pull Request

**Title:** {pr_title}

## Code Changes (Diff)

```diff
{diff}
```

## Your Task

1. Read the specification requirements carefully — both ticket intent and plan design
2. Analyze the diff to understand what was implemented
3. Use tools to verify implementation completeness beyond the diff
4. Score alignment and identify gaps, noting which spec layer each requirement comes from
"""
