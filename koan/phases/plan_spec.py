# Plan-spec phase -- 2-step workflow.
#
#   Step 1 (Analyze)  -- review intake context and codebase; no writes
#   Step 2 (Write)    -- write plan.md to the run directory
#
# Scope: "plan" -- specific to the plan workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "orchestrator"
SCOPE = "plan"           # specific to the plan workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Analyze",
    2: "Write",
}

SYSTEM_PROMPT = (
    "You are a technical architect writing an implementation plan for a coding task.\n"
    "\n"
    "You read the codebase thoroughly before planning. Your plans reference actual"
    " file paths and function names, not abstract descriptions. You write instructions"
    " specific enough that a coding agent can execute them without making judgment"
    " calls about what to do.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You plan implementation. You do NOT write code. You produce a plan.md that an"
    " executor agent will follow to implement the changes.\n"
    "\n"
    "## Output\n"
    "\n"
    "One file: **plan.md** in the run directory.\n"
    "\n"
    "## plan.md structure\n"
    "\n"
    "- **Approach summary**: 2-4 sentences on the overall strategy.\n"
    "- **Key decisions**: Numbered list of architectural/design decisions made.\n"
    "- **Implementation steps**: Numbered list, each specifying file path,\n"
    "  function/location, and the exact change. Be specific -- include function\n"
    "  signatures and type names where relevant.\n"
    "- **Constraints**: Hard boundaries the executor must respect.\n"
    "- **Verification**: How to verify the implementation is correct.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read the codebase files the plan references. Verify paths, signatures,\n"
    "  and types before including them in the plan.\n"
    "- MUST NOT write code -- write instructions for an executor that will write code.\n"
    "- MUST NOT invent file paths or function names without verifying them in the codebase.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines = [
            "Read and analyze before writing the plan. Do NOT write any files in this step.",
            "",
            "## What to read",
            "",
            "1. Review what you learned during intake \u2014 the task scope, codebase",
            "   findings, decisions, and constraints are in your context.",
            "2. Read every file the plan will reference. Open the actual source files",
            "   to verify function signatures, type names, and integration points.",
            "   Do not rely on intake memory alone \u2014 verify against the actual code.",
            "",
            "## What to analyze",
            "",
            "After reading, identify:",
            "- **Key architectural decisions**: What approach will you take and why?",
            "- **Integration points**: Which existing code will the changes touch?",
            "- **Risks**: Where could things go wrong during execution?",
            "- **Order**: What is the safest sequence of implementation steps?",
            "",
            "Call `koan_complete_step` with an analysis summary:",
            "- Overall approach (2-3 sentences)",
            "- Files that will be modified",
            "- Key decisions and rationale",
            "- Any ambiguities or risks spotted",
        ]
        if ctx.phase_instructions:
            lines.extend(["", "## Additional Context from Workflow Orchestrator", "", ctx.phase_instructions])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                f"Write `{ctx.run_dir}/plan.md` with a complete implementation plan.",
                "",
                "## Required sections",
                "",
                "### Approach summary",
                "2-4 sentences on the overall strategy.",
                "",
                "### Key decisions",
                "Numbered list of architectural/design decisions. For each decision, state",
                "the choice made and why (alternative considered + reason rejected if applicable).",
                "",
                "### Implementation steps",
                "Numbered list. Each step must specify:",
                "- **File**: exact path relative to project root",
                "- **Location**: function name, class, or section",
                "- **Change**: what to add, modify, or remove -- be specific",
                "  Include function signatures, type names, and interface names where relevant.",
                "",
                "Order steps so that each step's dependencies are satisfied by prior steps.",
                "",
                "### Constraints",
                "Hard boundaries the executor must respect (from intake findings).",
                "",
                "### Verification",
                "How to verify the implementation is correct (tests to run, behaviors to check).",
                "",
                "## After writing",
                "",
                "plan.md is now available in the artifacts panel for review.",
                "Call `koan_complete_step` when done.",
            ],
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step < TOTAL_STEPS:
        return step + 1
    return None  # linear, no review gate


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass
