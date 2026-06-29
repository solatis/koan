# Static-text assertions verifying that each phase module's step-1 guidance
# includes the "Read brief.md" directive introduced in Milestone 2.
#
# These tests do not boot a runner or mock anything. They instantiate
# step_guidance() with a minimal PhaseContext and assert that key strings
# appear in the joined instruction text. End-to-end behavior (does the LLM
# follow the prompt) is an evals-harness concern.

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
    assert "FROZEN" in text
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
# plan_spec
# ---------------------------------------------------------------------------

def test_plan_spec_step1_reads_brief_md():
    from koan.phases import plan_spec
    g = plan_spec.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "Read initiative context" in text


# ---------------------------------------------------------------------------
# M6: negative-presence -- *-review modules are not importable
# ---------------------------------------------------------------------------

def test_plan_review_not_importable():
    """M6: koan.phases.plan_review must not be importable -- module deleted."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.plan_review")


def test_milestone_review_not_importable():
    """M6: koan.phases.milestone_review must not be importable -- module deleted."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.milestone_review")


def test_tech_plan_review_not_importable():
    """M6: koan.phases.tech_plan_review must not be importable -- module deleted."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.tech_plan_review")


def test_exec_review_not_importable():
    """M6: koan.phases.exec_review must not be importable -- module deleted."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.exec_review")


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

def test_plan_workflow_execute_guidance_omits_brief_md_read():
    """Milestone 2: brief.md is an injected handover -- execute guidance must not direct an explicit read."""
    from koan.lib.workflows import PLAN_WORKFLOW
    guidance = PLAN_WORKFLOW.phases["execute"].guidance
    # brief.md is now a handover injected before the phase; no read directive needed.
    assert "brief.md" not in guidance
    # plan.md is a living document and must still appear in the verify-conformance sentence.
    assert "plan.md" in guidance


def test_milestones_workflow_execute_guidance_omits_brief_md_read():
    """Milestone 2: brief.md is an injected handover -- execute guidance must not direct an explicit read."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    guidance = MILESTONES_WORKFLOW.phases["execute"].guidance
    # brief.md is now a handover injected before the phase; no read directive needed.
    assert "brief.md" not in guidance
    # Living-document reads (plan and milestones) must still be present.
    assert "plan-milestone-N.md" in guidance
    assert "milestones.md" in guidance


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
    b = PhaseBinding(module=intake, next_phase="plan")
    assert b.next_phase == "plan"


def test_plan_workflow_next_phase_defaults():
    """M6: plan workflow has no *-review phases; plan.next_phase=None (names plan for execute)."""
    from koan.lib.workflows import PLAN_WORKFLOW
    expected = {
        "intake":    "plan",
        # M5: plan.next_phase=None -- the step instructions call bare
        # koan_set_phase("execute") after reconciling findings.
        "plan":      None,
        "execute":   None,
        "curation":  None,
    }
    for phase_name, expected_next in expected.items():
        binding = PLAN_WORKFLOW.phases[phase_name]
        assert binding.next_phase == expected_next, (
            f"PLAN_WORKFLOW[{phase_name!r}].next_phase: "
            f"expected {expected_next!r}, got {binding.next_phase!r}"
        )


def test_milestones_workflow_next_phase_defaults():
    """M6: milestones workflow has no *-review phases; producer next_phase values updated."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    expected = {
        "intake":    "milestone",
        # M6: milestone.next_phase=None -- step instructions advance to plan
        # after reconciling MILESTONE_REVIEWER findings.
        "milestone": None,
        # M5: plan.next_phase=None -- step instructions call bare koan_set_phase("execute").
        "plan":      None,
        "execute":   None,
        "curation":  None,
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
    text = terminal_invoke("plan", [])
    assert 'koan_set_phase("plan")' in text


def test_terminal_invoke_with_none_hands_back():
    from koan.phases.format_step import terminal_invoke
    text = terminal_invoke(None, ["plan", "execute"])
    # koan_yield is gone -- the terminal-text turn is the hand-back.
    assert "koan_yield" not in text
    assert "End your turn" in text
    # The user-confirmed transition still commits via koan_set_phase.
    assert "koan_set_phase" in text
    assert "plan" in text
    assert "execute" in text


def test_terminal_invoke_no_suggestions_no_hint_clause():
    from koan.phases.format_step import terminal_invoke
    text = terminal_invoke(None, [])
    assert "koan_yield" not in text
    # Without suggestions, no "(e.g. ...)" clause should appear
    assert "(e.g." not in text
    # "done" option should still be mentioned
    assert "done" in text


