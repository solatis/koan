# Execute phase (orchestrator-side) -- 3-step Run/Verify/Reconcile flow.
#
#   Step 1 (Run)        -- identify the plan; call koan_request_executor; read the report
#   Step 2 (Verify)     -- run bash verification commands; authoritative over executor report
#   Step 3 (Reconcile)  -- classify outcome; record inline ## Execution N section;
#                          on CONFORMING advance; on NON-CONFORMING re-run or escalate
#
# M5: Execution is now the orchestrator's explicit act. koan_set_phase("execute")
# is pure routing; koan_request_executor is called from within this phase to launch
# the executor. Re-execution is the orchestrator's own agency: call koan_request_executor
# again within Reconcile with an edited plan or free-form fix instructions. There is no
# .review.md sidecar, no frozen flag -- outcomes are recorded inline in the plan's
# ## Execution N [CONFORMING | NON-CONFORMING] section.
# M6: -remediation-K successors are fully removed; re-execution edits the living plan.
#
# General-purpose: reusable by any workflow. Scope: "general".

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "general"        # reusable by any workflow
TOTAL_STEPS = 3

STEP_NAMES: dict[int, str] = {
    1: "Run",
    2: "Verify",
    3: "Reconcile",
}

# The orchestrator DRIVES execution from within this phase. It calls
# koan_request_executor, independently verifies the result, and reconciles.
# Re-execution is expressed as repeated koan_request_executor calls --
# get_next_step stays a pure linear query and does not observe conformance.
PHASE_ROLE_CONTEXT = (
    "You are in the execute phase acting as the EXECUTION DRIVER AND INLINE REVIEWER.\n"
    "\n"
    "You launch the executor, independently verify the result, and reconcile.\n"
    "Re-execution is your own agency: if verification fails, call koan_request_executor\n"
    "again (editing the plan in place first or passing free-form fix instructions).\n"
    "\n"
    "## Your responsibilities\n"
    "\n"
    "1. Launch the executor via koan_request_executor with the appropriate plan.\n"
    "2. Verify what was accomplished by running bash checks (build, tests,\n"
    "   type-checks) -- your verification is authoritative and may mark a\n"
    "   clean-exit run non-conforming if checks fail.\n"
    "3. Classify the outcome (conforming / non-conforming) and record it inline\n"
    "   in the plan via koan_artifact_edit as '## Execution N [CONFORMING | NON-CONFORMING]'.\n"
    "4. On a conforming result: apply the milestones.md UPDATE (milestones/\n"
    "   initiative workflows only, gated by phase_instructions) and advance.\n"
    "5. On a non-conforming result: edit the plan in place or compose free-form\n"
    "   fix instructions and call koan_request_executor again, then re-verify.\n"
    "   On repeated failure, escalate to the user via koan_ask_question.\n"
    "\n"
    "## What you must NOT do\n"
    "\n"
    "- Do NOT write a .review.md sidecar -- there is no such file in this model.\n"
    "- Do NOT write a new plan file -- edit the living plan in place.\n"
    "- Do NOT loop back via get_next_step -- re-execution is repeated koan_request_executor.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Return the step guidance for the given step number.

    Step 1 (Run) instructs the orchestrator to identify the plan for this run
    and launch koan_request_executor. Step 2 (Verify) instructs independent
    bash verification. Step 3 (Reconcile) instructs outcome classification,
    inline recording, milestones.md UPDATE, and optional re-execution.
    """
    if step == 1:
        lines: list[str] = []

        # phase_instructions at top per established pattern.
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])

        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])

        lines.extend([
            "## Identify the plan for this run",
            "",
            "In the **plan workflow**: the plan is `plan.md`.",
            "",
            "In the **milestones/initiative workflows**: read `milestones.md` from the",
            "run directory, identify the `[in-progress]` milestone, and use its associated",
            "`plan-milestone-N.md` artifact.",
            "",
            "## Launch the executor",
            "",
            "Call `koan_request_executor(plan_file=<that plan>)` to spawn the executor.",
            "The tool blocks until the executor exits and returns its deviation report.",
            "",
            "Read and understand the deviation report: what was implemented, what",
            "deviated from the plan, and what was left incomplete.",
            "",
            "End your turn with a one-line note of what ran and the top-level outcome",
            "from the deviation report.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        lines = []

        lines.extend([
            "## Run verification commands",
            "",
            "Run bash verification commands to confirm what the executor accomplished:",
            "- Build or compile the project if applicable.",
            "- Run the test suite or relevant test subset.",
            "  Use `grep -q PATTERN file && echo \"FAIL\"` for negative-presence checks.",
            "- Run type checks (e.g. `npx tsc --noEmit`) if applicable.",
            "",
            "Your bash checks are **authoritative** -- a clean executor exit does NOT",
            "override failing builds or tests.",
            "",
            # brief.md is injected as a handover -- reference the injected copy
            # rather than directing a koan_artifact_read call.  The conformance
            # assessment framing is preserved.
            "`brief.md` is provided above as a handover -- use it to assess whether",
            "the implementation respects every stated decision and constraint, not just",
            "the milestone-specific plan.",
            "",
            "Read the plan artifact (plan.md or plan-milestone-N.md) to note what was planned.",
            "",
            "If the workflow guidance above instructs you to update `milestones.md`, read it",
            "now so you have the current state for the Reconcile step.",
            "",
            "End your turn with a verification summary:",
            "- Which verification commands you ran and their results.",
            "- Which planned goals appear met vs. incomplete based on your checks.",
        ])
        return StepGuidance(title=STEP_NAMES[2], instructions=lines)

    if step == 3:
        return StepGuidance(
            title=STEP_NAMES[3],
            instructions=[
                "Classify conformance and reconcile the outcome.",
                "",
                "## Outcome classification",
                "",
                "Based on your verification results from step 2, classify the outcome:",
                "- **Conforming**: verification passed; all goals met; any deviations",
                "  are minor and acceptable.",
                "- **Non-conforming**: verification failed (build errors, test failures,",
                "  type errors) OR significant goals were unmet; deviations are material.",
                "",
                "Your verification is authoritative -- a clean executor exit does NOT",
                "override failing bash checks.",
                "",
                "## Record the outcome inline",
                "",
                "Append an `## Execution N [CONFORMING | NON-CONFORMING]` section to the",
                "plan artifact via `koan_artifact_edit` (N = the execution attempt number).",
                "Record in the section:",
                "1. Outcome classification (conforming / non-conforming).",
                "2. Verification commands run and their results.",
                "3. Any deviations from plan (from the executor's report and your checks).",
                "4. Summary of what was accomplished.",
                "",
                "The plan is a living document -- edits are always allowed.",
                "",
                "## Branch on outcome",
                "",
                "### CONFORMING path",
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
                "for the UPDATE -- surgical edits preferred.",
                "",
                "After the UPDATE (or immediately for the plan workflow where no UPDATE is",
                "needed), end your turn. The workflow guidance above specifies what to do next.",
                "",
                "### NON-CONFORMING path",
                "",
                "Edit the plan in place to address the gaps, or compose free-form fix",
                "instructions that describe what to fix. Then call `koan_request_executor`",
                "again to re-run. Re-verify in step 2, then return here.",
                "",
                "On repeated non-conforming results, escalate to the user via",
                "`koan_ask_question` with these options:",
                "- **accept-as-is**: acknowledge the residual gap; record an",
                "  `ACCEPTED AS-IS: <gap summary>` note in the inline `## Execution N`",
                "  section, then advance to the next phase per workflow guidance.",
                "- **abort**: end the run.",
                "- **direct-further-attempts**: continue as the user directs.",
            ],
            # terminal_invoke supplies the phase-boundary invoke_after.
            # With next_phase=None (all workflows set execute.next_phase=None because
            # the conformance verdict determines the path), this yields to the user
            # with the workflow's suggested phases.
            invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases),
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    """Return the next step number, or None when all steps are complete.

    Stays a pure linear query: Run -> Verify -> Reconcile -> end.
    Re-execution is NOT expressed here -- the orchestrator calls
    koan_request_executor again within Reconcile as its own agency.
    """
    if step < TOTAL_STEPS:
        return step + 1
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    """Return an error string if the step completion requirements are not met."""
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    """Handle a loop-back (re-entering a prior step). No-op for execute phase."""
    pass
