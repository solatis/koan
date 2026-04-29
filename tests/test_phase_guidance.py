# Static-text assertions verifying that each phase module's step-1 guidance
# includes the "Read brief.md" directive introduced in Milestone 2.
#
# These tests do not boot a runner or mock anything. They instantiate
# step_guidance() with a minimal PhaseContext and assert that key strings
# appear in the joined instruction text. End-to-end behavior (does the LLM
# follow the prompt) is an evals-harness concern.

import pytest

from koan.phases import PhaseContext


# Minimal context that satisfies the PhaseContext constructor.
# run_dir and subagent_dir are the only non-default required fields.
def _ctx() -> PhaseContext:
    return PhaseContext(run_dir="", subagent_dir="")


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------

def test_intake_step3_writes_brief_md():
    from koan.phases import intake
    g = intake.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "koan_artifact_write" in text
    assert 'status="Final"' in text
    # All seven section headings must appear
    assert "Initiative" in text
    assert "Scope" in text
    assert "Affected subsystems" in text
    assert "Decisions" in text
    assert "Constraints" in text
    assert "Assumptions" in text
    assert "Open questions" in text


def test_intake_role_context_mentions_brief_md():
    from koan.phases import intake
    assert "brief.md" in intake.PHASE_ROLE_CONTEXT


# ---------------------------------------------------------------------------
# milestone_spec
# ---------------------------------------------------------------------------

def test_milestone_spec_step1_reads_brief_md():
    from koan.phases import milestone_spec
    g = milestone_spec.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "Read initiative context" in text


# ---------------------------------------------------------------------------
# milestone_review
# ---------------------------------------------------------------------------

def test_milestone_review_step1_reads_brief_md():
    from koan.phases import milestone_review
    g = milestone_review.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "Read initiative context" in text


# ---------------------------------------------------------------------------
# plan_spec
# ---------------------------------------------------------------------------

def test_plan_spec_step1_reads_brief_md():
    from koan.phases import plan_spec
    g = plan_spec.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "Read initiative context" in text


# ---------------------------------------------------------------------------
# plan_review
# ---------------------------------------------------------------------------

def test_plan_review_step1_reads_brief_md():
    from koan.phases import plan_review
    g = plan_review.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "Read initiative context" in text


# ---------------------------------------------------------------------------
# exec_review
# ---------------------------------------------------------------------------

def test_exec_review_step1_reads_brief_md():
    from koan.phases import exec_review
    g = exec_review.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "Read initiative context" in text


# ---------------------------------------------------------------------------
# curation
# ---------------------------------------------------------------------------

def test_curation_step1_reads_brief_md_conditionally():
    from koan.phases import curation
    g = curation.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    # The "if present" qualifier distinguishes curation from the unconditional
    # reads in the other five downstream phase modules.
    assert "if present" in text.lower() or "exists" in text.lower()


# ---------------------------------------------------------------------------
# workflow execute guidance
# ---------------------------------------------------------------------------

def test_plan_workflow_execute_guidance_includes_brief_md():
    from koan.lib.workflows import PLAN_WORKFLOW
    guidance = PLAN_WORKFLOW.phases["execute"].guidance
    assert "brief.md" in guidance


def test_milestones_workflow_execute_guidance_includes_brief_md():
    from koan.lib.workflows import MILESTONES_WORKFLOW
    guidance = MILESTONES_WORKFLOW.phases["execute"].guidance
    assert "brief.md" in guidance


# ---------------------------------------------------------------------------
# M3: PhaseBinding.next_phase field
# ---------------------------------------------------------------------------

def test_phasebinding_has_next_phase_field_default_none():
    from koan.lib.workflows import PhaseBinding
    from koan.phases import intake
    b = PhaseBinding(module=intake)
    assert b.next_phase is None


def test_phasebinding_next_phase_can_be_set():
    from koan.lib.workflows import PhaseBinding
    from koan.phases import intake
    b = PhaseBinding(module=intake, next_phase="plan-spec")
    assert b.next_phase == "plan-spec"


def test_plan_workflow_next_phase_defaults():
    from koan.lib.workflows import PLAN_WORKFLOW
    expected = {
        "intake":       "plan-spec",
        "plan-spec":    "plan-review",
        "plan-review":  None,
        "execute":      "exec-review",
        "exec-review":  None,
        "curation":     None,
    }
    for phase_name, expected_next in expected.items():
        binding = PLAN_WORKFLOW.phases[phase_name]
        assert binding.next_phase == expected_next, (
            f"PLAN_WORKFLOW[{phase_name!r}].next_phase: "
            f"expected {expected_next!r}, got {binding.next_phase!r}"
        )


