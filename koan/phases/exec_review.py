# Exec-review phase -- 2-step workflow.
#
#   Step 1 (Verify)  -- read plan and run verification commands; no writes
#   Step 2 (Assess)  -- classify outcome; apply rewrite-or-loopback against
#                       the plan artifact; apply milestones.md UPDATE when
#                       the workflow guidance instructs it (milestones only)
#
# Scope: "general" -- reusable by any workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "general"        # reusable by any workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Verify",
    2: "Assess",
}

PHASE_ROLE_CONTEXT = (
    "You are reviewing the results of an executor's implementation work. The executor was\n"
    "given a plan and implemented it. Your job is to verify what was accomplished, identify\n"
    "deviations from the plan, and assess whether the implementation meets the plan's goals.\n"
    "You may run verification commands (tests, type checks, linting) to confirm the\n"
    "executor's claims.\n"
    "\n"
    "## Your role\n"
    "\n"
    # M4: exec-review gains two artifact-write responsibilities in addition to
    # outcome classification; the "do NOT modify" rule is narrowed to code/implementation.
    "You are a reviewer. You verify the executor's work, classify the outcome,\n"
    "and apply rewrite-or-loop-back semantics to the plan artifact. In the\n"
    "milestones workflow, you also apply the milestones.md UPDATE: mark the\n"
    "completed milestone [done], append the four-subsection Outcome, advance the\n"
    "next [pending] milestone, and adjust remaining milestones based on deviations.\n"
    "You do NOT write code or modify the executor's implementation; you only\n"
    "modify the plan artifact and milestones.md (when applicable).\n"
    "\n"
    "## Evaluation dimensions\n"
    "\n"
    "- **Goal completion**: Were all planned goals met?\n"
    "- **Deviations**: What deviated from the plan, and are the deviations acceptable?\n"
    "- **Quality**: Does the implementation appear correct? Run verification commands.\n"
    "- **Completeness**: Was any planned work left incomplete?\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read the executor's deviation report from the conversation context.\n"
    "- MUST run at least one verification command (build, tests, type check) if applicable.\n"
    "- MUST NOT write code or modify the executor's implementation.\n"
    "- MUST classify the outcome (Clean / Minor deviations / Significant deviations / Incomplete).\n"
    "- MUST classify each plan deviation as internal or new-files-needed (rewrite-or-loop-back).\n"
    "- MUST apply milestones.md UPDATE when the workflow guidance instructs it.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines: list[str] = []
        # phase_instructions at top per established pattern (intake.py, execute.py)
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])
        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])
        # brief.md gives exec-review the original scope/decisions; the executor may
        # have diverged from the milestone plan in ways that still satisfy the initiative.
        lines.extend([
            "## Read initiative context",
            "",
            "Read `brief.md` from the run directory before verifying executor output.",
            "It contains the frozen initiative scope, decisions, and constraints from",
            "intake. Use it to assess whether the implementation respects every stated",
            "decision and constraint, not just the milestone-specific plan.",
            "",
            # M4: milestones.md read directive inserted here so exec-review has the
            # current milestone state in context before writing the UPDATE in step 2.
            "## Read milestone state (milestones workflow only)",
            "",
            "If the workflow guidance above instructs you to update milestones.md, read",
            "`milestones.md` from the run directory now. You will need its current state",
            "to apply the UPDATE in step 2.",
            "",
            "Verify what the executor accomplished. Do NOT make any code changes in this step.",
            "",
            "## What to verify",
            "",
            "1. Read the executor's deviation report from the conversation context (the final",
            "   message from the execute phase).",
            "2. Read the plan artifact and note what was planned.",
            "3. Run verification commands to confirm the executor's claims:",
            "   - Build or compile the project if applicable.",
            "   - Run the test suite or relevant test subset.",
            "   - Run type checks (e.g. `npx tsc --noEmit`) if applicable.",
            "4. List the codebase files the plan specified and confirm they were modified as intended.",
            "",
            "Do NOT write an assessment yet. Verify first.",
            "",
            "End your turn with a verification summary:",
            "- What verification commands you ran and their results",
            "- Which planned goals appear met vs. incomplete",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Report your assessment in this response.",
                "",
                "## Outcome classification",
                "",
                "Classify the execution outcome using exactly one of:",
                "- **Clean execution**: plan was followed, all goals met, no significant deviations.",
                "- **Minor deviations**: plan was mostly followed; deviations are acceptable or trivial.",
                "- **Significant deviations**: deviations require downstream adjustments.",
                "- **Incomplete**: planned work was not done.",
                "",
                "## Assessment structure",
                "",
                "1. **Outcome**: [classification]",
                "2. **Implemented as planned**: what matched the plan",
                "3. **Deviations**: what diverged and why (from the executor's own report + your verification)",
                "4. **Incomplete**: anything the plan specified that was not done",
                "5. **Verification results**: build/test outcomes",
                "",
                # M4: rewrite-or-loopback block for the plan artifact; clean executions
                # skip this step entirely since there are no deviation findings to classify.
                "## Rewrite-or-loop-back of the plan artifact",
                "",
                "After classifying the outcome (Clean / Minor / Significant / Incomplete):",
                "",
                "For each deviation finding, classify it as one of:",
                "",
                "- **Internal**: the producer (plan-spec) could have caught this from the",
                "  files it already loaded (the plan artifact + `brief.md`). The plan was",
                "  flawed in a way visible from its own scope.",
                "- **New-files-needed**: catching this would have required new analysis the",
                "  plan didn't do.",
                "",
                "## What to do with the classification",
                "",
                "- **All findings internal -> rewrite in place**. For targeted fixes, prefer",
                "  `koan_artifact_edit(filename=<plan_artifact>, anchor=..., text=...)`",
                "  for each change. For extensive rewrites, use",
                '  `koan_artifact_write(filename="<plan_artifact>", content=<corrected_plan>)`.',
                "  Use the workflow's plan filename (plan.md or plan-milestone-N.md). The",
                "  corrected plan reflects what the executor should have done; downstream",
                "  phases (next milestone) read it for context.",
                "- **Any finding new-files-needed -> recommend loop-back to plan-spec**.",
                "  Yield with `plan-spec` recommended for re-planning.",
                "- **Clean execution / no deviations**: skip the rewrite-or-loop-back step.",
                "  The plan artifact stands as-is.",
                "",
                # M4: milestones.md UPDATE block; plan-workflow exec-review skips this
                # entirely (no milestones.md exists in plan workflow runs).
                "## Apply milestones.md UPDATE (milestones workflow only)",
                "",
                "If the workflow guidance above instructs you to update `milestones.md`,",
                "apply the UPDATE in this step via `koan_artifact_write`:",
                "",
                "1. Mark the completed milestone `[done]`.",
                "2. Append an `### Outcome` section with the four-subsection structure:",
                "   - **Integration points created** -- new interfaces, extension seams,",
                "     modules subsequent milestones can depend on, named with file paths",
                "     and identifiers.",
                "   - **Patterns established** -- naming, file placement, error handling,",
                "     and test conventions this milestone committed to.",
                "   - **Constraints discovered** -- things harder/different than the sketch",
                "     anticipated; explicit facts that change what future milestones",
                "     can assume.",
                "   - **Deviations from plan** -- what the executor did differently and why,",
                "     sourced from your own deviation classification above.",
                "3. Advance the next `[pending]` milestone to `[in-progress]`.",
                "4. Adjust remaining milestone sketches if the deviations require it.",
                "5. Preserve all prior `[done]` Outcome sections intact.",
                "",
                'Issue `koan_artifact_write(filename="milestones.md", content=<updated>)`',
                "for the UPDATE.",
                "",
                "For the plan workflow, `milestones.md` does not exist -- skip this UPDATE",
                "block entirely.",
                "",
                "The workflow guidance above specifies what to do after this assessment.",
            ],
            # terminal_invoke supplies the phase-boundary invoke_after.
            # next_phase=None: exec-review outcome requires user direction.
            invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases),
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step < TOTAL_STEPS:
        return step + 1
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass
