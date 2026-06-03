"""Tests for fidelity data models."""

from baloo.fidelity.models import FidelitySpec


def test_fidelity_spec_has_content_when_ticket_present():
    spec = FidelitySpec(ticket="## Goal\n\nBuild login.", plan=None)
    assert spec.has_content is True


def test_fidelity_spec_has_content_when_plan_present():
    spec = FidelitySpec(ticket=None, plan="# Plan\n\nDesign doc.")
    assert spec.has_content is True


def test_fidelity_spec_has_content_when_both_present():
    spec = FidelitySpec(ticket="ticket", plan="plan")
    assert spec.has_content is True


def test_fidelity_spec_has_no_content_when_both_none():
    spec = FidelitySpec()
    assert spec.has_content is False


def test_fidelity_spec_has_no_content_when_both_empty_string():
    spec = FidelitySpec(ticket="", plan="")
    assert spec.has_content is False


def test_fidelity_spec_has_no_content_when_whitespace_only():
    spec = FidelitySpec(ticket="   ", plan="\n\t")
    assert spec.has_content is False
