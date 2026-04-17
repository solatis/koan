# Plan-review phase -- 2-step workflow.
#
#   Step 1 (Read)      -- review intake context and plan.md; no writes
#   Step 2 (Evaluate)  -- evaluate the plan and report findings via chat
#
# Advisory only: findings are reported in chat, not written to a file.
# Scope: "plan" -- specific to the plan workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "orchestrator"
SCOPE = "plan"           # specific to the plan workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Read",
    2: "Evaluate",
}

PHASE_ROLE_CONTEXT = (
    "You are the adversarial reviewer for an implementation plan.\n"
    "\n"
    "You are the ONLY phase in this workflow that independently verifies claims\n"
    "against the actual codebase. Intake explored and gathered context. Plan-spec\n"
    "structured that context into a plan. Neither was asked to doubt the other.\n"
    "Your job is to doubt both.\n"
    "\n"
    "## Your role\n"
    "\n"
    "Find problems that would cause the executor to fail or produce wrong results.\n"
    "Verify every codebase claim the plan makes -- file paths, function names,\n"
    "interfaces, types -- by reading the actual source files. The plan may reference\n"
    "code that was renamed, moved, or never existed. Find out.\n"
    "\n"
    "Do NOT flag trivial issues the executor can resolve independently (minor typos,\n"
    "missing imports, syntax in snippets). Focus on issues that change the approach.\n"
    "\n"
    "You are advisory -- you do NOT modify plan.md directly. You report findings\n"
    "organized by severity.\n"
    "\n"
    "## Evaluation dimensions\n"
    "\n"
    "- **Completeness**: Does the plan cover every requirement from the intake findings?\n"
    "- **Correctness**: Are the file paths, function names, and interfaces accurate?\n"
    "  Verify against the actual codebase.\n"
    "- **Feasibility**: Are the implementation steps actionable as described? Would\n"
    "  an executor be able to follow them without ambiguity?\n"
    "- **Risks**: What could go wrong during execution? Missing edge cases?\n"
    "- **Gaps**: Anything not addressed that should be?\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read plan.md before evaluating.\n"
    "- MUST read the codebase files the plan references. Verify every claim.\n"
    "- MUST NOT modify plan.md.\n"
    "- MUST NOT flag issues the executor can trivially resolve.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines = [
            "Read and comprehend before evaluating. Do NOT write any files in this step.",
            "",
            "## Your verification mandate",
            "",
            "You are the only phase that independently checks claims against reality.",
            "Intake and plan-spec trusted each other. You trust nobody.",
            "",
            "## What to read",
            "",
            "1. Review the intake findings in your context for the requirements and",
            "   constraints the plan must satisfy.",
            f"2. Read `{ctx.run_dir}/plan.md` from start to finish.",
            "3. For every codebase claim in the plan (file path, function name,",
            "   interface, type), open the actual source file and verify. If the plan",
            "   says 'modify function X in file Y', confirm X exists in Y with the",
            "   signature the plan assumes.",
            "",
            "## Build a mental model",
            "",
            "After reading, you should be able to answer:",
            "- What does the plan claim to change, and in which files?",
            "- Are those files and functions real and accurately described?",
            "- Does the plan cover all requirements from the intake findings?",
            "- Are the implementation steps in the right order?",
            "",
            "Do NOT write an evaluation yet. Comprehend first.",
        ]
        if ctx.phase_instructions:
            lines.extend(["", "## Additional Context from Workflow Orchestrator", "", ctx.phase_instructions])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Evaluate the plan and report findings in your response.",
                "",
                "## What to evaluate",
                "",
                "**Completeness**: Does the plan cover every requirement from the intake findings?",
                "List any requirements not addressed.",
                "",
                "**Correctness**: Are file paths, function names, and interfaces accurate?",
                "Note any incorrect references you verified against the codebase.",
                "",
                "**Feasibility**: Can an executor follow each step without ambiguity?",
                "Note any steps that are vague, contradictory, or would require judgment calls.",
                "",
                "**Risks**: What could go wrong? Missing edge cases, ordering issues, dependencies?",
                "",
                "**Gaps**: Anything the plan should address but doesn't?",
                "",
                "## Severity classification",
                "",
                "Report findings organized by severity:",
                "- **Critical**: would cause the executor to fail or produce wrong results",
                "- **Major**: significant gap or incorrectness requiring plan revision",
                "- **Minor**: small issue the executor can likely resolve independently",
                "",
                "Do NOT flag trivial executor-resolvable issues as major findings.",
                "",
                "## Using koan_ask_question",
                "",
                "If the review surfaces ambiguities requiring user input (requirements unclear,"
                " conflicting constraints, genuine design questions), call `koan_ask_question`.",
                "Only ask questions that affect the evaluation outcome.",
                "",
                "## After reporting",
                "",
                "Call `koan_complete_step` when your evaluation report is delivered in chat.",
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
