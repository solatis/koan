# Unit tests for koan.tools.artifact_registry -- pure grammar and validation.
#
# All tests are plain-data: no mocks, no filesystem. Every validator input
# is constructed inline; every expected output is asserted directly.

from __future__ import annotations

import pytest

from koan.tools.artifact_registry import (
    ARTIFACT_REGISTRY,
    ArtifactCoordinate,
    ValidationError,
    classify,
    is_review_sidecar,
    next_remediation_name,
    parse_artifact_filename,
    predecessor_chain,
    reviewer_for,
    sidecar_name_for,
    validate_edit,
    validate_execute_target,
    validate_write,
)


# -- parse_artifact_filename -------------------------------------------------- #


def test_parse_brief():
    """brief.md decodes to the brief family with no discriminator or chain."""
    assert parse_artifact_filename("brief.md") == ArtifactCoordinate("brief", None, None)


def test_parse_core_flows():
    """core-flows.md decodes to core-flows family."""
    assert parse_artifact_filename("core-flows.md") == ArtifactCoordinate("core-flows", None, None)


def test_parse_tech_plan():
    """tech-plan.md decodes to tech-plan, not accidentally matched by the plan branch."""
    assert parse_artifact_filename("tech-plan.md") == ArtifactCoordinate("tech-plan", None, None)


def test_parse_milestones():
    """milestones.md decodes to the milestones family."""
    assert parse_artifact_filename("milestones.md") == ArtifactCoordinate("milestones", None, None)


def test_parse_plan_bare():
    """plan.md decodes to the plan family with no discriminator."""
    assert parse_artifact_filename("plan.md") == ArtifactCoordinate("plan", None, None)


def test_parse_plan_milestone():
    """plan-milestone-N.md decodes with the correct discriminator."""
    assert parse_artifact_filename("plan-milestone-3.md") == ArtifactCoordinate("plan", 3, None)


def test_parse_plan_milestone_large_n():
    """plan-milestone-12.md correctly parses a multi-digit discriminator."""
    assert parse_artifact_filename("plan-milestone-12.md") == ArtifactCoordinate("plan", 12, None)


def test_parse_plan_remediation():
    """plan-remediation-K.md decodes with chain_position and no discriminator."""
    assert parse_artifact_filename("plan-remediation-1.md") == ArtifactCoordinate("plan", None, 1)


def test_parse_plan_milestone_remediation():
    """plan-milestone-N-remediation-K.md decodes both discriminator and chain_position."""
    result = parse_artifact_filename("plan-milestone-2-remediation-1.md")
    assert result == ArtifactCoordinate("plan", 2, 1)


def test_parse_plan_milestone_remediation_large_k():
    """Multi-digit K in plan-milestone-N-remediation-K.md parses correctly."""
    result = parse_artifact_filename("plan-milestone-1-remediation-10.md")
    assert result == ArtifactCoordinate("plan", 1, 10)


def test_parse_review_sidecar_returns_none():
    """plan.review.md is a koan-owned sidecar; the parser returns None."""
    assert parse_artifact_filename("plan.review.md") is None


def test_parse_milestone_review_sidecar_returns_none():
    """plan-milestone-1.review.md is also a sidecar; returns None."""
    assert parse_artifact_filename("plan-milestone-1.review.md") is None


def test_parse_zero_discriminator_returns_none():
    """plan-milestone-0.md has a zero index -- rejected (must be positive)."""
    assert parse_artifact_filename("plan-milestone-0.md") is None


def test_parse_zero_chain_returns_none():
    """plan-remediation-0.md has a zero chain index -- rejected."""
    assert parse_artifact_filename("plan-remediation-0.md") is None


def test_parse_leading_zero_discriminator_returns_none():
    """plan-milestone-01.md has a leading-zero discriminator -- rejected."""
    assert parse_artifact_filename("plan-milestone-01.md") is None


def test_parse_leading_zero_chain_returns_none():
    """plan-milestone-1-remediation-02.md has a leading-zero chain -- rejected."""
    assert parse_artifact_filename("plan-milestone-1-remediation-02.md") is None


def test_parse_arbitrary_filename_returns_none():
    """An unrecognized filename returns None."""
    assert parse_artifact_filename("random-file.md") is None


