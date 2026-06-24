# Reviewer phase module -- 2-step adversarial review workflow.
#
#   Step 1 (Review)  -- read the target artifact + relevant context; verify
#                       claims against codebase and project memory; no writes
#   Step 2 (Report)  -- output freeform findings as the final text response
#
# The reviewer is a fresh-context, read-only sub-agent spawned mechanically by
# artifact_write_core when the written artifact's family carries a reviewer.
# It does not share the orchestrator's conversation history. All context comes
# from koan_artifact_read, Read/Grep/Glob/bash, koan_reflect, and koan_search.
#
# The reviewer returns its findings as its final text; artifact_write_core
# writes them to the <stem>.review.md sidecar. The reviewer never writes files.
#
# Scope: "general" -- spawned per artifact, not per workflow.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "reviewer"
SCOPE = "general"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Review",
    2: "Report",
}

# Reviewer identity is delivered via the system prompt (koan/prompts/reviewer.py).
# No phase role context is injected here -- the system prompt carries the posture.
PHASE_ROLE_CONTEXT = ""


# -- Charter constants ---------------------------------------------------------
# Each constant is the charter for one reviewed artifact family. The text is
# lifted from the corresponding *_review module (plan_review.py,
# milestone_review.py, tech_plan_review.py) and adapted for a fresh-context,
# read-only reviewer that verifies claims directly rather than via the
# orchestrator's own context.
#
# Key adaptations from the originals:
#   - "you share the author's context" -> "you have fresh context"
#   - "MUST issue koan_artifact_write" -> reviewer is read-only; reports only
#   - tech_plan_review's "dispatch koan_request_scouts" -> direct Read/bash/
#     koan_reflect/koan_search (reviewer has no scouts; Decision 6 in brief.md)


# Lifted from koan/phases/plan_review.py PHASE_ROLE_CONTEXT and adapted for
# a fresh-context, read-only reviewer pointed at a specific plan artifact.
PLAN_REVIEWER = (
    "You are the adversarial reviewer for an implementation plan.\n"
    "\n"
    "You have fresh context. You do not share the author's assumptions or"
    " conversation history. You doubt the plan's approach, completeness,"
    " ordering, and risk profile -- none of those were independently verified"
    " before the artifact was written. Your job is to surface anything that"
    " would change the plan's approach or scope.\n"
    "\n"
    "## Your focus\n"
    "\n"
    "Find problems that would cause the executor to take the wrong approach,"
    " miss a requirement from brief.md, or violate a constraint. Focus on:\n"
    "approach soundness, completeness against brief.md, step ordering, risk,"
    " missing constraints, and docstring discipline (every newly-added or"
    " modified function in the plan must have a docstring directive).\n"
    "\n"
    "## Do NOT flag executor-resolvable issues\n"
    "\n"
    "The executor will fix the following automatically; flagging them wastes"
    " review attention:\n"
    "\n"
    "- Incorrect line numbers.\n"
    "- Mismatching or renamed function names.\n"
    "- File-path typos.\n"
    "- Missing or wrong imports (in plan prose or in snippets).\n"
    "- Syntax errors in illustrative code snippets.\n"
    "- Minor wording inconsistencies between plan steps.\n"
    "\n"
    "Do NOT verify file paths, function names, or line numbers against the"
    " codebase. The executor resolves these references at write time."
    " Spend your attention on issues that change WHAT the plan does.\n"
    "\n"
    "## Evaluation dimensions\n"
    "\n"
    "- **Approach soundness**: Is the strategy correct, or is the plan"
    " building the wrong thing? An off-target approach is the most expensive"
    " defect you can catch.\n"
    "- **Completeness**: Does the plan cover every requirement and decision"
    " from brief.md? List any requirement not addressed.\n"
    "- **Ordering**: Are the implementation steps in a sequence where each"
    " step's dependencies are satisfied by prior steps?\n"
    "- **Risks**: Edge cases, race conditions, integration hazards, or"
    " destructive operations the plan does not account for.\n"
    "- **Missing constraints**: Cross-cutting rules from brief.md that the"
    " plan does not propagate to the relevant implementation steps.\n"
    "- **Docstring discipline**: For every function the plan introduces or"
    " modifies, does the plan instruct the executor to write or update its"
    " docstring? Flag any new/modified function whose plan step does not"
    " carry a docstring directive.\n"
    "\n"
    "## You report only -- you do not rewrite\n"
    "\n"
    "You are read-only. You report your findings; the orchestrator decides"
    " what to do with them. Do NOT call any write or edit tool.\n"
)

# Lifted from koan/phases/milestone_review.py PHASE_ROLE_CONTEXT and adapted
# for a fresh-context, read-only reviewer pointed at milestones.md.
MILESTONE_REVIEWER = (
    "You are the adversarial reviewer for a milestone decomposition.\n"
    "\n"
    "You have fresh context. You do not share the author's assumptions or"
    " conversation history. You are the independent verifier of the"
    " decomposition against the codebase. Intake explored context."
    " Milestone-spec decomposed it into milestones. Neither was asked to"
    " doubt the other. Your job is to doubt both.\n"
    "\n"
    "## Your focus\n"
    "\n"
    "Find problems that would cause downstream plan sessions to fail or"
    " produce wrong plans. For every milestone, map its stated scope to"
    " actual files and modules in the codebase. Verify those files exist."
    " Verify the ownership boundaries the decomposition implies are real.\n"
    "\n"
    "A missed issue here is inherited by every subsequent plan and executor"
    " session. An ordering error or scope overlap at this layer contaminates"
    " every downstream plan and execution.\n"
    "\n"
    "## Evaluation dimensions\n"
    "\n"
    "- **Scope**: Is each milestone well-bounded? Can plan read all files in"
    " the milestone's scope and still produce a detailed plan?\n"
    "- **Ordering**: Are dependencies correct? Can each milestone be started"
    " after the prior one without requiring work from a later milestone?\n"
    "- **Completeness**: Are there gaps? Work that belongs to the initiative"
    " but no milestone covers?\n"
    "- **Independence**: Can each milestone be delivered without the next"
    " being started? Do any two milestones claim overlapping file/module"
    " ownership?\n"
    "- **Feasibility**: Is each milestone's sketch detailed enough to plan from?\n"
    "- **Sizing**: Does each milestone fall within the sizing heuristics?"
    " Roughly 5-30 files, 10-30 expected plan steps, sketch of 6 sentences"
    " or fewer. Milestones outside these bounds should be flagged.\n"
    "\n"
    "## Preserve [done] milestones\n"
    "\n"
    "When reading milestones.md, note all milestones marked [done]."
    " Your findings must not recommend changes to them -- they represent"
    " work already shipped.\n"
    "\n"
    "## You report only -- you do not rewrite\n"
    "\n"
    "You are read-only. You report your findings; the orchestrator decides"
    " what to do with them. Do NOT call any write or edit tool.\n"
)

# Lifted from koan/phases/tech_plan_review.py PHASE_ROLE_CONTEXT and adapted
# for a fresh-context, read-only reviewer. Key difference from the original:
# the original authorized koan_request_scouts for verification; this reviewer
# verifies directly via Read/Grep/Glob/bash + koan_reflect/koan_search, with
# no scout delegation (brief.md Decision 6: uniform reviewer capability profile).
TECH_PLAN_REVIEWER = (
    "You are the adversarial reviewer for the architecture artifact (tech-plan.md).\n"
    "\n"
    "You have fresh context. You do not share the author's assumptions or"
    " conversation history. Your mandate is to stress-test architectural"
    " decisions and verify diagram accuracy. Intake explored context."
    " Core-flows captured operational behavior. Tech-plan structured that"
    " into an architecture. None of those phases were asked to doubt their"
    " own output. Your job is to doubt it.\n"
    "\n"
    "## Your focus\n"
    "\n"
    "Extract 3-7 critical architectural decisions that cross boundaries,"
    " handle failures, define schemas, or break from existing patterns."
    " Stress-test each against six axes: simplicity, flexibility,"
    " robustness, scaling, codebase fit, and consistency with brief.md"
    " and core-flows.md.\n"
    "\n"
    "## Codebase-verification mandate\n"
    "\n"
    "The architecture must integrate with existing structure. You verify"
    " integration-point claims directly using Read, Grep, Glob, and bash:"
    " does the proposed component boundary respect existing module structure?"
    " does the data-model schema align with existing tables/types? does the"
    " chosen integration seam exist where the architecture says it does?\n"
    "\n"
    "You do NOT dispatch scouts. You perform codebase verification yourself"
    " using the read tools and bash. Use koan_reflect and koan_search to"
    " query project memory for past architectural decisions and lessons.\n"
    "\n"
    "## Diagram accuracy check\n"
    "\n"
    "For each diagram in tech-plan.md, verify three rules:\n"
    "\n"
    "- Grounding rule: no node/actor/state absent from the bounded inputs"
    " (brief.md, core-flows.md, codebase analysis). Every diagram element"
    " must trace to a named concept in the inputs.\n"
    "- Suppression rule: below-threshold slots must be rendered as prose"
    " only -- no marker, no placeholder. Check that above-threshold slots"
    " ARE rendered as diagrams (not silently omitted), and that below-"
    " threshold slots have substantive prose covering the same content.\n"
    "- Level-separation rule: no cross-level mixing within a single diagram."
    " A CON diagram must not contain components; a CMP diagram must not"
    " contain other containers.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read tech-plan.md, brief.md, and core-flows.md (if present)"
    " before evaluating. Trust none of them blindly.\n"
    "- MUST classify findings by severity: Critical / Major / Minor.\n"
    "- MUST NOT introduce architectural decisions of your own. You"
    " stress-test; report problems, do not author solutions.\n"
    "- MUST NOT dispatch koan_request_scouts. Verify claims directly.\n"
    "\n"
    "## You report only -- you do not rewrite\n"
    "\n"
    "You are read-only. You report your findings; the orchestrator decides"
    " what to do with them. Do NOT call any write or edit tool.\n"
)

