# Plan-review phase -- 2-step workflow.
#
#   Step 1 (Read)      -- review intake context and plan.md; no writes
#   Step 2 (Evaluate)  -- classify findings; rewrite internal ones in place
#                         or recommend loop-back for new-files findings
#
# Rewrite-or-loop-back: internal findings are fixed via koan_artifact_write;
# new-files findings surface by ending the turn with plan-spec recommended.
# Scope: "general" -- reusable by any workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "general"        # reusable by any workflow
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Read",
    2: "Evaluate",
}

PHASE_ROLE_CONTEXT = (
    "You are the adversarial reviewer for an implementation plan.\n"
    "\n"
    "You doubt the plan's approach. Intake explored and gathered context.\n"
    "Plan-spec structured that context into a plan. Neither was asked to\n"
    "review whether the approach is sound, complete, well-ordered, or\n"
    "respects the constraints in brief.md. Your job is to ask those\n"
    "questions and surface anything that would change the plan's approach\n"
    "or scope.\n"
    "\n"
    "## Your role\n"
    "\n"
    "Find problems that would cause the executor to take the wrong approach,\n"
    "miss a requirement from brief.md, or violate a constraint. You focus on\n"
    "approach soundness, completeness against brief.md, step ordering, risk,\n"
    "missing constraints, and docstring discipline (every newly-added or\n"
    "modified function in the plan must have a docstring directive).\n"
    "\n"
    "## Do NOT flag executor-resolvable issues\n"
    "\n"
    "The executor will fix the following automatically; flagging them wastes\n"
    "review attention and creates loop-back churn:\n"
    "\n"
    "- Incorrect line numbers.\n"
    "- Mismatching or renamed function names.\n"
    "- File-path typos.\n"
    "- Missing or wrong imports (in plan prose or in snippets).\n"
    "- Syntax errors in illustrative code snippets.\n"
    "- Minor wording inconsistencies between plan steps.\n"
    "\n"
    "Do NOT verify file paths, function names, or line numbers against the\n"
    "codebase. The executor reads the codebase when it implements the change\n"
    "and resolves these references at write time. Spend your attention on\n"
    "issues that change WHAT the plan does, not on its mechanical accuracy.\n"
    "\n"
    # M4: review phases apply rewrite-or-loopback semantics; prompt discipline
    # keeps each review phase rewriting only its own producer's artifact.
    "You apply rewrite-or-loop-back semantics. For each finding, you judge whether\n"
    "the producer (plan-spec) could have caught it from the files it already\n"
    "loaded; if yes, you fix the issue in place by issuing `koan_artifact_write`\n"
    "against the plan artifact. If the finding requires new files the producer\n"
    "didn't load, you recommend loop-back to plan-spec via the yield. See\n"
    "`docs/phase-trust.md` for the full doctrine.\n"
    "\n"
    "## Evaluation dimensions\n"
    "\n"
    "- **Approach soundness**: Is the strategy correct, or is the plan\n"
    "  building the wrong thing? An off-target approach is the most expensive\n"
    "  defect you can catch.\n"
    "- **Completeness**: Does the plan cover every requirement and decision\n"
    "  from brief.md? List any requirement not addressed.\n"
    "- **Ordering**: Are the implementation steps in a sequence where each\n"
    "  step's dependencies are satisfied by prior steps?\n"
    "- **Risks**: Edge cases, race conditions, integration hazards, or\n"
    "  destructive operations the plan does not account for.\n"
    "- **Missing constraints**: Cross-cutting rules from brief.md that the\n"
    "  plan does not propagate to the relevant implementation steps.\n"
    "- **Docstring discipline**: For every function the plan introduces or\n"
    "  modifies, does the plan instruct the executor to write or update its\n"
    "  docstring? Flag any new/modified function whose plan step does not\n"
    "  carry a docstring directive.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read the plan artifact and brief.md before evaluating.\n"
    "- MUST classify each finding as internal or new-files-needed.\n"
    "- MUST issue koan_artifact_write for internal findings (rewrite in place).\n"
    "- MUST recommend loop-back for new-files findings by ending your turn (no\n"
    "  tool call) with the recommendation, handing the decision to the user.\n"
    "- MUST NOT verify file paths, function names, line numbers, imports,\n"
    "  or snippet syntax against the codebase. Those are executor-resolvable\n"
    "  and listed in the do-not-flag enumeration above.\n"
    "- MUST flag any newly-added or modified function in the plan that lacks\n"
    "  a docstring directive at its Implementation step.\n"
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
        # brief.md gives the reviewer the authoritative requirement set, independent
        # of conversation history which may be long or noisy by this phase.
        lines.extend([
            "## Read initiative context",
            "",
            "Read `brief.md` from the run directory before verifying the plan's claims.",
            "It contains the frozen initiative scope, decisions, and constraints from",
            "intake. The plan must satisfy every requirement listed there; verify",
            "completeness against brief.md, not just the conversation history.",
            "",
            "Read and comprehend before evaluating. Do NOT write any files in this step.",
            "",
            "## Consult project memory",
            "",
            "Before verifying individual claims in plan.md, check what the",
            "project already knows about the correct approach for the",
            "subsystems being modified. Memory may contain past decisions that",
            "contradict the plan, lessons about what went wrong in similar",
            "changes, and procedures the executor must follow -- any of which",
            "reveal problems that cannot be detected by reading the plan and",
            "the code alone.",
            "",
            "If relevant memory entries appeared above (`## Relevant memory`),",
            "read them now.",
            "",
            "Then run `koan_reflect` with a broad question about the correct",
            "approach for the area the plan modifies (e.g. 'what is the",
            "expected approach for changes to the X subsystem?'). Use",
            "`koan_search` for specific past lessons or decisions that may bear",
            "on the plan.",
            "",
            "The question is not 'have we made this mistake before?' but 'what",
            "is the correct approach, and does this plan follow it?'",
            "",
            "Only after this should you verify individual claims.",
            "",
            "## Your evaluation mandate",
            "",
            "You doubt the plan's approach, completeness, ordering, and risk profile.",
            "Intake and plan-spec trusted each other on these dimensions; you trust",
            "neither. You do NOT verify file paths, function names, line numbers,",
            "imports, or snippet syntax against the codebase -- those are",
            "executor-resolvable and listed in the do-not-flag enumeration in your",
            "phase role context.",
            "",
            "## What to read",
            "",
            "1. Re-read brief.md so the requirements and constraints the plan must",
            "   satisfy are fresh in your context.",
            "2. Read the plan artifact. The workflow guidance above specifies which",
            "   file to review. If not specified, read `plan.md` in the run directory.",
            "3. Do NOT open codebase source files to verify file paths, function",
            "   names, or line numbers -- those are executor-resolvable. You may",
            "   open a source file when the plan's APPROACH for a specific change",
            "   is unclear and reading the surrounding code is the only way to",
            "   judge whether the approach makes sense.",
            "",
            "## Build a mental model",
            "",
            "After reading, you should be able to answer:",
            "- What does the plan claim to change, and is that the right thing to",
            "  change given brief.md?",
            "- Does the plan cover all requirements from brief.md?",
            "- Are the implementation steps in a sound order (dependencies before",
            "  dependents)?",
            "- For every newly-added or modified function in the plan, does the",
            "  matching Implementation step direct the executor to write or update",
            "  its docstring?",
            "",
            "Do NOT write an evaluation yet. Comprehend first.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Evaluate the plan and report findings in your response.",
                "",
                "## What to evaluate",
                "",
                "**Approach soundness**: Is the strategy correct? Will following the plan",
                "produce the change brief.md asks for, or is it building the wrong",
                "thing?",
                "",
                "**Completeness**: Does the plan cover every requirement from brief.md?",
                "List any requirement not addressed.",
                "",
                "**Ordering**: Are the implementation steps sequenced so each step's",
                "dependencies are satisfied by prior steps? List any out-of-order step.",
                "",
                "**Risks**: What could go wrong? Missing edge cases, race conditions,",
                "destructive operations the plan does not account for.",
                "",
                "**Missing constraints**: Are there constraints from brief.md that the",
                "plan does not propagate to the relevant Implementation steps?",
                "",
                "**Docstring discipline**: For every function the plan introduces or",
                "modifies, does the plan instruct the executor to write or update its",
                "docstring? Flag any new/modified function whose Implementation step",
                "lacks a docstring directive.",
                "",
                "## Severity classification",
                "",
                "Report findings organized by severity:",
                "- **Critical**: would cause the executor to fail or produce wrong results",
                "- **Major**: significant gap or incorrectness requiring plan revision",
                "- **Minor**: small issue the executor can likely resolve independently",
                "",
                "## Do NOT flag executor-resolvable issues",
                "",
                "The executor resolves the following automatically when it implements",
                "the plan. Do NOT flag them at any severity (not Critical, not Major,",
                "not Minor) and do NOT include them in your findings:",
                "",
                "- Incorrect line numbers.",
                "- Mismatching or renamed function names.",
                "- File-path typos.",
                "- Missing or wrong imports (in plan prose or in snippets).",
                "- Syntax errors in illustrative code snippets.",
                "- Minor wording inconsistencies between plan steps.",
                "",
                "Do NOT verify file paths, function names, or line numbers against the",
                "codebase. The executor will resolve those references at write time.",
                "Reviewer attention spent here is wasted: the issue gets fixed",
                "automatically and the loop-back round adds no value.",
                "",
                # M4: rewrite-or-loopback block; runs after severity classification,
                # before the yield. Internal findings are fixed in place; new-files
                # findings surface via the yield so the next plan-spec loads them.
                "## Rewrite-or-loop-back classification",
                "",
                "For each finding, classify it as one of:",
                "",
                "- **Internal**: the producer (plan-spec) could have caught this given the",
                "  files it already loaded (the plan artifact body + `brief.md`). Examples:",
                "  a step ordering bug, an inconsistency between two parts of the plan, a",
                "  decision that contradicts brief.md.",
                "- **New-files-needed**: catching this finding would have required the",
                "  producer to load files it did not load. Examples: a function-signature",
                "  claim against a file the plan does not reference; a constraint from",
                "  a sibling module the plan didn't open.",
                "",
                "## What to do with the classification",
                "",
                "- **All findings internal -> rewrite in place**. For targeted fixes (a few",
                "  lines), prefer `koan_artifact_edit(filename=<plan_artifact>, anchor=...,",
                "  text=...)` for each change. For extensive rewrites,",
                '  use `koan_artifact_write(filename="<plan_artifact>", content=<corrected_plan>)`',
                "  to replace the artifact wholesale. The corrected plan must address every",
                "  internal finding. Then end your turn with `execute` recommended",
                "  (proceed to executor handoff).",
                "- **Any finding new-files-needed -> recommend loop-back**. Do NOT call",
                "  `koan_artifact_write`. End your turn with `plan-spec` recommended so",
                "  the producer phase re-runs with the new files in scope. Surface the",
                "  new-files findings prominently so the next plan-spec session knows",
                "  what to load.",
                "- **Mixed**: rewrite the internal findings in place AND recommend",
                "  loop-back when you hand back. The producer phase, when it re-runs, will",
                "  see both the partially-rewritten plan and the new-files findings.",
                "",
                "The plan artifact filename comes from the workflow guidance: `plan.md`",
                "for plan workflow; `plan-milestone-N.md` for milestones workflow (read",
                "the workflow guidance above to determine N).",
                "",
                "## Using koan_ask_question",
                "",
                "If the review surfaces ambiguities requiring user input (requirements unclear,"
                " conflicting constraints, genuine design questions), call `koan_ask_question`.",
                "Only ask questions that affect the evaluation outcome.",
                "",
                "## After reporting",
            ],
            # terminal_invoke supplies the phase-boundary invoke_after.
            # next_phase=None: review findings determine whether to loop back to
            # plan-spec or proceed; user direction is required.
            invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases),
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
