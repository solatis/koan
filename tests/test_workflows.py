# Tests for koan/lib/workflows.py -- workflow type system.

import pytest

from koan.lib.workflows import (
    CURATION_WORKFLOW,
    MILESTONES_WORKFLOW,
    PLAN_WORKFLOW,
    WORKFLOWS,
    PhaseBinding,
    Workflow,
    get_suggested_phases,
    get_workflow,
    is_valid_transition,
)


# -- get_workflow --------------------------------------------------------------

def test_get_workflow_valid_plan():
    wf = get_workflow("plan")
    assert wf.name == "plan"


def test_get_workflow_valid_milestones():
    wf = get_workflow("milestones")
    assert wf.name == "milestones"


def test_get_workflow_invalid_raises():
    with pytest.raises(ValueError, match="Unknown workflow"):
        get_workflow("nonexistent")


def test_get_workflow_lists_valid_in_error():
    with pytest.raises(ValueError, match="plan"):
        get_workflow("bogus")


# -- PhaseBinding and Workflow.get_module / get_binding ------------------------

def test_get_module_returns_module():
    mod = PLAN_WORKFLOW.get_module("intake")
    assert mod is not None
    assert hasattr(mod, "step_guidance")
    assert hasattr(mod, "TOTAL_STEPS")


def test_get_module_unknown_returns_none():
    assert PLAN_WORKFLOW.get_module("nonexistent") is None


def test_get_binding_returns_binding():
    b = PLAN_WORKFLOW.get_binding("intake")
    assert isinstance(b, PhaseBinding)
    assert b.module is not None
    assert len(b.description) > 0


def test_get_binding_unknown_returns_none():
    assert PLAN_WORKFLOW.get_binding("nonexistent") is None


def test_curation_workflow_initial_module_is_curation():
    """Regression: the orchestrator's initial phase module must match
    the workflow's initial_phase. The previous global-registry design
    hardcoded intake for all workflows, causing standalone curation
    to receive intake step guidance (Gather/Deepen) instead of
    curation step guidance (Inventory/Memorize)."""
    from koan.phases import curation
    mod = CURATION_WORKFLOW.get_module(CURATION_WORKFLOW.initial_phase)
    assert mod is curation


def test_plan_workflow_initial_module_is_intake():
    from koan.phases import intake
    mod = PLAN_WORKFLOW.get_module(PLAN_WORKFLOW.initial_phase)
    assert mod is intake


def test_same_module_different_guidance_across_workflows():
    """The same phase module (curation) serves two workflows with
    different guidance bindings: postmortem in plan, standalone in
    the curation workflow."""
    plan_b = PLAN_WORKFLOW.get_binding("curation")
    cur_b = CURATION_WORKFLOW.get_binding("curation")
    assert plan_b.module is cur_b.module  # same module
    assert plan_b.guidance != cur_b.guidance  # different guidance
    assert "postmortem" in plan_b.guidance
    assert "standalone" in cur_b.guidance


# -- Backward-compat property accessors ---------------------------------------

def test_available_phases_is_tuple():
    assert isinstance(PLAN_WORKFLOW.available_phases, tuple)
    assert "intake" in PLAN_WORKFLOW.available_phases
    assert "curation" in PLAN_WORKFLOW.available_phases


def test_phase_descriptions_is_dict():
    descs = PLAN_WORKFLOW.phase_descriptions
    assert isinstance(descs, dict)
    for phase in PLAN_WORKFLOW.available_phases:
        assert phase in descs
        assert len(descs[phase]) > 0


def test_phase_guidance_is_dict_non_empty_only():
    guidance = PLAN_WORKFLOW.phase_guidance
    assert isinstance(guidance, dict)
    # intake and execute have guidance; plan-spec and plan-review do not
    assert "intake" in guidance
    assert "execute" in guidance
    # plan-spec has no guidance (carries its own context)
    assert "plan-spec" not in guidance


# -- get_suggested_phases -----------------------------------------------------

def test_get_suggested_phases_intake():
    phases = get_suggested_phases(PLAN_WORKFLOW, "intake")
    assert "plan-spec" in phases
    assert "execute" in phases


def test_get_suggested_phases_plan_spec():
    phases = get_suggested_phases(PLAN_WORKFLOW, "plan-spec")
    assert "plan-review" in phases
    assert "execute" in phases


def test_get_suggested_phases_plan_review():
    phases = get_suggested_phases(PLAN_WORKFLOW, "plan-review")
    assert "plan-spec" in phases
    assert "execute" in phases


def test_get_suggested_phases_execute():
    phases = get_suggested_phases(PLAN_WORKFLOW, "execute")
    assert "plan-review" in phases


def test_get_suggested_phases_execute_includes_curation():
    phases = get_suggested_phases(PLAN_WORKFLOW, "execute")
    assert "curation" in phases


