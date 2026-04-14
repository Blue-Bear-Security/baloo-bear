"""Filter and validate review findings."""

import re

from baloo.config.settings import settings
from baloo.github.models import ReviewComment


class FindingsFilter:
    """Filter low-confidence or false positive findings."""

    # Patterns that indicate low confidence or suggestions
    LOW_CONFIDENCE_PATTERNS = [
        r"might|maybe|could be|possibly|perhaps",
        r"consider|you may want to|you might want to",
        r"it would be nice|optionally",
    ]

    def __init__(self):
        """Initialize the findings filter."""
        self.min_severity = settings.review_min_severity

    def filter_findings(self, comments: list[ReviewComment]) -> list[ReviewComment]:
        """
        Filter out low-confidence or low-severity findings.

        Args:
            comments: List of review comments

        Returns:
            Filtered list of comments
        """
        filtered = []
        for comment in comments:
            if self._should_include(comment):
                filtered.append(comment)

        return filtered

    def _should_include(self, comment: ReviewComment) -> bool:
        """
        Determine if a comment should be included in the review.

        Args:
            comment: Review comment to evaluate

        Returns:
            True if comment should be included
        """
        # Check severity threshold
        severity_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        min_level = severity_order.get(self.min_severity, 2)
        comment_level = severity_order.get(comment.severity, 2)

        if comment_level < min_level:
            return False

        # Check for low-confidence language
        text = comment.body.lower()
        for pattern in self.LOW_CONFIDENCE_PATTERNS:
            if re.search(pattern, text):
                # Only filter out if it's also low/medium severity
                if comment.severity in ["LOW", "MEDIUM"]:
                    return False

        # Check for very short comments (likely not useful)
        if len(comment.body.strip()) < 20:
            return False

        return True
