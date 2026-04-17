# Brief-writer phase -- 2-step workflow.
#
#   Step 1 (Read)   -- read landscape.md; build mental model; no writes
#   Step 2 (Draft)  -- write brief.md; artifact available in panel
#
# SCOPE="legacy": not used by any active workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "brief-writer"
SCOPE = "legacy"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Read",
    2: "Draft",
}

PHASE_ROLE_CONTEXT = (
    "You are a brief writer for a coding task planner. You read intake context and"
    " produce a compact epic brief -- a product-level document that captures the"
    " problem, who's affected, goals, and constraints.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You distill intake findings into a clear problem statement. You do NOT design"
    " solutions, plan implementation, or decompose into stories.\n"
    "\n"
    "## Output\n"
    "\n"
    "One file: **brief.md** in the run directory.\n"
    "\n"
    "## Structure\n"
    "\n"
    "- **Summary**: 3-8 sentences describing what this epic is about.\n"
    "- **Context & Problem**: Who's affected, where in the product, the current pain.\n"
    "- **Goals**: Numbered list of measurable objectives.\n"
    "- **Constraints**: Hard constraints grounding decisions (from landscape.md).\n"
    "\n"
    "Keep the brief compact -- under 50 lines. No UI flows, no technical design,"
    " no implementation details.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines = [
            f"Read `{ctx.run_dir}/landscape.md`. Build a thorough mental model of:",
            "",
            "- Task Summary -- what is being built or changed",
            "- Prior Art -- previous attempts, related systems, or prior conversations",
            "- Codebase findings -- architecture, patterns, integration points",
            "- Decisions -- every question asked and the user's answer",
            "- Constraints -- technical, timeline, compatibility requirements",
            "",
            "Do NOT write any files in this step. Comprehend before drafting.",
        ]
        if ctx.phase_instructions:
            lines.extend(["", "## Additional Context from Workflow Orchestrator", "", ctx.phase_instructions])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                f"Draft `{ctx.run_dir}/brief.md` with the required sections",
                "(Summary, Context & Problem, Goals, Constraints). Keep it under 50",
                "lines. No UI flows, no technical design, no implementation details.",
                "",
                "brief.md is now available in the artifacts panel for review.",
                "Call `koan_complete_step` when done.",
            ],
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step == 1:
        return 2
    return None  # step 2 is terminal


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass
