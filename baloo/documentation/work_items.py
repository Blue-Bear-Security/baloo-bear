"""Build deterministic documentation drift work items from PR changes."""

from __future__ import annotations

import re

from baloo.documentation.models import (
    DocumentationCatalog,
    DocumentationWorkItem,
    DocumentationWorkItemMatch,
)
from baloo.github.models import PRContext

_DOC_EXTENSIONS = (".md", ".mdx", ".rst", ".csv")


def is_documentation_path(path: str) -> bool:
    """Return True for documentation-like paths."""
    normalized = path.lower()
    return normalized.endswith(_DOC_EXTENSIONS)


def rule_matches_path(path: str, patterns: list[str]) -> bool:
    """Match GitHub-style globs where * is one segment and ** is recursive."""
    normalized_path = path.strip("/")
    return any(_glob_to_regex(pattern).fullmatch(normalized_path) for pattern in patterns)


def build_documentation_work_item(
    *,
    pr_context: PRContext,
    catalog: DocumentationCatalog,
) -> DocumentationWorkItem:
    """Map changed implementation files to candidate documentation files."""
    changed_files = [file_change.filename for file_change in pr_context.files_changed]
    changed_docs = {path for path in changed_files if is_documentation_path(path)}
    implementation_files = [path for path in changed_files if not is_documentation_path(path)]

    matched_impl_files: set[str] = set()
    matches: list[DocumentationWorkItemMatch] = []

    for rule in catalog.rules:
        matched_files = [
            path for path in implementation_files if rule_matches_path(path, rule.patterns)
        ]
        if not matched_files:
            continue

        matched_impl_files.update(matched_files)
        docs_already_changed = [
            doc_path for doc_path in rule.recommended_docs if doc_path in changed_docs
        ]
        docs_to_review = (
            []
            if rule.read_only
            else [doc_path for doc_path in rule.recommended_docs if doc_path not in changed_docs]
        )
        matches.append(
            DocumentationWorkItemMatch(
                area=rule.area,
                matched_files=matched_files,
                docs_already_changed=docs_already_changed,
                docs_to_review=docs_to_review,
            )
        )

    unmapped_files = [path for path in implementation_files if path not in matched_impl_files]
    has_relevant_impl_changes = bool(matched_impl_files)
    has_docs_to_review = any(match.docs_to_review for match in matches)
    has_docs_already_changed = any(match.docs_already_changed for match in matches)
    has_catalog_gaps = bool(unmapped_files)
    needs_analysis = has_relevant_impl_changes or has_docs_already_changed or has_catalog_gaps

    return DocumentationWorkItem(
        repo_full_name=pr_context.repo_full_name,
        pr_number=pr_context.pr_number,
        title=pr_context.title,
        changed_files=changed_files,
        matches=matches,
        unmapped_files=unmapped_files,
        has_relevant_impl_changes=has_relevant_impl_changes,
        has_docs_to_review=has_docs_to_review,
        has_docs_already_changed=has_docs_already_changed,
        has_catalog_gaps=has_catalog_gaps,
        needs_analysis=needs_analysis,
    )


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    parts = pattern.strip("/").split("/")
    regex = "^"
    for index, part in enumerate(parts):
        if part == "**":
            if len(parts) == 1:
                regex += ".*"
            elif index == len(parts) - 1:
                regex += "(?:/.*)?"
            elif index == 0:
                regex += "(?:[^/]+/)*"
            else:
                regex += "/(?:[^/]+/)*"
            continue

        if index > 0 and parts[index - 1] != "**":
            regex += "/"
        regex += _segment_to_regex(part)
    regex += "$"
    return re.compile(regex)


def _segment_to_regex(segment: str) -> str:
    chars: list[str] = []
    for char in segment:
        if char == "*":
            chars.append("[^/]*")
        else:
            chars.append(re.escape(char))
    return "".join(chars)
