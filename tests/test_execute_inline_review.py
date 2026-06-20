# Tests for the M5 inline conformance review and remediation rework of the
# execute phase (koan/phases/execute.py).
#
# Covers:
#   (a) Step 1 guidance instructs verification + reading brief/plan/milestones.
#   (b) Step 2 clean-path guidance instructs milestones.md UPDATE with the
#       four-subsection Outcome structure.
#   (c) Step 2 non-conforming guidance instructs writing -remediation-1.md for
#       a base plan and escalating (koan_ask_question) for an already-remediation.
#   (d) "execute" is in _ORCHESTRATOR_BASH_PHASES; compose_toolset includes bash.
#   (e) All three workflow transitions["execute"] do NOT contain "exec-review".
#   (f) STEP_NAMES are Verify/Assess; no exec-review or koan_request_executor
#       references in execute.py text.
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
# (f) Step names and forbidden references
# ---------------------------------------------------------------------------

def test_execute_step_names_are_verify_and_assess():
    """STEP_NAMES must be {1: 'Verify', 2: 'Assess'} after M5."""
    from koan.phases import execute
    assert execute.STEP_NAMES == {1: "Verify", 2: "Assess"}


def test_execute_total_steps_is_two():
    """execute.TOTAL_STEPS must still be 2 after M5."""
    from koan.phases import execute
    assert execute.TOTAL_STEPS == 2


def test_execute_role_context_no_exec_review():
    """PHASE_ROLE_CONTEXT must not positively instruct advancing to exec-review.

    A prohibition mention ('do NOT advance to exec-review') is allowed.
    """
    from koan.phases import execute
    # Any line mentioning exec-review must be in a prohibition context.
    lines = [l for l in execute.PHASE_ROLE_CONTEXT.splitlines() if "exec-review" in l]
    for line in lines:
        assert "NOT" in line or "not" in line or "absorbs" in line, (
            f"Unexpected positive exec-review reference: {line!r}"
        )


def test_execute_role_context_no_koan_request_executor():
    """PHASE_ROLE_CONTEXT must not positively instruct calling koan_request_executor.

    It is allowed to appear in a 'do NOT call' prohibition sentence.
    """
    from koan.phases import execute
    # The prohibition "do NOT call koan_request_executor" may appear; a bare
    # positive instruction must not.
    text = execute.PHASE_ROLE_CONTEXT
    lines = [l for l in text.splitlines() if "koan_request_executor" in l]
    for line in lines:
        assert "NOT" in line or "not" in line or "no longer" in line, (
            f"Unexpected positive koan_request_executor reference: {line!r}"
        )


def test_execute_role_context_mentions_inline_reviewer():
    """PHASE_ROLE_CONTEXT must describe the inline reviewer role."""
    from koan.phases import execute
    assert "INLINE REVIEWER" in execute.PHASE_ROLE_CONTEXT or "inline reviewer" in execute.PHASE_ROLE_CONTEXT.lower()


# ---------------------------------------------------------------------------
# (a) Step 1 -- Verify
# ---------------------------------------------------------------------------

def test_execute_step1_title_is_verify():
    """Step 1 guidance title must be 'Verify'."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    assert g.title == "Verify"


def test_execute_step1_reads_brief_md():
    """Step 1 guidance must instruct reading brief.md."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text


def test_execute_step1_reads_executed_plan():
    """Step 1 guidance must instruct reading the executed plan artifact."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    # Must mention reading the plan; specific filenames vary by workflow.
    assert "plan" in text.lower()
    assert "plan_file" in text or "plan artifact" in text.lower()


def test_execute_step1_reads_milestones_md():
    """Step 1 guidance must mention milestones.md for the milestones workflow."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "milestones.md" in text


def test_execute_step1_instructs_bash_verification():
    """Step 1 guidance must instruct running bash verification commands."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "verification" in text.lower() or "verify" in text.lower()
    assert "bash" in text.lower() or "build" in text.lower() or "test" in text.lower()


def test_execute_step1_ends_with_verification_summary_instruction():
    """Step 1 guidance must instruct ending with a verification summary."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "verification summary" in text.lower() or "End your turn with" in text


def test_execute_step1_no_exec_review_reference():
    """Step 1 guidance must not reference exec-review."""
    from koan.phases import execute
    g = execute.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "exec-review" not in text


def test_execute_step1_renders_phase_instructions_at_top():
    """Step 1 guidance must render phase_instructions before the context artifact reads."""
    from koan.phases import execute
    ctx = PhaseContext(
        run_dir="",
        subagent_dir="",
        phase_instructions="## Custom guidance\nSome workflow context.",
    )
    g = execute.step_guidance(1, ctx)
    text = "\n".join(g.instructions)
    # phase_instructions must appear before "brief.md"
    assert "## Custom guidance" in text
    assert text.index("## Custom guidance") < text.index("brief.md")


# ---------------------------------------------------------------------------
# (b) Step 2 -- Assess: CLEAN path
# ---------------------------------------------------------------------------

def test_execute_step2_title_is_assess():
    """Step 2 guidance title must be 'Assess'."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    assert g.title == "Assess"


def test_execute_step2_appends_execution_review_section_to_sidecar():
    """Step 2 guidance must instruct appending '## Execution review (post-exec)' via koan_artifact_edit."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "Execution review (post-exec)" in text
    assert "koan_artifact_edit" in text
    assert ".review.md" in text


def test_execute_step2_sidecar_is_freeze_exempt():
    """Step 2 guidance must note the sidecar is freeze-exempt."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "freeze-exempt" in text or "freeze exempt" in text


def test_execute_step2_clean_path_has_milestones_update():
    """Step 2 guidance must instruct the milestones.md UPDATE on the clean path."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "milestones.md" in text
    assert "UPDATE" in text or "update" in text.lower()


def test_execute_step2_clean_path_has_four_subsection_outcome():
    """Step 2 guidance must include all four Outcome subsection headings."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "Integration points created" in text
    assert "Patterns established" in text
    assert "Constraints discovered" in text
    assert "Deviations from plan" in text


def test_execute_step2_clean_path_marks_done_and_advances_pending():
    """Step 2 guidance must instruct marking the milestone [done] and advancing [pending]."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "[done]" in text
    assert "[pending]" in text
    assert "[in-progress]" in text


def test_execute_step2_clean_path_preserves_prior_outcomes():
    """Step 2 guidance must instruct preserving prior [done] Outcome sections."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "prior" in text.lower() and "[done]" in text


# ---------------------------------------------------------------------------
# (c) Step 2 -- Assess: NON-CONFORMING path
# ---------------------------------------------------------------------------

def test_execute_step2_nonconforming_base_plan_instructs_remediation_write():
    """Step 2 non-conforming guidance must instruct writing -remediation-1.md for a base plan."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "-remediation-1.md" in text or "remediation-1.md" in text


def test_execute_step2_nonconforming_base_plan_instructs_set_phase_plan():
    """Step 2 non-conforming guidance must instruct koan_set_phase('plan') to return to planning."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert 'koan_set_phase("plan")' in text or "koan_set_phase('plan')" in text


def test_execute_step2_nonconforming_base_plan_folds_failure_signal():
    """Step 2 guidance must instruct folding the failure signal (deviation report + verification) into the remediation plan."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "deviation report" in text.lower() or "failure signal" in text.lower()
    assert "verification" in text.lower()


def test_execute_step2_nonconforming_base_plan_fires_plan_reviewer():
    """Step 2 guidance must note that writing the remediation fires the PLAN_REVIEWER."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "PLAN_REVIEWER" in text


def test_execute_step2_nonconforming_already_remediation_escalates():
    """Step 2 guidance must instruct escalation via koan_ask_question when already a remediation."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "koan_ask_question" in text
    assert "remediation" in text.lower()


def test_execute_step2_nonconforming_escalation_options():
    """Step 2 escalation must offer accept-as-is, abort, and direct-further-attempts."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "accept-as-is" in text.lower() or "accept as-is" in text.lower()
    assert "abort" in text.lower()
    assert "further-attempts" in text.lower() or "further attempts" in text.lower()


def test_execute_step2_accept_as_is_appends_to_sidecar():
    """Step 2 accept-as-is path must instruct appending ACCEPTED AS-IS to the sidecar."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "ACCEPTED AS-IS" in text


def test_execute_step2_invoke_after_uses_terminal_invoke():
    """Step 2 invoke_after must use terminal_invoke (matching the phase boundary contract)."""
    from koan.phases import execute
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["plan", "curation", "milestone"])
    g = execute.step_guidance(2, ctx)
    assert g.invoke_after == terminal_invoke(None, ["plan", "curation", "milestone"])


def test_execute_step2_no_exec_review_reference():
    """Step 2 guidance must not reference exec-review."""
    from koan.phases import execute
    g = execute.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "exec-review" not in text


# ---------------------------------------------------------------------------
# (d) Tool policy: bash available in execute phase for orchestrator
# ---------------------------------------------------------------------------

def test_execute_in_orchestrator_bash_phases():
    """'execute' must be in _ORCHESTRATOR_BASH_PHASES after M5."""
    from koan.tools.tool_policy import _ORCHESTRATOR_BASH_PHASES
    assert "execute" in _ORCHESTRATOR_BASH_PHASES


def test_compose_toolset_orchestrator_execute_includes_bash():
    """compose_toolset for (orchestrator, execute) must include bash."""
    from koan.tools.tool_policy import build_tool_policy, compose_toolset
    policy = build_tool_policy()
    tools = compose_toolset(policy, "orchestrator", "execute")
    assert "bash" in tools


# ---------------------------------------------------------------------------
# (e) Workflow transitions: exec-review absent from execute transitions
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


def test_milestones_workflow_execute_transitions_order():
    """MILESTONES_WORKFLOW.transitions['execute'] must list plan first, then curation, then milestone."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    t = MILESTONES_WORKFLOW.transitions["execute"]
    assert t[0] == "plan"
    assert "curation" in t
    assert "milestone" in t


def test_initiative_workflow_execute_transitions_includes_tech_plan():
    """INITIATIVE_WORKFLOW.transitions['execute'] must include tech-plan for architectural lookbacks."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    assert "tech-plan" in INITIATIVE_WORKFLOW.transitions["execute"]


def test_plan_workflow_execute_transitions_includes_curation():
    """PLAN_WORKFLOW.transitions['execute'] must include curation (clean path)."""
    from koan.lib.workflows import PLAN_WORKFLOW
    assert "curation" in PLAN_WORKFLOW.transitions["execute"]


# ---------------------------------------------------------------------------
# Workflow guidance: brief.md still present (guards against regression)
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
