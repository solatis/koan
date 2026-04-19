# Ticket-breakdown phase -- 2-step workflow.
#
#   Step 1 (Analysis)   -- read run artifacts; understand scope and dependencies
#   Step 2 (Breakdown)  -- generate story-sized implementation tickets
#
# New phase with dedicated "ticket-breakdown" role.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "ticket-breakdown"
SCOPE = "legacy"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Analysis",
    2: "Breakdown",
}

PHASE_ROLE_CONTEXT = (
    "You are a ticket-breakdown writer for a coding task planner. You read the"
    " epic brief, core flows, and technical plan, then split the work into"
    " independent, story-sized implementation tickets with clear dependency"
    " diagrams.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You define the delivery units and their ordering. You do NOT decide HOW each"
    " ticket is implemented -- that belongs to the executor.\n"
    "\n"
    "## Story definition\n"
    "\n"
    "A story must be:\n"
    "- **Independent**: it can be reviewed and merged without depending on an unreleased sibling story.\n"
    "- **Bounded**: it fits in one pull request -- one coherent change to the codebase.\n"
    "- **Testable**: the change can be verified in isolation.\n"
    "- **Sequenced**: if stories have dependencies, they are ordered so earlier stories provide a stable base.\n"
    "\n"
    "## Story ID format\n"
    "\n"
    "Story IDs use the format: `S-NNN-descriptive-slug`\n"
    "Examples: `S-001-auth-provider`, `S-002-protected-routes`, `S-003-user-profile`\n"
    "\n"
    "Use zero-padded three-digit numbers. The slug is a short kebab-case description.\n"
    "\n"
    "## Output files\n"
    "\n"
    "You write the following files, all inside the run directory:\n"
    "\n"
    "1. **epic.md** -- overview of the full scope and the story list with sequencing rationale.\n"
    "2. **stories/{story-id}/story.md** -- one file per story with title, goal, scope, and dependencies.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST NOT include implementation details (specific functions, algorithms, data structures).\n"
    "- MUST NOT invent scope not present in the upstream artifacts.\n"
    "- MUST produce one story sketch per deliverable unit of work.\n"
    "- SHOULD keep stories small: prefer 4-8 stories over 1-2 large ones.\n"
    "- SHOULD order stories so foundational work comes first.\n"
    "- MUST use the S-NNN-slug story ID format.\n"
    "\n"
    "## Tools available\n"
    "\n"
    "- All read tools (read, bash, grep, glob, find, ls) -- for reading upstream artifacts.\n"
    "- `koan_request_scouts` -- to request additional codebase exploration if needed.\n"
    "- `write` / `edit` -- for writing output files inside the run directory.\n"
    "- `koan_complete_step` -- to signal step completion."
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    ed = ctx.run_dir

    if step == 1:
        return StepGuidance(
            title=STEP_NAMES[1],
            instructions=[
                "Read all upstream artifacts. Build a complete understanding of scope and dependencies.",
                "",
                "## Files to read",
                "",
                f"- `{ed}/landscape.md` -- task summary, codebase findings, constraints",
                f"- `{ed}/brief.md` -- epic brief: problem statement, goals, constraints",
                f"- `{ed}/core-flows.md` -- user journeys and sequence diagrams",
                f"- `{ed}/tech-plan.md` -- technical architecture (if present)",
                "",
                "## What to understand",
                "",
                "After reading, you should be able to answer:",
                "- What is the top-level goal of this epic?",
                "- What are the distinct deliverable units of work?",
                "- Which units depend on each other, and what is the safe delivery order?",
                "- Are there any parts of the work that are conditional or optional?",
                "",
                "Do not write any output files during this step.",
            ],
        )

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Produce the full ticket breakdown: epic.md and one story.md per story.",
                "",
                "## Story ID format",
                "",
                "Use S-NNN-slug format: S-001-auth-provider, S-002-protected-routes, etc.",
                "",
                "## epic.md",
                "",
                f"Write `{ed}/epic.md` with these sections:",
                "",
                "### Overview",
                "One to three paragraphs describing the full scope of this epic.",
                "",
                "### Stories",
                "A numbered list of all stories in delivery order.",
                "Format: `{n}. [{story-id}] {story title} -- {one-sentence goal}`",
                "",
                "### Sequencing Rationale",
                "Explain why the stories are ordered as they are. Identify dependency chains.",
                "Note any stories that can be worked in parallel.",
                "",
                "### Dependency Diagram",
                "A mermaid graph showing story dependencies.",
                "",
                "## stories/{story-id}/story.md",
                "",
                "Write one file per story with these sections:",
                "",
                "### Goal",
                "One sentence: what this story delivers and why.",
                "",
                "### Scope",
                "What is included. List what is explicitly OUT OF SCOPE.",
                "",
                "### Dependencies",
                "Stories that must be merged first. If none: `(none -- this story can start immediately)`",
                "",
                "### Acceptance Criteria",
                "Three to six testable conditions. Format: `- [ ] [condition]`",
                "",
                "After writing all files, call `koan_complete_step` with a summary:",
                "number of stories produced and the delivery order.",
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
