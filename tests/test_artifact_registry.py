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
    parse_artifact_filename,
    reviewer_for,
    validate_edit,
    validate_executor_request,
    validate_write,
)


# -- parse_artifact_filename -------------------------------------------------- #


def test_parse_brief():
    """brief.md decodes to the brief family with no discriminator."""
    assert parse_artifact_filename("brief.md") == ArtifactCoordinate("brief", None)


def test_parse_core_flows():
    """core-flows.md decodes to core-flows family."""
    assert parse_artifact_filename("core-flows.md") == ArtifactCoordinate("core-flows", None)


def test_parse_tech_plan():
    """tech-plan.md decodes to tech-plan, not accidentally matched by the plan branch."""
    assert parse_artifact_filename("tech-plan.md") == ArtifactCoordinate("tech-plan", None)


def test_parse_milestones():
    """milestones.md decodes to the milestones family."""
    assert parse_artifact_filename("milestones.md") == ArtifactCoordinate("milestones", None)


def test_parse_plan_bare():
    """plan.md decodes to the plan family with no discriminator."""
    assert parse_artifact_filename("plan.md") == ArtifactCoordinate("plan", None)


def test_parse_plan_milestone():
    """plan-milestone-N.md decodes with the correct discriminator."""
    assert parse_artifact_filename("plan-milestone-3.md") == ArtifactCoordinate("plan", 3)


def test_parse_plan_milestone_large_n():
    """plan-milestone-12.md correctly parses a multi-digit discriminator."""
    assert parse_artifact_filename("plan-milestone-12.md") == ArtifactCoordinate("plan", 12)


def test_parse_plan_remediation_returns_none():
    """M6: plan-remediation-K.md is no longer a recognized grammar form."""
    assert parse_artifact_filename("plan-remediation-1.md") is None


def test_parse_plan_milestone_remediation_returns_none():
    """M6: plan-milestone-N-remediation-K.md is no longer a recognized grammar form."""
    assert parse_artifact_filename("plan-milestone-2-remediation-1.md") is None


def test_parse_review_sidecar_returns_none():
    """plan.review.md is a koan-owned sidecar; the parser returns None."""
    assert parse_artifact_filename("plan.review.md") is None


def test_parse_milestone_review_sidecar_returns_none():
    """plan-milestone-1.review.md is also a sidecar; returns None."""
    assert parse_artifact_filename("plan-milestone-1.review.md") is None


def test_parse_zero_discriminator_returns_none():
    """plan-milestone-0.md has a zero index -- rejected (must be positive)."""
    assert parse_artifact_filename("plan-milestone-0.md") is None


def test_parse_leading_zero_discriminator_returns_none():
    """plan-milestone-01.md has a leading-zero discriminator -- rejected."""
    assert parse_artifact_filename("plan-milestone-01.md") is None


def test_parse_arbitrary_filename_returns_none():
    """An unrecognized filename returns None."""
    assert parse_artifact_filename("random-file.md") is None


def test_parse_empty_string_returns_none():
    """An empty string is not a valid artifact filename."""
    assert parse_artifact_filename("") is None


def test_parse_no_extension_returns_none():
    """plan without .md extension is not recognized."""
    assert parse_artifact_filename("plan") is None


# -- classify / reviewer_for -------------------------------------------------- #


def test_classify_brief_entry():
    """classify returns the brief registry entry."""
    entry = classify("brief")
    assert entry is not None
    assert entry.reviewer_prompt is None
    assert entry.on_write == "create_no_review"


def test_classify_plan_entry():
    """classify returns the plan entry with PLAN_REVIEWER and discriminator support."""
    entry = classify("plan")
    assert entry is not None
    assert entry.reviewer_prompt == "PLAN_REVIEWER"
    assert entry.takes_discriminator is True


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


# -- validate_write ----------------------------------------------------------- #


def test_validate_write_happy_path_bare_plan():
    """Writing plan.md in the plan phase with no discriminator required succeeds."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),

    )
    assert err is None


def test_validate_write_happy_path_milestone_plan():
    """Writing plan-milestone-1.md in plan phase with requires_discriminator=True succeeds."""
    err = validate_write(
        "plan-milestone-1.md",
        phase="plan",
        requires_discriminator=True,
        existing_names=frozenset(),

    )
    assert err is None


def test_validate_write_happy_path_brief():
    """Writing brief.md in the intake phase succeeds."""
    err = validate_write(
        "brief.md",
        phase="intake",
        requires_discriminator=False,
        existing_names=frozenset(),

    )
    assert err is None


def test_validate_write_sidecar_rejected():
    """Attempting to write a .review.md name returns name_malformed.

    plan.review.md does not match parse_artifact_filename, so the normal
    grammar check returns name_malformed without any special sidecar logic.
    """
    err = validate_write(
        "plan.review.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),

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

    )
    assert err is not None
    assert err.code == "wrong_phase"
    assert err.suggested_name == "plan.md"


def test_validate_write_exists_draft():
    """Writing a filename that already exists as an editable draft returns exists_draft."""
    err = validate_write(
        "plan.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset({"plan.md"}),

    )
    assert err is not None
    assert err.code == "exists_draft"


def test_validate_write_milestones_wrong_phase():
    """milestones.md must be written in the milestone phase, not plan."""
    err = validate_write(
        "milestones.md",
        phase="plan",
        requires_discriminator=False,
        existing_names=frozenset(),

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

    )
    assert err is not None
    assert err.code == "exists_draft"
    assert err.allowed != ""


# -- validate_edit ------------------------------------------------------------ #


def test_validate_edit_happy_path():
    """Editing an existing, unfrozen artifact succeeds."""
    err = validate_edit(
        "plan.md",
        existing_names=frozenset({"plan.md"}),

    )
    assert err is None


def test_validate_edit_not_found():
    """Editing a non-existent artifact returns not_found."""
    err = validate_edit(
        "plan.md",
        existing_names=frozenset(),

    )
    assert err is not None
    assert err.code == "not_found"


def test_validate_edit_out_of_step_wrong_step():
    """Editing brief.md in intake but wrong step returns out_of_step."""
    err = validate_edit(
        "brief.md",
        existing_names=frozenset({"brief.md"}),

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

        phase="intake",
        step_name="Summarize",
    )
    assert err is None


def test_validate_edit_out_of_step_milestones_legal_execute_assess():
    """Editing milestones.md in execute/Assess is legal per the catalog."""
    err = validate_edit(
        "milestones.md",
        existing_names=frozenset({"milestones.md"}),

        phase="execute",
        step_name="Assess",
    )
    assert err is None


def test_validate_edit_step_name_none_skips_step_check():
    """step_name=None skips the per-step edit check (fail-open back-compat)."""
    err = validate_edit(
        "brief.md",
        existing_names=frozenset({"brief.md"}),

        phase="execute",
        step_name=None,  # no step info -- must not cause a false rejection
    )
    assert err is None


def test_validate_edit_living_doc_exempt_from_step_gate():
    """M2: living-doc families (plan, milestones) are editable from any phase/step."""
    # milestones.md is a living document: editable from any phase.
    err = validate_edit(
        "milestones.md",
        existing_names=frozenset({"milestones.md"}),

        phase="plan",
        step_name="Analyze",  # not in milestones edit_steps catalog
    )
    assert err is None

    # plan-milestone-1.md is a living document: editable from any phase.
    err = validate_edit(
        "plan-milestone-1.md",
        existing_names=frozenset({"plan-milestone-1.md"}),

        phase="exec-review",
        step_name="Verify",  # not in plan edit_steps catalog
    )
    assert err is None


def test_validate_edit_non_living_doc_still_gated():
    """M2: non-living-doc families (brief, core-flows, tech-plan) remain per-step gated."""
    err = validate_edit(
        "brief.md",
        existing_names=frozenset({"brief.md"}),

        phase="plan",
        step_name="Analyze",  # brief is only editable in intake/Summarize
    )
    assert err is not None
    assert err.code == "out_of_step"


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
        on_write="create_no_review",
        on_edit="revise_draft",
    )
    assert entry.origin_phases == frozenset({"intake"})


def test_origin_phases_multi_step_plan():
    """plan family's origin_phases contains only the phases from create_steps."""
    entry = classify("plan")
    assert entry is not None
    assert entry.origin_phases == frozenset({"plan"})


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


# -- validate_executor_request ------------------------------------------------ #


def test_validate_executor_request_no_args_returns_requires_instructions():
    """Neither plan_file nor instructions -> execute_requires_instructions."""
    err = validate_executor_request(None, None, existing_names=frozenset())
    assert err is not None
    assert err.code == "execute_requires_instructions"


def test_validate_executor_request_blank_instructions_returns_requires_instructions():
    """Whitespace-only instructions are treated as absent."""
    err = validate_executor_request(None, "   ", existing_names=frozenset())
    assert err is not None
    assert err.code == "execute_requires_instructions"


def test_validate_executor_request_instructions_only_succeeds():
    """Free-form instructions with no plan_file succeeds."""
    err = validate_executor_request(None, "Fix the tests.", existing_names=frozenset())
    assert err is None


def test_validate_executor_request_nonexistent_plan_file_returns_not_found():
    """plan_file not in existing_names returns execute_not_found."""
    err = validate_executor_request(
        "plan.md", None, existing_names=frozenset()
    )
    assert err is not None
    assert err.code == "execute_not_found"


def test_validate_executor_request_non_plan_family_returns_not_plan():
    """plan_file naming a non-plan family (e.g. tech-plan.md) returns execute_not_plan."""
    err = validate_executor_request(
        "tech-plan.md", None, existing_names=frozenset({"tech-plan.md"})
    )
    assert err is not None
    assert err.code == "execute_not_plan"


def test_validate_executor_request_valid_plan_succeeds():
    """Valid existing plan artifact returns None."""
    err = validate_executor_request(
        "plan-milestone-1.md", None, existing_names=frozenset({"plan-milestone-1.md"})
    )
    assert err is None


def test_validate_executor_request_no_already_executed_check():
    """Re-running the same plan does not return already_executed -- re-execution is the feature."""
    # Even if the plan were in an "executed" set, validate_executor_request
    # has no such concept; passing the same plan twice in sequence must succeed.
    for _ in range(2):
        err = validate_executor_request(
            "plan.md", None, existing_names=frozenset({"plan.md"})
        )
        assert err is None, "Re-execution must not be blocked"
