"""Tests for ticket ID extraction from PR metadata."""

import re
from unittest.mock import patch

import pytest

from baloo.fidelity.ticket_extractor import (
    _extract_from_branch,
    _extract_from_description,
    _extract_from_title,
    extract_ticket_id,
)

# Test constants
DEN_PREFIX = "DEN"
DEN_PATTERN = re.compile(rf"{DEN_PREFIX}-(\d+)", re.IGNORECASE)


@pytest.fixture
def patch_settings():
    with patch("baloo.config.settings.get_settings") as mock_get:
        mock_get.return_value.ticket_id_prefix = "DEN"
        yield


@pytest.fixture
def patch_custom_settings():
    with patch("baloo.config.settings.get_settings") as mock_get:
        mock_get.return_value.ticket_id_prefix = "JIRA"
        yield


class TestExtractFromBranch:
    """Tests for _extract_from_branch function."""

    def test_feat_slash_format(self):
        """Test feat/DEN-XXX/description format."""
        assert (
            _extract_from_branch("feat/DEN-123/add-feature", DEN_PREFIX, DEN_PATTERN) == "DEN-123"
        )
        assert (
            _extract_from_branch("feat/DEN-1234/some-thing", DEN_PREFIX, DEN_PATTERN) == "DEN-1234"
        )

    def test_fix_slash_format(self):
        """Test fix/DEN-XXX/description format."""
        assert _extract_from_branch("fix/DEN-456/bug-fix", DEN_PREFIX, DEN_PATTERN) == "DEN-456"

    def test_chore_slash_format(self):
        """Test chore/DEN-XXX/description format."""
        assert (
            _extract_from_branch("chore/DEN-789/update-deps", DEN_PREFIX, DEN_PATTERN) == "DEN-789"
        )

    def test_dash_format(self):
        """Test DEN-XXX-description format."""
        assert _extract_from_branch("fix/DEN-456-description", DEN_PREFIX, DEN_PATTERN) == "DEN-456"
        assert _extract_from_branch("DEN-123-something", DEN_PREFIX, DEN_PATTERN) == "DEN-123"

    def test_case_insensitive(self):
        """Test that extraction is case-insensitive."""
        assert _extract_from_branch("feat/den-123/feature", DEN_PREFIX, DEN_PATTERN) == "DEN-123"
        assert _extract_from_branch("feat/Den-456/feature", DEN_PREFIX, DEN_PATTERN) == "DEN-456"

    def test_no_ticket(self):
        """Test branch without ticket ID."""
        assert _extract_from_branch("main", DEN_PREFIX, DEN_PATTERN) is None
        assert _extract_from_branch("feat/add-feature", DEN_PREFIX, DEN_PATTERN) is None
        assert _extract_from_branch("fix-bug", DEN_PREFIX, DEN_PATTERN) is None

    def test_other_prefix(self):
        """Test that other prefixes (not DEN) don't match."""
        assert _extract_from_branch("feat/JIRA-123/feature", DEN_PREFIX, DEN_PATTERN) is None
        assert _extract_from_branch("feat/ABC-123/feature", DEN_PREFIX, DEN_PATTERN) is None


class TestExtractFromTitle:
    """Tests for _extract_from_title function."""

    def test_bracketed_format(self):
        """Test [DEN-XXX] format."""
        assert (
            _extract_from_title("[DEN-123] Add new feature", DEN_PREFIX, DEN_PATTERN) == "DEN-123"
        )
        assert _extract_from_title("[DEN-1234] Fix bug", DEN_PREFIX, DEN_PATTERN) == "DEN-1234"

    def test_colon_prefix(self):
        """Test DEN-XXX: format."""
        assert _extract_from_title("DEN-123: Add new feature", DEN_PREFIX, DEN_PATTERN) == "DEN-123"
        assert _extract_from_title("DEN-456:Fix bug", DEN_PREFIX, DEN_PATTERN) == "DEN-456"

    def test_dash_prefix(self):
        """Test DEN-XXX - format."""
        assert (
            _extract_from_title("DEN-123 - Add new feature", DEN_PREFIX, DEN_PATTERN) == "DEN-123"
        )

    def test_anywhere_in_title(self):
        """Test DEN-XXX anywhere in title (fallback)."""
        assert _extract_from_title("Fix the DEN-789 issue", DEN_PREFIX, DEN_PATTERN) == "DEN-789"
        assert (
            _extract_from_title("Implement feature for DEN-100", DEN_PREFIX, DEN_PATTERN)
            == "DEN-100"
        )

    def test_case_insensitive(self):
        """Test that extraction is case-insensitive."""
        assert _extract_from_title("[den-123] Feature", DEN_PREFIX, DEN_PATTERN) == "DEN-123"
        assert _extract_from_title("Den-456: Fix", DEN_PREFIX, DEN_PATTERN) == "DEN-456"

    def test_no_ticket(self):
        """Test title without ticket ID."""
        assert _extract_from_title("Add new feature", DEN_PREFIX, DEN_PATTERN) is None
        assert _extract_from_title("Fix authentication bug", DEN_PREFIX, DEN_PATTERN) is None


