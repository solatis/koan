# Workflow definitions for the koan orchestrator.
#
# A Workflow composes its phases directly via a dict[str, PhaseBinding].
# Each PhaseBinding carries the phase module reference and the per-workflow
# guidance injection. No global registry is needed at runtime -- dispatch
# reads from the workflow's phases dict, making the binding explicit and
# the invariant (module agrees with workflow) structurally enforced.
#
# Design notes:
#   - frozen=True prevents field reassignment after construction.
#   - frozen=True does NOT make Workflow hashable -- dict fields are unhashable.
#   - Workflows are defined as module-level constants (PLAN_WORKFLOW, etc.).
#   - Phase transition validation: any phase in phases.keys() is reachable
#     from any other (user-directed), except self-transitions. The transitions
#     dict guides UI suggestions but does not constrain.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..phases import (
    core_flows,
    curation,
    exec_review as exec_review_phase,
    execute as execute_phase,
    frame,
    intake,
    milestone_review,
    milestone_spec,
    plan_review,
    plan_spec,
    tech_plan_review,
    tech_plan_spec,
)


# -- Types --------------------------------------------------------------------

@dataclass(frozen=True)
class PhaseBinding:
    """Binds a phase module to its per-workflow configuration.

    Each workflow maps phase name strings to PhaseBinding values.
    The binding carries the module reference and the guidance
    injection, keeping them co-located so dispatch cannot desync.
    """
    module: Any          # phase module (e.g. intake, curation)
    description: str = ""
    guidance: str = ""   # injected as ctx.phase_instructions at step 1
    # Static retrieval directive for mechanical RAG injection at step 1.
    # Empty string disables injection for this phase. The directive belongs
    # here (not in the phase module) so the same module can be reused across
    # workflows with different retrieval intent.
    retrieval_directive: str = ""
    # Recommended next phase for auto-advance. None means the phase yields
    # with multi-option suggestions for user direction; a phase name means
    # the phase auto-advances via koan_set_phase. Treat as guidance: the
    # orchestrator may call koan_yield instead when findings warrant.
    # Same module can have different next_phase across workflows.
    next_phase: str | None = None


@dataclass(frozen=True)
class Workflow:
    """Immutable workflow definition with explicit phase bindings.

    The workflow composes its phases directly: each PhaseBinding
    carries the phase module reference, description, and guidance.
    Dispatch reads from get_module() / get_binding() instead of a
    global registry.

    Attributes:
        name: Short identifier (e.g. "plan", "milestones").
        description: Human-readable description shown in the UI.
        phases: Ordered dict of phase name -> PhaseBinding. Insertion
            order determines UI display order. Each binding carries
            the module reference and per-workflow guidance injection.
        initial_phase: Phase name the orchestrator starts in.
        transitions: Per-phase ordered list of suggested next phase
            names. Guides the orchestrator's boundary response; user
            can override. Any-to-any within the workflow is valid.
    """
    name: str
    description: str
    phases: dict[str, PhaseBinding]
    initial_phase: str
    transitions: dict[str, list[str]]

    # -- Derived accessors (backward compat) ----------------------------------

    @property
    def available_phases(self) -> tuple[str, ...]:
        """All phase names in this workflow (insertion-ordered)."""
        return tuple(self.phases.keys())

    @property
    def phase_descriptions(self) -> dict[str, str]:
        """Phase name -> description mapping."""
        return {k: b.description for k, b in self.phases.items()}

    @property
    def phase_guidance(self) -> dict[str, str]:
        """Phase name -> guidance text mapping (non-empty entries only)."""
        return {k: b.guidance for k, b in self.phases.items() if b.guidance}

    # -- Lookup ---------------------------------------------------------------

    def get_binding(self, name: str) -> PhaseBinding | None:
        """Look up a PhaseBinding by phase name."""
        return self.phases.get(name)

    def get_module(self, name: str) -> Any | None:
        """Look up the phase module by phase name."""
        b = self.phases.get(name)
        return b.module if b else None


# -- Exec-review guidance (injected as phase_instructions) --------------------
#
# Per-workflow guidance for the exec-review phase. The plan workflow routes
# to curation or plan-spec; the milestones workflow routes to milestone-spec.

_EXEC_REVIEW_PLAN_GUIDANCE = (
    "## Exec-review context\n"
    "\n"
    "Review what the executor accomplished for this plan. After your assessment,\n"
    "transition to `curation` to capture lessons. If the execution had significant\n"
    "deviations that require replanning, transition to `plan-spec` instead.\n"
)

# M4: exec-review now owns both the plan artifact rewrite-or-loopback AND the
# milestones.md UPDATE. milestone-spec UPDATE mode is retired; routine post-execution
# bookkeeping happens here. milestone-spec is only entered for RE-DECOMPOSE.
_EXEC_REVIEW_MILESTONES_GUIDANCE = (
    "## Exec-review context\n"
    "\n"
    "Review what the executor accomplished for this milestone. After classifying\n"
    "the outcome, apply two artifact updates in step 2:\n"
    "\n"
    "1. **Plan artifact rewrite-or-loop-back**: classify each deviation finding\n"
    "   as internal vs new-files-needed; rewrite plan-milestone-N.md in place\n"
    "   for internal findings; recommend loop-back to plan-spec for new-files.\n"
    "\n"
    "2. **milestones.md UPDATE**: mark the completed milestone `[done]`, append\n"
    "   the four-subsection Outcome (Integration points / Patterns / Constraints\n"
    "   / Deviations), advance the next `[pending]` milestone to `[in-progress]`,\n"
    "   and adjust remaining milestone sketches if execution surfaced new\n"
    "   constraints. Preserve all prior `[done]` Outcome sections intact.\n"
    "\n"
    "After both updates: yield. The orchestrator picks `plan-spec` to begin the\n"
    "next milestone, `curation` if all milestones are done or skipped, or\n"
    "`milestone-spec` for a manual RE-DECOMPOSE if the milestone graph itself\n"
    "needs to change.\n"
)


