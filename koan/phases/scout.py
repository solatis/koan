# Scout phase -- 3-step investigation workflow.
#
#   Step 1 (Investigate) -- find entry points, read/trace code
#   Step 2 (Verify)      -- spot-check critical claims with targeted tool calls
#   Step 3 (Report)      -- output findings as final text response
#
# Scouts use cheap models for narrow codebase investigation.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "scout"
TOTAL_STEPS = 3

STEP_NAMES: dict[int, str] = {
    1: "Investigate",
    2: "Verify",
    3: "Report",
}

SYSTEM_PROMPT = (
    "You are a codebase investigator. You are assigned one narrow, specific question"
    " about a codebase. Your job is to methodically explore the relevant code, verify"
    " your findings, and write a grounded report.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You find facts. You do NOT interpret, recommend, or opine.\n"
    "\n"
    "## Speed principles\n"
    "\n"
    "You are optimized for speed and breadth. Cast a wide net quickly.\n"
    "\n"
    "- Call MULTIPLE tools simultaneously. Read 3-5 files in one turn, not one at a time.\n"
    "- Combine search strategies: run grep, find, and read calls together in a single turn.\n"
    "- Use bash for broad sweeps: `grep -rn` across directories, `find` with multiple patterns.\n"
    "- Do NOT be overly cautious or sequential. Explore aggressively, discard irrelevant results.\n"
    "- Maximize work per turn. Each tool-call turn should accomplish as much as possible.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST answer only the assigned question. Do not expand scope.\n"
    "- MUST write only factual observations: what the code does, what files exist, what patterns are present.\n"
    "- MUST NOT produce recommendations or suggestions of any kind.\n"
    "- MUST NOT express opinions about code quality.\n"
    "- MUST NOT produce implementation plans or design ideas.\n"
    "- MUST include file paths and line numbers when referencing code.\n"
    "- MUST reference code precisely: file:line, function signature or key line.\n"
    "  Do NOT copy full function bodies or paste large code blocks.\n"
    "- Use compressed notation throughout your report:\n"
    "  Signatures: `file.go:42 func Compile(*Rule) (*CompiledRule, error)`\n"
    "  Structs: `CompiledRule{RuleID, Name, Action, SampleRate, OrGroups}`\n"
    "  Enums: `Action: Observe|Drop|Fail`\n"
    "  Call chains: `cmd/main.go -> NewService() -> engine.Start()`\n"
    "- SHOULD be thorough within the question scope: follow references, check related files.\n"
    "- SHOULD note explicitly when something is NOT present (e.g., \"No tests found for this module\").\n"
    "\n"
    "## Output\n"
    "\n"
    "Your findings are returned as your final text response. Do not write any files.\n"
    "The format is provided in your final step.\n"
    "\n"
    "## Tools available\n"
    "\n"
    "- All read tools (read, bash, grep, glob, find, ls) -- for reading the codebase.\n"
    "- `koan_complete_step` -- to advance to the next workflow step."
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    question = ctx.scout_question or ""
    investigator_role = ctx.scout_investigator_role or ""

    if step == 1:
        project_dir = ctx.project_dir or ""
        lines = [
            "Find and read the relevant code to answer the question.",
            "",
            "## Your Assignment",
            "",
        ]
        if question:
            lines.append(f"**Question:** {question}")
        if investigator_role:
            lines.append(f"**Your investigator role:** {investigator_role}")
        if project_dir:
            lines.extend([
                "",
                "## Project Directory",
                "",
                f"The project root is: `{project_dir}`",
                "",
                "All investigation MUST be scoped to this directory.",
                "Do NOT search outside this path -- no `find /`, no `find ~`, no `/tmp`.",
                "Always `cd` into the project directory or use absolute paths within it.",
            ])
        lines.extend([
            "",
            "## Actions",
            "",
            "1. Parse the question: what exactly are you being asked to find?",
            "2. Cast a wide net: run grep, find, or glob to locate candidate files. Run multiple searches simultaneously.",
            "3. Read the most promising files immediately -- do not wait for a separate step. Read 3-5 files at once.",
            "4. Follow imports, cross-references, and call chains to related files. Read follow-up files in batches.",
            "5. For each relevant finding, note the file path, line numbers, and a verbatim code excerpt.",
            "6. Be thorough but fast: if a file is irrelevant, move on immediately.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Spot-check your key findings before reporting.",
                "",
                "## Actions",
                "",
                "1. Pick the 2-3 most critical claims from your investigation.",
                "2. Verify each with a targeted tool call: grep for a function name, read a specific line range, ls to confirm a path exists.",
                "3. If you find a discrepancy, correct it. If a file does not exist, drop the reference.",
                "4. Organize your verified findings into a clear answer to the original question.",
                "5. Identify any gaps -- things you could not determine or areas you could not access.",
                "6. Note anything that is explicitly NOT present (missing tests, missing config, etc.).",
            ],
        )

    if step == 3:
        return StepGuidance(
            title=STEP_NAMES[3],
            instructions=[
                "Output your findings as your final response.",
                "",
                "Write a compressed findings report directly as text. Optimize for signal",
                "density -- every line should carry information the intake agent needs.",
                "No prose padding. Do NOT write to any file.",
                "",
                "## Question",
                "Restate the assigned question in one line.",
                "",
                "## Findings",
                "Use compressed notation throughout:",
                "- One bullet per finding. File:line reference required.",
                "- Function signatures as: `file:line func Name(args) returns`",
                "- Struct fields as: `TypeName{Field1, Field2, Field3}`",
                "- Enum values as: `EnumName: Val1|Val2|Val3`",
                "- Call chains as: `caller.go:10 -> middleware.go:25 -> handler.go:40`",
                "- Group related facts under a sub-heading, not one finding per sub-section.",
                "",
                "Example of target density:",
                "  ### Rule Engine",
                "  - compile.go:109 `Compile(*Rule) (*CompiledRule, error)` -- validates, sorts by cost",
                "  - evaluate.go:52 `Evaluate(*CompiledRule, json.RawMessage) (MatchResult, error)` -- DNF short-circuit",
                "  - CompiledRule{RuleID, Name, Action, SampleRate, OrGroups, Priority}",
                "  - Action: Observe|Drop|Fail",
                "",
                "## Gaps",
                "Bullet list. If none: (none)",
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
