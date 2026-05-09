"""Pydantic models for GitHub webhook payloads and API responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReviewSeverity(str, Enum):
    """Standard severity levels for review findings."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingCategory(str, Enum):
    """Standard categories for review findings."""

    SECURITY = "Security"
    BUGS = "Bugs"
    SILENT_FAILURES = "Silent Failures"
    GUIDELINES = "Guidelines"
    PERFORMANCE = "Performance"
    QUALITY = "Quality"


class User(BaseModel):
    """GitHub user model."""

    login: str
    id: int
    avatar_url: str
    html_url: str


class Repository(BaseModel):
    """GitHub repository model."""

    id: int
    name: str
    full_name: str
    owner: User
    html_url: str
    default_branch: str


class PullRequest(BaseModel):
    """GitHub pull request model."""

    number: int
    title: str
    body: str | None = None
    state: str
    html_url: str
    user: User
    head: dict[str, Any]
    base: dict[str, Any]
    merged: bool = False
    draft: bool = False


class Installation(BaseModel):
    """GitHub App installation model."""

    id: int


class PullRequestWebhookPayload(BaseModel):
    """GitHub pull_request webhook payload model."""

    action: str
    number: int
    pull_request: PullRequest
    repository: Repository
    installation: Installation
    sender: User


class FileChange(BaseModel):
    """Represents a changed file in a PR."""

    filename: str
    status: str  # added, removed, modified, renamed
    additions: int
    deletions: int
    changes: int
    patch: str | None = None  # Unified diff patch


class DiscussionComment(BaseModel):
    """Represents a comment that is part of PR discussion."""

    id: int
    author: str
    body: str
    created_at: datetime
    updated_at: datetime
    source: str  # review_comment, issue_comment, review
    is_baloo: bool = False
    path: str | None = None
    line: int | None = None
    url: str | None = None


class DiscussionThread(BaseModel):
    """Represents an inline review thread."""

    id: int
    path: str | None
    line: int | None
    comments: list[DiscussionComment]
    is_baloo_thread: bool = False
    awaiting_response: bool = False
    resolved: bool = False
    outdated: bool = False
    last_activity: datetime
    root_comment_id: int | None = None
    node_id: str | None = None


class PRMetadata(BaseModel):
    """Basic metadata about a PR."""

    repo_full_name: str
    pr_number: int
    title: str
    description: str | None
    author: str
    base_branch: str
    head_branch: str
    head_sha: str
    files_changed: list[FileChange]
    repo_guidelines: str | None = None
    commit_messages: list[str] = Field(default_factory=list)


class PRDiscussionContext(BaseModel):
    """Context about PR discussions."""

    threads: list[DiscussionThread] = Field(default_factory=list)
    issue_comments: list[DiscussionComment] = Field(default_factory=list)
    digest: str | None = None
    awaiting_response_count: int = 0


class PRContext(BaseModel):
    """Full context about a PR for review, combining metadata and discussion."""

    metadata: PRMetadata
    discussion: PRDiscussionContext
    diff: str
    feedback_signals: list = Field(default_factory=list)

    @property
    def repo_full_name(self) -> str:
        return self.metadata.repo_full_name

    @property
    def pr_number(self) -> int:
        return self.metadata.pr_number

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def description(self) -> str | None:
        return self.metadata.description

    @property
    def author(self) -> str:
        return self.metadata.author

    @property
    def base_branch(self) -> str:
        return self.metadata.base_branch

    @property
    def head_branch(self) -> str:
        return self.metadata.head_branch

    @property
    def head_sha(self) -> str:
        return self.metadata.head_sha

    @property
    def files_changed(self) -> list[FileChange]:
        return self.metadata.files_changed

    @property
    def discussion_threads(self) -> list[DiscussionThread]:
        return self.discussion.threads

    @property
    def issue_comments(self) -> list[DiscussionComment]:
        return self.discussion.issue_comments

    @property
    def discussion_digest(self) -> str | None:
        return self.discussion.digest

    @property
    def awaiting_response_threads(self) -> int:
        return self.discussion.awaiting_response_count

    @property
    def repo_guidelines(self) -> str | None:
        return self.metadata.repo_guidelines

    def get(self, key: str, default: Any = None) -> Any:
        """Backward compatibility for dict-like access."""
        if key == "changed_file_paths":
            return [f.filename for f in self.files_changed]
        if key == "awaiting_discussions":
            return self.awaiting_response_threads
        if hasattr(self, key):
            return getattr(self, key)
        return default


class ReviewComment(BaseModel):
    """A review comment on a specific file and line."""

    path: str
    line: int
    body: str
    severity: ReviewSeverity = ReviewSeverity.MEDIUM
    category: FindingCategory = FindingCategory.QUALITY


class ReviewResult(BaseModel):
    """Result of a code review."""

    summary: str
    comments: list[ReviewComment]
    approve: bool = False
    request_changes: bool = False
    metadata: dict = Field(default_factory=dict)
