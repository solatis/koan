# Frame phase -- 1-step divergent workflow.
#
#   Step 1 (Explore)   -- open-ended dialogue; no fixed artifact; always yields
#
# Frame is the only divergent phase in the system. It is a general-purpose
# exploration partner: the user may bring feature design questions, bug
# hunting and troubleshooting sessions, or general-purpose questions -- the
# phase refuses nothing. Its exit is negotiated with the user and is one of
# three options: promote into another workflow via koan_set_workflow, transition
# to another phase within the current workflow via koan_set_phase, or end the
# workflow via koan_set_phase("done"). The phase never auto-advances under any
# circumstance.
#
# Scope: "general" -- reusable by any workflow; discovery workflow is the
# primary binding, but any workflow can reach frame via koan_set_workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "general"       # reusable; discovery workflow binds it as initial phase
TOTAL_STEPS = 1

STEP_NAMES: dict[int, str] = {
    1: "Explore",
}

# Frame-global role context. Prepended at mcp_endpoint.py step-1 assembly;
# stacks with _DISCOVERY_FRAME_GUIDANCE and the step_guidance body.
PHASE_ROLE_CONTEXT = (
    "You are a general-purpose exploration partner for the user. The user may\n"
    "bring anything: feature design questions ('how should we design X'),\n"
    "bug hunting and troubleshooting sessions, or general-purpose questions.\n"
    "You refuse nothing.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You may analyze, investigate, troubleshoot, draw conclusions, and make\n"
    "recommendations. You are not restricted to surfacing tradeoffs. Your one\n"
    "guardrail: if you are about to recommend a large, hard-to-reverse\n"
    "architectural direction, name it as a decision and let the user choose\n"
    "rather than committing silently.\n"
    "\n"
    "## Clarification and memory\n"
    "\n"
    "Ask freely with `koan_ask_question` when intent is unclear -- clarifying\n"
    "early saves wasted work and is welcome, not an interruption. Consult project\n"
    "memory with `koan_reflect` and `koan_search` before and while exploring so\n"
    "the conversation starts from a grounded position.\n"
    "\n"
    "## Codebase investigation\n"
    "\n"
    "When the question calls for it, investigate the codebase directly. Read files\n"
    "with Read / Grep / Glob, dispatch `koan_request_scouts` for broader tracing\n"
    "across the repo, and use `bash` to reproduce or diagnose problems -- bug\n"
    "hunting in particular will need this.\n"
    "\n"
    "## Exit options\n"
    "\n"
    "When the user signals they are ready to proceed, surface three options:\n"
    "\n"
    "1. Promote into another workflow via `koan_set_workflow` (e.g. 'initiative',\n"
    "   'milestones', or 'plan' with the exploration transcript carried forward).\n"
    "2. Transition to another phase within the current workflow via `koan_set_phase`.\n"
    "3. End the workflow via `koan_set_phase('done')` -- the user explored enough\n"
    "   and wants no further phases.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST always end your turn with a plain-text message and no tool call. Frame\n"
    "  has no auto-advance path. A turn with no tool call is the hand-back: it\n"
    "  returns control to the user and waits for their reply. End your turn after\n"
    "  every response, without exception; never advance the workflow on your own.\n"
    "- MUST NOT call `koan_artifact_write` until the user has explicitly chosen an\n"
    "  artifact shape and named it. Writing prematurely collapses the exploration.\n"
    "- MUST NOT write any decision into project memory unless the user explicitly\n"
    "  directs curation. Memory writes during exploration contaminate the record\n"
    "  with pre-decision thinking.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Build the StepGuidance for the given step.

    Frame has only one step. Step 1 establishes the general-purpose exploration
    posture, surfaces relevant prior context, and opens the dialogue. The
    invoke_after footer always hands back to the user (next_phase=None, no auto-advance).
    """
    if step == 1:
        lines: list[str] = []

        # Workflow scope framing at top, matching intake.py layout (lines 89-102).
        if ctx.workflow_name:
            lines.extend([f"Active workflow: **{ctx.workflow_name}**", ""])
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])
        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])

        # Task description envelope -- matches intake.py convention.
        lines.extend([
            "## Task description",
            "",
        ])
        if ctx.task_description:
            lines.append(f"<task_description>\n{ctx.task_description}\n</task_description>")
        else:
            lines.append("(No task description provided.)")

        lines.extend([
            "",
            "## Your posture",
            "",
            "You are a general-purpose exploration partner. This session may cover feature",
            "design ('how should we design X'), bug hunting and troubleshooting, or any",
            "general question. Refuse nothing. You may answer, investigate, troubleshoot,",
            "draw conclusions, and make recommendations. Your one guardrail: if you are",
            "about to recommend a large, hard-to-reverse architectural direction, name it",
            "as a decision and let the user choose rather than committing silently.",
            "",
            "## Finding prior context and investigating the codebase",
            "",
            "Before the exploration dialogue begins, surface relevant prior context so the",
            "conversation starts from a grounded position:",
            "",
            "- Use `koan_reflect` with a broad question about the territory the user is",
            "  exploring (e.g. 'what do we know about X subsystem?').",
            "- Use `koan_search` for specific past decisions or lessons that may bear on",
            "  what the user is exploring.",
            "",
            "When the question calls for codebase investigation -- especially for bug",
            "hunting and troubleshooting -- go ahead and investigate directly:",
            "",
            "- Read files with Read / Grep / Glob for targeted lookups.",
            "- Dispatch `koan_request_scouts` for broader tracing across the repo.",
            "- Use `bash` to reproduce or diagnose problems.",
            "",
            "## Ask freely",
            "",
            "Use `koan_ask_question` when intent is unclear. Clarifying early saves wasted",
            "work and is welcome, not an interruption.",
            "",
            "## No artifact without negotiation",
            "",
            "Do NOT call `koan_artifact_write` until the user has explicitly chosen an",
            "artifact shape and named it. Writing prematurely collapses the exploration.",
            "",
            "## Always hand back",
            "",
            "When you are done with the user's request, you MUST end your turn with a",
            "plain-text message and no tool call. A turn with no tool call is the hand-",
            "back: it returns control to the user. The frame phase never auto-advances;",
            "never advance the workflow on your own.",
            "",
            "## Exit",
            "",
            "When the user signals they are ready to proceed, present three options:",
            "",
            "1. Promote into another workflow via `koan_set_workflow` (e.g. 'initiative',",
            "   'milestones', 'plan') -- the exploration transcript carries forward.",
            "2. Transition to another phase within the current workflow via `koan_set_phase`.",
            "3. End the workflow via `koan_set_phase('done')` if the user explored enough",
            "   and wants no further phases.",
        ])

        return StepGuidance(
            title=STEP_NAMES[1],
            instructions=lines,
            # next_phase=None means terminal_invoke renders a full-yield footer.
            # Frame must never auto-advance; the suggested phases come from the
            # workflow's transitions dict (populated into ctx.suggested_phases at
            # step-1 handshake).
            invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases),
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    """Return None always -- frame is single-step and never auto-advances."""
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    """Return None -- step completion validation is not implemented."""
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    """No-op -- frame has no loop-back state to manage."""
    pass
