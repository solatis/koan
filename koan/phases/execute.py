# Execute phase (orchestrator-side) -- 2-step workflow.
#
#   Step 1 (Compose)  -- read artifacts; compose koan_request_executor call
#   Step 2 (Request)  -- call koan_request_executor; report result
#
# General-purpose: reusable by any workflow. The workflow's phase_guidance["execute"]
# controls what artifacts and instructions the orchestrator hands off.
# Scope: "general" -- not tied to a specific workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "orchestrator"
SCOPE = "general"        # reusable by any workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Compose",
    2: "Request",
}

PHASE_ROLE_CONTEXT = (
    "You are an execution coordinator. The plan has been written and reviewed.\n"
    "Your job is to compose a clean handoff to the executor agent. You do NOT\n"
    "write code and you do NOT re-evaluate the plan.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You compose a `koan_request_executor` call with the right artifacts and"
    " instructions, then spawn the executor and report the result.\n"
    "\n"
    "## What the executor needs\n"
    "\n"
    "- **artifacts**: File paths relative to the run directory that the executor\n"
    "  must read before coding. These are the primary source of truth.\n"
    "- **instructions**: Free-form context NOT captured in the artifact files:\n"
    "  key decisions from plan-review, user clarifications, constraints.\n"
    "  Do NOT repeat artifact contents -- the executor reads them directly.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST call koan_request_executor and wait for it to complete.\n"
    "- MUST NOT write code yourself.\n"
    "- MUST report the result to the user after the executor exits.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines = [
            "Read the artifacts and compose the executor handoff. Do NOT call koan_request_executor yet.",
            "",
        ]

        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])

        if ctx.phase_instructions:
            lines.extend([
                "## Workflow guidance",
                "",
                ctx.phase_instructions,
                "",
            ])

        lines.extend([
            "## Compose the koan_request_executor call",
            "",
            "Review the artifacts the executor will need and decide:",
            "- **artifacts**: Which files in the run directory should the executor read?",
            "  Include the plan (plan.md) and any other files with context not captured",
            "  in the plan itself.",
            "- **instructions**: What context from this session is not in the artifact files?",
            "  Include: key findings from plan-review, user clarifications received,",
            "  constraints emphasized by the user. Keep it concise.",
            "",
            "Call `koan_complete_step` with the composed call parameters (artifacts list",
            "and instructions text) so they appear in the audit trail before execution.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Call `koan_request_executor` with the artifacts and instructions from step 1.",
                "",
                "```",
                "koan_request_executor(",
                '    artifacts=["plan.md", ...],',
                '    instructions="...",',
                ")",
                "```",
                "",
                "This tool blocks until the executor exits. While it's running, the",
                "executor is implementing the changes.",
                "",
                "## After the executor exits",
                "",
                "Report the result to the user:",
                "- If succeeded: summarize what was implemented.",
                "- If failed: relay the failure and suggest next steps (re-run, plan revision, etc.).",
                "",
                "Then call `koan_complete_step` to trigger the phase boundary.",
            ],
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step < TOTAL_STEPS:
        return step + 1
    return None  # linear


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass
