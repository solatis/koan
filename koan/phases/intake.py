# Intake phase -- 3-step workflow.
#
#   Step 1 (Gather)   -- read task description, explore obvious files, dispatch scouts
#   Step 2 (Evaluate) -- process scout results, verify, ask questions
#   Step 3 (Write)    -- write landscape.md, present for user review
#
# Step 3 is review-gated: blocks until koan_review_artifact accepted.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .review_protocol import REVIEW_PROTOCOL

ROLE = "intake"
TOTAL_STEPS = 3

STEP_NAMES: dict[int, str] = {
    1: "Gather",
    2: "Evaluate",
    3: "Write",
}

SYSTEM_PROMPT = (
    "You are an intake analyst for a coding task planner. You read a task"
    " description, explore the codebase, and ask the user targeted questions until you"
    " have complete context for planning.\n"
    "\n"
    "Your output -- a single landscape.md file -- is the sole foundation for all"
    " downstream work. Every story boundary, every implementation plan, and every"
    " line of code written downstream depends on the quality and completeness of"
    " this file. Gaps here compound into wrong plans and wrong code.\n"
    "\n"
    "An assumption you make without verifying will become a fact the decomposer"
    " treats as decided. A question you don't ask is an answer you're making up."
    " When the executor writes the wrong code because landscape.md contained an"
    " unchecked assumption, that failure traces back to this phase.\n"
    "\n"
    "## Your role\n"
    "\n"
    "You gather, verify, and organize background information. You do NOT plan,"
    " design, or implement. You do NOT define what work should be done -- you"
    " describe what exists and what was said.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST NOT infer decisions not explicitly stated in the task description.\n"
    "- MUST NOT add architectural opinions or suggest approaches.\n"
    "- MUST NOT produce implementation recommendations.\n"
    "- MUST NOT define deliverables, work units, or scope boundaries -- that"
    " belongs to the decomposer.\n"
    "- MUST capture only what was explicitly said. If unclear, mark it as unresolved.\n"
    "- SHOULD prefer multiple-choice questions when the answer space is bounded.\n"
    "- SHOULD ground questions in codebase findings.\n"
    "\n"
    "## Thinking style\n"
    "\n"
    "Your reasoning should be dense and efficient. Follow these rules:\n"
    "\n"
    "- Start with your first insight, not a preamble. Your first word should be\n"
    "  a finding, a fact, or a decision -- not \"Now\", \"Excellent\", \"Let me\", or\n"
    "  any other commentary about what you're about to do.\n"
    "- End with your last insight, not a summary. When there is nothing new to\n"
    "  say, stop. Do not recap what you just worked out.\n"
    "- State things once. Never restate something from earlier in the same\n"
    "  reasoning block or from a prior step.\n"
    "- Use compressed notation: -> for flow, [OK] exists, [FAIL] missing, [!!] conflict,\n"
    "  therefore. Abbreviate freely (fn, dep, impl, cfg, db, auth, mw, req, resp).\n"
    "  Bullets and sentence fragments over full prose.\n"
    "\n"
    "These rules apply to your internal reasoning only. Tool arguments (scout\n"
    "prompts, questions) and written artifacts (landscape.md) should remain\n"
    "clear and complete.\n"
    "\n"
    "Examples of target density (WRONG -> RIGHT):\n"
    "\n"
    "Processing scout reports:\n"
    "  WRONG: \"The kernel-structure scout found that CUDA kernels live in src/kernels/\n"
    "  and use shared memory for the parallel reduction step. The build-system scout\n"
    "  found CMake with FindCUDAToolkit. The host-code scout reports that device memory\n"
    "  is allocated with cudaMalloc and copied back with cudaMemcpy. This answers my\n"
    "  questions about project structure. Nothing unexpected so far.\"\n"
    "  RIGHT: \"kernel-structure scout: src/kernels/, shared mem for reductions\n"
    "  build-system scout: CMake + FindCUDAToolkit\n"
    "  host-code scout: cudaMalloc -> cudaMemcpy pattern\n"
    "  All three answered [OK]; no unexpected findings\"\n"
    "\n"
    "Resolving conflicting information:\n"
    "  WRONG: \"There's a conflict between what the user said and what the code\n"
    "  shows. The user said the data pipeline runs hourly, but the cron expression\n"
    "  in scheduler.py is set to daily at midnight. I need to figure out which is\n"
    "  correct. Since the user is describing the desired behavior and the code\n"
    "  shows the current behavior, this is likely a change they want to make. I\n"
    "  should note this as an existing gap and ask the user to confirm.\"\n"
    "  RIGHT: \"[!!] task description: pipeline runs hourly <-> scout: scheduler.py cron = daily@midnight\n"
    "  task description = desired vs code = current therefore likely a requested change -> ASK user to confirm\"\n"
    "\n"
    "Classifying unknowns:\n"
    "  WRONG: \"Looking at what I've gathered so far, I think I have a good\n"
    "  understanding of the database schema and the CLI argument parsing. But I\n"
    "  still don't know how the plugin system loads extensions at runtime -- if we\n"
    "  get that wrong it could affect story boundaries. The user also mentioned a\n"
    "  config file format I haven't found, but that's just an implementation detail.\n"
    "  I should dispatch a scout for the plugin system and ask the user about the\n"
    "  config format.\"\n"
    "  RIGHT: \"[OK] db schema, CLI arg parsing\n"
    "  [FAIL] plugin loading -- wrong assumption changes story boundaries -> SCOUT\n"
    "  [FAIL] cfg file format -- impl detail, no scope impact -> SAFE\"\n"
    "\n"
    "## Workflow\n"
    "\n"
    "You work in three steps: gather context (task description + codebase + scouts),"
    " evaluate findings and ask questions, then write landscape.md.\n"
    "\n"
    "## Output\n"
    "\n"
    "One file: **landscape.md** in the epic directory.\n"
    "\n"
    "## Tools\n"
    "\n"
    "- Read tools (read, bash, grep, glob, find, ls) -- reading the codebase.\n"
    "- `koan_request_scouts` -- request parallel codebase exploration.\n"
    "- `koan_ask_question` -- ask the user clarifying questions.\n"
    "- `koan_review_artifact` -- present landscape.md for user review (final step only).\n"
    "- `write` / `edit` -- for writing landscape.md (final step only).\n"
    "- `koan_complete_step` -- signal step completion.\n"
    "\n"
    + REVIEW_PROTOCOL
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    if step == 1:
        project_dir = ctx.project_dir or ""
        lines = [
            "Read the task description, orient yourself in the codebase, and dispatch scouts.",
            "",
            "## 1. Task description",
            "",
        ]
        if ctx.task_description:
            lines.append(f"<task_description>\n{ctx.task_description}\n</task_description>")
        else:
            lines.append("(No task description provided.)")
        lines.extend([
            "",
            "As you read the task, track:",
            "- **Topic**: What is being built or changed?",
            "- **File references**: Every file, directory, or module mentioned.",
            "- **Decisions already made**: Only those explicitly stated and agreed upon.",
            "- **Constraints**: Technical, timeline, compatibility requirements.",
            "- **Gaps**: Questions raised but unanswered. Things unclear or unstated that would affect story boundaries.",
            "- **Conventions mentioned**: Any references to coding standards, test approaches, doc standards, or patterns to follow.",
            "",
            "Be faithful to what was said. Do not invent context or infer unstated decisions.",
            "",
            "## 2. Quick orientation -- open obvious files",
            "",
        ])
        if project_dir:
            lines.append(f"Project root: `{project_dir}`")
            lines.append("")
        lines.extend([
            "Open up to **5 files** that any investigation would start from:",
            "",
            "- `ls` the project root.",
            "- Open root-level orientation files if they exist: README.md, AGENTS.md, CLAUDE.md.",
            "- Open any file the task description explicitly referenced -- skim structure,",
            "  exports, key patterns (first 50-100 lines is enough).",
            "- If the task description mentions a module by name without a path, one",
            "  `find` or `ls` to locate it, then open the entry point.",
            "",
            "Budget: 5 file reads max. This is orientation, not investigation.",
            "Just enough to write scout prompts that reference actual function names,",
            "actual patterns, and actual file paths instead of vague labels.",
            "",
            "## 3. Plan and dispatch scouts",
            "",
            "Using the task description and what you observed in the files, identify the",
            "concerns that need investigation. Consider both:",
            "",
            "- What the task description explicitly references (files, modules, integration",
            "  points, assumptions that need verification, project conventions).",
            "- What the task description did NOT mention but could matter (hidden callers,",
            "  related subsystems, prior art, invariants, test coverage).",
            "",
            "Group related concerns into **3-5 clusters**. Each cluster becomes one",
            "scout. A scout is a broad investigator -- it can examine multiple files,",
            "trace dependencies, and answer several related questions in a single run.",
            "Merge concerns that touch the same area of the codebase or the same",
            "conceptual boundary into one scout with a multi-part prompt.",
            "",
            "3-5 scouts is the target. Fewer than 3 means your prompts are probably",
            "too broad to produce focused findings. More than 5 means you are splitting",
            "related concerns that a single scout could cover together.",
            "",
            "Use `koan_request_scouts` to dispatch all scouts in a single call.",
            "",
            "Each scout needs:",
            "- id: short kebab-case identifier (e.g., 'auth-and-permissions', 'data-layer')",
            "- role: investigator focus (e.g., 'authentication auditor', 'dependency tracer')",
            "- prompt: a rich, multi-part investigation brief. Tell the scout what area",
            "  to explore, what questions to answer, and what to look for. Include file",
            "  paths and function names from the orientation step. A good prompt is 3-8",
            "  sentences covering the full cluster.",
            "",
            "Example of a well-scoped scout prompt:",
            "  'Investigate the authentication subsystem rooted at src/auth/. Find all",
            "   callers of verifyToken(), identify the middleware chain in server.ts,",
            "   check whether session storage uses Redis or in-memory, and note any",
            "   TODO or FIXME comments related to auth. Report the permission model",
            "   (RBAC, ACL, or ad-hoc checks) and how it integrates with the router.'",
        ])
        if ctx.phase_instructions:
            lines.extend(["", "## Additional Context from Workflow Orchestrator", "", ctx.phase_instructions])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Analyze scout results, verify findings, and ask the user questions.",
                "",
                "## 1. Analyze scout results",
                "",
                "When scouts return, analyze each report:",
                "- Does the finding answer the questions you asked?",
                "- Does it reveal anything unexpected about the codebase?",
                "- Does it conflict with what the task description stated?",
                "",
                "## 2. Verify -- read files to confirm",
                "",
                "Scouts are good at exploration but their output should be verified.",
                "For key findings that affect scope or story boundaries, open the",
                "actual files and confirm what the scout reported. This is especially",
                "important for:",
                "",
                "- Integration points the scout identified",
                "- Patterns or conventions the scout claims to have found",
                "- Anything that conflicts with what the task description stated",
                "",
                "## 3. Enumerate what you know and what you don't",
                "",
                "Walk through each area relevant to the task and state what you have learned.",
                "Use this structure for each area:",
                "",
                "  **[Area name]** (e.g., 'Authentication', 'Database schema', 'API endpoints')",
                "  - Known: [what the task description and/or scouts established]",
                "  - Unknown: [what remains unclear or unverified]",
                "  - Source: [task description / scout findings]",
                "",
                "Cover every area relevant to the task. Be thorough -- gaps you miss here",
                "become gaps in the final output.",
                "",
                "Include project conventions as an area: where are coding style, testing strategy,",
                "architecture patterns, and documentation standards defined? If not explicitly",
                "documented, note whether they are emergent from code patterns or absent entirely.",
                "",
                "## 4. Downstream impact assessment",
                "",
                "For each 'Unknown' item, briefly assess:",
                "- If you assume wrong about this, what happens to downstream planning?",
                "- Could a wrong assumption split a story that should be one, or merge two that should be separate?",
                "- Would the executor hit a surprise that requires re-planning?",
                "",
                "This is the only phase where the user can be consulted. After intake, all",
                "downstream phases work from landscape.md alone. Anything you get wrong here",
                "will silently propagate through decomposition, planning, and execution.",
                "",
                "Mark each unknown as:",
                "- **ASK**: user input needed -- this affects scope, boundaries, or sequencing.",
                "- **SAFE**: genuinely an implementation detail with no scope impact.",
                "",
                "## 5. Ask questions",
                "",
                "For each 'Unknown' marked ASK, ask yourself: if I get this wrong, does it affect",
                "the decomposer's ability to define correct story boundaries? If yes or maybe -- ask.",
                "",
                "The user is your collaborator, not an interruption. Questions are how you verify",
                "your understanding against reality. The decomposer cannot ask questions later --",
                "this is the only chance to get clarification.",
                "",
                "Default: ask. You may skip a question ONLY if ALL of these are true:",
                "- It is purely an implementation detail (HOW to code something, not WHAT to build).",
                "- Getting it wrong would not change any story boundary.",
                "- It cannot be misinterpreted -- there is exactly one reasonable interpretation.",
                "",
                "Call `koan_ask_question` once with all your questions in the `questions` array.",
                "The user sees them one at a time. Aim for 3-5 questions.",
                "",
                "Formatting rules:",
                "- Prefer multiple-choice when the answer space is bounded.",
                "- Option labels are plain text -- no letter prefixes like (a)/(b), no numbering.",
                "- Do NOT include 'Other', 'None of the above', or similar meta-options.",
                "  The UI provides a free-text input automatically.",
                "- Put background and rationale in the `context` field, not in the option labels.",
                "- Ground questions in specific findings:",
                "  'Scout found X -- should this story follow the same pattern?'",
                "",
                "## 6. Process answers and follow up",
                "",
                "When answers arrive, think through each one carefully:",
                "",
                "a) **Does an answer point to files you should read?** If the user references",
                "   specific files, code, or documentation -- read them immediately using read tools.",
                "   Confirm the answer against what you find in the codebase.",
                "",
                "b) **Does an answer raise new questions?** If understanding one answer reveals",
                "   a new ambiguity or decision point -- ask the follow-up immediately via another",
                "   `koan_ask_question` call. Think through those answers the same way.",
                "",
                "c) **Are you satisfied?** If all answers are clear and no follow-ups are needed,",
                "   proceed to the next step.",
                "",
                "When in doubt, check with the user. It is always better to confirm an assumption",
                "than to let a wrong assumption propagate through planning and execution.",
            ],
        )

    if step == 3:
        lines = [
            f"Write `{ctx.epic_dir}/landscape.md`."
            if ctx.epic_dir
            else "Write `landscape.md` to the epic directory.",
            "This file is the sole input for all downstream phases. Write it carefully.",
            "",
            "## Formatting rules (apply to all sections)",
            "",
            "- **File references**: Always use markdown link format: `[display name](relative/path)`.",
            "  After each reference, briefly state what the file contains or why it matters.",
            "  Example: `[base-phase.ts](src/planner/phases/base-phase.ts) -- abstract lifecycle for all phase subagents`.",
            "  Never use bare paths.",
            "- **Section headings**: Use exactly the heading names below. Downstream agents locate content by heading.",
            "- **Content rule**: Describe what IS, not what SHOULD be done. No recommendations, no deliverables, no implementation suggestions.",
            "",
            "## Required sections",
            "",
            "### Task Summary",
            "What is being built or changed, in the user's own framing.",
            "State the scope as the user described it -- what areas of the codebase are affected and why.",
            "Do NOT decompose this into deliverables or work units. A downstream agent will do that.",
            "",
            "### Prior Art",
            "Previous attempts, referenced plans, related systems, or prior conversations mentioned.",
            "For each reference: what it contains, what is relevant to the current task, and what to expect when reading it.",
            "Example:",
            "  - [phases.md](plans/phases.md) -- phased implementation plan; Phase 5 defines the deliverables this epic covers",
            "  - Previous PR #42 attempted this but was reverted due to migration issues",
            "If none: (none referenced)",
            "",
            "### Codebase Findings",
            "Key findings from scouts, organized by area of the codebase (not by scout task).",
            "",
            "For each area, include:",
            "- **Entry points**: files, functions, or modules that are the primary sites of interest.",
            "  Use annotated file references: `[filename](path) -- what this file does`.",
            "- **Current behavior**: how the relevant code works today.",
            "- **Patterns**: recurring patterns, conventions, or idioms observed in this area.",
            "- **Integration points**: how this area connects to other parts of the system.",
            "",
            "If no scouts were needed: (no codebase exploration was needed)",
            "",
            "### Project Conventions",
            "Where to find coding standards and patterns for this project -- pointers to sources,",
            "not the conventions themselves. Downstream agents will read the referenced sources directly.",
            "",
            "Cover at minimum these areas. Add any other convention categories relevant to this project:",
            "",
            "#### Coding Style",
            "Where style is defined: linter config, formatter config, or emergent from codebase.",
            'Example: "ESLint config at [.eslintrc.json](.eslintrc.json)" or "no linter; follows Go stdlib style"',
            "",
            "#### Testing Strategy",
            "Where testing approach is defined: doc, config, patterns.",
            'Example: "[testing-philosophy.md](doc/01-principles/testing-philosophy.md) -- integration-first with testcontainers"',
            "",
            "#### Architecture Patterns",
            "Where architecture conventions live: docs, or emergent from code.",
            'Example: "constructor-based DI, no framework; see [BasePhase](src/planner/phases/base-phase.ts)"',
            "",
            "#### Documentation",
            "Where documentation standards are defined.",
            'Example: "CLAUDE.md per package", "JSDoc on all exports"',
            "",
            "If no explicit conventions exist for an area, note whether patterns are emergent from code or absent entirely.",
            "",
            "### Decisions",
            "Every question asked and the user's answer.",
            "Format: **Q:** [question] / **A:** [answer]",
            "If no questions were needed: (no questions were needed -- context was sufficient)",
            "",
            "### Constraints",
            "All constraints discovered: from task description, codebase, user answers.",
            "If none: (none identified)",
            "",
            "### Open Items",
            "Anything unresolved.",
            "If none: (none)",
            "",
            "## Pre-write verification",
            "",
            "Before writing, verify landscape.md is complete -- a downstream agent must be able",
            "to understand the full background from this file alone:",
            "- What is being built or changed, and why?",
            "- What existing code is affected and how is it structured?",
            "- Where do project conventions live?",
            "- What decisions have been made that constrain downstream work?",
            "- Is every file reference annotated with what it contains?",
            "",
            "If you cannot answer any of these from what you've gathered, note it in Open Items.",
            "",
            "## After writing",
            "",
            (
                f"Call `koan_review_artifact` with the path `{ctx.epic_dir}/landscape.md`"
                ' and description "Landscape document -- background information for downstream planning".'
                if ctx.epic_dir
                else "Call `koan_review_artifact` with the path to landscape.md"
                ' and description "Landscape document -- background information for downstream planning".'
            ),
        ]
        return StepGuidance(title=STEP_NAMES[3], instructions=lines)

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step < 3:
        return step + 1
    # Step 3 (Write): review-gated.
    if ctx.last_review_accepted is True:
        return None
    return 3


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    if step == 3:
        if ctx.last_review_accepted is None:
            return "You must call koan_review_artifact to present landscape.md for review before completing this step."
        if ctx.last_review_accepted is False:
            return "The user requested revisions. Address the feedback, then call koan_review_artifact again."
        return None
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass  # no loop-back in current workflow
