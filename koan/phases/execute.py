# Execute phase (orchestrator-side) -- 2-step post-execution inline review flow.
#
#   Step 1 (Verify)  -- read context artifacts; run bash verification commands
#   Step 2 (Assess)  -- classify conformance; append sidecar notes; branch on outcome
#
# The executor has already run when this phase starts: koan_set_phase("execute",
# plan_file=...) froze the plan, spawned the executor (blocking), and returned its
# deviation report as the tool result. The orchestrator enters this phase as the
# INLINE REVIEWER of the executor's work -- independent of the executor's own
# exit-based outcome.
#
# Conformance is determined by the orchestrator's inline verification (bash checks),
# not the executor's exit code. A clean-exit run may still be marked non-conforming
# when verification fails.
#
# CLEAN outcome: in milestones/initiative workflows (gated by phase_instructions),
# apply the milestones.md UPDATE via koan_artifact_edit, then advance. In the plan
# workflow (no milestones.md), advance to curation directly.
#
# NON-CONFORMING outcome: if the executed plan is a BASE plan (no -remediation-K),
# drive one automated remediation: transition to plan, write
# <plan-base>-remediation-1.md folding the failure signal, re-execute.
# If the executed plan is ALREADY a remediation, the automated cap is reached:
# escalate to the user via koan_ask_question.
#
# General-purpose: reusable by any workflow. Scope: "general".

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

