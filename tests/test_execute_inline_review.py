# Tests for the M5 execute phase restructuring (koan/phases/execute.py).
#
# Covers:
#   (a) STEP_NAMES are Run/Verify/Reconcile; TOTAL_STEPS is 3.
#   (b) Step 1 (Run) guidance instructs launching koan_request_executor.
#   (c) Step 2 (Verify) guidance instructs bash verification + reading brief/plan/milestones.
#   (d) Step 3 (Reconcile) guidance instructs inline ## Execution N section,
#       milestones.md UPDATE on conforming path, and koan_request_executor re-run
#       or escalation on non-conforming path.
#   (e) "execute" is in _ORCHESTRATOR_BASH_PHASES; compose_toolset includes bash.
#   (f) Workflow transitions["execute"] do NOT contain "exec-review".
#   (g) Plan workflow execute -> curation only (no "plan"); initiative execute drops "tech-plan".
#
# Tests do not boot a runner or mock anything. They instantiate step_guidance()
# with minimal PhaseContext instances and assert key strings appear in the output.

import pytest

from koan.phases import PhaseContext


def _ctx() -> PhaseContext:
    """Minimal PhaseContext satisfying the constructor."""
    return PhaseContext(run_dir="", subagent_dir="")


def _ctx_with_next(next_phase, suggested_phases=None):
    """Build a PhaseContext with next_phase and suggested_phases populated."""
    return PhaseContext(
        run_dir="",
        subagent_dir="",
        next_phase=next_phase,
        suggested_phases=suggested_phases or [],
    )


# ---------------------------------------------------------------------------
# (a) Step names and step count
# ---------------------------------------------------------------------------

def test_execute_step_names_are_run_verify_reconcile():
    """STEP_NAMES must be {1: 'Run', 2: 'Verify', 3: 'Reconcile'} after M5."""
    from koan.phases import execute
    assert execute.STEP_NAMES == {1: "Run", 2: "Verify", 3: "Reconcile"}


def test_execute_total_steps_is_three():
    """execute.TOTAL_STEPS must be 3 after M5."""
    from koan.phases import execute
    assert execute.TOTAL_STEPS == 3


def test_execute_role_context_no_positive_sidecar_reference():
    """PHASE_ROLE_CONTEXT must not positively instruct writing .review.md sidecar.

    A prohibition mention ('Do NOT write a .review.md sidecar') is allowed.
    """
    from koan.phases import execute
    lines = [l for l in execute.PHASE_ROLE_CONTEXT.splitlines() if ".review.md" in l]
    for line in lines:
        assert "NOT" in line or "not" in line or "no" in line.lower(), (
            f"Unexpected positive .review.md reference: {line!r}"
        )


def test_execute_role_context_mentions_koan_request_executor():
    """PHASE_ROLE_CONTEXT must mention koan_request_executor as the launch tool."""
    from koan.phases import execute
    assert "koan_request_executor" in execute.PHASE_ROLE_CONTEXT


def test_execute_role_context_mentions_inline_reviewer():
    """PHASE_ROLE_CONTEXT must describe the inline reviewer / driver role."""
    from koan.phases import execute
    text = execute.PHASE_ROLE_CONTEXT.lower()
    assert "inline reviewer" in text or "execution driver" in text


# ---------------------------------------------------------------------------
# (b) Step 1 -- Run
# ---------------------------------------------------------------------------

def test_execute_step1_title_is_run():
    """Step 1 guidance title must be 'Run'."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    assert g.title == "Run"


def test_execute_step1_instructs_koan_request_executor():
    """Step 1 guidance must instruct calling koan_request_executor."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "koan_request_executor" in text


def test_execute_step1_identifies_plan():
    """Step 1 guidance must instruct identifying the plan artifact."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "plan" in text.lower()


def test_execute_step1_mentions_milestones_md():
    """Step 1 guidance must mention milestones.md for the milestones workflow."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "milestones.md" in text


def test_execute_step1_renders_phase_instructions_at_top():
    """Step 1 guidance must render phase_instructions before the body."""
    from koan.phases import execute
    ctx = PhaseContext(
        run_dir="",
        subagent_dir="",
        phase_instructions="## Custom guidance\nSome workflow context.",
    )
    g = execute.step_guidance(1, ctx)
    text = "\n".join(g.instructions)
    assert "## Custom guidance" in text
    assert text.index("## Custom guidance") < text.index("koan_request_executor")


def test_execute_step1_no_exec_review_reference():
    """Step 1 guidance must not reference exec-review."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "exec-review" not in text


def test_execute_step1_no_sidecar_reference():
    """Step 1 guidance must not reference .review.md sidecar."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert ".review.md" not in text


# ---------------------------------------------------------------------------
# (c) Step 2 -- Verify
# ---------------------------------------------------------------------------

def test_execute_step2_title_is_verify():
    """Step 2 guidance title must be 'Verify'."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    assert g.title == "Verify"


def test_execute_step2_reads_brief_md():
    """Step 2 guidance must instruct reading brief.md."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text


def test_execute_step2_instructs_bash_verification():
    """Step 2 guidance must instruct running bash verification commands."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "verification" in text.lower() or "verify" in text.lower()
    assert "bash" in text.lower() or "build" in text.lower() or "test" in text.lower()


def test_execute_step2_verification_is_authoritative():
    """Step 2 guidance must state that bash checks are authoritative."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "authoritative" in text.lower()


def test_execute_step2_ends_with_verification_summary_instruction():
    """Step 2 guidance must instruct ending with a verification summary."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "verification summary" in text.lower()


def test_execute_step2_reads_plan_artifact():
    """Step 2 guidance must instruct reading the plan artifact."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "plan" in text.lower()


def test_execute_step2_no_sidecar_reference():
    """Step 2 guidance must not reference .review.md sidecar."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert ".review.md" not in text


# ---------------------------------------------------------------------------
# (d) Step 3 -- Reconcile
# ---------------------------------------------------------------------------

def test_execute_step3_title_is_reconcile():
    """Step 3 guidance title must be 'Reconcile'."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    assert g.title == "Reconcile"


def test_execute_step3_records_inline_execution_section():
    """Step 3 guidance must instruct appending ## Execution N inline via koan_artifact_edit."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "## Execution" in text
    assert "koan_artifact_edit" in text


def test_execute_step3_no_sidecar_reference():
    """Step 3 guidance must not reference .review.md sidecar."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert ".review.md" not in text


def test_execute_step3_conforming_path_has_milestones_update():
    """Step 3 guidance must instruct the milestones.md UPDATE on the conforming path."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "milestones.md" in text
    assert "UPDATE" in text or "update" in text.lower()


def test_execute_step3_conforming_path_has_four_subsection_outcome():
    """Step 3 guidance must include all four Outcome subsection headings."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "Integration points created" in text
    assert "Patterns established" in text
    assert "Constraints discovered" in text
    assert "Deviations from plan" in text


def test_execute_step3_conforming_path_marks_done_and_advances_pending():
    """Step 3 guidance must instruct marking the milestone [done] and advancing [pending]."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "[done]" in text
    assert "[pending]" in text
    assert "[in-progress]" in text


def test_execute_step3_conforming_path_preserves_prior_outcomes():
    """Step 3 guidance must instruct preserving prior [done] Outcome sections."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "prior" in text.lower() and "[done]" in text


def test_execute_step3_nonconforming_instructs_re_run():
    """Step 3 non-conforming path must instruct calling koan_request_executor again."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "koan_request_executor" in text


def test_execute_step3_escalation_uses_koan_ask_question():
    """Step 3 must instruct escalation via koan_ask_question on repeated failure."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "koan_ask_question" in text


def test_execute_step3_escalation_options():
    """Step 3 escalation must offer accept-as-is, abort, and direct-further-attempts."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "accept-as-is" in text.lower() or "accept as-is" in text.lower()
    assert "abort" in text.lower()
    assert "further-attempts" in text.lower() or "further attempts" in text.lower()


def test_execute_step3_invoke_after_uses_terminal_invoke():
    """Step 3 invoke_after must use terminal_invoke (matching the phase boundary contract)."""
    from koan.phases import execute
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["plan", "curation"])
    g = execute.step_guidance(3, ctx)
    assert g.invoke_after == terminal_invoke(None, ["plan", "curation"])


def test_execute_step3_no_exec_review_reference():
    """Step 3 guidance must not reference exec-review."""
    from koan.phases import execute
    g = execute.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "exec-review" not in text


# ---------------------------------------------------------------------------
# (e) Tool policy: bash available in execute phase for orchestrator
# ---------------------------------------------------------------------------

def test_execute_in_orchestrator_bash_phases():
    """'execute' must be in _ORCHESTRATOR_BASH_PHASES after M5."""
    from koan.tools.tool_policy import _ORCHESTRATOR_BASH_PHASES
    assert "execute" in _ORCHESTRATOR_BASH_PHASES


def test_compose_toolset_orchestrator_execute_includes_bash():
    """compose_toolset for orchestrator must include bash (static role-based toolset)."""
    from koan.tools.tool_policy import build_tool_policy, compose_toolset
    policy = build_tool_policy()
    tools = compose_toolset(policy, "orchestrator")
    assert "bash" in tools


def test_compose_toolset_orchestrator_execute_includes_koan_request_executor():
    """compose_toolset for orchestrator must include koan_request_executor (static role-based toolset)."""
    from koan.tools.tool_policy import build_tool_policy, compose_toolset
    policy = build_tool_policy()
    tools = compose_toolset(policy, "orchestrator")
    assert "koan_request_executor" in tools


# ---------------------------------------------------------------------------
# (f) Workflow transitions: exec-review absent from execute transitions
# ---------------------------------------------------------------------------

def test_plan_workflow_execute_transitions_no_exec_review():
    """PLAN_WORKFLOW.transitions['execute'] must not contain 'exec-review'."""
    from koan.lib.workflows import PLAN_WORKFLOW
    assert "exec-review" not in PLAN_WORKFLOW.transitions["execute"]


def test_milestones_workflow_execute_transitions_no_exec_review():
    """MILESTONES_WORKFLOW.transitions['execute'] must not contain 'exec-review'."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    assert "exec-review" not in MILESTONES_WORKFLOW.transitions["execute"]


def test_initiative_workflow_execute_transitions_no_exec_review():
    """INITIATIVE_WORKFLOW.transitions['execute'] must not contain 'exec-review'."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    assert "exec-review" not in INITIATIVE_WORKFLOW.transitions["execute"]


# ---------------------------------------------------------------------------
# (g) M5 transition changes
# ---------------------------------------------------------------------------

def test_plan_workflow_execute_transitions_curation_only():
    """M5: PLAN_WORKFLOW.transitions['execute'] is ['curation'] only (dropped 'plan')."""
    from koan.lib.workflows import PLAN_WORKFLOW
    t = PLAN_WORKFLOW.transitions["execute"]
    assert t == ["curation"]


def test_milestones_workflow_execute_transitions_order():
    """MILESTONES_WORKFLOW.transitions['execute'] lists plan first then curation; milestone removed."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    t = MILESTONES_WORKFLOW.transitions["execute"]
    assert t[0] == "plan"
    assert "curation" in t
    assert "milestone" not in t


def test_initiative_workflow_execute_transitions_no_tech_plan():
    """M5: INITIATIVE_WORKFLOW.transitions['execute'] must NOT include tech-plan."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    assert "tech-plan" not in INITIATIVE_WORKFLOW.transitions["execute"]


def test_initiative_workflow_execute_transitions_has_plan_and_curation():
    """INITIATIVE_WORKFLOW.transitions['execute'] must include plan and curation."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    t = INITIATIVE_WORKFLOW.transitions["execute"]
    assert "plan" in t
    assert "curation" in t


