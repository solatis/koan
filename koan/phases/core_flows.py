# Core-flows phase -- 2-step workflow.
#
#   Step 1 (Analyze)   -- read brief.md, identify flows; no writes
#   Step 2 (Write)     -- write core-flows.md with status=Final
#
# core-flows.md is FROZEN at exit. Every downstream phase (tech-plan-spec,
# tech-plan-review, milestone-spec, plan-spec, exec-review) reads it as
# authoritative behavioral spec. The artifact must never be re-written after
# this phase exits.
#
# The artifact is visualization-first: one mermaid sequenceDiagram per flow
# plus step narrative. Constraint: no file paths, no component names, no
# implementation detail -- operational-behavior level only.
#
# Scope: "general" -- reusable by any workflow; initiative workflow is the
# primary binding.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "general"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Analyze",
    2: "Write",
}

PHASE_ROLE_CONTEXT = (
    "You are the producer of core-flows.md, the operational-behavior artifact for\n"
    "this initiative. Your job is to describe what the system does at the\n"
    "actor-and-trigger level -- not how it is structured inside.\n"
    "\n"
    "## What this artifact is\n"
    "\n"
    "core-flows.md is a FROZEN artifact. It is read by every downstream phase\n"
    "(tech-plan-spec, tech-plan-review, milestone-spec, plan-spec, exec-review)\n"
    "as authoritative behavioral spec, parallel to brief.md. Once you write it\n"
    "with status='Final', no downstream phase may re-write it.\n"
    "\n"
    "## Load-bearing content\n"
    "\n"
    "- One mermaid `sequenceDiagram` per flow (the SEQ slot).\n"
    "- A step narrative for each flow: trigger, sequenced steps, exit conditions.\n"
    "- No file paths, no component names, no implementation detail.\n"
    "\n"
    "## SEQ slot rules (from docs/visualization-system.md section 4)\n"
    "\n"
    "One `sequenceDiagram` per flow. Suppression rule: if a flow has only 2 actors\n"
    "AND fewer than 4 messages AND no branching, render the flow as prose only --\n"
    "no diagram, no marker comment, no 'suppressed' placeholder. Just the step\n"
    "narrative under the flow's heading.\n"
    "Grounding rule: no actor in any diagram may be absent from the bounded inputs\n"
    "(brief.md and the dialogue that preceded this phase).\n"
    "See docs/visualization-system.md for full slot-and-suppression detail.\n"
    "\n"
    "## Mermaid syntax hazards\n"
    "\n"
    # Inline the sequenceDiagram semicolon rule so the LLM sees it at generation
    # time rather than having to consult the reference doc. Mirrors the pattern
    # used by the suppression and grounding rules above.
    "Do not use `;` (semicolon) inside `Note over`, `Note left of`, or `Note right of`\n"
    "bodies, or inside message labels -- mermaid treats `;` as a statement separator\n"
    "and will break the parser mid-sentence. Use `,` or `--` instead.\n"
    "For multi-line Notes, use `<br>` rather than a raw newline in the body.\n"
    "See docs/visualization-system.md section 8 for the full list of syntax hazards.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST NOT include file paths, component names, or implementation detail.\n"
    "- MUST NOT include component diagrams (CMP, CON, STT) -- SEQ only.\n"
    "- MUST use `koan_artifact_write` for the terminal write.\n"
    "- MUST set status='Final' to mark frozen at exit.\n"
    "- SHOULD NOT call `koan_request_scouts` unless the dialogue explicitly refers\n"
    "  to specific subsystems and codebase reading becomes warranted. The permission\n"
    "  fence allows it, but operational behavior is usually derivable from brief.md\n"
    "  and the dialogue without codebase investigation.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Build the StepGuidance for the given step.

    Step 1 (Analyze): read brief.md, identify flows, decide diagram vs prose per
    flow -- no writes. Step 2 (Write): emit core-flows.md via koan_artifact_write
    with status='Final'.
    """
    if step == 1:
        lines: list[str] = []
        # phase_instructions at top -- matches plan_spec.py layout (lines 83-85)
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])
        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])

        lines.extend([
            "## Read initiative context",
            "",
            "Read `brief.md` from the run directory first via `koan_artifact_view`.",
            "It contains the frozen initiative scope, decisions, and constraints from",
            "intake. The flows you describe in core-flows.md must correspond to the",
            "operational behavior the initiative implies.",
            "",
            "Read and analyze before writing. Do NOT write any files in this step.",
            "",
            "## Consult project memory",
            "",
            "Before identifying flows, check what the project already knows about the",
            "system's operational behavior, user-visible flows, and integration points.",
            "",
            "If relevant memory entries appeared above (`## Relevant memory`), read them now.",
            "",
            "Run `koan_reflect` with a broad question about the operational behavior",
            "the initiative touches (e.g. 'what do we know about how X works end to end?').",
            "Use `koan_search` for specific past decisions about flows or actors.",
            "",
            "## Identify flows",
            "",
            "Enumerate the operational flows the initiative implies. For each flow:",
            "",
            "- Name: a short label (e.g. 'User submits a job', 'System retries a failed task').",
            "- Actors: who or what participates (system, user, external service, scheduler).",
            "- Trigger: what starts the flow.",
            "- Sequenced steps: the observable steps in order.",
            "- Exit conditions: the outcomes (success, failure, timeout, etc.).",
            "- Diagram decision: does this flow warrant a `sequenceDiagram`, or should",
            "  it render as prose only (no diagram, no marker, no placeholder)?",
            "  Render as prose only when: 2 actors AND fewer than 4 messages AND no",
            "  branching.",
            "",
            "## What to call koan_complete_step with",
            "",
            "Call `koan_complete_step` with:",
            "- A list of identified flows.",
            "- For each flow, the diagram-vs-prose decision and rationale.",
            "- Any ambiguities about the operational behavior that need resolving.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Compose core-flows.md and submit it via `koan_artifact_write`.",
                "",
                "```",
                "koan_artifact_write(",
                '    filename="core-flows.md",',
                '    content="""\\',
                "# Core Flows",
                "",
                "## Flow 1: <title>",
                "",
                "```mermaid",
                "sequenceDiagram",
                "    Actor1->>Actor2: Message",
                "    Actor2-->>Actor1: Response",
                "```",
                "",
                "Step narrative: trigger, sequenced steps, exit conditions.",
                "",
                "## Flow 2: <title>",
                "",
                "Step narrative: trigger, sequenced steps, exit conditions.",
                '""",',
                '    status="Final",',
                ")",
                "```",
                "",
                "## Required structure",
                "",
                "One section per flow (`## Flow N: <title>`). Each section contains:",
                "",
                "- A mermaid `sequenceDiagram` block, OR no diagram at all (prose only,",
                "  no marker, no placeholder) when the flow has 2 actors AND fewer than",
                "  4 messages AND no branching.",
                "- A step narrative: trigger, the sequenced steps in order, and exit",
                "  conditions (success, failure, timeout, etc.).",
                "",
                "## Constraints (repeated from PHASE_ROLE_CONTEXT at point of use)",
                "",
                "- No file paths, no component names, no implementation detail.",
                "- One `sequenceDiagram` per flow (SEQ slot); no CMP, CON, or STT diagrams.",
                "- Grounding rule: no actor in any diagram absent from the bounded inputs",
                "  (brief.md and the dialogue).",
                "- This artifact is FROZEN at exit. Downstream phases read it as authoritative.",
                "  Set status='Final'.",
            ],
            invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases),
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    """Return step + 1 if more steps remain; None after the terminal step."""
    if step < TOTAL_STEPS:
        return step + 1
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    """Return None -- step completion validation is not implemented."""
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    """No-op -- core_flows has no loop-back state to manage."""
    pass