def test_parse_empty_string_returns_none():
    """An empty string is not a valid artifact filename."""
    assert parse_artifact_filename("") is None


def test_parse_no_extension_returns_none():
    """plan without .md extension is not recognized."""
    assert parse_artifact_filename("plan") is None


# -- is_review_sidecar / sidecar_name_for ------------------------------------- #


def test_is_review_sidecar_true_for_review_md():
    """plan.review.md is a review sidecar."""
    assert is_review_sidecar("plan.review.md") is True


def test_is_review_sidecar_true_for_milestone_review():
    """plan-milestone-1.review.md is a review sidecar."""
    assert is_review_sidecar("plan-milestone-1.review.md") is True


def test_is_review_sidecar_false_for_plain_artifact():
    """plan.md is not a sidecar."""
    assert is_review_sidecar("plan.md") is False


def test_is_review_sidecar_false_for_milestones():
    """milestones.md is not a sidecar."""
    assert is_review_sidecar("milestones.md") is False


def test_sidecar_name_for_plan():
    """plan.md -> plan.review.md."""
    assert sidecar_name_for("plan.md") == "plan.review.md"


def test_sidecar_name_for_milestone_plan():
    """plan-milestone-1.md -> plan-milestone-1.review.md."""
    assert sidecar_name_for("plan-milestone-1.md") == "plan-milestone-1.review.md"


def test_sidecar_name_for_tech_plan():
    """tech-plan.md -> tech-plan.review.md."""
    assert sidecar_name_for("tech-plan.md") == "tech-plan.review.md"


def test_sidecar_name_for_remediation():
    """plan-remediation-1.md -> plan-remediation-1.review.md."""
    assert sidecar_name_for("plan-remediation-1.md") == "plan-remediation-1.review.md"


# -- classify / reviewer_for -------------------------------------------------- #


def test_classify_brief_entry():
    """classify returns the brief registry entry."""
    entry = classify("brief")
    assert entry is not None
    assert entry.reviewer_prompt is None
    assert entry.on_write == "create_no_review"


def test_classify_plan_entry():
    """classify returns the plan entry with PLAN_REVIEWER and chain support."""
    entry = classify("plan")
    assert entry is not None
    assert entry.reviewer_prompt == "PLAN_REVIEWER"
    assert entry.takes_discriminator is True
    assert entry.takes_chain is True


def test_classify_unknown_family_returns_none():
    """classify returns None for an unknown family."""
    assert classify("no-such-family") is None


def test_reviewer_for_plan():
    """plan.md has reviewer PLAN_REVIEWER."""
    assert reviewer_for("plan.md") == "PLAN_REVIEWER"


def test_reviewer_for_milestone_plan():
    """plan-milestone-1.md has reviewer PLAN_REVIEWER (same family)."""
    assert reviewer_for("plan-milestone-1.md") == "PLAN_REVIEWER"


def test_reviewer_for_milestones():
    """milestones.md has reviewer MILESTONE_REVIEWER."""
    assert reviewer_for("milestones.md") == "MILESTONE_REVIEWER"


def test_reviewer_for_tech_plan():
    """tech-plan.md has reviewer TECH_PLAN_REVIEWER."""
    assert reviewer_for("tech-plan.md") == "TECH_PLAN_REVIEWER"


def test_reviewer_for_brief_is_none():
    """brief.md has no reviewer."""
    assert reviewer_for("brief.md") is None


def test_reviewer_for_core_flows_is_none():
    """core-flows.md has no reviewer."""
    assert reviewer_for("core-flows.md") is None


def test_reviewer_for_unrecognized_returns_none():
    """An unrecognized filename returns None from reviewer_for."""
    assert reviewer_for("unknown.md") is None


def test_reviewer_for_sidecar_returns_none():
    """A sidecar filename returns None (not in grammar)."""
    assert reviewer_for("plan.review.md") is None


# -- next_remediation_name ---------------------------------------------------- #


def test_next_remediation_from_bare_plan():
    """plan.md -> plan-remediation-1.md."""
    assert next_remediation_name("plan.md") == "plan-remediation-1.md"


def test_next_remediation_from_milestone_plan():
    """plan-milestone-1.md -> plan-milestone-1-remediation-1.md."""
    assert next_remediation_name("plan-milestone-1.md") == "plan-milestone-1-remediation-1.md"


