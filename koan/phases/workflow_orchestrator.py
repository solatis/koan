# Workflow-orchestrator phase -- 2-step workflow.
#
#   Step 1 (Evaluate) -- read workflow-status.md and phase artifacts
#   Step 2 (Propose)  -- call koan_propose_workflow, handle feedback, commit
#
# Step 2 is double-gated: both koan_propose_workflow and koan_set_next_phase
# must be called before completion.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "workflow-orchestrator"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Evaluate",
    2: "Propose",
}

SYSTEM_PROMPT = (
    "You are a workflow orchestrator for a coding task planning pipeline. Your role"
    " is to evaluate what has been accomplished and guide the user in choosing what"
    " to do next.\n"
    "\n"
    "## Your responsibilities\n"
    "\n"
    "1. Read available context (workflow-status.md and any phase artifacts)\n"
    "2. Understand what was accomplished and what options are available\n"
    "3. Present a clear status report and phase options to the user\n"
    "4. Hold a conversation until the user's intent is clear\n"
    "5. Commit the next phase decision via koan_set_next_phase\n"
    "\n"
    "## Communication style\n"
    "\n"
    "- Be concise and direct\n"
    "- Focus on what matters to the user's goal\n"
    "- When the user's direction is clear, commit it -- don't over-clarify\n"
    "- Present phase options with helpful context, not technical jargon\n"
    "\n"
    "## Constraints\n"
    "\n"
    "- You must call koan_propose_workflow before koan_set_next_phase\n"
    "- You may call koan_propose_workflow multiple times if the user needs more clarification\n"
    "- The phase you commit must be in your available phases list"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    ed = ctx.epic_dir

    if step == 1:
        return StepGuidance(
            title=STEP_NAMES[1],
            instructions=[
                f"Read `{ed}/workflow-status.md` to understand:",
                "",
                "- Which phase just completed",
                "- What artifacts are available",
                "- Which phases are available next",
                "",
                "Then read any relevant artifacts (landscape.md, brief.md, etc.) to",
                "build a thorough understanding of what has been accomplished and what",
                "the user's goal is.",
                "",
                "Do NOT call koan_propose_workflow yet. Comprehend the current state first.",
            ],
        )

    if step == 2:
        from ..lib.phase_dag import PHASE_DESCRIPTIONS
        phase_list = [
            f"- **{p}**: {PHASE_DESCRIPTIONS.get(p, p)}"
            for p in ctx.available_phases
        ]
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Call koan_propose_workflow with:",
                "",
                "1. A **status_report** (markdown) summarizing what was accomplished",
                "   and why the available phases make sense right now",
                "",
                "2. **recommended_phases** -- the available next phases (in order of",
                "   recommendation):",
                "",
                *phase_list,
                "",
                "The user will respond with their direction. If their response is clear,",
                "call koan_set_next_phase to commit the decision (with optional instructions",
                "to focus the next phase). If their response needs clarification, call",
                "koan_propose_workflow again with an updated status report.",
                "",
                "You MUST call both koan_propose_workflow and koan_set_next_phase before",
                "completing this step.",
            ],
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step == 0:
        return 1
    if step == 1:
        return 2
    if step == 2:
        if ctx.proposal_made and ctx.next_phase_set:
            return None
        return 2
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    if step != 2:
        return None
    if not ctx.proposal_made:
        return "You must call koan_propose_workflow before completing this step."
    if not ctx.next_phase_set:
        return "You must call koan_set_next_phase to commit the phase decision before completing this step."
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass
