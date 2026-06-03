"""Pydantic models for fidelity report data."""

from dataclasses import dataclass

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    """A requirement from the plan and its fulfillment status."""

    description: str = Field(description="The requirement description from the plan")
    status: str = Field(description="Status: fulfilled, partial, missing")
    evidence: str | None = Field(
        default=None, description="Evidence of fulfillment (e.g., file/line reference)"
    )


class Discrepancy(BaseModel):
    """A discrepancy between the plan and implementation."""

    description: str = Field(description="Description of the discrepancy")
    severity: str = Field(default="MEDIUM", description="Severity: LOW, MEDIUM, HIGH")


class FidelityOutput(BaseModel):
    """Structured output from the fidelity agent (no ticket_id)."""

    fidelity_score: int = 0
    logic_summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)
    discrepancies: list[Discrepancy] = Field(default_factory=list)


def fidelity_output_schema() -> dict:
    """Return the JSON schema for fidelity output validation."""
    return {"type": "json_schema", "schema": FidelityOutput.model_json_schema()}


class FidelityResult(BaseModel):
    """Result of fidelity analysis comparing PR to design plan."""

    ticket_id: str = Field(description="The ticket ID (e.g., PROJ-123)")
    fidelity_score: int = Field(description="Fidelity score 0-100 indicating alignment with plan")
    logic_summary: str = Field(description="2-sentence business explanation of the implementation")
    requirements: list[Requirement] = Field(
        default_factory=list, description="Requirements and their fulfillment status"
    )
    extras: list[str] = Field(
        default_factory=list, description="Things implemented that weren't in the plan"
    )
    discrepancies: list[Discrepancy] = Field(
        default_factory=list, description="Critical differences from the plan"
    )
    metadata: dict = Field(default_factory=dict, description="Metadata like cost, tokens")


@dataclass
class FidelitySpec:
    ticket: str | None = None
    plan: str | None = None

    @property
    def has_content(self) -> bool:
        return bool((self.ticket or "").strip() or (self.plan or "").strip())
