"""Extract ticket ID from PR metadata."""

import logging
import re

from baloo.config.settings import get_settings

logger = logging.getLogger(__name__)





def extract_ticket_id(
    branch_name: str,
    pr_title: str,
    pr_description: str | None = None,
    prefix: str | None = None,
) -> str | None:
    """
    Extract ticket ID from PR metadata in priority order.

    Priority:
    1. Branch name: feat/TICKET-123/description
    2. PR title: [TICKET-123] or TICKET-123: prefix
    3. PR description: Ticket: TICKET-123 or any TICKET-XXX match

    Args:
        branch_name: Git branch name
        pr_title: PR title
        pr_description: PR description/body
        prefix: Optional prefix override (defaults to settings.ticket_id_prefix)

    Returns:
        Normalized ticket ID (e.g., "DEN-123") or None if not found
    """
    if prefix is None:
        prefix = get_settings().ticket_id_prefix
    
    pattern = re.compile(rf"{prefix}-(\d+)", re.IGNORECASE)

    # Try branch name first
    ticket_id = _extract_from_branch(branch_name, prefix, pattern)
    if ticket_id:
        logger.debug(f"Extracted ticket ID from branch: {ticket_id}")
        return ticket_id

    # Try PR title
    ticket_id = _extract_from_title(pr_title, prefix, pattern)
    if ticket_id:
        logger.debug(f"Extracted ticket ID from title: {ticket_id}")
        return ticket_id

    # Try PR description
    if pr_description:
        ticket_id = _extract_from_description(pr_description, prefix, pattern)
        if ticket_id:
            logger.debug(f"Extracted ticket ID from description: {ticket_id}")
            return ticket_id

    logger.debug("No ticket ID found in PR metadata")
    return None



def _extract_from_branch(branch_name: str, prefix: str, pattern: re.Pattern) -> str | None:
    """Extract ticket ID from branch name."""
    match = pattern.search(branch_name)
    if match:
        return f"{prefix}-{match.group(1)}"
    return None


def _extract_from_title(pr_title: str, prefix: str, pattern: re.Pattern) -> str | None:
    """Extract ticket ID from PR title."""
    # Check for bracketed format first: [TICKET-123]
    bracketed = re.search(rf"\[{prefix}-(\d+)\]", pr_title, re.IGNORECASE)
    if bracketed:
        return f"{prefix}-{bracketed.group(1)}"

    # Check for prefix format: TICKET-123: or TICKET-123 -
    prefix_match = re.match(rf"^\s*{prefix}-(\d+)\s*[:|-]", pr_title, re.IGNORECASE)
    if prefix_match:
        return f"{prefix}-{prefix_match.group(1)}"

    # Fallback: any TICKET-XXX in title
    match = pattern.search(pr_title)
    if match:
        return f"{prefix}-{match.group(1)}"

    return None


def _extract_from_description(pr_description: str, prefix: str, pattern: re.Pattern) -> str | None:
    """Extract ticket ID from PR description."""
    # Check for explicit ticket reference: Ticket: TICKET-123
    explicit = re.search(rf"Ticket:\s*{prefix}-(\d+)", pr_description, re.IGNORECASE)
    if explicit:
        return f"{prefix}-{explicit.group(1)}"

    # Check for Fixes/Closes patterns
    fixes_pattern = rf"(?:Fixes|Closes|Resolves)\s*[:#]?\s*{prefix}-(\d+)"
    fixes = re.search(fixes_pattern, pr_description, re.IGNORECASE)
    if fixes:
        return f"{prefix}-{fixes.group(1)}"

    # Fallback: first TICKET-XXX in description
    match = pattern.search(pr_description)
    if match:
        return f"{prefix}-{match.group(1)}"

    return None
