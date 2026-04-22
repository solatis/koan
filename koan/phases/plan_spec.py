# Plan-spec phase -- 2-step workflow.
#
#   Step 1 (Analyze)  -- review intake context and codebase; no writes
#   Step 2 (Write)    -- write plan.md to the run directory
#
# Scope: "plan" -- specific to the plan workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "orchestrator"
SCOPE = "plan"           # specific to the plan workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Analyze",
    2: "Write",
}

PHASE_ROLE_CONTEXT = (
    "You are a technical architect writing an implementation plan for a coding task.\n"
    "\n"
    "You read the codebase thoroughly before planning. Your plans reference actual"
    " file paths and function names, not abstract descriptions. You write instructions"
    " specific enough that a coding agent can execute them without making judgment"
    " calls about what to do.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You plan implementation. You do NOT write code. You produce a plan.md that an"
    " executor agent will follow to implement the changes.\n"
    "\n"
    "## Output\n"
    "\n"
    "One artifact: **plan.md**, produced via the MCP tool `koan_artifact_propose`."
    " Do NOT write files directly; the tool writes `plan.md` to the run directory"
    " and blocks until the user has reviewed it.\n"
    "\n"
    "## plan.md structure\n"
    "\n"
    "- **Approach summary**: 2-4 sentences on the overall strategy.\n"
    "- **Key decisions**: Numbered list of architectural/design decisions made.\n"
    "- **Implementation steps**: Numbered list, each specifying file path,\n"
    "  function/location, and the exact change. Be specific -- include function\n"
    "  signatures and type names where relevant.\n"
    "- **Constraints**: Hard boundaries the executor must respect.\n"
    "- **Verification**: How to verify the implementation is correct.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read codebase files the plan references to write precise instructions.\n"
    "  You read to understand structure, not to re-verify intake's findings.\n"
    "- MUST NOT write code -- write instructions for an executor that will write code.\n"
    "- MUST NOT invent file paths or function names you have not seen in the codebase.\n"
    "- MUST use koan_artifact_propose to produce plan.md. Built-in Write and Edit\n"
    "  tools are not available in this phase.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        lines: list[str] = []
        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])
        lines.extend([
            "## Consult project memory",
            "",
            "Before reading any codebase file, check what the project already",
            "knows about the subsystems you will plan changes for. Memory may",
            "contain coding conventions, procedures, and constraints that",
            "dictate HOW changes must be made in this codebase -- any of which",
            "will shape the instructions you write for the executor.",
            "",
            "If relevant memory entries appeared above (`## Relevant memory`),",
            "read them now.",
            "",
            "Then run `koan_reflect` with a broad question about the subsystems",
            "you will be planning for (e.g. 'what conventions govern changes to",
            "the X subsystem?'). Use `koan_search` for specific decisions or",
            "procedures you need to respect.",
            "",
            "Only after this should you read codebase files.",
            "",
            "Read and analyze before writing the plan. Do NOT write any files in this step.",
            "",
            "## What to read",
            "",
            "Intake has already explored the codebase and resolved ambiguities with the",
            "user. Trust those findings -- they are your starting point, not something",
            "to re-investigate.",
            "",
            "Read the codebase files you will reference in the plan. Your goal is to",
            "understand their structure well enough to write precise, file-level",
            "implementation instructions. Focus on:",
            "- Function signatures and type names you will reference in plan steps",
            "- Integration points between files the plan will touch",
            "- Ordering constraints (what depends on what)",
            "",
            "## What to analyze",
            "",
            "After reading, identify:",
            "- **Key architectural decisions**: What approach will you take and why?",
            "- **Integration points**: Which existing code will the changes touch?",
            "- **Risks**: Where could things go wrong during execution?",
            "- **Order**: What is the safest sequence of implementation steps?",
            "",
            "Call `koan_complete_step` with an analysis summary:",
            "- Overall approach (2-3 sentences)",
            "- Files that will be modified",
            "- Key decisions and rationale",
            "- Any ambiguities or risks spotted",
        ])
        if ctx.phase_instructions:
            lines.extend(["", "## Additional Context from Workflow Orchestrator", "", ctx.phase_instructions])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Compose the full plan and submit it via `koan_artifact_propose`.",
                "",
                "```",
                "koan_artifact_propose(",
                '    filename="plan.md",',
                '    content="""\\',
                "# Plan title",
                "...",
                '""",',
                ")",
                "```",
                "",
                "## Required sections in `content`",
                "",
                "### Approach summary",
                "2-4 sentences on the overall strategy.",
                "",
                "### Key decisions",
                "Numbered list of architectural/design decisions. For each"
                " decision, state the choice made and why (alternative"
                " considered + reason rejected if applicable).",
                "",
                "### Implementation steps",
                "Numbered list. Each step must specify:",
                "- **File**: exact path relative to project root",
                "- **Location**: function name, class, or section",
                "- **Change**: what to add, modify, or remove -- be specific.",
                "  Include function signatures, type names, and interface names"
                " where relevant.",
                "",
                "Order steps so that each step's dependencies are satisfied by"
                " prior steps.",
                "",
                "### Constraints",
                "Hard boundaries the executor must respect (from intake"
                " findings).",
                "",
                "### Verification",
                "How to verify the implementation is correct (tests to run,"
                " behaviors to check).",
                "",
                "## About the tool",
                "",
                "`koan_artifact_propose` writes plan.md to the run directory"
                " immediately and blocks until the user has reviewed it. The"
                " tool returns the review outcome as a text string. If the user"
                " approves, proceed normally. If the user requests revisions,"
                " revise and call `koan_artifact_propose` again with the same"
                " filename (full rewrite).",
                "",
                "Do NOT use Write or Edit -- those tools are not available in"
                " this phase.",
                "",
                "Call `koan_complete_step` when the review is accepted.",
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