# The orchestrator IS the reviewer here (no separate exec-review sub-agent in M5).
# "do NOT call koan_request_executor" is documented because the tool was removed
# in M4 and the prompt-space habit needs clearing. Similarly, exec-review is
# bypassed by M5 transitions -- the orchestrator must not try to route there.
PHASE_ROLE_CONTEXT = (
    "You are in the execute phase acting as the POST-EXECUTION INLINE REVIEWER.\n"
    "\n"
    "The executor has already run. When you called koan_set_phase('execute',\n"
    "plan_file=...), koan froze the plan, spawned the executor (blocking), and\n"
    "returned its deviation report as the tool result. You are now the independent\n"
    "reviewer of that work.\n"
    "\n"
    "## Your responsibilities\n"
    "\n"
    "1. Verify what was accomplished by running bash checks (build, tests,\n"
    "   type-checks) -- your verification is authoritative and may mark a\n"
    "   clean-exit run non-conforming if checks fail.\n"
    "2. Classify the outcome (conforming / non-conforming) and append conformance\n"
    "   notes to the plan's .review.md sidecar via koan_artifact_edit.\n"
    "3. On a clean/conforming result: apply the milestones.md UPDATE (milestones/\n"
    "   initiative workflows only, gated by phase_instructions) and advance.\n"
    "4. On a non-conforming result: drive one automated remediation if the\n"
    "   executed plan is a base plan; escalate to the user via koan_ask_question\n"
    "   if the executed plan is already a remediation.\n"
    "\n"
    "## What you must NOT do\n"
    "\n"
    "- Do NOT call koan_request_executor -- it no longer exists. Execution is\n"
    "  triggered only by koan_set_phase('execute', plan_file=...).\n"
    "- Do NOT edit the frozen plan artifact -- it is immutable. Conformance notes\n"
    "  go to the .review.md sidecar (freeze-exempt); a non-conforming result\n"
    "  requires a new -remediation-K.md successor written via koan_artifact_write.\n"
    "- Do NOT advance to exec-review -- this phase absorbs exec-review's role.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Return the step guidance for the given step number.

    Step 1 (Verify) instructs the orchestrator to read context artifacts
    (brief.md, the executed plan, and milestones.md if applicable), then run
    bash verification commands (build/tests/type-checks) and end with a
    verification summary.

    Step 2 (Assess) instructs the orchestrator to classify conformance
    (authoritative: bash results override the executor's exit code), append
    a '## Execution review (post-exec)' section to the plan's .review.md sidecar
    via koan_artifact_edit, then branch:
    - CLEAN: apply milestones.md UPDATE (milestones/initiative only, gated by
      phase_instructions) and advance.
    - NON-CONFORMING, base plan: koan_set_phase("plan"), write
      <plan-base>-remediation-1.md folding the failure signal, re-execute.
    - NON-CONFORMING, already-remediation: koan_ask_question to escalate
      (accept-as-is / abort / direct-further-attempts).
    """
    if step == 1:
        lines: list[str] = []

        # phase_instructions at top per established pattern (exec_review.py, intake.py).
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])

        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])

        lines.extend([
            "## Read context artifacts",
            "",
            "Read `brief.md` from the run directory -- it contains the frozen initiative",
            "scope, decisions, and constraints from intake. Use it to assess whether the",
            "implementation respects every stated decision and constraint, not just the",
            "milestone-specific plan.",
            "",
            "Read the executed plan artifact (the filename you passed as plan_file= to",
            "koan_set_phase -- e.g. plan.md or plan-milestone-N.md). Note what was planned.",
            "",
            "## Read milestone state (milestones workflow only)",
            "",
            "If the workflow guidance above instructs you to update milestones.md, read",
            "`milestones.md` from the run directory now. You will need its current state",
            "to apply the UPDATE in step 2.",
            "",
            "## Run verification commands",
            "",
            "Run bash verification commands to confirm what the executor accomplished:",
            "- Build or compile the project if applicable.",
            "- Run the test suite or relevant test subset.",
            "  Use `grep -q PATTERN file && echo \"FAIL\"` for negative-presence checks.",
            "- Run type checks (e.g. `npx tsc --noEmit`) if applicable.",
            "",
            "Compare the executor's deviation report (the tool result from the",
            "koan_set_phase call that entered this phase) against your verification results.",
            "Your bash checks are authoritative -- a clean executor exit does NOT override",
            "failing builds or tests.",
            "",
            "Do NOT write an assessment yet. Verify first.",
            "",
            "End your turn with a verification summary:",
            "- Which verification commands you ran and their results.",
            "- Which planned goals appear met vs. incomplete based on your checks.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Classify conformance and record your assessment.",
                "",
                "## Outcome classification",
                "",
                "Based on your verification results from step 1, classify the outcome:",
                "- **Conforming (clean)**: verification passed; all goals met; any deviations",
                "  are minor and acceptable.",
                "- **Non-conforming**: verification failed (build errors, test failures,",
                "  type errors) OR significant goals were unmet; deviations are material.",
                "",
                "Your verification is authoritative -- a clean executor exit does NOT",
                "override failing bash checks.",
                "",
                "## Append to the review sidecar",
                "",
                "Append a `## Execution review (post-exec)` section to the plan's",
                "`.review.md` sidecar via `koan_artifact_edit`.",
                "The sidecar filename is the plan stem + `.review.md`",
                "(e.g. `plan-milestone-1.review.md` for `plan-milestone-1.md`).",
                "Record in the section:",
                "1. Outcome classification (conforming / non-conforming).",
                "2. Verification commands run and their results.",
                "3. Any deviations from plan (from the executor's report and your checks).",
                "4. Summary of what was accomplished.",
                "",
                "The `.review.md` sidecar is freeze-exempt -- you can append to it even",
                "though the plan itself is frozen.",
                "",
                "## Branch on outcome",
                "",
                "### CLEAN / CONFORMING path",
                "",
                "If the workflow guidance above instructs you to update `milestones.md`,",
                "apply the milestones.md UPDATE via `koan_artifact_edit`:",
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
                "     sourced from the executor's deviation report and your verification above.",
                "3. Advance the next `[pending]` milestone to `[in-progress]`.",
                "4. Preserve all prior `[done]` Outcome sections intact.",
                "",
                "Read milestones.md via `koan_artifact_read` to get current content and",
                "anchors; then issue `koan_artifact_edit(filename=\"milestones.md\", ...)`",
                "for the UPDATE -- surgical edits preferred, or edit_type=\"replace\" with",
                "the opening anchor for a full replacement.",
                "",
                "After the UPDATE (or immediately for the plan workflow where no UPDATE is",
                "needed), end your turn. The workflow guidance above specifies what to do next.",
                "",
                "### NON-CONFORMING path",
                "",
                "#### If the executed plan is a BASE plan (no `-remediation-K` in the name):",
                "",
                "1. Call `koan_set_phase(\"plan\")` to return to the planning phase.",
                "2. Write a remediation plan `<plan-base>-remediation-1.md` via",
                "   `koan_artifact_write`. Fold the failure signal into the new plan:",
                "   - The executor's deviation report.",
                "   - Your verification output (commands run + failures).",
                "   - Any still-unaddressed prior findings from the .review.md sidecar.",
                "   The remediation plan is the executor's only input -- the failure signal",
                "   MUST be in the artifact text (brief 5.3 / artifact-as-interface).",
                "   Writing it fires the PLAN_REVIEWER automatically with the full",
                "   predecessor chain.",
                "3. After reviewing the findings, incorporate valid findings via",
                "   `koan_artifact_edit` on the remediation plan.",
                "4. Call `koan_set_phase(\"execute\", plan_file=\"<plan-base>-remediation-1.md\")`",
                "   to re-execute.",
                "",
                "#### If the executed plan is ALREADY a remediation (name contains `-remediation-K`):",
                "",
                "The automated one-attempt cap is reached. Escalate to the user via",
                "`koan_ask_question` with these options:",
                "- **accept-as-is**: acknowledge the residual gap; append an",
                "  `ACCEPTED AS-IS: <gap summary>` entry to the .review.md sidecar via",
                "  koan_artifact_edit, then advance to the next phase per workflow guidance.",
                "- **abort**: end the run.",
                "- **direct-further-attempts**: write another remediation as the user directs.",
                "",
                "The cap is prompt-driven: the registry still allows contiguous remediations",
                "so the user can direct further attempts after escalation if needed.",
            ],
            # terminal_invoke supplies the phase-boundary invoke_after. With next_phase=None
            # (all workflows set execute.next_phase=None because the review outcome determines
            # the path), this renders the yield-to-user hand-back with the workflow's suggested
            # phases. The actual phase-transition calls are in the branch instructions above.
            invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases),
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    """Return the next step number, or None when all steps are complete."""
    if step < TOTAL_STEPS:
        return step + 1
    return None  # linear


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    """Return an error string if the step completion requirements are not met."""
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    """Handle a loop-back (re-entering a prior step). No-op for execute phase."""
    pass