def test_milestones_workflow_next_phase_defaults():
    from koan.lib.workflows import MILESTONES_WORKFLOW
    expected = {
        "intake":           "milestone-spec",
        "milestone-spec":   "milestone-review",
        "milestone-review": None,
        "plan-spec":        "plan-review",
        "plan-review":      None,
        "execute":          "exec-review",
        "exec-review":      None,
        "curation":         None,
    }
    for phase_name, expected_next in expected.items():
        binding = MILESTONES_WORKFLOW.phases[phase_name]
        assert binding.next_phase == expected_next, (
            f"MILESTONES_WORKFLOW[{phase_name!r}].next_phase: "
            f"expected {expected_next!r}, got {binding.next_phase!r}"
        )


# ---------------------------------------------------------------------------
# M3: PhaseContext.next_phase and suggested_phases fields
# ---------------------------------------------------------------------------

def test_phase_context_has_next_phase_and_suggested_phases_defaults():
    ctx = _ctx()
    assert ctx.next_phase is None
    assert ctx.suggested_phases == []


# ---------------------------------------------------------------------------
# M3: terminal_invoke helper
# ---------------------------------------------------------------------------

def test_terminal_invoke_with_next_phase_calls_set_phase():
    from koan.phases.format_step import terminal_invoke
    text = terminal_invoke("plan-spec", [])
    assert 'koan_set_phase("plan-spec")' in text


def test_terminal_invoke_with_none_calls_yield():
    from koan.phases.format_step import terminal_invoke
    text = terminal_invoke(None, ["plan-spec", "execute"])
    assert "koan_yield" in text
    assert "plan-spec" in text
    assert "execute" in text


def test_terminal_invoke_yield_with_no_suggestions_no_hint_clause():
    from koan.phases.format_step import terminal_invoke
    text = terminal_invoke(None, [])
    assert "koan_yield" in text
    # Without suggestions, no "(e.g. ...)" clause should appear
    assert "(e.g." not in text
    # "done" option should still be mentioned
    assert "done" in text


def test_format_phase_complete_removed():
    import importlib
    import koan.phases.format_step as mod
    # format_phase_complete must not exist on the module after M3
    assert not hasattr(mod, "format_phase_complete"), (
        "format_phase_complete was not removed from koan.phases.format_step"
    )


# ---------------------------------------------------------------------------
# M3: per-phase last-step invoke_after uses terminal_invoke
# ---------------------------------------------------------------------------

def _ctx_with_next(next_phase, suggested_phases=None):
    """Build a PhaseContext with next_phase and suggested_phases populated."""
    ctx = PhaseContext(
        run_dir="",
        subagent_dir="",
        next_phase=next_phase,
        suggested_phases=suggested_phases or [],
    )
    return ctx


def test_intake_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import intake
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next("plan-spec", ["plan-spec"])
    g = intake.step_guidance(intake.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke("plan-spec", ["plan-spec"])


def test_milestone_spec_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import milestone_spec
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next("plan-spec", ["milestone-review", "plan-spec"])
    g = milestone_spec.step_guidance(milestone_spec.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke("plan-spec", ["milestone-review", "plan-spec"])


def test_milestone_review_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import milestone_review
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["milestone-spec", "plan-spec"])
    g = milestone_review.step_guidance(milestone_review.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, ["milestone-spec", "plan-spec"])


def test_plan_spec_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import plan_spec
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next("plan-review", ["plan-review", "execute"])
    g = plan_spec.step_guidance(plan_spec.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke("plan-review", ["plan-review", "execute"])


def test_plan_review_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import plan_review
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["plan-spec", "execute"])
    g = plan_review.step_guidance(plan_review.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, ["plan-spec", "execute"])


def test_execute_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import execute
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next("exec-review", ["exec-review", "curation"])
    g = execute.step_guidance(execute.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke("exec-review", ["exec-review", "curation"])


def test_exec_review_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import exec_review
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["curation", "plan-spec"])
    g = exec_review.step_guidance(exec_review.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, ["curation", "plan-spec"])


def test_curation_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import curation
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, [])
    g = curation.step_guidance(curation.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, [])


# ---------------------------------------------------------------------------
# M4: rewrite-or-loopback in review phases
# ---------------------------------------------------------------------------

def test_plan_review_step2_has_rewrite_or_loopback():
    from koan.phases import plan_review
    g = plan_review.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "Rewrite-or-loop-back classification" in text
    assert "koan_artifact_write" in text
    assert "loop-back to plan-spec" in text or "plan-spec" in text
    assert "new-files-needed" in text


def test_milestone_review_step2_has_rewrite_or_loopback():
    from koan.phases import milestone_review
    g = milestone_review.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "Rewrite-or-loop-back classification" in text
    assert "koan_artifact_write" in text
    assert "milestone-spec" in text
    assert "new-files-needed" in text


def test_exec_review_step2_has_rewrite_or_loopback():
    from koan.phases import exec_review
    g = exec_review.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "Rewrite-or-loop-back of the plan artifact" in text
    assert "koan_artifact_write" in text
    assert "new-files-needed" in text


def test_exec_review_step2_has_milestones_update_block():
    from koan.phases import exec_review
    g = exec_review.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "milestones.md UPDATE" in text
    assert "Integration points created" in text
    assert "Patterns established" in text
    assert "Constraints discovered" in text
    assert "Deviations from plan" in text


def test_exec_review_step1_reads_milestones_md():
    from koan.phases import exec_review
    g = exec_review.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "milestones.md" in text
    assert "Read milestone state" in text


def test_milestone_spec_step1_redecompose_mode_replaces_update():
    from koan.phases import milestone_spec
    g = milestone_spec.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    # RE-DECOMPOSE must appear
    assert "RE-DECOMPOSE" in text
    # UPDATE mode directives must be gone -- exec-review owns these transitions
    assert "mark the completed milestone" not in text.lower()
    assert "add an Outcome section" not in text.lower() or "do NOT add Outcome" in text


def test_milestone_spec_phase_binding_guidance_redecompose_framing():
    from koan.lib.workflows import MILESTONES_WORKFLOW
    guidance = MILESTONES_WORKFLOW.phases["milestone-spec"].guidance
    assert "RE-DECOMPOSE" in guidance
    # Old UPDATE-mode framing must be gone
    assert "UPDATE mode" not in guidance
    assert "mark the completed\nmilestone [done]" not in guidance


def test_exec_review_milestones_guidance_specifies_update():
    from koan.lib.workflows import _EXEC_REVIEW_MILESTONES_GUIDANCE
    assert "milestones.md UPDATE" in _EXEC_REVIEW_MILESTONES_GUIDANCE
    assert "Integration points" in _EXEC_REVIEW_MILESTONES_GUIDANCE
    assert "four-subsection Outcome" in _EXEC_REVIEW_MILESTONES_GUIDANCE


def test_exec_review_plan_guidance_no_milestones_update():
    from koan.lib.workflows import _EXEC_REVIEW_PLAN_GUIDANCE
    # Plan workflow has no milestones.md; UPDATE block must not appear there
    assert "milestones.md UPDATE" not in _EXEC_REVIEW_PLAN_GUIDANCE


def test_milestones_workflow_exec_review_transitions_order():
    from koan.lib.workflows import MILESTONES_WORKFLOW
    assert MILESTONES_WORKFLOW.transitions["exec-review"] == [
        "plan-spec", "curation", "milestone-spec"
    ]


def test_phase_trust_doc_describes_rewrite_or_loopback():
    import pathlib
    doc = pathlib.Path(__file__).parent.parent / "docs" / "phase-trust.md"
    text = doc.read_text()
    assert "rewrite-or-loop-back" in text.lower() or "rewrite-or-loopback" in text.lower()
    assert "role-level" in text.lower()
    assert "prompt discipline" in text.lower()
    # Old advisory-only framing must be gone
    assert "advisory only" not in text.lower()
    assert "reports findings, does not modify" not in text.lower()


# ---------------------------------------------------------------------------
# M5: inline-review backend removal + comments-as-steering channel
# ---------------------------------------------------------------------------

def test_steering_message_block_renders_artifact_path():
    """steering_message_block prefixes [artifact: {path}] when artifact_path is set."""
    from koan.phases.format_step import steering_message_block
    from koan.state import ChatMessage

    msg = ChatMessage(content="Add error handling", timestamp_ms=0, artifact_path="brief.md")
    block = steering_message_block(msg)
    assert "[artifact: brief.md]" in block.text
    assert "Add error handling" in block.text


def test_steering_message_block_no_artifact_path():
    """steering_message_block omits [artifact:] prefix when artifact_path is None."""
    from koan.phases.format_step import steering_message_block
    from koan.state import ChatMessage

    msg = ChatMessage(content="general comment", timestamp_ms=0, artifact_path=None)
    block = steering_message_block(msg)
    assert "[artifact:" not in block.text
    assert "general comment" in block.text


def test_koan_artifact_propose_removed_from_permissions():
    """koan_artifact_propose must not appear in orchestrator ROLE_PERMISSIONS."""
    from koan.lib.permissions import ROLE_PERMISSIONS
    assert "koan_artifact_propose" not in ROLE_PERMISSIONS["orchestrator"]


def test_koan_artifact_propose_not_importable_as_handler():
    """koan_artifact_propose must not be importable as a handler from mcp_endpoint."""
    from koan.web.mcp_endpoint import Handlers
    assert not hasattr(Handlers, "koan_artifact_propose"), (
        "koan_artifact_propose field was not removed from Handlers dataclass"
    )


def test_phase_summaries_field_removed():
    """Run.phase_summaries must not exist after M5."""
    from koan.projections import Run
    assert "phase_summaries" not in Run.model_fields, (
        "Run.phase_summaries field was not removed"
    )


def test_active_artifact_review_field_removed():
    """Run.active_artifact_review must not exist after M5."""
    from koan.projections import Run
    assert "active_artifact_review" not in Run.model_fields, (
        "Run.active_artifact_review field was not removed"
    )


def test_intake_step3_no_chat_synthesis():
    """Intake step 3 must not instruct the orchestrator to compose a prose synthesis."""
    from koan.phases import intake
    g = intake.step_guidance(3, _ctx())
    text = "\n".join(g.instructions)
    assert "Compose the prose synthesis in chat" not in text
    assert "phase summary" not in text
    assert "RAG anchor" not in text
    # The artifact write is still there
    assert "koan_artifact_write" in text
    assert "brief.md" in text


# ---------------------------------------------------------------------------
# frame
# ---------------------------------------------------------------------------

def test_frame_step1_yields_no_artifact():
    """Frame step 1 must not write artifacts and must mention koan_yield and sounding board.

    The step may mention koan_artifact_write in a prohibitive context (per cross-reference
    repetition rule), but must not contain a write directive (an actual call template).
    """
    from koan.phases import frame
    g = frame.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "sounding board" in text.lower()
    assert "koan_yield" in g.invoke_after
    # Must not contain an actual write call template; prohibition mention is OK
    assert 'koan_artifact_write(filename=' not in text
    assert 'koan_artifact_write(\n' not in text


def test_frame_role_context_forbids_scouts():
    """Frame PHASE_ROLE_CONTEXT must explicitly prohibit koan_request_scouts."""
    from koan.phases import frame
    ctx_text = frame.PHASE_ROLE_CONTEXT
    assert "koan_request_scouts" in ctx_text
    assert "MUST NOT" in ctx_text


def test_frame_total_steps_is_one():
    """Frame must have exactly one step."""
    from koan.phases import frame
    assert frame.TOTAL_STEPS == 1


def test_frame_get_next_step_returns_none():
    """Frame get_next_step must always return None (single-step, never auto-advances)."""
    from koan.phases import frame
    assert frame.get_next_step(1, _ctx()) is None


# ---------------------------------------------------------------------------
# core_flows
# ---------------------------------------------------------------------------

def test_core_flows_step1_reads_brief_md():
    """Core-flows step 1 must instruct reading brief.md via koan_artifact_view."""
    from koan.phases import core_flows
    g = core_flows.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "koan_artifact_view" in text or "Read initiative context" in text


def test_core_flows_step2_writes_core_flows_md():
    """Core-flows step 2 must write core-flows.md with status=Final."""
    from koan.phases import core_flows
    g = core_flows.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "core-flows.md" in text
    assert "koan_artifact_write" in text
    assert 'status="Final"' in text or "status='Final'" in text


