# Orchestrator phase -- dynamic step count.
#
# Pre-execution (2 steps):
#   Step 1 (Dependency Analysis) -- read run artifacts, build dependency model
#   Step 2 (Story Selection)     -- select the first story for execution
#
# Post-execution (4 steps):
#   Step 1 (Verify)       -- run verification checks from verify.md
#   Step 2 (Verdict)      -- issue pass/retry/ask verdict
#   Step 3 (Propagate)    -- propagate learnings to remaining stories
#   Step 4 (Select Next)  -- select next story or complete epic
#
# ctx.step_sequence determines which mode: "pre-execution" or "post-execution".
# Sequence-specific context is injected via step_guidance(), not the system prompt.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "orchestrator"
SCOPE = "legacy"
TOTAL_STEPS = 2  # default; actual depends on step_sequence

PHASE_ROLE_CONTEXT = (
    "You are a workflow orchestrator for a multi-story coding epic. You make"
    " judgment calls at execution boundaries -- before and after each coding story runs.\n"
    "\n"
    "## Important: status.md may be stale\n"
    "\n"
    "Do not rely on `status.md` for current story state. The driver sets intermediate"
    " statuses (`planning`, `executing`, `verifying`) in its internal JSON state only --"
    " `status.md` is only updated by orchestrator tool calls (`koan_select_story`,"
    " `koan_complete_story`, etc.). Your authoritative inputs are `verify.md`, `plan.md`,"
    " git diff, and `epic.md` -- not `status.md`.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You are a decision-maker. You read content, apply judgment, and direct the workflow."
    " You do NOT write code. You do NOT modify source code files. You do NOT produce"
    " implementation plans.\n"
    "\n"
    "## What you own\n"
    "\n"
    "- **Verification**: Running the checks defined in a story's verify.md to determine whether the implementation is correct.\n"
    "- **Verdict**: Declaring the outcome of a story's execution -- success or retry with feedback.\n"
    "- **Story selection**: Choosing which story executes next based on the dependency graph and current epic state.\n"
    "- **Learning propagation**: When you discover something during verification, update remaining story.md files and the Decisions section of landscape.md. Mark every autonomous update with `[autonomous]`.\n"
    "- **User communication**: When you encounter genuine ambiguity or need human judgment, call `koan_ask_question`. After getting the answer, decide what to do (retry with new context, skip, etc.) and call the appropriate tool.\n"
    "\n"
    "## When to ask the user\n"
    "\n"
    "Call `koan_ask_question` when:\n"
    "- Verification reveals an ambiguity in requirements that cannot be resolved by reading the code.\n"
    "- A story fails in a way that suggests the spec was wrong, not the implementation.\n"
    "- You need human judgment on whether to retry, skip, or take a different approach.\n"
    "\n"
    "After getting the answer, record it and proceed with an appropriate tool call:\n"
    "- `koan_retry_story` -- if the user provided direction that lets you retry with a better plan\n"
    "- `koan_skip_story` -- if the user decided the story is no longer needed\n"
    "- `koan_complete_story` -- if the user confirmed the outcome is acceptable\n"
    "\n"
    "## Tools available\n"
    "\n"
    "- All read tools (read, bash, grep, glob, find, ls) -- for reading run artifacts and running verification checks.\n"
    "- `koan_select_story` -- to declare which story should execute next.\n"
    "- `koan_complete_story` -- to mark a story as successfully verified and completed.\n"
    "- `koan_retry_story` -- to send a story back to the executor with a detailed failure summary.\n"
    "- `koan_skip_story` -- to skip a story that is superseded or no longer needed.\n"
    "- `koan_ask_question` -- to ask the human a targeted question when judgment is genuinely ambiguous.\n"
    "- `koan_complete_step` -- to signal step completion with your findings.\n"
    "- `write` / `edit` -- for updating artifact files inside the run directory only.\n"
    "- `bash` -- for running verification commands.\n"
    "\n"
    "## The [autonomous] marker\n"
    "\n"
    "When you make a decision that modifies artifacts without explicit human instruction,"
    " prefix the added content with `[autonomous]` in the artifact file. This lets the"
    " human audit all autonomous decisions.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST NOT write or modify source code files.\n"
    "- MUST NOT call more than one verdict tool per verdict step.\n"
    "- MUST run ALL verification checks in verify.md before issuing a verdict.\n"
    "- MUST include a concrete, actionable failure summary when calling koan_retry_story.\n"
    "- When uncertain about a verdict, prefer koan_retry_story with a detailed failure_summary."
    " Ask the user only when the failure reveals a genuine requirements ambiguity."
)

