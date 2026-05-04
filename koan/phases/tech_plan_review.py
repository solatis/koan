# Tech-plan-review phase -- 2-step workflow.
#
#   Step 1 (Read)       -- read brief.md, core-flows.md, tech-plan.md; no writes
#   Step 2 (Evaluate)   -- stress-test decisions, verify diagrams, rewrite-or-loop-back
#
# This module is NOT a copy of plan_review.py with name substitutions. The
# verification mandate is fundamentally different:
#
#   - Codebase-verification authority: scouts ARE authorized and ENCOURAGED to
#     verify architectural integration-point claims. The do-not-verify-file-paths
#     rule from plan_review.py MUST NOT be carried here -- architectural review is
#     exactly when codebase verification matters.
#   - The do-not-flag-executor-resolvable list from plan_review.py does NOT apply.
#     Line numbers, file-path typos, and snippet syntax errors do not appear at
#     the architectural layer.
#   - This phase stress-tests architectural decisions, not implementation steps.
#
# Rewrite-or-loop-back: internal findings are corrected via koan_artifact_write;
# new-files findings surface via koan_yield with tech-plan-spec recommended.
# The phase does NOT auto-advance -- review outcome requires user direction.
#
# Scope: "general" -- reusable by any workflow; initiative workflow binds it.

from __future__ import annotations

from . import PhaseContext, StepGuidance
from .format_step import terminal_invoke

ROLE = "orchestrator"
SCOPE = "general"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Read",
    2: "Evaluate",
}

PHASE_ROLE_CONTEXT = (
    "You are the adversarial reviewer for the architecture artifact (tech-plan.md).\n"
    "\n"
    "Your mandate is to stress-test architectural decisions and verify diagram\n"
    "accuracy. Intake explored context. Core-flows captured operational behavior.\n"
    "Tech-plan-spec structured that into an architecture. None of those phases were\n"
    "asked to doubt their own output. Your job is to doubt it.\n"
    "\n"
    "## Your role\n"
    "\n"
    "Extract 3-7 critical architectural decisions that cross boundaries, handle\n"
    "failures, define schemas, or break from existing patterns. Stress-test each\n"
    "against six axes: simplicity, flexibility, robustness, scaling, codebase fit,\n"
    "and consistency with brief.md and core-flows.md.\n"
    "\n"
    "## Codebase-verification authority\n"
    "\n"
    "The architecture must integrate with existing structure. You ARE authorized\n"
    "and ENCOURAGED to dispatch `koan_request_scouts` to verify integration-point\n"
    "claims: does the proposed component boundary respect existing module structure?\n"
    "does the data-model schema align with existing tables/types? does the chosen\n"
    "integration seam exist where the architecture says it does?\n"
    "\n"
    "This is what distinguishes this phase from plan-review. The do-not-verify-file-\n"
    "paths rule from plan-review does NOT apply here. Architectural review is exactly\n"
    "when codebase verification matters. Scout dispatch is encouraged when integration-\n"
    "point claims are non-obvious.\n"
    "\n"
    "## Diagram accuracy check\n"
    "\n"
    "For each diagram in tech-plan.md, verify three rules (from\n"
    "docs/visualization-system.md, repeated here at point of use):\n"
    "\n"
    "- Grounding rule (section 6): no node/actor/state absent from the bounded\n"
    "  inputs (brief.md, core-flows.md, codebase analysis). Every diagram element\n"
    "  must trace to a named concept in the inputs.\n"
    "- Suppression rule (section 5): below-threshold slots must be rendered as\n"
    "  prose only -- no marker, no placeholder. Check that above-threshold slots\n"
    "  ARE rendered as diagrams (not silently omitted), and that below-threshold\n"
    "  slots have substantive prose covering the same content.\n"
    "- Level-separation rule (section 7 anti-patterns): no cross-level mixing\n"
    "  within a single diagram. A CON diagram must not contain components; a CMP\n"
    "  diagram must not contain other containers.\n"
    "\n"
    "## Rewrite-or-loop-back semantics\n"
    "\n"
    "For each finding, judge whether tech-plan-spec could have caught it from\n"
    "material already in scope (brief.md, core-flows.md, codebase notes it loaded).\n"
    "If yes: internal -- correct in place via `koan_artifact_write`. If no: new-\n"
    "files-needed -- surface via `koan_yield` with tech-plan-spec recommended.\n"
    "See docs/phase-trust.md for the full rewrite-or-loop-back doctrine.\n"
    "\n"
    "## Strict rules\n"
    "\n"
    "- MUST read tech-plan.md, brief.md, and core-flows.md (if present) before\n"
    "  evaluating. Trust none of them blindly.\n"
    "- MUST classify findings by severity: Critical / Major / Minor.\n"
    "- MUST classify each finding as internal or new-files-needed.\n"
    "- MUST issue `koan_artifact_write` for internal findings.\n"
    "- MUST recommend loop-back via `koan_yield` for new-files findings.\n"
    "- MUST NOT introduce architectural decisions of your own. You stress-test;\n"
    "  if a stress-test reveals a missing decision, recommend loop-back to\n"
    "  tech-plan-spec rather than authoring the decision yourself.\n"
    "- MAY dispatch `koan_request_scouts` to verify integration claims; this is\n"
    "  encouraged when the architecture asserts boundaries or seams whose existence\n"
    "  in the codebase is non-obvious.\n"
)


# -- Step guidance -------------------------------------------------------------

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Build the StepGuidance for the given step.

    Step 1 (Read): read brief.md, core-flows.md, tech-plan.md; build a mental
    model of 3-7 critical architectural decisions -- no writes. Step 2 (Evaluate):
    stress-test, verify diagrams, classify findings, rewrite-or-loop-back.
    """
    if step == 1:
        lines: list[str] = []
        # phase_instructions at top -- matches plan_review.py layout (lines 107-110)
        if ctx.phase_instructions:
            lines.extend(["## Workflow guidance", "", ctx.phase_instructions, ""])
        if ctx.memory_injection:
            lines.extend([ctx.memory_injection, ""])

        lines.extend([
            "## Read initiative context",
            "",
            "Read the following artifacts via `koan_artifact_view` before evaluating:",
            "",
            "1. `brief.md` -- frozen initiative scope, decisions, and constraints.",
            "2. `core-flows.md` -- frozen operational-behavior artifact (read if present;",
            "   it constrains the architecture's actor set and integration seams).",
            "3. `tech-plan.md` -- the artifact you are reviewing.",
            "",
            "Read and comprehend before evaluating. Do NOT write any files in this step.",
            "",
            "## Verification mandate",
            "",
            "You are the independent stress-tester. Trust nobody's claims. The architecture",
            "in tech-plan.md asserts component boundaries, integration seams, and data-model",
            "schemas. Your job is to doubt those assertions and verify the non-obvious ones",
            "against the actual codebase.",
            "",
            "Scouts are sanctioned and encouraged in this phase. When the architecture",
            "asserts a boundary or seam whose existence in the codebase is non-obvious,",
            "dispatch `koan_request_scouts` to verify it. This is unlike plan-review where",
            "mechanical accuracy is executor-resolvable. Architectural integration claims",
            "must be verified now, before milestone-spec decomposes work that assumes them.",
            "",
            "## Consult project memory",
            "",
            "Before verifying claims, check what the project already knows about the",
            "architectural territory in tech-plan.md.",
            "",
            "If relevant memory entries appeared above (`## Relevant memory`), read them now.",
            "",
            "Run `koan_reflect` with a question about the architecture (e.g. 'what do we",
            "know about the constraints on X subsystem's boundaries?'). Use `koan_search`",
            "for specific past architectural decisions or lessons.",
            "",
            "## Build a mental model",
            "",
            "After reading, extract 3-7 critical architectural decisions from tech-plan.md.",
            "For each decision, identify:",
            "",
            "- The claim: what does the architecture assert about this decision?",
            "- Upstream evidence: which concepts in brief.md and core-flows.md support it?",
            "- Codebase claims: what does the architecture assert about existing structure",
            "  (module boundaries, schema alignment, integration seams)?",
            "",
            "## What to call koan_complete_step with",
            "",
            "Call `koan_complete_step` with:",
            "- The list of 3-7 extracted architectural decisions.",
            "- For each: upstream evidence cross-reference AND codebase claims.",
            "- Immediate concerns or red flags spotted during reading.",
        ])
        return StepGuidance(title=STEP_NAMES[1], instructions=lines)

    if step == 2:
        return StepGuidance(
            title=STEP_NAMES[2],
            instructions=[
                "Evaluate tech-plan.md and report findings. Then apply rewrite-or-loop-back.",
                "",
                "## Severity classification",
                "",
                "Organize findings by severity:",
                "- **Critical**: would cause milestone-spec to decompose from a wrong",
                "  architectural assumption, or causes integration failure.",
                "- **Major**: significant architectural gap or inconsistency requiring",
                "  revision before milestone decomposition can proceed.",
                "- **Minor**: small issue the spec phase could likely address independently.",
                "",
                "## Architectural stress-test",
                "",
                "For each of the 3-7 critical decisions extracted in step 1, apply the",
                "six-axis stress-test:",
                "",
                "- **Simplicity**: is this the simplest architecture that satisfies the",
                "  requirements in brief.md?",
                "- **Flexibility**: does the architecture allow the initiative to evolve",
                "  without a complete redesign?",
                "- **Robustness**: how does the architecture handle failure, partial state,",
                "  and unexpected inputs?",
                "- **Scaling**: are there scaling assumptions that may not hold at the",
                "  initiative's intended load?",
                "- **Codebase fit**: does the architecture respect existing module structure,",
                "  conventions, and patterns? (verify non-obvious claims via scouts)",
                "- **Consistency with brief/core-flows**: does the architecture realize every",
                "  actor and flow described in core-flows.md, and does it satisfy every",
                "  constraint in brief.md?",
                "",
                "## Codebase-verification block",
                "",
                "For each codebase claim identified in step 1, decide whether to verify:",
                "- If the claim is obvious (well-known module boundary, widely documented",
                "  pattern): accept without verification.",
                "- If the claim is non-obvious: dispatch `koan_request_scouts` to verify.",
                "  Ground each finding in the scout report.",
                "",
                "## Diagram accuracy check",
                "",
                "For each diagram in tech-plan.md, verify three rules (repeated from",
                "PHASE_ROLE_CONTEXT at point of use):",
                "",
                "- **Grounding**: every node/actor/state must trace to a named concept in",
                "  brief.md, core-flows.md (if present), or codebase analysis.",
                "- **Suppression**: below-threshold slots must be rendered as prose only",
                "  -- no marker, no placeholder. Above-threshold slots must be rendered",
                "  as diagrams (not omitted). If you find a `<!-- diagram suppressed ...`",
                "  marker, treat it as an internal finding and rewrite to remove it.",
                "- **Level-separation**: no cross-level mixing within a single diagram.",
                "  CON must not contain components; CMP must not contain other containers.",
                "",
                "## Rewrite-or-loop-back classification",
                "",
                "For each finding, classify as one of:",
                "",
                "- **Internal**: tech-plan-spec could have caught this from brief.md,",
                "  core-flows.md, and the codebase material it already loaded. Examples:",
                "  a diagram violating the grounding rule, an inconsistency between two",
                "  sections, a decision that contradicts brief.md.",
                "- **New-files-needed**: catching this required loading codebase files",
                "  the spec phase did not open. Examples: an integration seam that does",
                "  not exist in the codebase as asserted; a schema alignment claim that",
                "  fails against the actual database types.",
                "",
                "## What to do with the classification",
                "",
                "- **All internal** -> rewrite tech-plan.md in place via",
                '  `koan_artifact_write(filename="tech-plan.md", content=<corrected>,',
                '  status="Final")`. Set Final if the rewrite addresses every finding.',
                "  Then yield with `milestone-spec` recommended.",
                "- **Any new-files-needed** -> do NOT rewrite yet. Yield with",
                "  `tech-plan-spec` recommended so the spec phase re-runs with the new",
                "  files in scope.",
                "- **Mixed** -> rewrite internal findings AND yield with `tech-plan-spec`",
                "  recommended. The spec phase will see both the partially-corrected",
                "  tech-plan.md and the new-files findings.",
                "",
                "## Using koan_ask_question",
                "",
                "If the review surfaces genuine ambiguities requiring user input (conflicting",
                "constraints, requirements unclear from brief.md), call `koan_ask_question`.",
                "Only ask questions that affect the evaluation outcome.",
                "",
                "## After reporting",
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
    """No-op -- tech_plan_review has no loop-back state to manage."""
    pass
