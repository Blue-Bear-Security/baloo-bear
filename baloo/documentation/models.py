"""Pydantic models for documentation drift analysis."""

from typing import Literal

from pydantic import BaseModel, Field


class DocumentationCatalogRule(BaseModel):
    area: str
    patterns: list[str] = Field(default_factory=list)
    recommended_docs: list[str] = Field(default_factory=list)
    read_only: bool = False


class DocumentationCatalog(BaseModel):
    schema_version: int = 1
    rules: list[DocumentationCatalogRule] = Field(default_factory=list)


class DocumentationWorkItemMatch(BaseModel):
    area: str
    matched_files: list[str]
    docs_already_changed: list[str]
    docs_to_review: list[str]


class DocumentationWorkItem(BaseModel):
    repo_full_name: str
    pr_number: int
    title: str
    changed_files: list[str]
    matches: list[DocumentationWorkItemMatch]
    unmapped_files: list[str]
    ignored_unmapped_files: list[str] = Field(default_factory=list)
    has_relevant_impl_changes: bool
    has_docs_to_review: bool
    has_docs_already_changed: bool
    has_catalog_gaps: bool
    needs_analysis: bool


class DocumentationDriftFinding(BaseModel):
    doc_path: str
    verdict: Literal["required", "optional", "not_needed"]
    rationale: str
    evidence: list[str] = Field(default_factory=list)
    suggested_update: str | None = None


class DocumentationDriftResult(BaseModel):
    action_required: Literal["none", "update_docs", "catalog_hygiene"] | None = None
    summary: str = ""
    required_updates: list[DocumentationDriftFinding] = Field(default_factory=list)
    optional_updates: list[DocumentationDriftFinding] = Field(default_factory=list)
    not_needed: list[DocumentationDriftFinding] = Field(default_factory=list)
    catalog_gaps: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
