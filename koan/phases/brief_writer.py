# Brief-writer phase -- 3-step workflow.
#
#   Step 1 (Read)           -- read landscape.md; build mental model; no writes
#   Step 2 (Draft & Review) -- write brief.md + review gate (loops until Accept)
#   Step 3 (Finalize)       -- phase complete
#
# Step 2 is review-gated via validate_step_completion.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .review_protocol import REVIEW_PROTOCOL

ROLE = "brief-writer"
TOTAL_STEPS = 3

STEP_NAMES: dict[int, str] = {
    1: "Read",
    2: "Draft & Review",
    3: "Finalize",
}

SYSTEM_PROMPT = (
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
    "One file: **brief.md** in the epic directory.\n"
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
    "\n"
    + REVIEW_PROTOCOL
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines = [
            f"Read `{ctx.epic_dir}/landscape.md`. Build a thorough mental model of:",
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
                f"Draft `{ctx.epic_dir}/brief.md` with the required sections",
                "(Summary, Context & Problem, Goals, Constraints). Keep it under 50",
                "lines. No UI flows, no technical design, no implementation details.",
                "",
                f"After writing, invoke `koan_review_artifact` with the path to `{ctx.epic_dir}/brief.md`.",
            ],
        )

    if step == 3:
        return StepGuidance(title=STEP_NAMES[3], instructions=["Phase complete."])

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step == 0:
        return 1
    if step == 1:
        return 2
    if step == 2:
        if ctx.last_review_accepted is True:
            return 3
        return 2
    if step == 3:
        return None
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    if step != 2:
        return None
    if ctx.last_review_accepted is None:
        return "You must call koan_review_artifact to present brief.md for review before completing this step."
    if ctx.last_review_accepted is False:
        return "The user requested revisions. Address the feedback, then call koan_review_artifact again."
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass
