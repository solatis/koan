# Tests for the curation phase module.

from __future__ import annotations

from koan.phases import PhaseContext, curation


def _ctx(**kw) -> PhaseContext:
    defaults = {"run_dir": "/tmp/run", "subagent_dir": "/tmp/sub"}
    defaults.update(kw)
    return PhaseContext(**defaults)


class TestModuleShape:
    def test_total_steps_is_2(self):
        assert curation.TOTAL_STEPS == 2

    def test_role_is_orchestrator(self):
        assert curation.ROLE == "orchestrator"

    def test_scope_is_general(self):
        assert curation.SCOPE == "general"

    def test_step_names(self):
        assert curation.STEP_NAMES == {1: "Inventory", 2: "Memorize"}

    def test_system_prompt_is_nonempty(self):
        assert isinstance(curation.SYSTEM_PROMPT, str)
        assert len(curation.SYSTEM_PROMPT) > 100

    def test_system_prompt_writing_discipline_is_high_level_only(self):
        # Post-rewrite: writing discipline in the system prompt is a
        # one-paragraph high-level summary. The full rules and the
        # contrastive examples live in step 2's body, rendered at the
        # drafting moment. The system prompt keeps just the pillars
        # ("temporally grounded, attributed, event-style") and an
        # explicit pointer to step 2.
        sp = curation.SYSTEM_PROMPT.lower()
        assert "temporally grounded" in sp
        assert "attributed" in sp
        assert "event-style" in sp
        assert "step 2" in sp  # points at where the full rules live

    def test_system_prompt_has_type_discrimination_tree(self):
        sp = curation.SYSTEM_PROMPT
        # The 4-question tree, with first-match-wins semantics, must
        # be present as a procedure (not just definitions).
        assert "Picking the type for a candidate" in sp
        assert "first match wins" in sp.lower() or "FIRST match wins" in sp
        # Each of the four types must appear as a tree outcome.
        for type_name in ("decision", "lesson", "procedure", "context"):
            assert type_name in sp
        # Lesson trigger includes the user-correction case.
        assert "correct the agent" in sp

    def test_system_prompt_derivable_rule_preserves_decisions(self):
        # The "what not to capture" rule must explicitly preserve
        # decisions' rationale and prior-workflow lessons, even when
        # the resulting implementation is in code.
        sp = curation.SYSTEM_PROMPT
        assert "EXCEPT" in sp
        assert "rationale and rejected alternatives" in sp
        assert "lessons from prior workflows" in sp

    def test_system_prompt_enumerates_memory_tools(self):
        # Tools must be visible at the role layer.
        sp = curation.SYSTEM_PROMPT
        assert "koan_memorize" in sp
        assert "koan_forget" in sp
        assert "koan_memory_status" in sp

    def test_system_prompt_declares_classification_schema(self):
        sp = curation.SYSTEM_PROMPT
        for label in ("ADD", "UPDATE", "NOOP", "DEPRECATE"):
            assert label in sp, f"schema label {label!r} missing from SYSTEM_PROMPT"

    def test_system_prompt_declares_structural_invariant(self):
        # Propose-then-write must be stated, not buried.
        sp = curation.SYSTEM_PROMPT.lower()
        assert "propose" in sp and "approve" in sp

    def test_system_prompt_declares_read_write_asymmetry(self):
        # Reads of .koan/memory/*.md are allowed; writes are not.
        sp = curation.SYSTEM_PROMPT
        # Reads explicitly allowed and explained:
        assert "Reading individual entries" in sp
        assert ".koan/memory/" in sp
        # Writes explicitly forbidden:
        assert "Do NOT write or delete files under `.koan/`" in sp

    def test_system_prompt_acknowledges_coding_agent_memory(self):
        # CLAUDE.md / AGENTS.md / .cursor/ etc. are a separate, read-only system.
        sp = curation.SYSTEM_PROMPT
        assert "coding agent" in sp.lower()
        assert "CLAUDE.md" in sp
        assert "READ-ONLY" in sp


class TestLifecycle:
    def test_get_next_step_linear(self):
        ctx = _ctx()
        assert curation.get_next_step(1, ctx) == 2

    def test_get_next_step_terminal(self):
        assert curation.get_next_step(2, _ctx()) is None

    def test_validate_all_none(self):
        ctx = _ctx()
        for s in (1, 2):
            assert curation.validate_step_completion(s, ctx) is None


class TestStepHeaders:
    """Every step must render workflow_shape, goal, and tools_this_step blocks
    with a YOU-ARE-HERE marker pointing at the current step."""

    def test_step_1_renders_workflow_shape(self):
        g = curation.step_guidance(1, _ctx())
        text = "\n".join(g.instructions)
        assert "<workflow_shape>" in text
        assert "</workflow_shape>" in text
        # Position marker on step 1.
        # Format: `... step 1 -- Inventory ...   (<-- YOU ARE HERE)` on the step-1 line.
        for line in text.splitlines():
            if "step 1 -- Inventory" in line:
                assert "YOU ARE HERE" in line, f"step-1 line missing marker: {line!r}"
                break
        else:
            raise AssertionError("step-1 line not found in workflow_shape block")
        for line in text.splitlines():
            if "step 2 -- Memorize" in line:
                assert "YOU ARE HERE" not in line, f"step-2 line wrongly marked: {line!r}"

    def test_step_2_renders_workflow_shape(self):
        g = curation.step_guidance(2, _ctx())
        text = "\n".join(g.instructions)
        assert "<workflow_shape>" in text
        for line in text.splitlines():
            if "step 2 -- Memorize" in line:
                assert "YOU ARE HERE" in line, f"step-2 line missing marker: {line!r}"
                break
        else:
            raise AssertionError("step-2 line not found in workflow_shape block")

    def test_both_steps_render_goal_block(self):
        for step in (1, 2):
            text = "\n".join(curation.step_guidance(step, _ctx()).instructions)
            assert "<goal>" in text and "</goal>" in text
            assert "koan_memorize" in text  # the goal names the central tool

    def test_step_1_tools_block_calls_memory_status_first(self):
        text = "\n".join(curation.step_guidance(1, _ctx()).instructions)
        assert "<tools_this_step>" in text
        assert "koan_memory_status" in text
        # FIRST is the load-bearing word.
        assert "FIRST" in text

    def test_step_2_tools_block_lists_write_tools(self):
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        assert "<tools_this_step>" in text
        assert "koan_yield" in text
        assert "koan_memorize" in text
        assert "koan_forget" in text


class TestStep1Inventory:
    def test_title_is_inventory(self):
        g = curation.step_guidance(1, _ctx())
        assert g.title == "Inventory"

    def test_renders_directive_block(self):
        ctx = _ctx(phase_instructions="## Source: postmortem\n\nWork from transcript.")
        g = curation.step_guidance(1, ctx)
        text = "\n".join(g.instructions)
        assert "<directive>" in text
        assert "</directive>" in text
        assert "postmortem" in text
        assert "transcript" in text

    def test_renders_task_block_when_present(self):
        ctx = _ctx(task_description="audit my memory entries for staleness")
        g = curation.step_guidance(1, ctx)
        text = "\n".join(g.instructions)
        assert "<task>" in text
        assert "</task>" in text
        assert "audit my memory entries for staleness" in text

    def test_renders_task_block_placeholder_when_absent(self):
        g = curation.step_guidance(1, _ctx())
        text = "\n".join(g.instructions)
        assert "<task>" in text
        assert "no user task" in text.lower()

    def test_default_directive_when_missing(self):
        g = curation.step_guidance(1, _ctx())
        text = "\n".join(g.instructions)
        assert "No directive provided" in text

    def test_calls_out_memory_status(self):
        g = curation.step_guidance(1, _ctx())
        text = "\n".join(g.instructions)
        assert "koan_memory_status" in text

    def test_acknowledges_coding_agent_memory_as_read_only(self):
        text = "\n".join(curation.step_guidance(1, _ctx()).instructions)
        assert "CLAUDE.md" in text or "coding agent" in text.lower()

    def test_produces_candidate_list_contract(self):
        text = "\n".join(curation.step_guidance(1, _ctx()).instructions)
        assert "candidate list" in text.lower()

    def test_points_at_type_discrimination_tree(self):
        # Step 1 must reference the system prompt's type discrimination
        # tree at the point where types are assigned, so the orchestrator
        # applies the tree procedurally rather than picking types from
        # the abstract definitions alone.
        # Flatten whitespace so the substring match works across line wraps.
        import re
        text = "\n".join(curation.step_guidance(1, _ctx()).instructions)
        flat = re.sub(r"\s+", " ", text).lower()
        assert "discrimination tree" in flat
        assert "first match wins" in flat


