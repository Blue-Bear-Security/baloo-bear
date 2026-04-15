"""GitHub Checks API client for posting code quality findings."""

import logging

import httpx

from baloo.github.auth import GitHubAuth
from baloo.github.models import ReviewComment

logger = logging.getLogger(__name__)

# GitHub limits annotations to 50 per request
MAX_ANNOTATIONS = 50


def _enum_value(value: object) -> object:
    """Return enum values for user-facing strings without changing plain strings."""
    return getattr(value, "value", value)


class GitHubChecksClient:
    """Client for interacting with GitHub Checks API."""

    def __init__(self, installation_id: int):
        """
        Initialize GitHub Checks API client.

        Args:
            installation_id: GitHub App installation ID
        """
        self.installation_id = installation_id
        self.auth = GitHubAuth()
        self.base_url = "https://api.github.com"

    def _get_headers(self) -> dict[str, str]:
        """Get headers for GitHub API requests."""
        token = self.auth.get_installation_token(self.installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_check_run(
        self, repo_full_name: str, commit_sha: str, name: str, conclusion: str, summary: str
    ) -> str:
        """
        Create a GitHub Check Run.

        Args:
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Commit SHA to attach check to
            name: Check run name (e.g., "Baloo Code Quality")
            conclusion: "success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required"
            summary: Summary text for the check

        Returns:
            Check run ID as string
        """
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/repos/{repo_full_name}/check-runs"
            payload = {
                "name": name,
                "head_sha": commit_sha,
                "status": "completed",
                "conclusion": conclusion,
                "output": {"title": name, "summary": summary},
            }

            logger.debug(f"Creating check run: {name} for {repo_full_name}@{commit_sha[:7]}")

            response = await client.post(url, headers=self._get_headers(), json=payload)
            response.raise_for_status()
            data = response.json()

            logger.info(f"Created check run ID {data['id']} for {repo_full_name}")
            return str(data["id"])

    async def add_annotations(
        self, repo_full_name: str, check_run_id: str, findings: list[ReviewComment]
    ) -> None:
        """
        Add annotations to a check run.

        Annotations appear in the "Files changed" tab and provide inline feedback.

        Args:
            repo_full_name: Repository full name (owner/repo)
            check_run_id: Check run ID from create_check_run
            findings: List of findings to add as annotations
        """
        if not findings:
            logger.debug("No findings to annotate")
            return

        if len(findings) > MAX_ANNOTATIONS:
            logger.warning(
                f"Truncating {len(findings)} findings to {MAX_ANNOTATIONS} "
                f"(GitHub Checks API limit)"
            )

        # Format findings as annotations with category prefix
        annotations = []
        for finding in findings[:MAX_ANNOTATIONS]:
            severity = _enum_value(finding.severity)
            category = _enum_value(finding.category)
            annotation = {
                "path": finding.path,
                "start_line": finding.line,
                "end_line": finding.line,
                "annotation_level": "warning",  # Can be: notice, warning, failure
                "message": f"{category}: {finding.body}",
                "title": f"[{severity}] {category}",
            }
            annotations.append(annotation)

        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/repos/{repo_full_name}/check-runs/{check_run_id}"
            payload = {
                "output": {
                    "title": "Baloo Code Quality",
                    "summary": f"Found {len(findings)} code quality issue(s)",
                    "annotations": annotations,
                }
            }

            logger.debug(f"Adding {len(annotations)} annotations to check run {check_run_id}")

            response = await client.patch(url, headers=self._get_headers(), json=payload)
            response.raise_for_status()

            logger.info(
                f"Added {len(annotations)} annotations to check run {check_run_id} "
                f"for {repo_full_name}"
            )