def test_next_remediation_from_bare_remediation():
    """plan-remediation-2.md -> plan-remediation-3.md."""
    assert next_remediation_name("plan-remediation-2.md") == "plan-remediation-3.md"


def test_next_remediation_from_milestone_remediation():
    """plan-milestone-1-remediation-2.md -> plan-milestone-1-remediation-3.md."""
    result = next_remediation_name("plan-milestone-1-remediation-2.md")
    assert result == "plan-milestone-1-remediation-3.md"


def test_next_remediation_for_non_plan_returns_none():
    """milestones.md is not a plan family; returns None."""
    assert next_remediation_name("milestones.md") is None


def test_next_remediation_for_brief_returns_none():
    """brief.md is not a plan family; returns None."""
    assert next_remediation_name("brief.md") is None


def test_next_remediation_for_unrecognized_returns_none():
    """Unrecognized filename returns None."""
    assert next_remediation_name("garbage.md") is None


# -- predecessor_chain -------------------------------------------------------- #


def test_predecessor_chain_for_base_plan_is_empty():
    """A base plan has no predecessors."""
    assert predecessor_chain("plan.md", ["plan.md"]) == []


def test_predecessor_chain_for_remediation_1_returns_base():
    """plan-remediation-1.md has plan.md as its only predecessor."""
    result = predecessor_chain("plan-remediation-1.md", ["plan.md", "plan-remediation-1.md"])
    assert result == ["plan.md"]


def test_predecessor_chain_for_remediation_2():
    """plan-remediation-2.md: chain is [plan.md, plan-remediation-1.md]."""
    all_names = ["plan.md", "plan-remediation-1.md", "plan-remediation-2.md"]
    result = predecessor_chain("plan-remediation-2.md", all_names)
    assert result == ["plan.md", "plan-remediation-1.md"]


def test_predecessor_chain_for_milestone_remediation():
    """plan-milestone-1-remediation-1.md has plan-milestone-1.md as predecessor."""
    all_names = ["plan-milestone-1.md", "plan-milestone-1-remediation-1.md"]
    result = predecessor_chain("plan-milestone-1-remediation-1.md", all_names)
    assert result == ["plan-milestone-1.md"]


def test_predecessor_chain_excludes_missing_entries():
    """Missing links in all_names are simply excluded from the chain."""
    # plan-remediation-1.md is absent from all_names
    all_names = ["plan.md", "plan-remediation-2.md"]
    result = predecessor_chain("plan-remediation-2.md", all_names)
    assert result == ["plan.md"]


def test_predecessor_chain_for_unrecognized_is_empty():
    """Unrecognized filename returns empty list."""
    assert predecessor_chain("garbage.md", ["garbage.md"]) == []


# -- validate_write ----------------------------------------------------------- #


def test_validate_write_happy_path_bare_plan():
    """Writing plan.md in the plan phase with no discriminator required succeeds."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is None


def test_validate_write_happy_path_milestone_plan():
    """Writing plan-milestone-1.md in plan phase with requires_discriminator=True succeeds."""
    err = validate_write(
        "plan-milestone-1.md",
        phase="plan",
        requires_discriminator=True,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is None


def test_validate_write_happy_path_contiguous_remediation():
    """Writing plan-remediation-1.md when plan.md exists succeeds."""
    err = validate_write(
        "plan-remediation-1.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset({"plan.md"}),
    )
    assert err is None


def test_validate_write_happy_path_brief():
    """Writing brief.md in the intake phase succeeds."""
    err = validate_write(
        "brief.md",
        phase="intake",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is None


def test_validate_write_sidecar_rejected():
    """Attempting to write a .review.md sidecar returns name_malformed."""
    err = validate_write(
        "plan.review.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "name_malformed"


def test_validate_write_malformed_name():
    """An unrecognized filename returns name_malformed."""
    err = validate_write(
        "unknown-thing.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "name_malformed"


def test_validate_write_wrong_phase():
    """Writing brief.md in the plan phase returns wrong_phase."""
    err = validate_write(
        "brief.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "wrong_phase"


def test_validate_write_bare_plan_when_discriminator_required():
    """Writing bare plan.md when requires_discriminator=True returns wrong_phase with suggestion."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=True,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "wrong_phase"
    assert err.suggested_name == "plan-milestone-1.md"