# -- Curation directives (injected as phase_instructions) ---------------------
#
# Directives bind the static curation step prompts to a specific entry
# point. They own *what to look for* and *which source-gathering moves
# are authorized*. They must NOT own step mechanics (which belong to
# koan/phases/curation.py) or writing discipline (which belongs to the
# curation system prompt).

_POSTMORTEM_DIRECTIVE = (
    "## Source: postmortem\n"
    "\n"
    "The source for this curation is your conversation history with the\n"
    "user during the workflow that just completed. The transcript IS the\n"
    "task. Ignore the <task> block in step 1 -- it carries the parent\n"
    "workflow's task description, which is not your curation source.\n"
    "\n"
    "## What to harvest\n"
    "\n"
    "- Decisions made during the workflow, with rationale and rejected\n"
    "  alternatives.\n"
    "- Lessons from mistakes, corrections, or surprises.\n"
    "- Procedures that emerged from patterns the user reinforced.\n"
    "- Context facts about the project that surfaced during dialogue.\n"
    "\n"
    "## How to walk the transcript\n"
    "\n"
    "1. Step back. Identify 2-4 themes from this run -- the major\n"
    "   decisions, the surprises, the corrections, the reusable patterns.\n"
    "2. For each theme, walk the relevant turns and harvest candidates.\n"
    "   Most impactful first.\n"
    "\n"
    "## Forbidden moves\n"
    "\n"
    "- Do NOT call `koan_request_scouts`. The source is bounded by what\n"
    "  you already discussed in this run.\n"
    "- Do NOT read codebase files for new context. Anything you did not\n"
    "  already touch in the workflow is out of scope.\n"
    "- Do NOT call `koan_ask_question`. If clarification is needed,\n"
    "  surface it inside a batch yield instead.\n"
    "\n"
    "## What this phase produces\n"
    "\n"
    "Your output for this phase is `koan_memorize` calls (and `koan_forget`\n"
    "where DEPRECATE applies), not analysis. Step 1 is preparation; step 2\n"
    "is where the writes happen. A curation phase that ends with zero\n"
    "writes -- when the transcript clearly contains harvestable knowledge --\n"
    "is a failed phase."
)

_STANDALONE_DIRECTIVE = (
    "## Source: standalone curation\n"
    "\n"
    "Your source is determined by the user's task in the <task> block\n"
    "above combined with the current state of memory in <existing_memory>.\n"
    "Unlike the postmortem entry point, you do NOT have a recent workflow\n"
    "transcript to draw from -- context must be gathered.\n"
    "\n"
    "## Mode pivot (do this in step 1, before gathering)\n"
    "\n"
    "Decide which mode you are in by walking these four moves:\n"
    "\n"
    "- **Describe**  Paraphrase the user's <task> in one sentence.\n"
    "- **Explain**   Look at <existing_memory>: empty, sparse, or\n"
    "                populated? Does the task reference specific source\n"
    "                material (a doc path, a subsystem name, a file)?\n"
    "- **Plan**      Pick exactly one mode:\n"
    "                  - **Review**     Memory is populated and the task\n"
    "                                   is health/maintenance (\"audit my\n"
    "                                   memory\", \"check for stale\n"
    "                                   entries\", \"find duplicates\").\n"
    "                  - **Document**   The task points at specific\n"
    "                                   source material -- a doc, a spec,\n"
    "                                   a subsystem, a path. Ingest it.\n"
    "                  - **Bootstrap**  Memory is empty or near-empty and\n"
    "                                   the task is open-ended (\"set up\n"
    "                                   memory for this project\").\n"
    "- **Select**    Commit to the mode. Name it in your end-of-step-1\n"
    "                orientation summary so the user can correct you\n"
    "                before you start gathering.\n"
    "\n"
    "## Source-gathering posture by mode\n"
    "\n"
    "- **Review**:    Read suspect entries directly from `.koan/memory/`.\n"
    "                 Dispatch 1-2 scouts via `koan_request_scouts` to\n"
    "                 verify high-stakes decisions against the current\n"
    "                 codebase. Use `koan_ask_question` only for\n"
    "                 ambiguities the files cannot resolve.\n"
    "\n"
    "- **Document**:  Read the source the user pointed at directly. If\n"
    "                 it spans multiple subsystems, dispatch 2-4 scouts\n"
    "                 in parallel to cover each one. Treat the document\n"
    "                 as authoritative for facts; treat the codebase as\n"
    "                 authoritative for current state.\n"
    "\n"
    "- **Bootstrap**: Lean heavily on scouts -- 3-5 to cover the major\n"
    "                 subsystems. Read README, AGENTS.md, and CLAUDE.md\n"
    "                 directly if they exist. Interview the user via\n"
    "                 `koan_ask_question` for context the codebase\n"
    "                 cannot reveal: team size, deployment, conventions,\n"
    "                 historical decisions.\n"
    "\n"
    "In every mode you may always read individual memory entries\n"
    "directly from `.koan/memory/NNNN-*.md` -- direct reads are the\n"
    "intended duplicate-detection path. Writes still go through\n"
    "`koan_memorize` / `koan_forget` only.\n"
    "\n"
    "## What this phase produces\n"
    "\n"
    "Your output for this phase is `koan_memorize` calls (and `koan_forget`\n"
    "where DEPRECATE applies), not analysis. Step 1 is preparation; step 2\n"
    "is where the writes happen. A curation phase that ends with zero\n"
    "writes -- when there is genuine novel knowledge to capture -- is a\n"
    "failed phase."
)


# -- Plan workflow -------------------------------------------------------------
# intake -> plan-spec -> plan-review -> execute -> curation
# Lightweight focused-change pipeline. Single executor spawn.

PLAN_WORKFLOW = Workflow(
    name="plan",
    description="Plan an implementation approach, review it, then execute",
    phases={
        "intake": PhaseBinding(
            module=intake,
            description="Explore the codebase and align on requirements through Q&A",
            guidance=(
                "## Scope\n"
                "This is a **plan** workflow -- a focused change touching a bounded\n"
                "area of the codebase.\n"
                "\n"
                "## Downstream\n"
                "The understanding you build here feeds into an implementation plan.\n"
                "The planner needs enough context to write specific file-level\n"
                "instructions, but does not need exhaustive coverage of the entire\n"
                "codebase.\n"
                "\n"
                "## Investigation posture\n"
                "- **Prefer direct reading.** For focused changes, reading the referenced\n"
                "  files yourself is faster and more precise than dispatching scouts.\n"
                "- **Dispatch scouts** when the task references subsystems you're unfamiliar\n"
                "  with, or when dependency tracing would require opening more than ~10 files.\n"
                "- If you dispatch scouts, 1-3 is typical for a plan workflow.\n"
                "\n"
                "## Question posture\n"
                "- Always ask at least one round of questions. Even well-specified tasks\n"
                "  benefit from confirming assumptions and surfacing implicit decisions.\n"
                "- A plan workflow needs 2-4 targeted questions covering: approach\n"
                "  confirmation, constraint verification, and scope boundaries.\n"
                "- The user wants to be consulted -- asking questions is a feature, not a\n"
                "  burden. When in doubt, ask.\n"
                "\n"
                "## User override\n"
                "The user can always ask you to go deeper, dispatch more scouts, or ask\n"
                "more questions. Follow their lead over these defaults."
            ),
            retrieval_directive=(
                "Architectural decisions, constraints, and context entries that shape"
                " how this codebase is organized. Entries about subsystems the task"
                " may touch, team conventions, and deployment invariants."
            ),
            next_phase="plan-spec",
        ),
        "plan-spec": PhaseBinding(
            module=plan_spec,
            description="Write or update a technical implementation plan grounded in the codebase",
            guidance="Use `plan.md` as the artifact filename.",
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that constrain"
                " how changes are made in this codebase. Entries about coding patterns,"
                " module layout rules, and past lessons from similar changes."
            ),
            next_phase="plan-review",
        ),
        "plan-review": PhaseBinding(
            module=plan_review,
            description="Evaluate the plan for completeness, correctness, and risks",
            guidance="Review `plan.md` -- the plan artifact for this workflow.",
            # Same directive as plan-spec: review evaluates against the same
            # implementation-level knowledge that spec used to write the plan.
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that constrain"
                " how changes are made in this codebase. Entries about coding patterns,"
                " module layout rules, and past lessons from similar changes."
            ),
            # None: review outcome requires user direction -- loop back to plan-spec
            # or proceed to execute; cannot auto-advance.
            next_phase=None,
        ),
        "execute": PhaseBinding(
            module=execute_phase,
            description="Hand off the plan to an executor agent for implementation",
            # brief.md listed first so it is the highest-priority context for the
            # executor; plan.md is the implementation plan that follows from it.
            guidance=(
                "## What to hand off\n"
                "Call `koan_request_executor` with:\n"
                "- **artifacts**: `[\"brief.md\", \"plan.md\"]` -- brief.md provides initiative\n"
                "  context (scope, decisions, constraints); plan.md is the implementation plan.\n"
                "- **instructions**: Key decisions from plan-review, user clarifications,\n"
                "  or constraints. Do NOT repeat plan.md contents -- the executor reads\n"
                "  it directly. Instructions are for context that isn't in the files.\n"
                "\n"
                "## After execution\n"
                "Report the result. Transition to `exec-review` to verify what was done."
            ),
            retrieval_directive=(
                "Procedures, conventions, and past lessons related to the subsystems"
                " being modified. Executor-facing rules about testing policy, secret"
                " handling, file placement, and other coding-time constraints."
            ),
            next_phase="exec-review",
        ),
        "exec-review": PhaseBinding(
            module=exec_review_phase,
            description="Review execution results and identify deviations from the plan",
            guidance=_EXEC_REVIEW_PLAN_GUIDANCE,
            retrieval_directive=(
                "Past lessons about execution quality, common deviations, and"
                " post-execution review patterns in this codebase."
            ),
            # None: review outcome requires user direction -- proceed to curation
            # or loop back to plan-spec for replanning.
            next_phase=None,
        ),
        "curation": PhaseBinding(
            module=curation,
            description="Capture lessons, decisions, and context from the completed run",
            guidance=_POSTMORTEM_DIRECTIVE,
            # Curation already calls koan_memory_status which surfaces the full
            # entry listing. Mechanical injection would be redundant and noisy.
            retrieval_directive="",
            next_phase=None,  # terminal phase -- workflow ends here
        ),
    },
    initial_phase="intake",
    transitions={
        "intake":       ["plan-spec", "execute"],
        "plan-spec":    ["plan-review", "execute"],
        "plan-review":  ["plan-spec", "execute"],
        "execute":      ["exec-review", "curation"],
        "exec-review":  ["curation", "plan-spec"],
        "curation":     [],
    },
)


# -- Milestones workflow -------------------------------------------------------
# intake -> milestone-spec -> [milestone-review] -> plan-spec ->
# [plan-review] -> execute -> exec-review -> milestone-spec (loop) -> curation

_MILESTONES_PLAN_SPEC_GUIDANCE = (
    "## Milestone plan-spec context\n"
    "\n"
    "Read `milestones.md` to identify the current milestone:\n"
    "- The current milestone is the one marked `[in-progress]`.\n"
    "- Write `plan-milestone-N.md` for that milestone (where N is the milestone number).\n"
    "- The plan should be scoped to just that milestone's work.\n"
    "\n"
    "## Cross-milestone learning\n"
    "\n"
    "When planning milestone N > 1: before reading codebase files, read the Outcome\n"
    "sections of all completed milestones in milestones.md. These describe what was\n"
    "actually built, including integration points, patterns, and constraints\n"
    "established by prior milestones that this plan must respect. If the Outcome\n"
    "sections reference specific files or interfaces you will extend, read those\n"
    "files in the codebase directly -- the code is the source of truth, not the plan.\n"
)

_MILESTONES_PLAN_REVIEW_GUIDANCE = (
    "## Milestone plan-review context\n"
    "\n"
    "Review the most recently written `plan-milestone-N.md` artifact.\n"
    "Check `milestones.md` to identify which milestone is `[in-progress]` and use\n"
    "its number to determine the correct plan artifact filename.\n"
)

_MILESTONES_EXECUTE_GUIDANCE = (
    "## Milestone execute context\n"
    "\n"
    "Hand off the current milestone's plan to the executor:\n"
    "- **artifacts**: `[\"brief.md\", \"plan-milestone-N.md\", \"milestones.md\"]` (where N is\n"
    "  the current `[in-progress]` milestone number). brief.md is the frozen initiative\n"
    "  context; plan-milestone-N.md is the milestone-specific plan; milestones.md gives\n"
    "  the broader initiative context with prior milestone Outcomes.\n"
    "- **instructions**: Key findings from plan-review and any user clarifications.\n"
    "\n"
    "After execution, transition to `exec-review`.\n"
)

MILESTONES_WORKFLOW = Workflow(
    name="milestones",
    description="Break work into milestones and execute each with planning and review",
    phases={
        "intake": PhaseBinding(
            module=intake,
            description="Explore the codebase and align on requirements through Q&A",
            next_phase="milestone-spec",
            guidance=(
                "## Scope\n"
                "This is a **milestones** workflow -- a broad initiative spanning\n"
                "multiple subsystems requiring significant codebase exploration.\n"
                "\n"
                "## Downstream\n"
                "The understanding you build here feeds into milestone decomposition\n"
                "and multi-phase planning. Downstream phases need comprehensive\n"
                "coverage: every affected subsystem, integration point, and constraint\n"
                "must be documented.\n"
                "\n"
                "## Investigation posture\n"
                "- **Dispatch scouts broadly.** Explore every subsystem the task touches\n"
                "  and adjacent areas that might be affected. 3-5 scouts is typical.\n"
                "- **Also read directly** -- verify key scout findings against the actual\n"
                "  code, especially integration points and conventions.\n"
                "\n"
                "## Question posture\n"
                "- Ask multiple rounds of questions. For broad initiatives, 2-3 rounds\n"
                "  of 3-6 questions is typical.\n"
                "- Surface assumptions early. Each answer may reveal new areas to probe.\n"
                "- Probe cross-cutting concerns: shared patterns, naming conventions,\n"
                "  error handling strategies, test coverage expectations.\n"
                "\n"
                "## User override\n"
                "The user can always tell you to narrow scope or skip questions.\n"
                "Follow their lead over these defaults."
            ),
            retrieval_directive=(
                "Architectural decisions, constraints, and context entries that shape"
                " how this codebase is organized. Entries about subsystems the task"
                " may touch, team conventions, and deployment invariants."
            ),
        ),
        "milestone-spec": PhaseBinding(
            module=milestone_spec,
            # M4: description updated to drop "update after execution" -- that is now exec-review's job.
            description="Decompose the initiative into ordered milestones, or re-decompose after a major deviation",
            guidance=(
                "## Milestone-spec context\n"
                "\n"
                "If milestones.md does not exist, you are in CREATE mode: decompose the\n"
                "initiative into milestones grounded in code structure.\n"
                "\n"
                "If milestones.md exists, you are in RE-DECOMPOSE mode: the user has\n"
                "explicitly redirected here, typically after exec-review surfaced a major\n"
                "deviation that requires changing the milestone graph itself. Revise\n"
                "[pending] / [in-progress] milestone sketches; preserve all [done]\n"
                "milestones and their Outcome sections intact. Routine post-execution\n"
                "UPDATE work is owned by exec-review.\n"
            ),
            retrieval_directive=(
                "Architectural decisions and constraints relevant to milestone scope"
                " and ordering. Entries about subsystem boundaries and delivery sequencing."
            ),
            # Auto-advance to milestone-review after decomposition, mirroring
            # plan-spec -> plan-review and execute -> exec-review. milestone-review
            # then yields to the user to pick plan-spec or loop back.
            next_phase="milestone-review",
        ),
        "milestone-review": PhaseBinding(
            module=milestone_review,
            description="Review the milestone decomposition for scope, ordering, and gaps",
            guidance=(
                "## Milestone-review context\n"
                "\n"
                "After reviewing, if you found Critical or Major issues, transition to\n"
                "`milestone-spec` so the decomposition can be revised. If the decomposition\n"
                "looks sound, transition to `plan-spec` to begin the first milestone.\n"
            ),
            retrieval_directive=(
                "Past lessons about milestone decomposition, scope boundaries, and"
                " sequencing decisions in similar initiatives."
            ),
            # None: review outcome determines next step (milestone-spec for revision
            # or plan-spec to proceed); user direction is required.
            next_phase=None,
        ),
        "plan-spec": PhaseBinding(
            module=plan_spec,
            description="Write a technical implementation plan for the current milestone",
            guidance=_MILESTONES_PLAN_SPEC_GUIDANCE,
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that constrain"
                " how changes are made in this codebase. Entries about coding patterns,"
                " module layout rules, and past lessons from similar changes."
            ),
            next_phase="plan-review",
        ),
        "plan-review": PhaseBinding(
            module=plan_review,
            description="Evaluate the milestone plan for completeness, correctness, and risks",
            guidance=_MILESTONES_PLAN_REVIEW_GUIDANCE,
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that constrain"
                " how changes are made in this codebase. Entries about coding patterns,"
                " module layout rules, and past lessons from similar changes."
            ),
            # None: review outcome requires user direction -- loop back to plan-spec
            # or proceed to execute.
            next_phase=None,
        ),
        "execute": PhaseBinding(
            module=execute_phase,
            description="Hand off the milestone plan to an executor agent for implementation",
            guidance=_MILESTONES_EXECUTE_GUIDANCE,
            retrieval_directive=(
                "Procedures, conventions, and past lessons related to the subsystems"
                " being modified. Executor-facing rules about testing policy, secret"
                " handling, file placement, and other coding-time constraints."
            ),
            next_phase="exec-review",
        ),
        "exec-review": PhaseBinding(
            module=exec_review_phase,
            description="Review milestone execution results and identify deviations",
            guidance=_EXEC_REVIEW_MILESTONES_GUIDANCE,
            retrieval_directive=(
                "Past lessons about execution quality, common deviations, and"
                " post-execution review patterns in this codebase."
            ),
            # None: review outcome requires user direction -- milestone-spec loop
            # or plan-spec for replanning; cannot auto-advance.
            next_phase=None,
        ),
        "curation": PhaseBinding(
            module=curation,
            description="Capture lessons, decisions, and context from the completed initiative",
            guidance=_POSTMORTEM_DIRECTIVE,
            retrieval_directive="",
            next_phase=None,  # terminal phase -- workflow ends here
        ),
    },
    initial_phase="intake",
    transitions={
        "intake":           ["milestone-spec"],
        "milestone-spec":   ["milestone-review", "plan-spec"],
        "milestone-review": ["milestone-spec", "plan-spec"],
        "plan-spec":        ["plan-review", "execute"],
        "plan-review":      ["plan-spec", "execute"],
        "execute":          ["exec-review", "milestone-spec"],
        # M4: reordered so the natural next-milestone path (plan-spec) comes first,
        # then curation (all done), then milestone-spec (manual RE-DECOMPOSE override).
        "exec-review":      ["plan-spec", "curation", "milestone-spec"],
        "curation":         [],
    },
)


# -- Curation workflow --------------------------------------------------------
# Standalone memory maintenance workflow (standalone directive).

CURATION_WORKFLOW = Workflow(
    name="curation",
    description="Maintain the project memory: review, bootstrap, or ingest documents",
    phases={
        "curation": PhaseBinding(
            module=curation,
            description="Review and maintain the project's memory entries",
            guidance=_STANDALONE_DIRECTIVE,
            retrieval_directive="",  # explicit: curation uses koan_memory_status instead
        ),
    },
    initial_phase="curation",
    transitions={"curation": []},
)


# -- Initiative workflow guidance constants ------------------------------------
# Per-workflow guidance for the initiative phases. These constants are injected
# via PhaseBinding.guidance into ctx.phase_instructions at step 1 of each phase.