def test_plan_workflow_execute_transitions_includes_curation():
    """PLAN_WORKFLOW.transitions['execute'] must include curation (conforming path)."""
    from koan.lib.workflows import PLAN_WORKFLOW
    assert "curation" in PLAN_WORKFLOW.transitions["execute"]


# ---------------------------------------------------------------------------
# Workflow guidance: brief.md still present (regression guard)
# ---------------------------------------------------------------------------

def test_plan_workflow_execute_guidance_mentions_brief_md():
    """PLAN_WORKFLOW execute guidance must still mention brief.md after M5."""
    from koan.lib.workflows import PLAN_WORKFLOW
    guidance = PLAN_WORKFLOW.phases["execute"].guidance
    assert "brief.md" in guidance


def test_milestones_workflow_execute_guidance_mentions_brief_md():
    """MILESTONES_WORKFLOW execute guidance must still mention brief.md after M5."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    guidance = MILESTONES_WORKFLOW.phases["execute"].guidance
    assert "brief.md" in guidance


def test_initiative_workflow_execute_guidance_mentions_brief_md():
    """INITIATIVE_WORKFLOW execute guidance must still mention brief.md after M5."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    guidance = INITIATIVE_WORKFLOW.phases["execute"].guidance
    assert "brief.md" in guidance


def test_milestones_execute_guidance_mentions_milestones_md_update():
    """_MILESTONES_EXECUTE_GUIDANCE must mention the milestones.md UPDATE (gating hook)."""
    from koan.lib.workflows import _MILESTONES_EXECUTE_GUIDANCE
    assert "milestones.md" in _MILESTONES_EXECUTE_GUIDANCE
    assert "UPDATE" in _MILESTONES_EXECUTE_GUIDANCE or "update" in _MILESTONES_EXECUTE_GUIDANCE.lower()


def test_milestones_execute_guidance_no_exec_review():
    """_MILESTONES_EXECUTE_GUIDANCE must not reference exec-review."""
    from koan.lib.workflows import _MILESTONES_EXECUTE_GUIDANCE
    assert "exec-review" not in _MILESTONES_EXECUTE_GUIDANCE


def test_initiative_execute_guidance_no_exec_review():
    """_INITIATIVE_EXECUTE_GUIDANCE must not reference exec-review."""
    from koan.lib.workflows import _INITIATIVE_EXECUTE_GUIDANCE
    assert "exec-review" not in _INITIATIVE_EXECUTE_GUIDANCE


def test_plan_workflow_execute_guidance_no_exec_review():
    """PLAN_WORKFLOW execute phase guidance must not reference exec-review."""
    from koan.lib.workflows import PLAN_WORKFLOW
    guidance = PLAN_WORKFLOW.phases["execute"].guidance
    assert "exec-review" not in guidance


def test_execute_guidance_no_set_phase_plan_file_wording():
    """No execute guidance string should use koan_set_phase with plan_file (M5: pure routing).

    koan_request_executor(plan_file=...) is correct usage and may appear.
    Only the old koan_set_phase("execute", plan_file=...) pattern is stale.
    """
    from koan.lib.workflows import (
        INITIATIVE_WORKFLOW,
        MILESTONES_WORKFLOW,
        PLAN_WORKFLOW,
        _INITIATIVE_EXECUTE_GUIDANCE,
        _MILESTONES_EXECUTE_GUIDANCE,
    )
    for guidance in [
        _MILESTONES_EXECUTE_GUIDANCE,
        _INITIATIVE_EXECUTE_GUIDANCE,
        PLAN_WORKFLOW.phases["execute"].guidance,
        MILESTONES_WORKFLOW.phases["execute"].guidance,
        INITIATIVE_WORKFLOW.phases["execute"].guidance,
    ]:
        # The old pattern was: koan_set_phase('execute', plan_file=...) or
        # koan_set_phase("execute", plan_file=...). That pattern is gone.
        assert "set_phase" not in guidance or "plan_file" not in guidance, (
            f"Found koan_set_phase with plan_file in guidance: {guidance[:150]!r}"
        )
