# Milestone phase -- 2-step workflow.
#
#   Step 1 (Analyze)  -- analyze scope; no writes
#   Step 2 (Write)    -- write milestones.md via koan_artifact_write
#
# M2: The milestone phase is ONE-TIME per initiative. milestones.md is a living
# document edited in place; the discard hook was removed (M2). This phase always
# CREATEs milestones.md (it is entered once); routine post-execution edits live
# in the execute phase. The MILESTONE_REVIEWER runs mechanically on write;
# findings are reconciled inline before advancing to plan.
#
# Scope: "milestones" -- specific to the milestones workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "milestones"     # specific to the milestones workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Analyze",
    2: "Write",
}

PHASE_ROLE_CONTEXT = (
    "You are a technical architect managing milestone decomposition for a broad initiative.\n"
    # M2: milestone phase is one-time. milestones.md is a living document edited
    # in place; this phase always CREATEs it (entered once per initiative).
    # Routine post-execution UPDATE work lives in the execute phase.
    "You decompose the initiative into milestones grounded in the codebase's dependency\n"
    "structure. Read the codebase, propose milestones, write milestones.md.\n"
    "\n"
    "## What a milestone is\n"
    "\n"
    "A milestone is a coherent, independently-deliverable unit of work. Decomposition\n"
    "is a graph partitioning problem over the codebase's dependency structure -- you cut\n"
    "along module boundaries, not against them. You decompose and track progress; you\n"
    "do not plan implementation details.\n"
    "\n"
    "## Soundness criteria\n"
    "\n"
    "Every milestone must satisfy:\n"
    "1. **Independently deliverable**: if only milestone N were implemented and work\n"
    "   stopped, N's stated outcome would still hold. If N requires N+1 to land, N\n"
    "   is not independent.\n"
    "2. **Grounded in code structure**: the milestone's scope maps to a connected\n"
    "   subgraph of the affected codebase. Milestones that slice across strongly-\n"
    "   connected components guarantee integration pain.\n"
    "3. **Plannable in one plan session**: plan can read the milestone's\n"
    "   files and produce a specific implementation plan without exhausting context.\n"
    "4. **Executable in one executor session**: the resulting plan fits in roughly\n"
    "   10-30 implementation steps.\n"
    "\n"
    "## Sizing heuristics\n"
    "\n"
    "- **Files touched**: roughly 5-30 files per milestone. Fewer means merge with\n"
    "  a neighbor. More means split.\n"
    "- **Plan steps**: the plan that will be written for this milestone should be\n"
    "  around 10-30 steps. If you can already see 50+ steps, the milestone is too large.\n"
    "- **Sketch length**: if the milestone sketch needs more than 6 sentences, it is\n"
    "  probably doing too much.\n"
    "\n"
    "## milestones.md format\n"
    "\n"
    "```markdown\n"
    "# Milestones: <initiative title>\n"
    "\n"
    "## Milestone 1: <title> [done]\n"
    "\n"
    "<description of what was accomplished>\n"
    "\n"
    "### Outcome\n"
    "\n"
    "<post-execution notes added during milestone update>\n"
    "\n"
    "## Milestone 2: <title> [in-progress]\n"
    "\n"
    "<rough sketch of what should happen>\n"
    "\n"
    "## Milestone 3: <title> [pending]\n"
    "\n"
    "<rough sketch of what should happen>\n"
    "```\n"
    "\n"
    "## Status markers\n"
    "\n"
    "- `[pending]`: not yet started\n"
    "- `[in-progress]`: currently being planned or executed\n"
    "- `[done]`: execution complete\n"
    "- `[skipped]`: intentionally omitted\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST use koan_artifact_write to write milestones.md.\n"
    "- MUST NOT plan implementation details -- rough sketches only.\n"
    "- MUST NOT mark milestones [done] or add Outcomes -- execute phase owns that.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Build step guidance for the given step number.

    Step 1 (Analyze): analyze the injected brief handover and codebase module
    structure; identify affected subgraph; propose milestones. Step 2 (Write):
    write milestones.md via koan_artifact_write (always CREATE -- the milestone
    phase is one-time), which triggers the mechanical MILESTONE_REVIEWER.
    Reconcile findings inline, then advance to plan.
    """
    if step == 1:
        lines: list[str] = []
        # phase_instructions at top per established pattern (intake.py, execute.py)
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])
        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])
        # brief.md is injected as a handover -- reframed to reference the injected
        # copy rather than directing a koan_artifact_read call.
        lines.extend([
            "## Read initiative context",
            "",
            "`brief.md` is provided above as a handover. It contains the frozen",
            "initiative scope, decisions, constraints, and affected subsystems from",
            "intake -- treat it as authoritative.",
            "",
            "Analyze before writing. Do NOT write milestones.md in this step.",
            "",
            "## Understand the initiative scope",
            "",
            "Read intake findings from the conversation context.",
            "",
            "## Read the project's module structure",
            "",
            "Read the directory tree and top-level packages -- not individual files.",
            "This is the prior for where milestones should cut. Use `find`, `ls`, or",
            "`tree` to see the structure. Understand the visible module boundaries.",
            "",
            "## Identify the affected subgraph",
            "",
            "From intake findings, identify which packages/modules the initiative",
            "touches. Read the import graph among those (or at least the outgoing",
            "imports from entry points). Understand how the affected modules relate",
            "to each other.",
            "",
            "## Consult project memory",
            "",
            "Run `koan_reflect` for architectural constraints relevant to milestone",
            "scope and ordering. Use `koan_search` for specific past decomposition",
            "patterns or subsystem boundary decisions.",
            "",
            "## Propose milestones",
            "",
            "Identify 3-7 milestones. For each proposed milestone:",
            "- Name the files or modules it owns. If the scope cannot be named in",
            "  terms of existing code structure (unless it is greenfield), the",
            "  decomposition is not grounded.",
            "- Verify no two milestones claim the same file/function. Overlapping",
            "  ownership means the milestones are not truly independent.",
            "- Check the sizing heuristics (5-30 files, 10-30 plan steps, <=6",
            "  sentence sketch). If a milestone exceeds these, split it.",
            "- Order by dependency: earlier milestones must not depend on later ones.",
            "",
            "End your turn with:",
            "- Proposed milestone list with rough sketches and file/module scope",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Write milestones.md via `koan_artifact_write`.",
                "",
                "```",
                "koan_artifact_write(",
                '    filename="milestones.md",',
                '    content="""\\ ',
                "# Milestones: <initiative title>",
                "",
                "## Milestone 1: <title> [status]",
                "...",
                '""",',
                ")",
                "```",
                "",
                # M2: always CREATE -- the milestone phase is one-time, entered once
                # per initiative; milestones.md does not exist when this step runs.
                "Give the **first** milestone `[in-progress]` status; give all subsequent",
                "milestones `[pending]` status.",
                "Write a rough sketch (3-6 sentences) describing what each milestone covers.",
                "Order milestones by dependency: earlier milestones must not depend on later ones.",
                "",
                "## Reconcile reviewer findings (inline, after write returns)",
                "",
                # M6: reconcile folded into the Write step -- the write triggers the
                # MILESTONE_REVIEWER mechanically and returns its findings as the tool result.
                # M1: findings and dispositions are recorded inline in milestones.md,
                # not in a .review.md sidecar.
                "Once `koan_artifact_write` returns, you have the MILESTONE_REVIEWER's",
                "freeform findings. Judge each finding and act:",
                "",
                "- **Valid finding**: incorporate it by editing milestones.md in place via",
                "  `koan_artifact_edit`.",
                "- **Reviewer misconception**: overrule it by editing to add missing context.",
                "- **Approach-invalidating finding**: escalate via `koan_ask_question`.",
                "",
                "After judging all findings, append a `## Review` section to the END of"
                " milestones.md. The edit protocol is anchor-based -- there is no \"append\""
                " mode -- so append by inserting after the last line:",
                "",
                "1. Re-read milestones.md with `koan_artifact_read` (your in-place edits",
                "   changed it; fetch current anchors).",
                "2. Take the LAST line in that read (highest line number) and copy its whole",
                "   anchor token verbatim -- everything after the line-number tab.",
                "3. Call `koan_artifact_edit` with `edit_type=\"insert_after\"` and that anchor:",
                "",
                "```",
                "koan_artifact_edit(",
                '    filename="milestones.md",',
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
                "## Advance to plan",
                "",
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
    """No-op -- milestone_spec has no loop-back state to manage."""
    pass