_INITIATIVE_INTAKE_GUIDANCE = (
    "## Scope\n"
    "This is an **initiative** workflow -- a substantial undertaking that spans\n"
    "multiple milestones, crosses architectural boundaries, and warrants a shared,\n"
    "persistent record of design decisions made along the way.\n"
    "\n"
    "## Downstream\n"
    "The understanding you build here feeds into four upstream artifacts:\n"
    "`core-flows.md` (operational behavior), `tech-plan.md` (system architecture),\n"
    "`milestones.md` (decomposition), and per-milestone plans. Downstream phases\n"
    "will produce visualization-first artifacts; surface operational flows and\n"
    "architectural decisions explicitly during intake so they are captured in\n"
    "brief.md.\n"
    "\n"
    "## Investigation posture\n"
    "- **Dispatch scouts broadly.** An initiative spans multiple subsystems.\n"
    "  3-5 scouts is typical.\n"
    "- **Also read directly** -- verify key scout findings against the actual\n"
    "  code, especially integration points and existing data-model conventions.\n"
    "\n"
    "## Question posture\n"
    "- Ask multiple rounds of questions. For broad initiatives, 2-3 rounds\n"
    "  of 3-6 questions is typical.\n"
    "- Surface assumptions early. Each answer may reveal new areas to probe.\n"
    "- Probe cross-cutting concerns: shared patterns, naming conventions,\n"
    "  error handling strategies, test coverage expectations.\n"
    "\n"
    "## User override\n"
    "The user can always tell you to narrow scope or skip questions.\n"
    "Follow their lead over these defaults."
)

_INITIATIVE_CORE_FLOWS_GUIDANCE = (
    "## Initiative workflow context\n"
    "\n"
    "You are in the `core-flows` phase of the initiative workflow. The artifact\n"
    "you produce (`core-flows.md`) will be read by EVERY downstream phase.\n"
    "\n"
    "This phase is yield-skippable. If the operational behavior is already settled\n"
    "in the intake dialogue and writing it down adds nothing new, yield from intake\n"
    "directly to tech-plan-spec.\n"
)

_INITIATIVE_TECH_PLAN_SPEC_GUIDANCE = (
    "## Initiative workflow context\n"
    "\n"
    "You are in the `tech-plan-spec` phase of the initiative workflow. The\n"
    "architecture you produce gates milestone decomposition: milestone-spec reads\n"
    "tech-plan.md as authoritative for the architectural decisions that constrain\n"
    "the decomposition and sequencing of milestones.\n"
    "\n"
    "Read `core-flows.md` if present (via `koan_artifact_view`). It is frozen and\n"
    "authoritative for the actors and operational flows the architecture must support.\n"
    "\n"
    "Produce all three required sections: Architectural Approach, Data Model, and\n"
    "Component Architecture.\n"
)

_INITIATIVE_TECH_PLAN_REVIEW_GUIDANCE = (
    "## Initiative workflow context\n"
    "\n"
    "You are in the `tech-plan-review` phase of the initiative workflow. The\n"
    "user's phase-switch decision after your yield is the implicit acceptance\n"
    "moment. Not pushing back IS acceptance -- the user advancing to\n"
    "`milestone-spec` is confirmation that the architecture is sound.\n"
    "\n"
    "If your review finds loop-back findings (new-files-needed), yield with\n"
    "`tech-plan-spec` recommended. If the architecture passes review (all findings\n"
    "internal and corrected), yield with `milestone-spec` recommended.\n"
    "\n"
    "Read `core-flows.md` (if present) in addition to brief.md and tech-plan.md.\n"
)

_INITIATIVE_MILESTONE_SPEC_GUIDANCE = (
    "## Initiative milestone-spec context\n"
    "\n"
    "Read `tech-plan.md` first via `koan_artifact_view` before reading codebase\n"
    "files. It contains the architectural decisions that constrain how work is\n"
    "decomposed and sequenced.\n"
    "\n"
    "Also read `core-flows.md` (if present) via `koan_artifact_view`. The\n"
    "milestones must collectively realize every operational flow described there.\n"
    "\n"
    "If milestones.md does not exist, you are in CREATE mode: decompose the\n"
    "initiative into milestones grounded in code structure and consistent with\n"
    "the architectural decisions in tech-plan.md.\n"
    "\n"
    "If milestones.md exists, you are in RE-DECOMPOSE mode: revise [pending] /\n"
    "[in-progress] milestone sketches; preserve all [done] milestones intact.\n"
)

_INITIATIVE_MILESTONE_REVIEW_GUIDANCE = (
    "## Initiative milestone-review context\n"
    "\n"
    "After reviewing, cross-check the milestone decomposition against\n"
    "`tech-plan.md`: do the milestones collectively realize the architectural\n"
    "decisions documented there? If not, that is a Major finding.\n"
    "\n"
    "If Critical or Major issues are found, transition to `milestone-spec` for\n"
    "revision. If sound, transition to `plan-spec` to begin the first milestone.\n"
)

_INITIATIVE_PLAN_SPEC_GUIDANCE = (
    "## Initiative plan-spec context\n"
    "\n"
    "Read `milestones.md` to identify the current milestone:\n"
    "- The current milestone is the one marked `[in-progress]`.\n"
    "- Write `plan-milestone-N.md` for that milestone.\n"
    "\n"
    "Before reading codebase files, read two upstream architectural artifacts:\n"
    "\n"
    "1. `tech-plan.md` (via `koan_artifact_view`): the architectural decisions\n"
    "   that constrain how this milestone is implemented.\n"
    "2. `core-flows.md` (via `koan_artifact_view`, if present): the operational\n"
    "   flows this milestone must support or preserve.\n"
    "\n"
    "## Cross-milestone learning\n"
    "\n"
    "When planning milestone N > 1: before reading codebase files, read the Outcome\n"
    "sections of all completed milestones in milestones.md.\n"
)