def test_validate_write_discriminated_plan_when_discriminator_not_required():
    """Writing plan-milestone-1.md when requires_discriminator=False returns wrong_phase."""
    err = validate_write(
        "plan-milestone-1.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "wrong_phase"
    assert err.suggested_name == "plan.md"


def test_validate_write_exists_frozen():
    """Writing a filename that already exists and is frozen returns exists_frozen with suggestion."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset({"plan.md"}),
    )
    assert err is not None
    assert err.code == "exists_frozen"
    assert err.suggested_name == "plan-remediation-1.md"


def test_validate_write_exists_draft():
    """Writing a filename that already exists as an editable draft returns exists_draft."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "exists_draft"


def test_validate_write_chain_gap():
    """Writing plan-remediation-2.md when plan-remediation-1.md is absent returns chain_gap."""
    err = validate_write(
        "plan-remediation-2.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset({"plan.md"}),
    )
    assert err is not None
    assert err.code == "chain_gap"


def test_validate_write_milestone_remediation_chain_gap():
    """Writing plan-milestone-1-remediation-2.md without the -1 predecessor returns chain_gap."""
    err = validate_write(
        "plan-milestone-1-remediation-2.md",
        phase="plan",
        requires_discriminator=True,
        existing_names=frozenset({"plan-milestone-1.md"}),
        frozen_names=frozenset({"plan-milestone-1.md"}),
    )
    assert err is not None
    assert err.code == "chain_gap"


def test_validate_write_milestones_wrong_phase():
    """milestones.md must be written in the milestone phase, not plan."""
    err = validate_write(
        "milestones.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "wrong_phase"


def test_validate_write_out_of_step_wrong_step():
    """Writing brief.md in intake phase but wrong step returns out_of_step."""
    err = validate_write(
        "brief.md",
        phase="intake",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
        step_name="Gather",  # legal phase, but brief is created in "Summarize"
    )
    assert err is not None
    assert err.code == "out_of_step"
    assert err.allowed  # self-correction hint must be non-empty


def test_validate_write_out_of_step_correct_step():
    """Writing brief.md in intake/Summarize (the legal step) returns None."""
    err = validate_write(
        "brief.md",
        phase="intake",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
        step_name="Summarize",
    )
    assert err is None


def test_validate_write_step_name_none_skips_step_check():
    """step_name=None skips the per-step check (fail-open back-compat)."""
    err = validate_write(
        "brief.md",
        phase="intake",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
        step_name=None,  # missing step metadata must not cause a false rejection
    )
    assert err is None


def test_validate_write_step_name_empty_skips_step_check():
    """step_name='' (empty string) also skips the per-step check (falsy)."""
    err = validate_write(
        "brief.md",
        phase="intake",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
        step_name="",
    )
    assert err is None


def test_validate_write_out_of_step_allowed_field_populated():
    """out_of_step error must include a non-empty allowed hint."""
    err = validate_write(
        "tech-plan.md",
        phase="tech-plan",
        requires_discriminator=False,
        existing_names=frozenset(),
        frozen_names=frozenset(),
        step_name="Analyze",  # tech-plan creates in Write, not Analyze
    )
    assert err is not None
    assert err.code == "out_of_step"
    assert err.allowed != ""
    assert "Write" in err.allowed  # hint must name the legal step


def test_validate_write_exists_draft_allowed_field():
    """exists_draft error includes the allowed hint directing to koan_artifact_edit."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "exists_draft"
    assert err.allowed != ""


def test_validate_write_exists_frozen_allowed_field():
    """exists_frozen error includes the allowed hint directing to use a successor."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset({"plan.md"}),
    )
    assert err is not None
    assert err.code == "exists_frozen"
    assert err.allowed != ""


# -- validate_edit ------------------------------------------------------------ #


def test_validate_edit_happy_path():
    """Editing an existing, unfrozen artifact succeeds."""
    err = validate_edit(
        "plan.md",
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset(),
    )
    assert err is None


def test_validate_edit_sidecar_always_allowed():
    """Editing a .review.md sidecar is always allowed (append path, no freeze check)."""
    err = validate_edit(
        "plan.review.md",
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is None


def test_validate_edit_sidecar_allowed_even_if_frozen():
    """Sidecar edit exempt from freeze check even when primary is in frozen_names."""
    err = validate_edit(
        "plan.review.md",
        existing_names=frozenset({"plan.review.md"}),
        frozen_names=frozenset({"plan.review.md"}),
    )
    assert err is None


def test_validate_edit_not_found():
    """Editing a non-existent artifact returns not_found."""
    err = validate_edit(
        "plan.md",
        existing_names=frozenset(),
        frozen_names=frozenset(),
    )
    assert err is not None
    assert err.code == "not_found"


def test_validate_edit_frozen():
    """Editing a frozen artifact returns frozen with a suggested remediation name."""
    err = validate_edit(
        "plan.md",
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset({"plan.md"}),
    )
    assert err is not None
    assert err.code == "frozen"
    assert err.suggested_name == "plan-remediation-1.md"


def test_validate_edit_frozen_milestone_plan():
    """Frozen plan-milestone-1.md suggests plan-milestone-1-remediation-1.md."""
    err = validate_edit(
        "plan-milestone-1.md",
        existing_names=frozenset({"plan-milestone-1.md"}),
        frozen_names=frozenset({"plan-milestone-1.md"}),
    )
    assert err is not None
    assert err.code == "frozen"
    assert err.suggested_name == "plan-milestone-1-remediation-1.md"


def test_validate_edit_frozen_allowed_field():
    """frozen error includes the allowed hint directing to write a successor."""
    err = validate_edit(
        "plan.md",
        existing_names=frozenset({"plan.md"}),
        frozen_names=frozenset({"plan.md"}),
    )
    assert err is not None
    assert err.code == "frozen"
    assert err.allowed != ""


def test_validate_edit_out_of_step_wrong_step():
    """Editing brief.md in intake but wrong step returns out_of_step."""
    err = validate_edit(
        "brief.md",
        existing_names=frozenset({"brief.md"}),
        frozen_names=frozenset(),
        phase="intake",
        step_name="Gather",  # brief is only editable in Summarize
    )
    assert err is not None
    assert err.code == "out_of_step"
    assert err.allowed != ""


def test_validate_edit_out_of_step_legal_step():
    """Editing brief.md in intake/Summarize (the legal step) returns None."""
    err = validate_edit(
        "brief.md",
        existing_names=frozenset({"brief.md"}),
        frozen_names=frozenset(),
        phase="intake",
        step_name="Summarize",
    )
    assert err is None


def test_validate_edit_out_of_step_milestones_legal_execute_assess():
    """Editing milestones.md in execute/Assess is legal per the catalog."""
    err = validate_edit(
        "milestones.md",
        existing_names=frozenset({"milestones.md"}),
        frozen_names=frozenset(),
        phase="execute",
        step_name="Assess",
    )
    assert err is None


def test_validate_edit_sidecar_exempt_from_step_gate():
    """Sidecar edits are exempt from per-step gating at any phase/step."""
    # Phase and step that would otherwise gate a primary artifact.
    err = validate_edit(
        "plan.review.md",
        existing_names=frozenset(),
        frozen_names=frozenset(),
        phase="intake",
        step_name="Gather",
    )
    assert err is None


def test_validate_edit_step_name_none_skips_step_check():
    """step_name=None skips the per-step edit check (fail-open back-compat)."""
    err = validate_edit(
        "brief.md",
        existing_names=frozenset({"brief.md"}),
        frozen_names=frozenset(),
        phase="execute",
        step_name=None,  # no step info -- must not cause a false rejection
    )
    assert err is None


# -- ArtifactRegistryEntry.origin_phases property ----------------------------- #


def test_origin_phases_derived_from_create_steps():
    """origin_phases is a @property derived from create_steps, not a stored field."""
    from koan.tools.artifact_registry import ArtifactRegistryEntry
    entry = ArtifactRegistryEntry(
        family="brief",
        create_steps=frozenset({("intake", "Summarize")}),
        edit_steps=frozenset({("intake", "Summarize")}),
        reviewer_prompt=None,
        takes_discriminator=False,
        takes_chain=False,
        on_write="create_no_review",
        on_edit="revise_draft",
    )
    assert entry.origin_phases == frozenset({"intake"})


def test_origin_phases_multi_step_plan():
    """plan family's origin_phases contains only the phases from create_steps."""
    entry = classify("plan")
    assert entry is not None
    assert entry.origin_phases == frozenset({"plan"})


# -- validate_execute_target -------------------------------------------------- #


def test_validate_execute_target_happy_path():
    """Executing an existing plan.md that has not been executed succeeds."""
    err = validate_execute_target(
        "plan.md",
        existing_names=frozenset({"plan.md"}),
        executed_names=frozenset(),
    )
    assert err is None


def test_validate_execute_target_milestone_plan_happy():
    """Executing plan-milestone-1.md that exists and was not yet executed succeeds."""
    err = validate_execute_target(
        "plan-milestone-1.md",
        existing_names=frozenset({"plan-milestone-1.md"}),
        executed_names=frozenset(),
    )
    assert err is None


def test_validate_execute_target_not_found_unrecognized():
    """Unrecognized filename returns execute_not_found."""
    err = validate_execute_target(
        "garbage.md",
        existing_names=frozenset(),
        executed_names=frozenset(),
    )
    assert err is not None
    assert err.code == "execute_not_found"


def test_validate_execute_target_not_found_missing():
    """A valid plan filename absent from existing_names returns execute_not_found."""
    err = validate_execute_target(
        "plan.md",
        existing_names=frozenset(),
        executed_names=frozenset(),
    )
    assert err is not None
    assert err.code == "execute_not_found"


def test_validate_execute_target_not_plan_milestones():
    """milestones.md exists but is not a plan; returns execute_not_plan."""
    err = validate_execute_target(
        "milestones.md",
        existing_names=frozenset({"milestones.md"}),
        executed_names=frozenset(),
    )
    assert err is not None
    assert err.code == "execute_not_plan"


def test_validate_execute_target_not_plan_tech_plan():
    """tech-plan.md is not a plan artifact; returns execute_not_plan."""
    err = validate_execute_target(
        "tech-plan.md",
        existing_names=frozenset({"tech-plan.md"}),
        executed_names=frozenset(),
    )
    assert err is not None
    assert err.code == "execute_not_plan"


def test_validate_execute_target_already_executed():
    """A plan that was already executed returns already_executed with remediation suggestion."""
    err = validate_execute_target(
        "plan.md",
        existing_names=frozenset({"plan.md"}),
        executed_names=frozenset({"plan.md"}),
    )
    assert err is not None
    assert err.code == "already_executed"
    assert err.suggested_name == "plan-remediation-1.md"


def test_validate_execute_target_already_executed_milestone():
    """Executed plan-milestone-1.md suggests plan-milestone-1-remediation-1.md."""
    err = validate_execute_target(
        "plan-milestone-1.md",
        existing_names=frozenset({"plan-milestone-1.md"}),
        executed_names=frozenset({"plan-milestone-1.md"}),
    )
    assert err is not None
    assert err.code == "already_executed"
    assert err.suggested_name == "plan-milestone-1-remediation-1.md"


# -- ARTIFACT_REGISTRY integrity ---------------------------------------------- #


def test_registry_has_five_families():
    """The registry contains exactly the five canonical families."""
    assert set(ARTIFACT_REGISTRY.keys()) == {
        "brief", "core-flows", "tech-plan", "milestones", "plan"
    }


def test_registry_origin_phases_use_m1_names():
    """Every origin_phases set uses only the final M1 phase name vocabulary."""
    legal = {"intake", "core-flows", "tech-plan", "milestone", "plan"}
    for family, entry in ARTIFACT_REGISTRY.items():
        assert entry.origin_phases <= legal, (
            f"Family {family!r} has unexpected origin_phases {entry.origin_phases}"
        )


def test_registry_on_write_values():
    """on_write is always one of the two defined values."""
    for family, entry in ARTIFACT_REGISTRY.items():
        assert entry.on_write in {"create_and_review", "create_no_review"}, (
            f"Unexpected on_write {entry.on_write!r} for {family!r}"
        )


def test_registry_on_edit_values():
    """on_edit is always one of the two defined values."""
    for family, entry in ARTIFACT_REGISTRY.items():
        assert entry.on_edit in {"revise_draft", "bookkeeping"}, (
            f"Unexpected on_edit {entry.on_edit!r} for {family!r}"
        )