PRE_STEP_NAMES: dict[int, str] = {
    1: "Dependency Analysis",
    2: "Story Selection",
}

POST_STEP_NAMES: dict[int, str] = {
    1: "Verify",
    2: "Verdict",
    3: "Propagate",
    4: "Select Next",
}


def _total_steps(ctx: PhaseContext) -> int:
    return 2 if ctx.step_sequence == "pre-execution" else 4


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    seq = ctx.step_sequence or "pre-execution"
    if seq == "pre-execution":
        return _pre_step_guidance(step, ctx)
    return _post_step_guidance(step, ctx)


def _pre_step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    ed = ctx.run_dir

    if step == 1:
        return StepGuidance(
            title=PRE_STEP_NAMES[1],
            instructions=[
                "You are beginning an execution run. Analyze story dependencies and select the first story for execution.",
                "",
                "Read the run artifacts to understand the full scope of work and story dependencies.",
                "",
                "## What to read",
                "",
                f"1. Read `{ed}/epic.md` -- understand the overall goal and scope.",
                f"2. Read `{ed}/brief.md` -- understand the product-level goals and constraints.",
                f"3. Read the Decisions section of `{ed}/landscape.md` -- understand decisions that shape execution.",
                f"4. Read each `story.md` file in `{ed}/stories/` -- understand what each story builds and depends on.",
                "",
                "## What to analyze",
                "",
                "After reading, build a dependency model:",
                "- Which stories must complete before others can begin? (explicit dependencies)",
                "- Which stories share files or interfaces? (implicit coupling)",
                "- Which stories are independent and could run in any order?",
                "- Are there any circular dependencies or unresolvable conflicts?",
                "",
                "Note the risk profile of each story: stories that touch shared infrastructure are higher risk.",
                "",
                "## Checklist before advancing",
                "",
                "Before calling koan_complete_step, confirm you have determined:",
                "- The execution order you recommend and why",
                "- Any risks or concerns you identified",
                "- The ID of the story you believe should run first",
            ],
        )

    if step == 2:
        return StepGuidance(
            title=PRE_STEP_NAMES[2],
            instructions=[
                "Select the first story for execution based on your dependency analysis from step 1.",
                "",
                "## Selection criteria",
                "",
                "Choose the story that:",
                "1. Has all its dependencies satisfied (no blockers)",
                "2. Is highest priority given the epic's goal",
                "3. Creates the most unblocking value for subsequent stories if completed",
                "",
                "Prefer foundational stories (shared types, interfaces, infrastructure) over leaf stories.",
                "",
                "## What to do",
                "",
                "Call `koan_select_story` with the ID of the story that should execute first.",
                "Then call `koan_complete_step` with your reasoning.",
            ],
            invoke_after=(
                "WHEN DONE: Call koan_select_story with your chosen story ID, then call koan_complete_step with your reasoning.\n"
                "Do NOT call koan_complete_step until koan_select_story has been called."
            ),
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


def _post_step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    ed = ctx.run_dir
    sid = ctx.story_id or "<story-id>"
    story_ref = f"story `{sid}`"
    verify_path = f"{ed}/stories/{sid}/plan/verify.md"

    if step == 1:
        return StepGuidance(
            title=POST_STEP_NAMES[1],
            instructions=[
                "Execution has just completed for a story. Verify the result, issue a verdict, propagate learnings, and select the next story.",
                "",
                f"Run all verification checks defined for {story_ref}.",
                "",
                "## What to read",
                "",
                f"1. Read `{verify_path}` -- every check you must run.",
                "2. Read the story's `story.md` to understand the acceptance criteria.",
                "",
                "## Running checks",
                "",
                "Execute every check listed in verify.md using bash. Do not skip checks.",
                "",
                "- Run compilation/type checks first (cheapest).",
                "- Run linting and static analysis next.",
                "- Run unit and integration tests last (most expensive).",
                "",
                "For each check, record:",
                "- The exact command you ran",
                "- The exit code",
                "- Relevant output (errors, failures, warnings)",
                "",
                "## Output",
                "",
                "Call koan_complete_step with your verification findings:",
                "- A summary of every check run and its result (pass/fail)",
                "- The full error output for any failures",
                "- Your preliminary assessment: does the implementation appear correct?",
            ],
        )

    if step == 2:
        return StepGuidance(
            title=POST_STEP_NAMES[2],
            instructions=[
                "Issue a verdict based on your verification findings from step 1.",
                "",
                "## Verdict options",
                "",
                "**koan_complete_story** -- All verification checks passed. The implementation is correct.",
                "",
                "**koan_retry_story** -- Verification failed, but the failure is fixable by the executor.",
                "MUST provide a detailed `failure_summary` that includes:",
                "  - Which checks failed and why",
                "  - The exact error messages",
                "  - What the executor should do differently",
                "",
                "**koan_ask_question then decide** -- The failure reveals a genuine requirements ambiguity.",
                "Ask the user a focused question. Based on the answer:",
                "  - Call koan_retry_story with the user's direction as context",
                "  - Call koan_skip_story if the user decides the story is no longer needed",
                "  - Call koan_complete_story if the user confirmed the outcome is acceptable",
                "",
                "## Decision rule",
                "",
                "If any check failed AND the failure is a concrete code bug -> koan_retry_story.",
                "If any check failed AND the failure reveals a requirements contradiction -> koan_ask_question then decide.",
                "If all checks passed -> koan_complete_story.",
                "",
                "Call EXACTLY ONE verdict tool (after any koan_ask_question).",
            ],
            invoke_after=(
                "WHEN DONE: Call EXACTLY ONE of: koan_complete_story, koan_retry_story, or (koan_ask_question then verdict tool).\n"
                "Then call koan_complete_step to advance to the next step."
            ),
        )

    if step == 3:
        return StepGuidance(
            title=POST_STEP_NAMES[3],
            instructions=[
                f"Propagate lessons from this story's execution to remaining stories and the Decisions section of `{ed}/landscape.md`.",
                "",
                "## What to propagate",
                "",
                "Review what you learned from verification (step 1) and the verdict (step 2):",
                "- Did the executor encounter something that affects remaining stories?",
                "- Did verification reveal an incorrect assumption in a remaining story's plan?",
                "- Did the implementation introduce a pattern remaining stories should follow?",
                "",
                "Only propagate information directly relevant to remaining stories.",
                "",
                "## How to propagate",
                "",
                "For each remaining story that is affected:",
                "1. Read its `story.md`.",
                "2. Add a `## [autonomous] Propagated Context` section with the relevant information.",
                "",
                f"Update the Decisions section of `{ed}/landscape.md` if a new decision was made or an existing one was invalidated.",
                "Add `[autonomous]` prefix to any autonomous additions.",
                "",
                "If no propagation is needed, skip file updates and proceed.",
                "",
                "## Skipping stories",
                "",
                "If this story's completion makes another story unnecessary, call `koan_skip_story` with a clear reason.",
                "",
                "Then call koan_complete_step with a summary of what was propagated.",
            ],
        )

    if step == 4:
        return StepGuidance(
            title=POST_STEP_NAMES[4],
            instructions=[
                "Select the next story to execute, or complete the epic if all stories are done.",
                "",
                "## What to check",
                "",
                "Read each story directory to understand which stories remain:",
                "- Stories with `pending` or `retry` status are candidates.",
                "- Done, skipped, or currently-selected stories are not candidates.",
                "",
                "## Selection criteria",
                "",
                "Among remaining stories:",
                "1. Filter to those whose dependencies are all completed.",
                "2. Among unblocked stories, prefer the one with highest value.",
                "3. A story in 'retry' state is highest priority -- it was already planned and executed.",
                "",
                "## What to do",
                "",
                "If one or more stories remain and are unblocked:",
                "- Call `koan_select_story` with the ID of the next story.",
                "- Then call `koan_complete_step` with your reasoning.",
                "",
                "If no stories remain (all completed or skipped):",
                "- Call `koan_complete_step` with a summary stating the epic is complete.",
                "  Do NOT call koan_select_story.",
                "",
                "If stories remain but all are blocked (dependencies not satisfied):",
                "- Call `koan_ask_question` to ask the user how to proceed (reorder, skip, or abort).",
                "  Based on the answer, call the appropriate tool.",
            ],
            invoke_after=(
                "WHEN DONE: If stories remain, call koan_select_story then koan_complete_step. If none remain, call koan_complete_step only."
            ),
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    total = _total_steps(ctx)
    if step < total:
        return step + 1
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass
