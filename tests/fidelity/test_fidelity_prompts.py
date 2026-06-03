"""Tests for fidelity prompt construction."""

from baloo.fidelity.models import FidelitySpec
from baloo.fidelity.prompts import _build_spec_section, build_fidelity_prompt


def test_spec_section_shows_both_layers_when_present():
    spec = FidelitySpec(
        ticket="# Ticket\n\nBuild login.",
        plan="# Plan\n\nUse OAuth2.",
    )
    section = _build_spec_section(spec)
    assert "What Was Requested" in section
    assert "Technical Design" in section
    assert "Build login." in section
    assert "Use OAuth2." in section


def test_spec_section_shows_absent_notice_for_missing_ticket():
    spec = FidelitySpec(ticket=None, plan="# Plan\n\nUse OAuth2.")
    section = _build_spec_section(spec)
    assert "No ticket content available" in section
    assert "Use OAuth2." in section


def test_spec_section_shows_absent_notice_for_missing_plan():
    spec = FidelitySpec(ticket="# Ticket\n\nBuild login.", plan=None)
    section = _build_spec_section(spec)
    assert "Build login." in section
    assert "No plan document found" in section


def test_build_fidelity_prompt_includes_spec_section():
    spec = FidelitySpec(ticket="# Ticket\n\nBuild login.", plan="# Plan\n\nOAuth2.")
    prompt = build_fidelity_prompt(spec, pr_title="Add login", diff="diff --git ...")
    assert "What Was Requested" in prompt
    assert "Technical Design" in prompt
    assert "Add login" in prompt
    assert "diff --git" in prompt


def test_build_fidelity_prompt_includes_layer_attribution_instruction():
    spec = FidelitySpec(ticket="ticket", plan="plan")
    prompt = build_fidelity_prompt(spec, pr_title="title", diff="diff")
    assert "ticket" in prompt.lower()
    assert "plan" in prompt.lower()
