# Tech-plan-spec phase -- 2-step workflow.
#
#   Step 1 (Analyze)   -- read brief.md, core-flows.md, codebase; no writes
#   Step 2 (Write)     -- write tech-plan.md with status=In-Progress
#
# tech-plan-spec is the structural counterpart to core-flows: where core-flows
# describes externally visible behavior, tech-plan-spec describes internal structure.
# The artifact (tech-plan.md) is disposable: consumed by downstream phases and
# superseded once milestone outcomes compress its decisions. status=In-Progress
# at write time because the reviewer phase (tech-plan-review) may rewrite in place.
#
# Auto-advances to tech-plan-review per PhaseBinding.next_phase in the workflow.
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
    "Suppression marker: `<!-- diagram suppressed: below complexity threshold -->`.\n"
    "Use this marker comment in place of the diagram when the slot is below\n"
    "threshold; follow with prose describing the content.\n"
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
    "- MUST read `brief.md` and `core-flows.md` (when present) before writing.\n"
    "- MUST NOT specify per-file or per-function implementation steps -- that is\n"
    "  the HOW band's job (plan-spec). Describe structure, not implementation steps.\n"
    "- MUST express each section's chosen path AND rejected alternatives with\n"
    "  rationale, so the reviewer phase (tech-plan-review) has material to\n"
    "  stress-test.\n"
    "- MUST use `koan_artifact_write` for the terminal write.\n"
    "- MUST set status='In-Progress' at write time. The reviewer may rewrite in\n"
    "  place; the status flips to 'Final' at review exit when no rewrite was needed,\n"
    "  or stays 'In-Progress' if the reviewer did rewrite. Final status is the\n"
    "  reviewer's call.\n"
    "- Per brief.md decision 1, no 'Approved' gate is enforced. Status discipline\n"
    "  is conventional only -- no code path reads 'Approved' to gate transitions.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Build the StepGuidance for the given step.

    Step 1 (Analyze): read brief.md, core-flows.md, and codebase; decide diagram
    vs suppression-prose per slot -- no writes. Step 2 (Write): emit tech-plan.md
    via koan_artifact_write with status='In-Progress'.
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
            "Read the following artifacts via `koan_artifact_view` before doing anything else:",
            "",
            "1. `brief.md` -- frozen initiative scope, decisions, and constraints.",
            "2. `core-flows.md` -- frozen operational-behavior artifact (read if present;",
            "   the core-flows phase is yield-skippable, so it may not exist). When present,",
            "   it is authoritative for the actors and flows that constrain the architecture.",
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
            "suppression-prose (with the suppression marker comment). Recall the thresholds",
            "from PHASE_ROLE_CONTEXT -- repeated here at point of use:",
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
            "## What to call koan_complete_step with",
            "",
            "Call `koan_complete_step` with:",
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
                '    status="In-Progress",',
                ")",
                "```",
                "",
                "## Required sections",
                "",
                "### Architectural Approach",
                "CON diagram (`flowchart` container view) showing runtime processes,",
                "services, and data stores. Suppress (with marker comment) when single",
                "container OR 2 containers with one connection. Include: chosen path AND",
                "rejected alternatives with rationale.",
                "",
                "### Data Model",
                "Fenced code blocks for schema definitions. NOT ER diagrams. Include",
                "the entities introduced or modified with their fields and types.",
                "",
                "### Component Architecture",
                "CMP diagrams (`classDiagram` or `flowchart` per container) for internal",
                "structure. SEQ (`sequenceDiagram`) for cross-component flows. STT",
                "(`stateDiagram-v2`) for per-entity lifecycles when warranted (>= 3 states",
                "with conditional transitions). Suppress below-threshold slots with marker",
                "comment. Include: chosen path AND rejected alternatives with rationale.",
                "",
                "## Constraints (repeated from PHASE_ROLE_CONTEXT at point of use)",
                "",
                "- Grounding rule: every node/actor/state must trace to a named concept in",
                "  brief.md, core-flows.md (if present), or codebase analysis notes.",
                "- Level-separation: no cross-level mixing within a single diagram.",
                "- Suppression marker: `<!-- diagram suppressed: below complexity threshold -->`.",
                "- status='In-Progress': the reviewer may rewrite in place.",
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
