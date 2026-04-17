# Cross-artifact-validation phase -- 2-step workflow.
#
#   Step 1 (Read)      -- read all spec artifacts produced so far
#   Step 2 (Validate)  -- check cross-boundary consistency, write validation report
#
# New phase with dedicated "cross-artifact-validator" role.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "cross-artifact-validator"
SCOPE = "legacy"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Read",
    2: "Validate",
}

PHASE_ROLE_CONTEXT = (
    "You are a cross-artifact validator for a coding task planner. You read all"
    " spec artifacts produced by upstream phases and validate that they are"
    " internally consistent and complete.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You find contradictions, gaps, and inconsistencies across artifacts. You do"
    " NOT fix them -- you report them so upstream phases can be re-run if needed.\n"
    "\n"
    "## What you check\n"
    "\n"
    "- **Terminology consistency**: same concept must use the same name everywhere.\n"
    "- **Scope alignment**: stories in epic.md must cover all goals in brief.md.\n"
    "- **Flow coverage**: every core flow must be addressed by at least one story.\n"
    "- **Constraint propagation**: constraints from landscape.md must appear in relevant stories.\n"
    "- **Dependency validity**: story dependencies must form a DAG (no cycles).\n"
    "- **Acceptance criteria**: every story's acceptance criteria must be testable.\n"
    "\n"
    "## Output\n"
    "\n"
    "One file: **validation-report.md** in the epic directory.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST NOT modify any artifact. Report issues only.\n"
    "- MUST cite specific file and section for each finding.\n"
    "- MUST classify each finding as: BLOCKER (must fix before execution),"
    " WARNING (should fix), or NOTE (minor inconsistency).\n"
    "\n"
    "## Tools available\n"
    "\n"
    "- All read tools (read, bash, grep, glob, find, ls) -- for reading artifacts.\n"
    "- `write` / `edit` -- for writing the validation report.\n"
    "- `koan_complete_step` -- to signal step completion."
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    ed = ctx.run_dir

    if step == 1:
        return StepGuidance(
            title=STEP_NAMES[1],
            instructions=[
                "Read all spec artifacts produced so far.",
                "",
                "## Files to read",
                "",
                f"- `{ed}/landscape.md` -- task background, decisions, constraints",
                f"- `{ed}/brief.md` -- problem statement, goals, constraints",
                f"- `{ed}/core-flows.md` -- user journeys and sequence diagrams",
                f"- `{ed}/epic.md` -- story list, sequencing rationale, dependency diagram",
                f"- Each `{ed}/stories/*/story.md` -- individual story definitions",
                "",
                "Build a cross-reference map: for each concept, constraint, and goal,",
                "track where it appears across all artifacts.",
                "",
                "Do not write any output files during this step.",
            ],
        )

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Validate cross-boundary consistency and write the validation report.",
                "",
                f"Write `{ed}/validation-report.md` with these sections:",
                "",
                "## Summary",
                "Overall validation result: PASS (no blockers), WARN (warnings only), or FAIL (blockers found).",
                "",
                "## Findings",
                "One subsection per finding. Each must include:",
                "- **Severity**: BLOCKER / WARNING / NOTE",
                "- **Artifacts**: which files are involved",
                "- **Description**: what the inconsistency is",
                "- **Evidence**: specific quotes or references from the artifacts",
                "",
                "## Coverage Matrix",
                "A table mapping brief.md goals to stories, confirming each goal is addressed.",
                "",
                "## Flow Coverage",
                "A table mapping core flows to stories, confirming each flow is addressed.",
                "",
                "After writing, call `koan_complete_step` with a summary:",
                "number of findings by severity and overall result.",
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