class TestStep2Memorize:
    def test_title_is_memorize(self):
        g = curation.step_guidance(2, _ctx())
        assert g.title == "Memorize"

    def test_contains_loop_vocabulary(self):
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions).lower()
        assert "draft" in text
        assert "yield" in text
        assert "apply" in text
        assert "batch" in text

    def test_contains_classification_labels(self):
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        for label in ("ADD", "UPDATE", "NOOP", "DEPRECATE"):
            assert label in text

    def test_references_memory_tools(self):
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        assert "koan_memorize" in text
        assert "koan_forget" in text
        assert "koan_yield" in text

    def test_renders_writing_discipline_at_drafting_moment(self):
        # Post-rewrite: writing discipline is now INTENTIONALLY rendered
        # in step 2's body, right at the drafting moment. The previous
        # design kept it only in the system prompt, which was too far
        # from the drafting turn; 7/10 entries in the audit violated
        # rules the system prompt had correctly stated.
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        assert "## Writing discipline" in text
        # All 5 rules must be visible inline, not by reference.
        assert "Open with a named subsystem" in text
        assert "Temporally ground every claim" in text
        assert "Attribute every claim" in text
        assert "Event-style, past tense" in text
        assert "Name things concretely" in text

    def test_renders_contrastive_examples(self):
        # Two contrastive bad/good pairs must appear in step 2's body:
        # one decision pair (Redis session storage), one lesson pair
        # (Alembic migration). Examples are general-purpose, not
        # koan-specific.
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        assert '<example type="decision-bad">' in text
        assert '<example type="decision-good">' in text
        assert '<example type="lesson-bad">' in text
        assert '<example type="lesson-good">' in text
        # Decision good-example sentinel:
        assert "Redis 7.2" in text
        # Lesson good-example sentinel:
        assert "Alembic" in text
        # Examples must NOT reference koan itself.
        assert "koan" not in text.lower() or "koan_" in text  # tool names OK
        # "What changed between bad and good" explanations must follow each pair.
        assert text.count("What changed between bad and good") == 2

    def test_renders_6_substep_loop(self):
        # The per-batch loop has 6 committed sub-operations in order:
        # Draft -> Self-critique -> Revise -> Yield -> Apply -> Cross off.
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        for header in (
            "### A. Draft",
            "### B. Self-critique",
            "### C. Revise",
            "### D. Yield",
            "### E. Apply",
            "### F. Cross off",
        ):
            assert header in text, f"missing substep header: {header!r}"
        # The critical anti-simulated-refinement guardrails.
        assert "Do not collapse substeps" in text
        assert "Do not skip this substep" in text

    def test_renders_draft_quality_checklist(self):
        # The 5-item checklist must be present as a schema the orchestrator
        # can apply per-draft in substep B.
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        assert "Draft-quality checklist" in text
        assert "PASS / FAIL" in text
        # The checklist items map 1-to-1 onto the 5 writing discipline rules.
        for item in (
            "Opens with named subsystem",
            "Contains absolute date",
            "Contains attribution",
            "Event-style, past tense",
            "Concrete naming",
        ):
            assert item in text, f"missing checklist item: {item!r}"

    def test_includes_anticipatory_tool_call_check(self):
        # The tool-call anticipatory check from the previous round is
        # preserved (renamed to "Anticipatory tool-call check" to
        # distinguish from the new draft-quality gate in substeps B/C).
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        assert "Anticipatory tool-call check" in text
        assert "Did you call" in text  # the verification question

    def test_wrap_up_calls_memory_status(self):
        # Wrap-up (folded in from former step 3) calls koan_memory_status
        # for summary regeneration.
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions)
        assert "Wrap-up" in text
        # koan_memory_status appears multiple times; just ensure it's there.
        assert "koan_memory_status" in text

    def test_reports_counts_in_schema_terms(self):
        text = "\n".join(curation.step_guidance(2, _ctx()).instructions).lower()
        assert "added" in text
        assert "updated" in text
        assert "deprecated" in text
        assert "noop" in text
