# Core-flows phase -- 2-step workflow.
#
#   Step 1 (Analysis)    -- read intake output and brief; understand scope
#   Step 2 (Core Flows)  -- define user journeys with sequence diagrams
#
# Uses the "decomposer" role (reuses existing permissions).

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "decomposer"
SCOPE = "legacy"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Analysis",
    2: "Core Flows",
}

PHASE_ROLE_CONTEXT = (
    "You are a core-flows analyst for a coding task planner. You read intake"
    " output and the epic brief, then define the user journeys and interaction"
    " flows that the implementation must support.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You define WHAT flows exist and HOW users interact with the system. You do"
    " NOT decide implementation details or story boundaries -- those belong to"
    " downstream phases.\n"
    "\n"
    "## Output\n"
    "\n"
    "One file: **core-flows.md** in the run directory.\n"
    "\n"
    "## Structure\n"
    "\n"
    "For each user journey:\n"
    "- **Journey name**: descriptive title\n"
    "- **Actor**: who initiates the flow\n"
    "- **Trigger**: what starts the flow\n"
    "- **Steps**: numbered sequence of interactions\n"
    "- **Sequence diagram**: mermaid sequenceDiagram showing component interactions\n"
    "- **Edge cases**: exceptional paths and error conditions\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST NOT include implementation details (specific functions, algorithms, data structures).\n"
    "- MUST NOT make decisions that require user input. Those belong to intake.\n"
    "- MUST NOT invent scope not present in landscape.md or brief.md.\n"
    "- MUST ground every flow in codebase findings from landscape.md.\n"
    "- SHOULD keep flows focused: one journey per logical user interaction.\n"
    "\n"
    "## Tools available\n"
    "\n"
    "- All read tools (read, bash, grep, glob, find, ls) -- for reading intake output and codebase.\n"
    "- `koan_request_scouts` -- to request additional codebase exploration if needed.\n"
    "- `write` / `edit` -- for writing output files inside the run directory.\n"
    "- `koan_complete_step` -- to signal step completion."
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        return StepGuidance(
            title=STEP_NAMES[1],
            instructions=[
                "Read the intake output and brief. Build a complete understanding of the scope",
                "before producing any output.",
                "",
                "## Files to read",
                "",
                f"- `{ctx.run_dir}/landscape.md` -- task summary, prior art, codebase findings, project conventions, decisions, and constraints",
                f"- `{ctx.run_dir}/brief.md` -- epic brief: problem statement, goals, and constraints",
                "",
                "## What to understand",
                "",
                "After reading, you should be able to answer:",
                "- What are the distinct user-facing interactions this epic introduces or changes?",
                "- What existing flows are affected?",
                "- What components participate in each flow?",
                "- What are the key integration boundaries?",
                "",
                "Do not write any output files during this step.",
            ],
        )

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Produce the core-flows document with user journeys and sequence diagrams.",
                "",
                f"Write `{ctx.run_dir}/core-flows.md` with one section per user journey.",
                "",
                "For each journey include:",
                "- Journey name, actor, and trigger",
                "- Numbered interaction steps",
                "- A mermaid sequenceDiagram showing component interactions",
                "- Edge cases and error conditions",
                "",
                "Ground every flow in codebase findings from landscape.md.",
                "Do not invent flows not implied by the brief's goals.",
                "",
                "After writing all flows, call `koan_complete_step` with a summary:",
                "number of journeys documented and the key integration boundaries identified.",
            ],
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
