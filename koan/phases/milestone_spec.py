# Milestone-spec phase -- 2-step workflow.
#
#   Step 1 (Analyze)  -- determine mode (CREATE/RE-DECOMPOSE), analyze scope; no writes
#   Step 2 (Write)    -- write or revise milestones.md via koan_artifact_write
#
# Handles initial decomposition (CREATE mode) and explicit RE-DECOMPOSE when
# the user redirects here after a major deviation. Routine post-execution UPDATE
# (mark [done], append Outcome, advance next) has moved to exec-review in M4.
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
    # M4: UPDATE mode removed; routine post-execution UPDATE is now exec-review's job.
    # milestone-spec retains CREATE + manual RE-DECOMPOSE entry path only.
    "You may be creating the initial decomposition (CREATE mode) or revising it after\n"
    "the user has explicitly redirected here following a major deviation (RE-DECOMPOSE\n"
    "mode). Routine post-execution UPDATE work has moved to exec-review.\n"
    "Read `milestones.md` in the run directory -- if it exists, you are in RE-DECOMPOSE\n"
    "mode; if not, you are creating from intake findings.\n"
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
    "3. **Plannable in one plan-spec session**: plan-spec can read the milestone's\n"
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
    "<post-execution notes added during milestone-spec update>\n"
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
    "- MUST read milestones.md (if it exists) before writing.\n"
    "- MUST use koan_artifact_write to write milestones.md.\n"
    "- MUST NOT plan implementation details -- rough sketches only.\n"
    # M4: "When updating: MUST add an Outcome section" removed -- exec-review
    # now owns Outcome authoring. RE-DECOMPOSE must NOT add Outcomes.
    "- In RE-DECOMPOSE mode: MUST preserve all [done] milestones and their\n"
    "  Outcome sections intact. MUST NOT mark milestones [done] or add Outcomes.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines: list[str] = []
        # phase_instructions at top per established pattern (intake.py, execute.py)
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])
        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])
        # brief.md directive comes first so the orchestrator reads initiative context
        # before deciding mode or proposing milestones (plan decision 4).
        lines.extend([
            "## Read initiative context",
            "",
            "Read `brief.md` from the run directory before deciding mode (CREATE / UPDATE) or",
            "proposing milestones. It contains the frozen initiative scope, decisions,",
            "constraints, and affected subsystems from intake -- treat it as authoritative.",
            "",
            "Read and analyze before writing. Do NOT write milestones.md in this step.",
            "",
            "## Determine mode",
            "",
            "Check whether milestones.md exists in the run directory.",
            "- If it does NOT exist: you are in **CREATE** mode.",
            # M4: UPDATE mode retired; routine post-execution UPDATE is exec-review's job.
            # milestone-spec is only entered explicitly after a major deviation.
            "- If it DOES exist: you are in **RE-DECOMPOSE** mode.",
            "",
            "---",
            "",
            "## CREATE mode",
            "",
            "### 1. Understand the initiative scope",
            "",
            "Read intake findings from the conversation context.",
            "",
            "### 2. Read the project's module structure",
            "",
            "Read the directory tree and top-level packages -- not individual files.",
            "This is the prior for where milestones should cut. Use `find`, `ls`, or",
            "`tree` to see the structure. Understand the visible module boundaries.",
            "",
            "### 3. Identify the affected subgraph",
            "",
            "From intake findings, identify which packages/modules the initiative",
            "touches. Read the import graph among those (or at least the outgoing",
            "imports from entry points). Understand how the affected modules relate",
            "to each other.",
            "",
            "### 4. Consult project memory",
            "",
            "Run `koan_reflect` for architectural constraints relevant to milestone",
            "scope and ordering. Use `koan_search` for specific past decomposition",
            "patterns or subsystem boundary decisions.",
            "",
            "### 5. Propose milestones",
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
            "---",
            "",
            # M4: RE-DECOMPOSE replaces UPDATE mode. The key framing distinction is
            # that this mode is for changing the milestone graph (adding, splitting,
            # merging milestones), NOT for routine post-execution bookkeeping.
            "## RE-DECOMPOSE mode",
            "",
            "### 1. Read milestones.md and the trigger context",
            "",
            "You are in this mode because milestones.md already exists AND the user has",
            "explicitly redirected to milestone-spec (typically after a major deviation",
            "surfaced in exec-review). Read milestones.md to understand the current state.",
            "Read the conversation context to understand WHY the user wants re-decomposition",
            "(what changed, what assumption was wrong, what scope shifted).",
            "",
            "### 2. Plan the revisions",
            "",
            "Identify which `[pending]` and `[in-progress]` milestones need revision. You",
            "may add new milestones, split existing ones, merge two pending milestones, or",
            "adjust scope sketches. You MUST preserve all `[done]` milestones and their",
            "Outcome sections intact -- those represent work already shipped.",
            "",
            "Routine post-execution UPDATE work (mark completed [done], append Outcome,",
            "advance next [pending]) does NOT happen here -- exec-review owns that flow",
            "per the M4 design. RE-DECOMPOSE is for when the milestone graph itself",
            "needs to change.",
            "",
            "---",
            "",
            "Call `koan_complete_step` with:",
            "- Mode (CREATE or RE-DECOMPOSE)",
            "- CREATE: proposed milestone list with rough sketches and file/module scope",
            "- RE-DECOMPOSE: what changed and why, proposed adjustments to [pending]/[in-progress] milestones",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Write or update milestones.md via `koan_artifact_write`.",
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
                '    status="In-Progress",',
                ")",
                "```",
                "",
                "## CREATE mode",
                "",
                "- Give the **first** milestone `[in-progress]` status; give all subsequent milestones `[pending]` status.",
                "- Write a rough sketch (3-6 sentences) describing what this milestone covers.",
                "- Order milestones by dependency: earlier milestones must not depend on later ones.",
                "",
                # M4: RE-DECOMPOSE replaces UPDATE mode in step 2. The critical
                # constraint is that exec-review is the sole owner of [done] transitions
                # and Outcome authoring; milestone-spec must not usurp that role.
                "## RE-DECOMPOSE mode",
                "",
                "- Add, split, merge, or revise `[pending]` and `[in-progress]` milestone sketches.",
                "- Preserve all `[done]` milestones and their Outcome sections intact.",
                "- Adjust the `[in-progress]` marker if the next milestone to work on changes.",
                "- Do NOT mark any milestone `[done]` -- exec-review owns that transition.",
                "- Do NOT add Outcome sections -- exec-review owns Outcome authoring.",
                "",
            ],
            # terminal_invoke replaces the "After artifact is approved" block.
            # next_phase="milestone-review" is bound in the workflow, mirroring
            # plan-spec -> plan-review and execute -> exec-review.
            invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases),
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
