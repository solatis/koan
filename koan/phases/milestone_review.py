# Milestone-review phase -- 2-step workflow.
#
#   Step 1 (Read)      -- read milestones.md and codebase areas; no writes
#   Step 2 (Evaluate)  -- classify findings; rewrite internal ones against
#                         milestones.md or recommend loop-back to milestone-spec
#
# Rewrite-or-loop-back: internal findings are fixed via koan_artifact_write
# (preserving [done] Outcome sections); new-files findings surface via yield.
# Scope: "milestones" -- specific to the milestones workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "milestones"     # specific to the milestones workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Read",
    2: "Evaluate",
}

PHASE_ROLE_CONTEXT = (
    "You are the adversarial reviewer for a milestone decomposition.\n"
    "\n"
    "You are the ONLY phase that independently verifies the decomposition against\n"
    "the codebase. Intake explored and gathered context. Milestone-spec decomposed\n"
    "that context into milestones. Neither was asked to doubt the other. Your job\n"
    "is to doubt both.\n"
    "\n"
    "## Your role\n"
    "\n"
    "Find problems that would cause downstream plan-spec sessions to fail or\n"
    "produce wrong plans. For every milestone, map its stated scope to actual\n"
    "files and modules in the codebase. Verify those files exist. Verify the\n"
    "ownership boundaries the decomposition implies are real.\n"
    "\n"
    "A missed issue here is inherited by every subsequent plan-spec and executor\n"
    "session. An ordering error or scope overlap at this layer contaminates every\n"
    "downstream plan and execution.\n"
    "\n"
    # M4: rewrite-or-loopback semantics; prompt discipline keeps milestone-review
    # rewriting only milestones.md (not plan artifacts or other files).
    "You apply rewrite-or-loop-back semantics. For each finding, you judge whether\n"
    "the producer (milestone-spec) could have caught it from the files it already\n"
    "loaded (`milestones.md` body + `brief.md`); if yes, you rewrite milestones.md\n"
    "in place via `koan_artifact_write`. If the finding requires new files, you\n"
    "recommend loop-back to milestone-spec via the yield. See `docs/phase-trust.md`\n"
    "for the full doctrine.\n"
    "\n"
    "## Evaluation dimensions\n"
    "\n"
    "- **Scope**: Is each milestone well-bounded? Can plan-spec read all files in\n"
    "  the milestone's scope and still produce a detailed plan?\n"
    "- **Ordering**: Are dependencies correct? Can each milestone be started after\n"
    "  the prior one without requiring work from a later milestone?\n"
    "- **Completeness**: Are there gaps? Work that belongs to the initiative but\n"
    "  no milestone covers?\n"
    "- **Independence**: Can each milestone be delivered without the next being\n"
    "  started? Do any two milestones claim overlapping file/module ownership?\n"
    "- **Feasibility**: Is each milestone's sketch detailed enough to plan from?\n"
    "- **Sizing**: Does each milestone fall within the sizing heuristics? Roughly\n"
    "  5-30 files, 10-30 expected plan steps, sketch of 6 sentences or fewer.\n"
    "  Milestones outside these bounds should be flagged.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read milestones.md before evaluating.\n"
    "- MUST open the actual files and modules each milestone claims to own.\n"
    "  Verify they exist and that the boundaries are real.\n"
    "- MUST check for overlapping ownership between milestones.\n"
    "- MUST classify findings by severity (Critical / Major / Minor).\n"
    "- MUST classify each finding as internal or new-files-needed.\n"
    "- MUST issue koan_artifact_write against milestones.md for internal findings.\n"
    "- When rewriting, MUST preserve all [done] Outcome sections intact.\n"
    "- MUST recommend loop-back for new-files findings by ending your turn (no\n"
    "  tool call) with the recommendation, handing the decision to the user.\n"
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
        # brief.md gives the reviewer the authoritative scope/decisions to check
        # milestones against, independent of what intake communicated in chat.
        lines.extend([
            "## Read initiative context",
            "",
            "Read `brief.md` from the run directory before evaluating the decomposition.",
            "It contains the frozen initiative scope, decisions, and constraints from",
            "intake. Use it to check whether milestones cover all in-scope work and",
            "respect every stated constraint and decision.",
            "",
            "Read and verify before evaluating. Do NOT write anything in this step.",
            "",
            "## Verification mandate",
            "",
            "You are the only phase that independently checks the decomposition against",
            "the codebase. Intake and milestone-spec trusted each other. You trust nobody.",
            "",
            "## What to read and verify",
            "",
            "1. Read `milestones.md` from start to finish.",
            "2. For each milestone, open the actual files and modules it claims to own.",
            "   Verify they exist. Verify the module boundaries the decomposition assumes",
            "   are real -- do the files form a connected subgraph, or does the milestone",
            "   cut across strongly-connected components?",
            "3. Check for overlapping ownership: do any two milestones claim the same",
            "   file or function? Overlapping ownership means they are not independent.",
            "4. Check ordering: would implementing milestone N require changes that",
            "   milestone N+1 also modifies?",
            "5. Estimate sizing: roughly how many files does each milestone touch?",
            "   Would the resulting plan likely exceed 30 steps?",
            "",
            "End your turn with a verification summary:",
            "- What you verified (files opened, boundaries checked)",
            "- Ownership overlaps found (if any)",
            "- Sizing estimates per milestone",
            "- Immediate concerns",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Report your findings in this response.",
                "",
                "## Compound-risk framing",
                "",
                "Every issue you miss here propagates to every subsequent plan-spec and",
                "executor session. Classify accordingly -- when in doubt, escalate severity.",
                "",
                "## Severity classification",
                "",
                "- **Critical**: a fundamental problem (wrong ordering, impossible dependency,",
                "  overlapping ownership, missing major area) that would cause downstream",
                "  plan-spec sessions to fail or produce wrong plans.",
                "- **Major**: significant gap or scope problem requiring milestone revision.",
                "- **Minor**: small issue the milestone-spec phase can address independently.",
                "",
                "## Evaluation dimensions",
                "",
                "For each dimension, report findings or confirm it is sound:",
                "- **Scope**: Are milestones well-bounded? Can plan-spec read all relevant",
                "  files without exhausting context?",
                "- **Ordering**: Are dependencies correct? Are any milestones misordered?",
                "- **Completeness**: Are there gaps in coverage?",
                "- **Independence**: Can each be delivered without the next? Any overlapping",
                "  file/module ownership between milestones?",
                "- **Feasibility**: Is each sketch detailed enough to plan from?",
                "- **Sizing**: Does each milestone fall within 5-30 files, 10-30 expected",
                "  plan steps, and 6 sentences or fewer in its sketch? Flag outliers.",
                "",
                # M4: rewrite-or-loopback block; runs after the evaluation dimensions.
                # The [done] Outcome preservation rule is critical -- exec-review is
                # the only phase that writes Outcome sections; milestone-review must
                # not destroy them when rewriting milestones.md for internal findings.
                "## Rewrite-or-loop-back classification",
                "",
                "For each finding, classify it as one of:",
                "",
                "- **Internal**: the producer (milestone-spec) could have caught this from",
                "  files it already loaded (`milestones.md` body + `brief.md`). Examples:",
                "  a sizing violation, an ordering inconsistency, a milestone scope that",
                "  contradicts brief.md.",
                "- **New-files-needed**: catching this would have required loading additional",
                "  codebase files. Examples: a milestone claims ownership of a file that",
                "  doesn't exist in the codebase.",
                "",
                "## What to do with the classification",
                "",
                "- **All findings internal -> rewrite in place**. For targeted fixes, prefer",
                "  `koan_artifact_edit(filename=\"milestones.md\", anchor=..., text=...)`",
                "  for each change (preserving `[done]` Outcome sections",
                "  is especially safe with surgical edits). For extensive rewrites, use",
                '  `koan_artifact_write(filename="milestones.md", content=<revised>)` --',
                "  preserve all `[done]` entries and their Outcome sections intact.",
                "  Then yield with `plan-spec` recommended.",
                "- **Any finding new-files-needed -> recommend loop-back**. Do NOT call",
                "  `koan_artifact_write`. Yield with `milestone-spec` recommended.",
                "- **Mixed**: rewrite the internal findings in place AND recommend loop-back",
                "  via the yield.",
                "",
                "## After reporting",
                "",
                "The workflow guidance above specifies where to go next.",
            ],
            # terminal_invoke supplies the phase-boundary invoke_after.
            # next_phase=None: review outcome requires user direction.
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