_INITIATIVE_PLAN_REVIEW_GUIDANCE = (
    "## Initiative plan-review context\n"
    "\n"
    "Review the most recently written `plan-milestone-N.md` artifact.\n"
    "Cross-check the plan against `tech-plan.md`: does the plan respect the\n"
    "architectural decisions documented there? A plan that violates the\n"
    "architecture is a Critical finding.\n"
)

_INITIATIVE_EXECUTE_GUIDANCE = (
    "## Initiative execute context\n"
    "\n"
    "Hand off the current milestone's plan to the executor:\n"
    "- **artifacts**: `[\"brief.md\", \"tech-plan.md\", \"core-flows.md\","
    " \"plan-milestone-N.md\", \"milestones.md\"]` (omit `core-flows.md` if it\n"
    "  does not exist in the run directory).\n"
    "- **instructions**: Key findings from plan-review and any user clarifications.\n"
    "\n"
    "After execution, transition to `exec-review`.\n"
)

_INITIATIVE_EXEC_REVIEW_GUIDANCE = (
    "## Initiative exec-review context\n"
    "\n"
    "Review what the executor accomplished for this milestone. After classifying\n"
    "the outcome, apply two artifact updates in step 2:\n"
    "\n"
    "1. **Plan artifact rewrite-or-loop-back**.\n"
    "2. **milestones.md UPDATE**: mark the completed milestone `[done]`, append\n"
    "   the four-subsection Outcome, advance the next `[pending]` milestone.\n"
    "\n"
    "After both updates: yield. The orchestrator picks `plan-spec` to begin the\n"
    "next milestone, `curation` if all milestones are done, `milestone-spec` for\n"
    "a manual RE-DECOMPOSE, or `tech-plan-spec` for an architectural lookback.\n"
)


# -- Initiative workflow -------------------------------------------------------
# intake -> core-flows -> tech-plan-spec -> tech-plan-review ->
# milestone-spec -> [milestone-review] -> plan-spec -> [plan-review] ->
# execute -> exec-review -> milestone-spec (loop) -> curation

INITIATIVE_WORKFLOW = Workflow(
    name="initiative",
    description=(
        "Full-ceremony initiative pipeline: intake, core-flows, tech-plan,"
        " milestones, plans, executions, and curation"
    ),
    phases={
        "intake": PhaseBinding(
            module=intake,
            description="Explore the codebase and align on requirements through Q&A",
            next_phase="core-flows",
            guidance=_INITIATIVE_INTAKE_GUIDANCE,
            retrieval_directive=(
                "Architectural decisions, constraints, and context entries that shape"
                " how this codebase is organized."
            ),
        ),
        "core-flows": PhaseBinding(
            module=core_flows,
            description=(
                "Describe the system's externally visible behavior as mermaid"
                " sequence diagrams plus step narratives"
            ),
            guidance=_INITIATIVE_CORE_FLOWS_GUIDANCE,
            retrieval_directive=(
                "Past decisions and lessons about the system's operational behavior."
            ),
            next_phase=None,
        ),
        "tech-plan-spec": PhaseBinding(
            module=tech_plan_spec,
            description=(
                "Write the architecture artifact: Architectural Approach,"
                " Data Model, Component Architecture"
            ),
            guidance=_INITIATIVE_TECH_PLAN_SPEC_GUIDANCE,
            retrieval_directive=(
                "Past architectural decisions and constraints relevant to the"
                " new system's structure."
            ),
            next_phase="tech-plan-review",
        ),
        "tech-plan-review": PhaseBinding(
            module=tech_plan_review,
            description=(
                "Adversarial check on the architecture artifact and diagram"
                " accuracy"
            ),
            guidance=_INITIATIVE_TECH_PLAN_REVIEW_GUIDANCE,
            retrieval_directive=(
                "Past architectural decisions relevant to verification of the"
                " new system's structure."
            ),
            next_phase=None,
        ),
        "milestone-spec": PhaseBinding(
            module=milestone_spec,
            description=(
                "Decompose the initiative into ordered milestones, or"
                " re-decompose after a major deviation"
            ),
            guidance=_INITIATIVE_MILESTONE_SPEC_GUIDANCE,
            retrieval_directive=(
                "Architectural decisions and constraints relevant to milestone"
                " scope and ordering."
            ),
            next_phase="milestone-review",
        ),
        "milestone-review": PhaseBinding(
            module=milestone_review,
            description="Review the milestone decomposition for scope, ordering, and gaps",
            guidance=_INITIATIVE_MILESTONE_REVIEW_GUIDANCE,
            retrieval_directive=(
                "Past lessons about milestone decomposition."
            ),
            next_phase=None,
        ),
        "plan-spec": PhaseBinding(
            module=plan_spec,
            description="Write a technical implementation plan for the current milestone",
            guidance=_INITIATIVE_PLAN_SPEC_GUIDANCE,
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that"
                " constrain how changes are made in this codebase."
            ),
            next_phase="plan-review",
        ),
        "plan-review": PhaseBinding(
            module=plan_review,
            description="Evaluate the milestone plan for completeness, correctness, and risks",
            guidance=_INITIATIVE_PLAN_REVIEW_GUIDANCE,
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions relevant"
                " to plan review."
            ),
            next_phase=None,
        ),
        "execute": PhaseBinding(
            module=execute_phase,
            description="Hand off the milestone plan to an executor agent for implementation",
            guidance=_INITIATIVE_EXECUTE_GUIDANCE,
            retrieval_directive=(
                "Procedures, conventions, and past lessons related to the"
                " subsystems being modified."
            ),
            next_phase="exec-review",
        ),
        "exec-review": PhaseBinding(
            module=exec_review_phase,
            description="Review milestone execution results and identify deviations",
            guidance=_INITIATIVE_EXEC_REVIEW_GUIDANCE,
            retrieval_directive=(
                "Past lessons about execution quality and post-execution review."
            ),
            next_phase=None,
        ),
        "curation": PhaseBinding(
            module=curation,
            description="Capture lessons, decisions, and context from the completed initiative",
            guidance=_POSTMORTEM_DIRECTIVE,
            retrieval_directive="",
            next_phase=None,
        ),
    },
    initial_phase="intake",
    transitions={
        "intake":           ["core-flows", "tech-plan-spec"],
        "core-flows":       ["tech-plan-spec", "core-flows"],
        "tech-plan-spec":   ["tech-plan-review"],
        "tech-plan-review": ["milestone-spec", "tech-plan-spec"],
        "milestone-spec":   ["milestone-review", "plan-spec"],
        "milestone-review": ["milestone-spec", "plan-spec"],
        "plan-spec":        ["plan-review", "execute"],
        "plan-review":      ["plan-spec", "execute"],
        "execute":          ["exec-review", "milestone-spec"],
        "exec-review":      ["plan-spec", "curation", "milestone-spec", "tech-plan-spec"],
        "curation":         [],
    },
)

# -- Discovery workflow guidance constants -------------------------------------

_DISCOVERY_FRAME_GUIDANCE = (
    "## Discovery workflow context\n"
    "\n"
    "You are in the standalone `discovery` workflow. This workflow is a single\n"
    "phase (`frame`) with no other phases and no fixed artifact. Your role is\n"
    "that of a sounding board: surface tradeoffs, name hidden assumptions, and\n"
    "help the user think without converging prematurely on a plan or artifact.\n"
    "\n"
    "Exit is user-driven. When the user signals they are ready, present three\n"
    "options:\n"
    "\n"
    "1. Promote into another workflow via `koan_set_workflow` (e.g. 'initiative',\n"
    "   'milestones', 'plan') -- the discovery transcript carries forward.\n"
    "2. Transition to another phase within the current workflow via `koan_set_phase`\n"
    "   (the discovery workflow has only `frame`, so this path ends the frame\n"
    "   session without producing an artifact).\n"
    "3. End the workflow via `koan_set_phase('done')`.\n"
    "\n"
    "There is no curation step at exit from discovery. If the user wants to\n"
    "capture lessons from this session, they can switch to the `curation` workflow\n"
    "via `koan_set_workflow('curation')`.\n"
)


# -- Discovery workflow --------------------------------------------------------
# Single-phase standalone exploration workflow. Structurally identical to
# CURATION_WORKFLOW in shape (single phase, no transitions).

DISCOVERY_WORKFLOW = Workflow(
    name="discovery",
    description=(
        "Single-phase open-ended exploration. The agent is a sounding board;"
        " exit is user-driven."
    ),
    phases={
        "frame": PhaseBinding(
            module=frame,
            description=(
                "Open-ended dialogue when the user is not yet sure what they"
                " want or what shape it should take"
            ),
            guidance=_DISCOVERY_FRAME_GUIDANCE,
            retrieval_directive=(
                "Past decisions, lessons, and context that may inform open-ended"
                " exploration of intent. Broad coverage rather than a specific"
                " subsystem."
            ),
            next_phase=None,
        ),
    },
    initial_phase="frame",
    transitions={"frame": []},
)


# -- Registry -----------------------------------------------------------------

WORKFLOWS: dict[str, Workflow] = {
    "plan": PLAN_WORKFLOW,
    "milestones": MILESTONES_WORKFLOW,
    "initiative": INITIATIVE_WORKFLOW,
    "discovery": DISCOVERY_WORKFLOW,
    "curation": CURATION_WORKFLOW,
}


def get_workflow(name: str) -> Workflow:
    """Return the Workflow for the given name, or raise ValueError."""
    wf = WORKFLOWS.get(name)
    if wf is None:
        raise ValueError(f"Unknown workflow: {name!r}. Valid: {list(WORKFLOWS)}")
    return wf


def get_suggested_phases(workflow: Workflow, phase: str) -> list[str]:
    """Return the ordered suggested next phases for the current phase."""
    return list(workflow.transitions.get(phase, []))


def is_valid_transition(workflow: Workflow, from_phase: str, to_phase: str) -> bool:
    """Any phase in the workflow is reachable from any other (except self-transition).

    The user drives macro-level progression; transitions guides defaults
    but does not constrain choices.
    """
    return to_phase in workflow.available_phases and to_phase != from_phase
