# Executor phase -- 3-step workflow.
#
#   Step 1 (Comprehend)   -- read artifacts and codebase; build mental model
#   Step 2 (Plan)         -- explain implementation approach (no file written)
#   Step 3 (Implement)    -- implement all changes
#
# The executor is the only agent that writes source code.
# Scope: "general" -- reusable by any workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "executor"
SCOPE = "general"        # reusable by any workflow
TOTAL_STEPS = 3

STEP_NAMES: dict[int, str] = {
    1: "Comprehend",
    2: "Plan",
    3: "Implement",
}

# Phase role context -- empty for executor. The executor's identity is
# delivered via the agent-type system prompt at spawn time (koan/prompts/executor.py).
# The executor does not switch phases, so there is no role-switching context.
PHASE_ROLE_CONTEXT = ""


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines = [
            "Read and understand the implementation scope before writing any code.",
            "",
            "## Artifacts to read",
            "",
        ]

        if ctx.executor_artifacts:
            for artifact in ctx.executor_artifacts:
                lines.append(f"- `{ctx.run_dir}/{artifact}`")
        else:
            lines.append("(No specific artifacts listed -- read all relevant files in the run directory.)")

        lines.extend([
            "",
            "## Instructions from orchestrator",
            "",
            ctx.phase_instructions or "(no additional instructions)",
            "",
            "## What to understand",
            "",
            "Read every artifact. For each file or module they reference, open it and",
            "understand its current state. Build a mental model of:",
            "- What changes are needed",
            "- Which files are affected",
            "- What order makes sense",
            "- Any risks or edge cases",
            "",
            "Do NOT write code in this step.",
            "",
            "Call `koan_complete_step` with a comprehension summary:",
            "- What you will change and in what order",
            "- Files affected",
            "- Any ambiguities or concerns (do not block on these -- note them)",
        ])

        if ctx.retry_context:
            lines.extend([
                "",
                "## Retry context -- read this first",
                "",
                "This is a retry attempt. A previous execution failed. The failure summary is:",
                "",
                ctx.retry_context,
                "",
                "Keep this in mind as you read the artifacts.",
            ])

        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Explain your implementation approach before coding.",
                "",
                "Walk through in your response:",
                "- What you will change and in what order",
                "- Any risks or edge cases you identified",
                "- How you will verify the changes work",
                "",
                "Do NOT write a plan file. This is your reasoning made visible for the",
                "audit trail, communicated as a regular response.",
                "",
                "Call `koan_complete_step` with your approach summary.",
            ],
        )

    if step == 3:
        return StepGuidance(
            title=STEP_NAMES[3],
            instructions=[
                "Implement the changes according to your plan from step 2.",
                "",
                "For each change:",
                "1. Read the target file to confirm its current state.",
                "2. Make the change.",
                "3. Move to the next change.",
                "",
                "## Rationale comments",
                "",
                "When you make an implementation choice, write a brief comment",
                "(1-3 lines) at the code location explaining why. These comments",
                "are the primary record of implementation-level decisions. Focus",
                "on \"why\", not \"what\". Examples: why a function was split a",
                "certain way, why a parameter has a specific default, why one",
                "approach was chosen over another.",
                "",
                "## Trivial issues",
                "",
                "Resolve independently:",
                "- Wrong path \u2192 find the correct one",
                "- Typo or syntax error in plan \u2192 fix it",
                "- Missing import \u2192 add it",
                "",
                "## Genuine ambiguity",
                "",
                "Call `koan_ask_question` when:",
                "- Artifacts are ambiguous about what to build",
                "- You discover a plan/codebase conflict that isn't trivial",
                "- A prerequisite is missing that blocks implementation",
                "",
                "## When done",
                "",
                "Verify your work (run builds/tests if relevant).",
                "Call `koan_complete_step` with a summary of what was implemented:",
                "- Files modified",
                "- Any concerns or observations",
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