def test_core_flows_role_context_forbids_implementation_detail():
    """Core-flows PHASE_ROLE_CONTEXT must forbid file paths and component names."""
    from koan.phases import core_flows
    ctx_text = core_flows.PHASE_ROLE_CONTEXT
    assert "no file paths" in ctx_text.lower()
    assert "no component names" in ctx_text.lower()


def test_core_flows_role_context_includes_seq_slot_rules():
    """Core-flows PHASE_ROLE_CONTEXT must mention sequenceDiagram, suppression marker, and visualization-system.md."""
    from koan.phases import core_flows
    ctx_text = core_flows.PHASE_ROLE_CONTEXT
    assert "sequenceDiagram" in ctx_text
    assert "diagram suppressed" in ctx_text
    assert "docs/visualization-system.md" in ctx_text


def test_core_flows_role_context_includes_mermaid_syntax_hazards():
    """Core-flows PHASE_ROLE_CONTEXT must include the mermaid syntax-hazards subsection (semicolon, <br>, doc reference)."""
    from koan.phases import core_flows
    ctx_text = core_flows.PHASE_ROLE_CONTEXT
    assert "Mermaid syntax hazards" in ctx_text
    assert "semicolon" in ctx_text.lower() or "`;`" in ctx_text
    assert "<br>" in ctx_text
    assert "docs/visualization-system.md" in ctx_text


# ---------------------------------------------------------------------------
# tech_plan_spec
# ---------------------------------------------------------------------------

def test_tech_plan_spec_step1_reads_brief_and_core_flows():
    """Tech-plan-spec step 1 must reference both brief.md and core-flows.md."""
    from koan.phases import tech_plan_spec
    g = tech_plan_spec.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "core-flows.md" in text


def test_tech_plan_spec_step2_writes_tech_plan_md():
    """Tech-plan-spec step 2 must write tech-plan.md with the three required sections."""
    from koan.phases import tech_plan_spec
    g = tech_plan_spec.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "tech-plan.md" in text
    assert "koan_artifact_write" in text
    assert "Architectural Approach" in text
    assert "Data Model" in text
    assert "Component Architecture" in text


def test_tech_plan_spec_role_context_includes_slot_mapping():
    """Tech-plan-spec PHASE_ROLE_CONTEXT must reference the CON/CMP/SEQ/STT slot mapping."""
    from koan.phases import tech_plan_spec
    ctx_text = tech_plan_spec.PHASE_ROLE_CONTEXT
    # At minimum, the four diagram types must appear
    assert "flowchart" in ctx_text
    assert "classDiagram" in ctx_text
    assert "sequenceDiagram" in ctx_text
    assert "stateDiagram-v2" in ctx_text


def test_tech_plan_spec_role_context_includes_grounding_rule():
    """Tech-plan-spec PHASE_ROLE_CONTEXT must include suppression marker and grounding rule."""
    from koan.phases import tech_plan_spec
    ctx_text = tech_plan_spec.PHASE_ROLE_CONTEXT
    assert "diagram suppressed" in ctx_text
    assert "Grounding rule" in ctx_text or "grounding rule" in ctx_text.lower()


def test_tech_plan_spec_role_context_includes_mermaid_syntax_hazards():
    """Tech-plan-spec PHASE_ROLE_CONTEXT must include the mermaid syntax-hazards subsection (semicolon, <br>, doc reference)."""
    from koan.phases import tech_plan_spec
    ctx_text = tech_plan_spec.PHASE_ROLE_CONTEXT
    assert "Mermaid syntax hazards" in ctx_text
    assert "semicolon" in ctx_text.lower() or "`;`" in ctx_text
    assert "<br>" in ctx_text
    assert "docs/visualization-system.md" in ctx_text


# ---------------------------------------------------------------------------
# tech_plan_review
# ---------------------------------------------------------------------------

def test_tech_plan_review_step1_reads_brief_core_flows_tech_plan():
    """Tech-plan-review step 1 must reference all three upstream artifacts."""
    from koan.phases import tech_plan_review
    g = tech_plan_review.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "core-flows.md" in text
    assert "tech-plan.md" in text


def test_tech_plan_review_step2_classifies_findings():
    """Tech-plan-review step 2 must describe internal/new-files classification and koan_artifact_write."""
    from koan.phases import tech_plan_review
    g = tech_plan_review.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "internal" in text.lower()
    assert "new-files" in text.lower()
    assert "koan_artifact_write" in text


