"""Fidelity report module for comparing PR changes against design plans."""

from baloo.fidelity.fidelity_analyzer import analyze_fidelity
from baloo.fidelity.fidelity_report import format_fidelity_report
from baloo.fidelity.models import Discrepancy, FidelityResult, Requirement
from baloo.fidelity.plan_fetcher import fetch_plan_content
from baloo.fidelity.ticket_extractor import extract_ticket_id

__all__ = [
    "extract_ticket_id",
    "fetch_plan_content",
    "analyze_fidelity",
    "format_fidelity_report",
    "FidelityResult",
    "Requirement",
    "Discrepancy",
]
