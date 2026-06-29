# Tech-plan phase -- 2-step workflow.
#
#   Step 1 (Analyze)   -- analyze injected handovers, investigate codebase; no writes
#   Step 2 (Write)     -- write tech-plan.md, reconcile TECH_PLAN_REVIEWER
#                         findings inline, then advance to milestone
#
# tech-plan is the structural counterpart to core-flows: where core-flows
# describes externally visible behavior, tech-plan describes internal structure.
# The artifact (tech-plan.md) is consumed by downstream phases and superseded
# once milestone outcomes compress its decisions.
#
# M6: tech-plan-review is removed. The TECH_PLAN_REVIEWER runs mechanically on
# koan_artifact_write (M3). The producer reconciles findings inline before
# advancing to milestone (auto-advance per PhaseBinding.next_phase).
#
# Scope: "general" -- reusable by any workflow; initiative workflow binds it.

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
    "You are the producer of tech-plan.md, the system architecture artifact for\n"
    "this initiative. Your job is to describe the system's internal structure --\n"
    "the counterpart to core-flows.md's externally visible behavior description.\n"
    "\n"
    "## What this artifact contains\n"
    "\n"
    "tech-plan.md has three load-bearing sections:\n"
    "\n"
    "1. **Architectural Approach**: the high-level structural strategy, rendered\n"
    "   with a CON diagram (`flowchart` container view showing runtime processes,\n"
    "   services, and data stores).\n"
    "2. **Data Model**: schemas for the entities introduced or modified, rendered\n"
    "   as fenced code blocks. NOT ER diagrams.\n"
    "3. **Component Architecture**: internal structure per container, rendered\n"
    "   with CMP diagrams (`classDiagram` or `flowchart` per container). Cross-\n"
    "   component flows use SEQ (`sequenceDiagram`). Per-entity lifecycles use\n"
    "   STT (`stateDiagram-v2`) when warranted.\n"
    "\n"
    "## Slot mapping (from docs/visualization-system.md section 4)\n"
    "\n"
    "- CON (Architectural Approach): `flowchart` container view.\n"
    "  Suppress when: single container, OR 2 containers with only one connection.\n"
    "- CMP (Component Architecture): `classDiagram` or `flowchart` per container.\n"
    "  Suppress when: fewer than 4 components in scope.\n"
    "- SEQ (cross-component flows): `sequenceDiagram`.\n"
    "  Suppress when: 2 actors AND fewer than 4 messages AND no branching.\n"
    "- STT (per-entity lifecycles): `stateDiagram-v2`, warranted only when >= 3\n"
    "  states with conditional transitions.\n"
    "  Suppress when: fewer than 3 states OR no guards/conditional transitions.\n"
    "- Data Model: fenced code blocks for schema definitions. NOT ER diagrams.\n"
    "\n"
    "When a slot is below threshold, render it as prose only -- no diagram, no\n"
    "marker comment, no 'suppressed' placeholder. The prose alone is the slot.\n"
    "\n"
    "See docs/visualization-system.md for full slot-and-suppression detail.\n"
    "\n"
    "## Grounding rule (docs/visualization-system.md section 6)\n"
    "\n"
    "No nodes, actors, or states in any diagram may be absent from the bounded\n"
    "inputs (brief.md, core-flows.md, codebase analysis notes). Every diagram\n"
    "element must trace to a named concept in the inputs.\n"
    "\n"
    "## Level-separation rule (docs/visualization-system.md section 7 anti-patterns)\n"
    "\n"
    "No cross-level mixing within a single diagram. A CON diagram shows containers,\n"
    "not components. A CMP diagram shows components within one container, not other\n"
    "containers. A SEQ diagram shows messages between identified actors, not internal\n"
    "component calls.\n"
    "\n"
    "## Mermaid syntax hazards\n"
    "\n"
    # Inline the sequenceDiagram semicolon rule so the LLM sees it at generation
    # time rather than having to consult the reference doc. Mirrors the pattern
    # used by the grounding and level-separation rules above.
    "Do not use `;` (semicolon) inside `Note over`, `Note left of`, or `Note right of`\n"
    "bodies, or inside message labels -- mermaid treats `;` as a statement separator\n"
    "and will break the parser mid-sentence. Use `,` or `--` instead.\n"
    "For multi-line Notes, use `<br>` rather than a raw newline in the body.\n"
    "See docs/visualization-system.md section 8 for the full list of syntax hazards.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    # Reframed from "MUST read" to "MUST use" -- both artifacts are injected as
    # handovers before this phase runs; directing the agent to use them (not re-read
    # them) keeps the injected prefix as the canonical copy.
    "- MUST use the provided `brief.md` and `core-flows.md` (when present) handovers before writing.\n"
    "- MUST NOT specify per-file or per-function implementation steps -- that is\n"
    "  the HOW band's job (plan). Describe structure, not implementation steps.\n"
    "- MUST express each section's chosen path AND rejected alternatives with\n"
    "  rationale, so the mechanical TECH_PLAN_REVIEWER (M3) has material to\n"
    "  stress-test.\n"
    "- MUST use `koan_artifact_write` for the terminal write.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Build the StepGuidance for the given step.

    Step 1 (Analyze): analyze the injected brief and core-flows handovers plus
    codebase investigation; decide diagram vs suppression-prose per slot -- no
    writes. Step 2 (Write): emit tech-plan.md via koan_artifact_write, which
    triggers the mechanical TECH_PLAN_REVIEWER (blocking). The producer reconciles
    findings inline, then advances to milestone.
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
            # Both artifacts are injected as handovers -- no koan_artifact_read call
            # is needed.  Reframed to direct the agent to USE the injected content.
            "`brief.md` is provided above as a handover -- frozen initiative scope,",
            "decisions, and constraints.",
            "",
            "`core-flows.md` is provided above as a handover when present (the core-flows",
            "phase is yield-skippable, so it may not exist). When present, it is",
            "authoritative for the actors and flows that constrain the architecture.",
            "",
            "Read and analyze before writing. Do NOT write any files in this step.",
            "",
            "## Consult project memory",
            "",
            "Before reading codebase files, check what the project already knows about",
            "architectural decisions and constraints relevant to the new system's structure.",
            "",
            "If relevant memory entries appeared above (`## Relevant memory`), read them now.",
            "",
            "Run `koan_reflect` with a question about the architectural territory the",
            "initiative touches (e.g. 'what architectural decisions constrain changes to X?').",
            "Use `koan_search` for specific past decisions about data-model conventions,",
            "component boundaries, and integration patterns.",
            "",
            "## Investigate codebase",
            "",
            "When the architecture must integrate with existing structure, dispatch scouts",
            "via `koan_request_scouts`. The permission fence permits scouts in this phase.",
            "Focus on integration points: existing module structure, data-model schemas,",
            "integration seams the new architecture will touch.",
            "",
            "## Identify the three sections' content",
            "",
            "For each section, decide which visualization slots warrant diagrams vs",
            "prose-only rendering (no diagram, no marker, no placeholder). Recall the",
            "thresholds from PHASE_ROLE_CONTEXT -- repeated here at point of use:",
            "",
            "- CON: suppress when single container OR 2 containers with one connection.",
            "- CMP: suppress when fewer than 4 components in scope.",
            "- SEQ: suppress when 2 actors AND fewer than 4 messages AND no branching.",
            "- STT: suppress when fewer than 3 states OR no conditional transitions.",
            "- Data Model: always fenced code blocks, not ER diagrams.",
            "",
            "Check grounding: every node/actor/state you plan to include must trace to a",
            "named concept in brief.md, core-flows.md, or your codebase analysis notes.",
            "",
            "## What to conclude this step with",
            "",
            "End your turn with:",
            "- A draft outline of the three sections.",
            "- Per-slot diagram-vs-prose decisions with rationale.",
            "- Any architectural questions that need resolving before writing.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Compose tech-plan.md and submit it via `koan_artifact_write`.",
                "",
                "```",
                "koan_artifact_write(",
                '    filename="tech-plan.md",',
                '    content="""\\',
                "# Technical Plan",
                "",
                "## Architectural Approach",
                "",
                "```mermaid",
                "flowchart LR",
                "    ServiceA --> DB[(Database)]",
                "    ServiceA --> ServiceB",
                "```",
                "",
                "Prose: chosen path, rejected alternatives with rationale.",
                "",
                "## Data Model",
                "",
                "```python",
                "@dataclass",
                "class Entity:",
                "    ...",
                "```",
                "",
                "Prose: schema choices and rationale.",
                "",
                "## Component Architecture",
                "",
                "```mermaid",
                "classDiagram",
                "    class ComponentA {",
                "        +method()",
                "    }",
                "    ComponentA --> ComponentB",
                "```",
                "",
                "Prose: component responsibilities, boundaries, chosen path, rejected",
                "alternatives with rationale.",
                '""",',
                ")",
                "```",
                "",
                "## Required sections",
                "",
                "### Architectural Approach",
                "CON diagram (`flowchart` container view) showing runtime processes,",
                "services, and data stores. When single container OR 2 containers with",
                "one connection, omit the diagram and use prose only -- no marker, no",
                "placeholder. Include: chosen path AND rejected alternatives with rationale.",
                "",
                "### Data Model",
                "Fenced code blocks for schema definitions. NOT ER diagrams. Include",
                "the entities introduced or modified with their fields and types.",
                "",
                "### Component Architecture",
                "CMP diagrams (`classDiagram` or `flowchart` per container) for internal",
                "structure. SEQ (`sequenceDiagram`) for cross-component flows. STT",
                "(`stateDiagram-v2`) for per-entity lifecycles when warranted (>= 3 states",
                "with conditional transitions). For below-threshold slots, render prose",
                "only -- no diagram, no marker, no placeholder. Include: chosen path AND",
                "rejected alternatives with rationale.",
                "",
                "## Constraints (repeated from PHASE_ROLE_CONTEXT at point of use)",
                "",
                "- Grounding rule: every node/actor/state must trace to a named concept in",
                "  brief.md, core-flows.md (if present), or codebase analysis notes.",
                "- Level-separation: no cross-level mixing within a single diagram.",
                "- Below-threshold slots: prose only. No diagram, no marker, no placeholder.",
                "",
                "## Reconcile reviewer findings (inline, after write returns)",
                "",
                # M6: reconcile folded into the Write step -- the write triggers the
                # TECH_PLAN_REVIEWER mechanically and returns its findings as the tool result.
                # M1: findings and dispositions are recorded inline in tech-plan.md,
                # not in a .review.md sidecar.
                "Once `koan_artifact_write` returns, you have the TECH_PLAN_REVIEWER's",
                "freeform findings. Judge each finding and act:",
                "",
                "- **Valid finding**: incorporate it by editing tech-plan.md in place via",
                "  `koan_artifact_edit`.",
                "- **Reviewer misconception**: overrule it by editing to add the missing context.",
                "- **Approach-invalidating finding**: escalate via `koan_ask_question`.",
                "",
                "After judging all findings, append a `## Review` section to the END of"
                " tech-plan.md. The edit protocol is anchor-based -- there is no \"append\""
                " mode -- so append by inserting after the last line:",
                "",
                # Use generic "the artifact" to avoid a koan_artifact_read directive
                # that names tech-plan.md -- the artifact was just written by this phase
                # so the agent knows which file to re-read from context.
                "1. Re-read the artifact with `koan_artifact_read` (your in-place edits",
                "   changed it; fetch current anchors).",
                "2. Take the LAST line in that read (highest line number) and copy its whole",
                "   anchor token verbatim -- everything after the line-number tab.",
                "3. Call `koan_artifact_edit` with `edit_type=\"insert_after\"` and that anchor:",
                "",
                "```",
                "koan_artifact_edit(",
                '    filename="tech-plan.md",',
                '    anchor="<last-line anchor token, copied verbatim from the read>",',
                "    edit_type=\"insert_after\",",
                '    text="""',
                "",
                "## Review",
                "",
                "### Finding 1 [INCORPORATED | OVERRULED | ESCALATED] -- <rationale>",
                '""",',
                ")",
                "```",
                "",
                "A failed edit (e.g. `{\"ok\": false}` from a stale anchor) is recoverable:"
                " re-read for fresh anchors and retry.",
                "",
                "After reconciling, advance to the next phase.",
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
    """No-op -- tech_plan_spec has no loop-back state to manage."""
    pass