def test_get_suggested_phases_milestones_intake_empty():
    phases = get_suggested_phases(MILESTONES_WORKFLOW, "intake")
    assert phases == []


def test_get_suggested_phases_unknown_phase():
    phases = get_suggested_phases(PLAN_WORKFLOW, "nonexistent")
    assert phases == []


# -- is_valid_transition -------------------------------------------------------

def test_is_valid_transition_available_phase():
    assert is_valid_transition(PLAN_WORKFLOW, "intake", "plan-spec") is True


def test_is_valid_transition_self_blocked():
    assert is_valid_transition(PLAN_WORKFLOW, "intake", "intake") is False


def test_is_valid_transition_unavailable_phase():
    assert is_valid_transition(PLAN_WORKFLOW, "intake", "execution") is False


def test_is_valid_transition_any_to_any_within_workflow():
    """Any phase can transition to any other phase in the workflow (user-directed)."""
    phases = list(PLAN_WORKFLOW.available_phases)
    for from_p in phases:
        for to_p in phases:
            if from_p != to_p:
                assert is_valid_transition(PLAN_WORKFLOW, from_p, to_p) is True, \
                    f"{from_p} -> {to_p} should be valid"


def test_is_valid_transition_milestones_to_plan_spec_denied():
    assert is_valid_transition(MILESTONES_WORKFLOW, "intake", "plan-spec") is False


# -- PLAN_WORKFLOW structure ---------------------------------------------------

def test_plan_workflow_structure():
    wf = PLAN_WORKFLOW
    assert wf.name == "plan"
    assert "intake" in wf.available_phases
    assert "plan-spec" in wf.available_phases
    assert "plan-review" in wf.available_phases
    assert "execute" in wf.available_phases
    assert "curation" in wf.available_phases
    assert wf.initial_phase == "intake"


def test_plan_workflow_has_phase_descriptions():
    for phase in PLAN_WORKFLOW.available_phases:
        assert phase in PLAN_WORKFLOW.phase_descriptions
        assert len(PLAN_WORKFLOW.phase_descriptions[phase]) > 0


def test_plan_workflow_has_guidance_for_intake():
    assert "intake" in PLAN_WORKFLOW.phase_guidance
    assert len(PLAN_WORKFLOW.phase_guidance["intake"]) > 0


def test_plan_workflow_has_guidance_for_execute():
    assert "execute" in PLAN_WORKFLOW.phase_guidance
    assert len(PLAN_WORKFLOW.phase_guidance["execute"]) > 0


# -- MILESTONES_WORKFLOW structure ---------------------------------------------

def test_milestones_workflow_structure():
    wf = MILESTONES_WORKFLOW
    assert wf.name == "milestones"
    assert wf.available_phases == ("intake",)
    assert wf.initial_phase == "intake"
    assert wf.transitions == {"intake": []}


def test_milestones_workflow_has_intake_guidance():
    assert "intake" in MILESTONES_WORKFLOW.phase_guidance
    assert len(MILESTONES_WORKFLOW.phase_guidance["intake"]) > 0


# -- CURATION_WORKFLOW structure -----------------------------------------------

def test_curation_workflow_exists():
    assert "curation" in WORKFLOWS


def test_curation_workflow_structure():
    wf = CURATION_WORKFLOW
    assert wf.name == "curation"
    assert wf.initial_phase == "curation"
    assert "curation" in wf.available_phases


def test_curation_workflow_has_standalone_directive():
    guidance = CURATION_WORKFLOW.phase_guidance.get("curation", "")
    # Standalone directive defines the review/document/bootstrap pivot.
    assert "standalone curation" in guidance
    assert "Review" in guidance
    assert "Document" in guidance
    assert "Bootstrap" in guidance


def test_plan_workflow_curation_uses_postmortem_directive():
    guidance = PLAN_WORKFLOW.phase_guidance.get("curation", "")
    # Postmortem directive binds source to the in-context transcript and
    # forbids scout dispatch.
    assert "postmortem" in guidance
    assert "transcript" in guidance
    assert "koan_request_scouts" in guidance


# -- Workflow immutability -----------------------------------------------------

def test_workflow_frozen():
    """Workflow instances cannot have fields reassigned (frozen=True)."""
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        PLAN_WORKFLOW.name = "mutated"


def test_phase_binding_frozen():
    """PhaseBinding instances cannot have fields reassigned (frozen=True)."""
    b = PLAN_WORKFLOW.get_binding("intake")
    with pytest.raises(Exception):
        b.module = None


# -- WORKFLOWS registry -------------------------------------------------------

def test_workflows_registry_complete():
    assert "plan" in WORKFLOWS
    assert "milestones" in WORKFLOWS
    assert "curation" in WORKFLOWS


def test_workflows_registry_values_are_workflow_instances():
    for name, wf in WORKFLOWS.items():
        assert isinstance(wf, Workflow)
        assert wf.name == name