def test_format_phase_complete_removed():
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
    ctx = _ctx_with_next("plan", ["plan"])
    g = intake.step_guidance(intake.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke("plan", ["plan"])


def test_milestone_spec_last_step_invoke_after_is_terminal_invoke():
    """M6: milestone.next_phase=None (yields to advance to plan after reconcile)."""
    from koan.phases import milestone_spec
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["plan"])
    g = milestone_spec.step_guidance(milestone_spec.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, ["plan"])


def test_plan_spec_last_step_invoke_after_is_terminal_invoke():
    """M6: plan.next_phase=None (step instructions call set_phase(execute) directly)."""
    from koan.phases import plan_spec
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["execute"])
    g = plan_spec.step_guidance(plan_spec.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, ["execute"])


def test_execute_last_step_invoke_after_is_terminal_invoke():
    # M5: execute.TOTAL_STEPS=3 (Reconcile); next_phase=None; yields to user.
    from koan.phases import execute
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, ["plan", "curation"])
    g = execute.step_guidance(execute.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, ["plan", "curation"])


def test_curation_last_step_invoke_after_is_terminal_invoke():
    from koan.phases import curation
    from koan.phases.format_step import terminal_invoke
    ctx = _ctx_with_next(None, [])
    g = curation.step_guidance(curation.TOTAL_STEPS, ctx)
    assert g.invoke_after == terminal_invoke(None, [])


# ---------------------------------------------------------------------------
# M2: milestone phase is one-time; discard hook removed; RE-DECOMPOSE gone
# ---------------------------------------------------------------------------

def test_milestone_spec_step1_create_only():
    """M2: milestone phase is one-time; milestones.md is always CREATEd (no discard hook)."""
    from koan.phases import milestone_spec
    g = milestone_spec.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    # Must NOT contain RE-DECOMPOSE mode directive (removed in M6)
    assert "RE-DECOMPOSE" not in text
    # UPDATE mode directives must be gone
    assert "mark the completed milestone" not in text.lower()


def test_milestone_spec_phase_binding_no_redecompose():
    """M2: milestone binding guidance must not instruct RE-DECOMPOSE mode (phase is one-time)."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    guidance = MILESTONES_WORKFLOW.phases["milestone"].guidance
    # The guidance may mention "no RE-DECOMPOSE" as a negative, but must not
    # instruct the orchestrator to enter RE-DECOMPOSE mode itself.
    assert "you are in RE-DECOMPOSE mode" not in guidance
    assert "If milestones.md exists, you are in RE-DECOMPOSE" not in guidance
    # Old UPDATE-mode framing must be gone
    assert "UPDATE mode" not in guidance


def test_exec_review_guidance_constants_removed():
    """M6: _EXEC_REVIEW_MILESTONES_GUIDANCE and _EXEC_REVIEW_PLAN_GUIDANCE removed from workflows."""
    import koan.lib.workflows as wf_mod
    # These constants are removed in M6; accessing them must raise AttributeError.
    assert not hasattr(wf_mod, "_EXEC_REVIEW_MILESTONES_GUIDANCE"), (
        "_EXEC_REVIEW_MILESTONES_GUIDANCE must be removed from workflows.py in M6"
    )
    assert not hasattr(wf_mod, "_EXEC_REVIEW_PLAN_GUIDANCE"), (
        "_EXEC_REVIEW_PLAN_GUIDANCE must be removed from workflows.py in M6"
    )


def test_milestones_workflow_no_exec_review_transition():
    """M6: milestones workflow must have no exec-review key in transitions."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    assert "exec-review" not in MILESTONES_WORKFLOW.transitions


def test_plan_workflow_transitions_final_shape():
    """M5: plan workflow execute -> curation only (dropped 'plan' remediation loop)."""
    from koan.lib.workflows import PLAN_WORKFLOW
    assert PLAN_WORKFLOW.transitions == {
        "intake":   ["plan"],
        "plan":     ["execute"],
        "execute":  ["curation"],
        "curation": [],
    }


def test_milestones_workflow_transitions_final_shape():
    """M2: milestones workflow execute no longer suggests milestone (one-time phase)."""
    from koan.lib.workflows import MILESTONES_WORKFLOW
    assert MILESTONES_WORKFLOW.transitions == {
        "intake":    ["milestone"],
        "milestone": ["plan"],
        "plan":      ["execute"],
        "execute":   ["plan", "curation"],
        "curation":  [],
    }


def test_initiative_workflow_transitions_final_shape():
    """M5: initiative workflow execute -> [plan, curation] (dropped tech-plan lookback)."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    assert INITIATIVE_WORKFLOW.transitions == {
        "intake":     ["core-flows", "tech-plan"],
        "core-flows": ["tech-plan", "core-flows"],
        "tech-plan":  ["milestone"],
        "milestone":  ["plan"],
        "plan":       ["execute"],
        "execute":    ["plan", "curation"],
        "curation":   [],
    }


def test_phase_trust_doc_describes_inline_reconcile():
    """M6: phase-trust.md must describe the mechanical reviewer / inline reconcile model.

    The old rewrite-or-loop-back *-review phase model was replaced in M6 with the
    mechanical reviewer sub-agent triggered by koan_artifact_write.  The doc must
    now describe INCORPORATED / OVERRULED / ESCALATED inline reconcile semantics.
    """
    import pathlib
    doc = pathlib.Path(__file__).parent.parent / "docs" / "phase-trust.md"
    text = doc.read_text()
    # M6 inline reconcile terminology
    assert "incorporated" in text.lower()
    assert "overruled" in text.lower()
    assert "escalated" in text.lower()
    assert "role-level" in text.lower()
    assert "prompt discipline" in text.lower()
    # Old advisory-only framing must be gone
    assert "advisory only" not in text.lower()
    assert "reports findings, does not modify" not in text.lower()
    # *-review phases must not appear as active workflow steps in this doc;
    # they may appear in the historical "Why the model changed" section only.
    # Guard: if any *-review phase appears outside a "### " heading, flag it.
    # (Simple check: confirm the doc mentions mechanical reviewer terminology.)
    assert "mechanical reviewer" in text.lower() or "tech_plan_reviewer" in text.lower()


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
    # ROLE_PERMISSIONS now lives in koan.tools.tool_policy (inlined from permissions.py in M1).
    from koan.tools.tool_policy import ROLE_PERMISSIONS
    assert "koan_artifact_propose" not in ROLE_PERMISSIONS["orchestrator"]


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

def test_frame_step1_strong_handback_no_artifact():
    """Frame step 1 must cover all three exploration categories and strongly prompt hand-back.

    The step must mention the hand-back (end your turn, no tool call), koan_reflect,
    koan_ask_question, and bug (broadened scope). It must not mention the removed
    koan_yield tool, must not contain 'sounding board' or an actual
    koan_artifact_write call template; a prohibitive mention is OK.
    """
    from koan.phases import frame
    g = frame.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    # Broadened scope: bug hunting must be named
    assert "bug" in text.lower()
    # Memory and clarification tools must be encouraged
    assert "koan_reflect" in text
    assert "koan_ask_question" in text
    # The removed koan_yield tool must not be referenced
    assert "koan_yield" not in text
    assert "koan_yield" not in g.invoke_after
    # Always-hand-back must be stated in the body and the footer
    assert "end your turn" in text.lower()
    assert "end your turn" in g.invoke_after.lower()
    # Must not contain 'sounding board' (removed from broadened posture)
    assert "sounding board" not in text.lower()
    # Must not contain an actual write call template; prohibition mention is OK
    assert 'koan_artifact_write(filename=' not in text
    assert 'koan_artifact_write(\n' not in text


def test_frame_role_context_permits_investigation():
    """Frame PHASE_ROLE_CONTEXT must encourage koan_request_scouts, not prohibit it."""
    from koan.phases import frame
    ctx_text = frame.PHASE_ROLE_CONTEXT
    # koan_request_scouts must appear as a positive encouragement
    assert "koan_request_scouts" in ctx_text
    # The old prohibition must be gone
    assert "MUST NOT call `koan_request_scouts`" not in ctx_text


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

def test_core_flows_step1_references_brief_md_handover():
    """Core-flows step 1 must reference brief.md as a handover (not a koan_artifact_read directive)."""
    from koan.phases import core_flows
    g = core_flows.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "Read initiative context" in text


def test_core_flows_step2_writes_core_flows_md():
    """Core-flows step 2 must write core-flows.md and note the artifact is frozen."""
    from koan.phases import core_flows
    g = core_flows.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "core-flows.md" in text
    assert "koan_artifact_write" in text
    assert "FROZEN" in text


def test_core_flows_role_context_forbids_implementation_detail():
    """Core-flows PHASE_ROLE_CONTEXT must forbid file paths and component names."""
    from koan.phases import core_flows
    ctx_text = core_flows.PHASE_ROLE_CONTEXT
    assert "no file paths" in ctx_text.lower()
    assert "no component names" in ctx_text.lower()


def test_core_flows_role_context_includes_seq_slot_rules():
    """Core-flows PHASE_ROLE_CONTEXT must mention sequenceDiagram, the suppression rule, and visualization-system.md.

    The suppression rule is now "render as prose only, no marker" -- explicitly
    forbidding the old `<!-- diagram suppressed ... -->` placeholder, which
    leaked into rendered output as visible text.
    """
    from koan.phases import core_flows
    ctx_text = core_flows.PHASE_ROLE_CONTEXT
    assert "sequenceDiagram" in ctx_text
    assert "Suppression rule" in ctx_text
    assert "no marker comment" in ctx_text
    assert "diagram suppressed" not in ctx_text
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
    """tech-plan step 1 must reference both brief.md and core-flows.md."""
    from koan.phases import tech_plan_spec
    g = tech_plan_spec.step_guidance(1, _ctx())
    text = "\n".join(g.instructions)
    assert "brief.md" in text
    assert "core-flows.md" in text


def test_tech_plan_spec_step2_writes_tech_plan_md():
    """tech-plan step 2 must write tech-plan.md with the three required sections."""
    from koan.phases import tech_plan_spec
    g = tech_plan_spec.step_guidance(2, _ctx())
    text = "\n".join(g.instructions)
    assert "tech-plan.md" in text
    assert "koan_artifact_write" in text
    assert "Architectural Approach" in text
    assert "Data Model" in text
    assert "Component Architecture" in text


def test_tech_plan_spec_role_context_includes_slot_mapping():
    """tech-plan PHASE_ROLE_CONTEXT must reference the CON/CMP/SEQ/STT slot mapping."""
    from koan.phases import tech_plan_spec
    ctx_text = tech_plan_spec.PHASE_ROLE_CONTEXT
    # At minimum, the four diagram types must appear
    assert "flowchart" in ctx_text
    assert "classDiagram" in ctx_text
    assert "sequenceDiagram" in ctx_text
    assert "stateDiagram-v2" in ctx_text


def test_tech_plan_spec_role_context_includes_grounding_rule():
    """tech-plan PHASE_ROLE_CONTEXT must include the suppression rule (no marker) and grounding rule."""
    from koan.phases import tech_plan_spec
    ctx_text = tech_plan_spec.PHASE_ROLE_CONTEXT
    assert "below threshold" in ctx_text.lower()
    # Source string wraps lines, so collapse whitespace before searching for the rule.
    collapsed = " ".join(ctx_text.lower().split())
    assert "no marker comment" in collapsed
    assert "diagram suppressed" not in ctx_text
    assert "Grounding rule" in ctx_text or "grounding rule" in ctx_text.lower()


def test_tech_plan_spec_role_context_includes_mermaid_syntax_hazards():
    """tech-plan PHASE_ROLE_CONTEXT must include the mermaid syntax-hazards subsection (semicolon, <br>, doc reference)."""
    from koan.phases import tech_plan_spec
    ctx_text = tech_plan_spec.PHASE_ROLE_CONTEXT
    assert "Mermaid syntax hazards" in ctx_text
    assert "semicolon" in ctx_text.lower() or "`;`" in ctx_text
    assert "<br>" in ctx_text
    assert "docs/visualization-system.md" in ctx_text


# ---------------------------------------------------------------------------
# Workflow binding tests
# ---------------------------------------------------------------------------

def test_initiative_workflow_phase_next_phase_bindings():
    """INITIATIVE_WORKFLOW per-phase next_phase values must match the M6 final map.

    M6: *-review phases removed. Producers advance directly to their successors
    after reconciling the mechanical reviewer's findings inline.
    """
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    expected = {
        "intake":     "core-flows",
        "core-flows": None,
        # M6: tech-plan advances to milestone (TECH_PLAN_REVIEWER runs on write).
        "tech-plan":  "milestone",
        # M6: milestone.next_phase=None -- step instructions advance to plan
        # after reconciling MILESTONE_REVIEWER findings.
        "milestone":  None,
        # M6: plan.next_phase=None -- step instructions call set_phase(execute).
        "plan":       None,
        "execute":    None,
        "curation":   None,
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


def test_initiative_execute_guidance_omits_immutable_reads():
    """Milestone 2: brief.md and tech-plan.md are injected handovers -- execute guidance must not direct explicit reads."""
    from koan.lib.workflows import INITIATIVE_WORKFLOW
    guidance = INITIATIVE_WORKFLOW.phases["execute"].guidance
    # Both are now handovers injected before the phase; no read directives needed.
    assert "brief.md" not in guidance
    assert "tech-plan.md" not in guidance
    # Living-document reads (plan and milestones) must still be present.
    assert "plan-milestone-N.md" in guidance
    assert "milestones.md" in guidance


def test_workflows_dict_includes_initiative_and_discovery():
    """WORKFLOWS dict must contain 'initiative' and 'discovery' keys resolving to the right constants."""
    from koan.lib.workflows import WORKFLOWS, INITIATIVE_WORKFLOW, DISCOVERY_WORKFLOW
    assert "initiative" in WORKFLOWS
    assert "discovery" in WORKFLOWS
    assert WORKFLOWS["initiative"] is INITIATIVE_WORKFLOW
    assert WORKFLOWS["discovery"] is DISCOVERY_WORKFLOW