def test_tech_plan_review_role_context_no_legacy_gate_language():
    """Tech-plan-review PHASE_ROLE_CONTEXT must not contain koan_artifact_propose or legacy Approved gate phrases."""
    from koan.phases import tech_plan_review
    ctx_text = tech_plan_review.PHASE_ROLE_CONTEXT
    assert "koan_artifact_propose" not in ctx_text
    assert "transition to Approved" not in ctx_text
    assert "Approved before" not in ctx_text


def test_tech_plan_review_role_context_diagram_accuracy_check():
    """Tech-plan-review PHASE_ROLE_CONTEXT must mention grounding, suppression, and level-separation."""
    from koan.phases import tech_plan_review
    ctx_text = tech_plan_review.PHASE_ROLE_CONTEXT
    assert "grounding" in ctx_text.lower()
    assert "suppression" in ctx_text.lower() or "diagram suppressed" in ctx_text
    assert "level-separation" in ctx_text.lower() or "level separation" in ctx_text.lower()


def test_tech_plan_review_role_context_authorizes_scouts():
    """Tech-plan-review PHASE_ROLE_CONTEXT must authorize koan_request_scouts (not forbid it)."""
    from koan.phases import tech_plan_review
    ctx_text = tech_plan_review.PHASE_ROLE_CONTEXT
    assert "koan_request_scouts" in ctx_text
    # Must be in an authorization context, not a prohibition
    assert "MUST NOT call koan_request_scouts" not in ctx_text
    assert "MUST NOT call `koan_request_scouts`" not in ctx_text


# ---------------------------------------------------------------------------
# Workflow binding tests
# ---------------------------------------------------------------------------

def test_initiative_workflow_phase_next_phase_bindings():
    """INITIATIVE_WORKFLOW per-phase next_phase values must match the expected map."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    expected = {
        "intake":           "core-flows",
        "core-flows":       None,
        "tech-plan-spec":   "tech-plan-review",
        "tech-plan-review": None,
        "milestone-spec":   "milestone-review",
        "milestone-review": None,
        "plan-spec":        "plan-review",
        "plan-review":      None,
        "execute":          "exec-review",
        "exec-review":      None,
        "curation":         None,
    }
    for phase_name, expected_next in expected.items():
        binding = INITIATIVE_WORKFLOW.phases[phase_name]
        assert binding.next_phase == expected_next, (
            f"INITIATIVE_WORKFLOW[{phase_name!r}].next_phase: "
            f"expected {expected_next!r}, got {binding.next_phase!r}"
        )


def test_discovery_workflow_phase_next_phase_bindings():
    """DISCOVERY_WORKFLOW frame binding must have next_phase=None."""
    from koan.lib.workflows import DISCOVERY_WORKFLOW
    assert DISCOVERY_WORKFLOW.phases["frame"].next_phase is None


def test_initiative_workflow_transitions_well_formed():
    """Every key and value in INITIATIVE_WORKFLOW.transitions must be in available_phases."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    available = set(INITIATIVE_WORKFLOW.available_phases)
    for phase, successors in INITIATIVE_WORKFLOW.transitions.items():
        assert phase in available, f"transitions key {phase!r} not in available_phases"
        for s in successors:
            assert s in available, (
                f"transitions[{phase!r}] references {s!r} not in available_phases"
            )


def test_discovery_workflow_transitions_frame_only():
    """DISCOVERY_WORKFLOW.transitions must be exactly {\"frame\": []}."""
    from koan.lib.workflows import DISCOVERY_WORKFLOW
    assert DISCOVERY_WORKFLOW.transitions == {"frame": []}


def test_initiative_execute_guidance_includes_tech_plan_md():
    """INITIATIVE_WORKFLOW execute binding guidance must reference tech-plan.md for executor handoff."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    guidance = INITIATIVE_WORKFLOW.phases["execute"].guidance
    assert "tech-plan.md" in guidance


def test_workflows_dict_includes_initiative_and_discovery():
    """WORKFLOWS dict must contain 'initiative' and 'discovery' keys resolving to the right constants."""
    from koan.lib.workflows import WORKFLOWS, INITIATIVE_WORKFLOW, DISCOVERY_WORKFLOW
    assert "initiative" in WORKFLOWS
    assert "discovery" in WORKFLOWS
    assert WORKFLOWS["initiative"] is INITIATIVE_WORKFLOW
    assert WORKFLOWS["discovery"] is DISCOVERY_WORKFLOW