class TestExtractFromDescription:
    """Tests for _extract_from_description function."""

    def test_explicit_ticket_reference(self):
        """Test Ticket: DEN-XXX format."""
        assert (
            _extract_from_description(
                "Ticket: DEN-123\n\nDescription here", DEN_PREFIX, DEN_PATTERN
            )
            == "DEN-123"
        )
        assert _extract_from_description("ticket: den-456", DEN_PREFIX, DEN_PATTERN) == "DEN-456"

    def test_fixes_pattern(self):
        """Test Fixes DEN-XXX format."""
        assert _extract_from_description("Fixes DEN-123", DEN_PREFIX, DEN_PATTERN) == "DEN-123"
        assert _extract_from_description("Fixes: DEN-456", DEN_PREFIX, DEN_PATTERN) == "DEN-456"
        assert _extract_from_description("fixes #DEN-789", DEN_PREFIX, DEN_PATTERN) == "DEN-789"

    def test_closes_pattern(self):
        """Test Closes DEN-XXX format."""
        assert _extract_from_description("Closes DEN-123", DEN_PREFIX, DEN_PATTERN) == "DEN-123"

    def test_resolves_pattern(self):
        """Test Resolves DEN-XXX format."""
        assert _extract_from_description("Resolves DEN-123", DEN_PREFIX, DEN_PATTERN) == "DEN-123"

    def test_anywhere_in_description(self):
        """Test DEN-XXX anywhere in description (fallback)."""
        desc = """
        This PR implements the feature described in DEN-123.

        Changes:
        - Added new endpoint
        - Updated tests
        """
        assert _extract_from_description(desc, DEN_PREFIX, DEN_PATTERN) == "DEN-123"

    def test_no_ticket(self):
        """Test description without ticket ID."""
        assert _extract_from_description("This is a simple fix", DEN_PREFIX, DEN_PATTERN) is None
        assert _extract_from_description("", DEN_PREFIX, DEN_PATTERN) is None


class TestExtractTicketId:
    """Tests for main extract_ticket_id function."""

    def test_priority_branch_first(self, patch_settings):
        """Test that branch takes priority over title and description."""
        ticket_id = extract_ticket_id(
            branch_name="feat/DEN-111/feature",
            pr_title="[DEN-222] Title",
            pr_description="Ticket: DEN-333",
            prefix="DEN",
        )
        assert ticket_id == "DEN-111"

    def test_priority_title_second(self, patch_settings):
        """Test that title takes priority over description when no branch match."""
        ticket_id = extract_ticket_id(
            branch_name="feature-branch",
            pr_title="[DEN-222] Title",
            pr_description="Ticket: DEN-333",
            prefix="DEN",
        )
        assert ticket_id == "DEN-222"

    def test_priority_description_last(self, patch_settings):
        """Test that description is checked last."""
        ticket_id = extract_ticket_id(
            branch_name="feature-branch",
            pr_title="Add new feature",
            pr_description="Ticket: DEN-333",
            prefix="DEN",
        )
        assert ticket_id == "DEN-333"

    def test_no_ticket_anywhere(self, patch_settings):
        """Test when no ticket ID is found anywhere."""
        ticket_id = extract_ticket_id(
            branch_name="feature-branch",
            pr_title="Add new feature",
            pr_description="This is a description",
            prefix="DEN",
        )
        assert ticket_id is None

    def test_none_description(self, patch_settings):
        """Test with None description."""
        ticket_id = extract_ticket_id(
            branch_name="feat/DEN-123/feature", pr_title="Title", pr_description=None, prefix="DEN"
        )
        assert ticket_id == "DEN-123"

    def test_empty_description(self, patch_settings):
        """Test with empty description."""
        ticket_id = extract_ticket_id(
            branch_name="feature-branch", pr_title="Add feature", pr_description="", prefix="DEN"
        )
        assert ticket_id is None

    def test_normalizes_to_uppercase(self, patch_settings):
        """Test that ticket ID is normalized to uppercase."""
        ticket_id = extract_ticket_id(
            branch_name="feat/den-123/feature", pr_title="", pr_description=None, prefix="DEN"
        )
        assert ticket_id == "DEN-123"

    def test_custom_prefix(self, patch_custom_settings):
        """Test extraction with a custom prefix (e.g., JIRA)."""
        ticket_id = extract_ticket_id(
            branch_name="feat/JIRA-999/feature",
            pr_title="Title",
            pr_description=None,
            prefix="JIRA",
        )
        assert ticket_id == "JIRA-999"
