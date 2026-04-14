"""Fetch plan file content from GitHub."""

import logging
import os

from baloo.config.settings import settings
from baloo.github.api_client import GitHubAPIClient

logger = logging.getLogger(__name__)


async def fetch_plan_content(
    github_client: GitHubAPIClient,
    repo_full_name: str,
    ticket_id: str,
    ref: str | None = None,
) -> str | None:
    """
    Fetch the plan file content for a given ticket.

    Searches for plan files in two ways:
    1. Exact match: docs/plans/{ticket_id}.md
    2. Prefix match: docs/plans/{ticket_id}-*.md (e.g., DEN-123-feature-name.md)

    Args:
        github_client: GitHub API client
        repo_full_name: Repository full name (owner/repo)
        ticket_id: Ticket ID (e.g., DEN-123)
        ref: Git reference (branch, tag, or commit SHA)

    Returns:
        Plan file content as string, or None if not found
    """
    # Build the exact path using the configured pattern
    exact_path = settings.fidelity_plan_path_pattern.format(ticket_id=ticket_id)
    plans_dir = os.path.dirname(exact_path)

    logger.debug(f"Fetching plan file: {repo_full_name}/{exact_path} (ref={ref})")

    try:
        # 1. Try exact match
        content = await github_client.get_file_content(repo_full_name, exact_path, ref)
        if content:
            logger.info(f"Found plan file for {ticket_id}: {len(content)} chars")
            return content

        # 2. Try prefix match (e.g., DEN-123-description.md)
        logger.debug(f"Exact path not found, searching {plans_dir} for {ticket_id}-*.md")
        files = await github_client.list_directory(repo_full_name, plans_dir, ref)
        if not files:
            logger.info(f"No plan file found for {ticket_id} at {exact_path}")
            return None

        # Find files that start with the ticket ID
        ticket_prefix = f"{ticket_id}-"
        matching_files = [
            f for f in files
            if f.startswith(ticket_prefix) and f.endswith(".md")
        ]

        if not matching_files:
            logger.info(f"No plan file found for {ticket_id} at {exact_path}")
            return None

        # Use the first matching file
        plan_file = matching_files[0]
        plan_path = f"{plans_dir}/{plan_file}"
        logger.debug(f"Found matching plan file: {plan_path}")

        content = await github_client.get_file_content(
            repo_full_name, plan_path, ref
        )
        if content:
            logger.info(
                f"Found plan file for {ticket_id} ({plan_file}): {len(content)} chars"
            )
            return content

        return None

    except Exception as e:
        logger.warning(f"Error fetching plan file for {ticket_id}: {e}")
        return None