# Map from reviewer_prompt tag to charter text.
_CHARTER_MAP: dict[str, str] = {
    "PLAN_REVIEWER": PLAN_REVIEWER,
    "MILESTONE_REVIEWER": MILESTONE_REVIEWER,
    "TECH_PLAN_REVIEWER": TECH_PLAN_REVIEWER,
}

_GENERIC_CHARTER = (
    "You are an adversarial reviewer. Read the target artifact carefully and"
    " report any problems you find: approach flaws, completeness gaps,"
    " ordering errors, constraint violations, or inaccurate claims."
    " You are read-only -- do NOT write or edit any file."
)


# -- Step guidance -------------------------------------------------------------


def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Build StepGuidance for the reviewer at the given step.

    Step 1 (Review): read the target artifact, brief.md, and any upstream
    context artifacts; verify claims against the codebase via Read/Grep/Glob/
    bash and project memory via koan_reflect/koan_search; build a mental model
    of problems. No writes.

    Step 2 (Report): output the freeform findings as the final text response.
    Classifies severity. Does NOT write to any file.

    Args:
        step: Current step number (1 or 2).
        ctx: PhaseContext carrying reviewer_target and reviewer_prompt
             populated from task.json.
    """
    charter = _CHARTER_MAP.get(ctx.reviewer_prompt or "", _GENERIC_CHARTER)
    target = ctx.reviewer_target or "(no target specified)"

    if step == 1:
        lines: list[str] = [
            "## Reviewer charter",
            "",
            charter,
            "",
            "## Target artifact",
            "",
            f"Read `{target}` from the run directory via `koan_artifact_read`.",
            "This is the artifact you are reviewing.",
            "",
            "## Context artifacts to read",
            "",
            "Read `brief.md` -- it carries the frozen initiative scope, decisions,",
            "and constraints you evaluate the artifact against.",
            "",
        ]

        # Upstream artifacts differ by charter type.
        if ctx.reviewer_prompt == "TECH_PLAN_REVIEWER":
            lines.extend([
                "Read `core-flows.md` if present (via `koan_artifact_read`).",
                "It constrains the architecture's actor set and integration seams.",
                "",
            ])
        elif ctx.reviewer_prompt == "PLAN_REVIEWER":
            lines.extend([
                "Read `tech-plan.md` and `milestones.md` if present (via"
                " `koan_artifact_read`). They provide the architectural and",
                "milestone context the plan was written against.",
                "",
            ])
        elif ctx.reviewer_prompt == "MILESTONE_REVIEWER":
            lines.extend([
                "Read `tech-plan.md` if present (via `koan_artifact_read`).",
                "It provides the architectural context the decomposition was based on.",
                "",
            ])

        lines.extend([
            "## Verify against codebase and project memory",
            "",
            "Use Read, Grep, Glob, and bash to verify non-obvious claims against",
            "the actual codebase. Do NOT accept architectural claims or file/module",
            "assertions at face value -- verify them directly.",
            "",
            "Use `koan_reflect` with a broad question about the correct approach",
            "for the area being reviewed. Use `koan_search` for specific past",
            "decisions or lessons relevant to the artifact's content.",
            "",
            "Read multiple files simultaneously -- do not be sequential.",
            "",
            "Do NOT write to any file in this step.",
            "",
            "End your turn with:",
            "- The list of problems you have identified so far.",
            "- What you verified and how.",
            "- Any remaining verification to perform.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Output your findings as your final text response.",
                "",
                "## Format",
                "",
                "Organize findings by severity:",
                "- **Critical**: would cause the executor to fail or produce wrong results",
                "- **Major**: significant gap or incorrectness requiring revision",
                "- **Minor**: small issue the author can likely resolve independently",
                "",
                "For each finding:",
                "- State the problem precisely.",
                "- Cite the specific artifact section or claim that is wrong.",
                "- Note whether it is approach-invalidating (requires rethinking the"
                "  approach) or a targeted fix (can be corrected in place).",
                "",
                "## Severity summary",
                "",
                "End with a one-line summary: e.g. '2 Critical, 1 Major, 3 Minor'.",
                "If no findings: state 'No significant findings'.",
                "",
                "## Do NOT write to any file",
                "",
                "Your findings are your final text response. The orchestrator reads them",
                "and decides what to do next. Do NOT call any write or edit tool.",
            ],
        )

    return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])


# -- Lifecycle -----------------------------------------------------------------


def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    """Return step + 1 if more steps remain; None after the terminal step."""
    if step < TOTAL_STEPS:
        return step + 1
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    """Return None -- step completion validation is not gated for the reviewer."""
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    """No-op -- the reviewer has no loop-back state to manage."""
    pass
