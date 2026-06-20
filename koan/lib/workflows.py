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
    execute as execute_phase,
    frame,
    intake,
    milestone_spec,
    plan_spec,
    tech_plan_spec,
)
# M6: plan_review, milestone_review, tech_plan_review, and exec_review are
# removed. Review is now mechanical: koan_artifact_write triggers the
# PLAN/MILESTONE/TECH_PLAN_REVIEWER sub-agent (M3); execution inline
# conformance review lives in the execute phase (M5). The *-review modules
# are deleted; all transitions and bindings below reference only the 8 final
# phases: intake, core-flows, tech-plan, milestone, plan, execute, curation, frame.


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
    # orchestrator may hand back to the user instead when findings warrant.
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


# M6: _EXEC_REVIEW_PLAN_GUIDANCE and _EXEC_REVIEW_MILESTONES_GUIDANCE removed.
# exec-review is collapsed into the execute phase (M5 inline conformance review).

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
# intake -> plan -> execute -> curation
# Lightweight focused-change pipeline. Single executor spawn.
# M6: plan-review and exec-review removed (mechanical reviewer + inline execute review).

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
            next_phase="plan",
        ),
        "plan": PhaseBinding(
            module=plan_spec,
            description="Write a technical implementation plan grounded in the codebase",
            guidance="Use `plan.md` as the artifact filename.",
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that constrain"
                " how changes are made in this codebase. Entries about coding patterns,"
                " module layout rules, and past lessons from similar changes."
            ),
            # M6: next_phase=None -- the plan step instructions name the plan for
            # execution via koan_set_phase("execute", plan_file=...) directly, which
            # freezes it, spawns the executor, and returns the deviation report.
            next_phase=None,
        ),
        "execute": PhaseBinding(
            module=execute_phase,
            description="Execute the plan and review conformance inline",
            # M5: the execute phase is now the inline reviewer. next_phase=None because
            # the review outcome (clean -> curation; non-conforming -> plan + remediation)
            # requires the orchestrator to choose rather than auto-advancing.
            guidance=(
                "## Inline review context (plan workflow)\n"
                "\n"
                "Execution is complete. The deviation report was returned by the\n"
                "koan_set_phase('execute', plan_file='plan.md') call that entered\n"
                "this phase.\n"
                "\n"
                "Your task: verify conformance (run bash checks, read brief.md and\n"
                "plan.md), append conformance notes to plan.review.md via\n"
                "koan_artifact_edit, then branch.\n"
                "\n"
                "## Outcome paths (plan workflow)\n"
                "\n"
                "- CLEAN: transition to `curation` to capture lessons. No milestones.md\n"
                "  UPDATE is needed in the plan workflow.\n"
                "- NON-CONFORMING (base plan): call koan_set_phase('plan'), write\n"
                "  plan-remediation-1.md folding the failure signal, re-execute.\n"
                "- NON-CONFORMING (already a remediation): escalate via koan_ask_question.\n"
            ),
            retrieval_directive=(
                "Procedures, conventions, and past lessons related to the subsystems"
                " being modified. Executor-facing rules about testing policy, secret"
                " handling, file placement, and other coding-time constraints."
            ),
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
    # M6 final transitions (brief 5.4): intake->plan->execute->(curation|plan)->curation.
    transitions={
        "intake":   ["plan"],
        "plan":     ["execute"],
        "execute":  ["curation", "plan"],
        "curation": [],
    },
)


# -- Milestones workflow -------------------------------------------------------
# intake -> milestone -> plan -> execute -> (milestone loop | curation)
# M6: milestone-review, plan-review, exec-review removed (mechanical reviewer + inline review).

_MILESTONES_PLAN_SPEC_GUIDANCE = (
    "## Milestone plan context\n"
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

# M6: _MILESTONES_PLAN_REVIEW_GUIDANCE removed -- plan-review collapsed into the
# mechanical PLAN_REVIEWER spawned by koan_artifact_write.

# M5: rewritten for inline-review + remediation model. The orchestrator is the
# reviewer after the handoff returns; exec-review is bypassed. milestones.md UPDATE
# is gated on this guidance string being present (phase_instructions check in
# execute.py step 2), mirroring the pattern exec_review.py used.
_MILESTONES_EXECUTE_GUIDANCE = (
    "## Milestone execute context\n"
    "\n"
    "Execution is complete. The deviation report was returned by the\n"
    "koan_set_phase('execute', plan_file='plan-milestone-N.md') call that\n"
    "entered this phase.\n"
    "\n"
    "Your task: verify conformance (run bash checks, read brief.md,\n"
    "plan-milestone-N.md, and milestones.md), append conformance notes to\n"
    "plan-milestone-N.review.md via koan_artifact_edit, then branch.\n"
    "\n"
    "## Outcome paths (milestones workflow)\n"
    "\n"
    "- CLEAN: apply the milestones.md UPDATE (mark milestone [done], append\n"
    "  four-subsection Outcome, advance the next [pending] milestone to\n"
    "  [in-progress], preserve all prior [done] Outcomes). Then yield:\n"
    "  pick `plan` for the next milestone, `curation` if all milestones are\n"
    "  done, or `milestone` for a manual RE-DECOMPOSE.\n"
    "- NON-CONFORMING (base plan): call koan_set_phase('plan'), write\n"
    "  plan-milestone-N-remediation-1.md folding the failure signal, re-execute.\n"
    "- NON-CONFORMING (already a remediation): escalate via koan_ask_question.\n"
)

MILESTONES_WORKFLOW = Workflow(
    name="milestones",
    description="Break work into milestones and execute each with planning and review",
    phases={
        "intake": PhaseBinding(
            module=intake,
            description="Explore the codebase and align on requirements through Q&A",
            next_phase="milestone",
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
        "milestone": PhaseBinding(
            module=milestone_spec,
            # M6: description updated to CREATE-only -- RE-DECOMPOSE mode removed
            # because the discard hook deletes milestones.md on re-entry, so this
            # phase always creates fresh. Mechanical MILESTONE_REVIEWER runs on write.
            description="Decompose the initiative into ordered milestones",
            guidance=(
                "## Milestone context\n"
                "\n"
                "Decompose the initiative into milestones grounded in code structure.\n"
                "\n"
                "If milestones.md existed before entering this phase, the discard hook\n"
                "has already deleted it (along with non-executed plan drafts and their\n"
                "sidecars). Always CREATE -- there is no RE-DECOMPOSE mode.\n"
                "\n"
                "After writing milestones.md, the MILESTONE_REVIEWER runs automatically\n"
                "and returns its findings as the tool result. Reconcile inline, then\n"
                "advance to `plan` to begin the first milestone.\n"
            ),
            retrieval_directive=(
                "Architectural decisions and constraints relevant to milestone scope"
                " and ordering. Entries about subsystem boundaries and delivery sequencing."
            ),
            # M6: next_phase=None -- the step instructions advance to plan after
            # reconciling reviewer findings. No auto-advance to milestone-review.
            next_phase=None,
        ),
        "plan": PhaseBinding(
            module=plan_spec,
            description="Write a technical implementation plan for the current milestone",
            guidance=_MILESTONES_PLAN_SPEC_GUIDANCE,
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that constrain"
                " how changes are made in this codebase. Entries about coding patterns,"
                " module layout rules, and past lessons from similar changes."
            ),
            # M6: next_phase=None -- plan step instructions name the plan for execution
            # via koan_set_phase("execute", plan_file=...) after reconciling findings.
            next_phase=None,
        ),
        "execute": PhaseBinding(
            module=execute_phase,
            description="Execute the milestone plan and review conformance inline",
            guidance=_MILESTONES_EXECUTE_GUIDANCE,
            retrieval_directive=(
                "Procedures, conventions, and past lessons related to the subsystems"
                " being modified. Executor-facing rules about testing policy, secret"
                " handling, file placement, and other coding-time constraints."
            ),
            # M5/M6: next_phase=None -- review outcome determines path.
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
    # M6 final transitions (brief 5.4): intake->milestone->plan->execute->(loop|curation).
    transitions={
        "intake":     ["milestone"],
        "milestone":  ["plan"],
        "plan":       ["execute"],
        "execute":    ["plan", "curation", "milestone"],
        "curation":   [],
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
    "directly to tech-plan.\n"
)

_INITIATIVE_TECH_PLAN_SPEC_GUIDANCE = (
    "## Initiative workflow context\n"
    "\n"
    "You are in the `tech-plan` phase of the initiative workflow. The\n"
    "architecture you produce gates milestone decomposition: `milestone` reads\n"
    "tech-plan.md as authoritative for the architectural decisions that constrain\n"
    "the decomposition and sequencing of milestones.\n"
    "\n"
    "Read `core-flows.md` if present (via `koan_artifact_read`). It is frozen and\n"
    "authoritative for the actors and operational flows the architecture must support.\n"
    "\n"
    "Produce all three required sections: Architectural Approach, Data Model, and\n"
    "Component Architecture.\n"
)

# M6: _INITIATIVE_TECH_PLAN_REVIEW_GUIDANCE removed -- tech-plan-review collapsed
# into the mechanical TECH_PLAN_REVIEWER spawned by koan_artifact_write.

_INITIATIVE_MILESTONE_SPEC_GUIDANCE = (
    "## Initiative milestone context\n"
    "\n"
    "Read `tech-plan.md` first via `koan_artifact_read` before reading codebase\n"
    "files. It contains the architectural decisions that constrain how work is\n"
    "decomposed and sequenced.\n"
    "\n"
    "Also read `core-flows.md` (if present) via `koan_artifact_read`. The\n"
    "milestones must collectively realize every operational flow described there.\n"
    "\n"
    # M6: always CREATE -- the discard hook removes any previous milestones.md
    # on milestone re-entry. RE-DECOMPOSE mode is removed (brief 9.3).
    "Decompose the initiative into milestones grounded in code structure and\n"
    "consistent with the architectural decisions in tech-plan.md.\n"
    "\n"
    "After writing milestones.md, the MILESTONE_REVIEWER runs automatically.\n"
    "Reconcile its findings inline, then advance to `plan`.\n"
)

# M6: _INITIATIVE_MILESTONE_REVIEW_GUIDANCE removed -- milestone-review collapsed
# into the mechanical MILESTONE_REVIEWER spawned by koan_artifact_write.

_INITIATIVE_PLAN_SPEC_GUIDANCE = (
    "## Initiative plan context\n"
    "\n"
    "Read `milestones.md` to identify the current milestone:\n"
    "- The current milestone is the one marked `[in-progress]`.\n"
    "- Write `plan-milestone-N.md` for that milestone.\n"
    "\n"
    "Before reading codebase files, read two upstream architectural artifacts:\n"
    "\n"
    "1. `tech-plan.md` (via `koan_artifact_read`): the architectural decisions\n"
    "   that constrain how this milestone is implemented.\n"
    "2. `core-flows.md` (via `koan_artifact_read`, if present): the operational\n"
    "   flows this milestone must support or preserve.\n"
    "\n"
    "## Cross-milestone learning\n"
    "\n"
    "When planning milestone N > 1: before reading codebase files, read the Outcome\n"
    "sections of all completed milestones in milestones.md.\n"
)

# M6: _INITIATIVE_PLAN_REVIEW_GUIDANCE removed -- plan-review collapsed into
# the mechanical PLAN_REVIEWER spawned by koan_artifact_write.

# M5: rewritten for inline-review + remediation model. The orchestrator is the
# reviewer after the handoff returns; exec-review is bypassed. milestones.md UPDATE
# is gated on this guidance string being present (phase_instructions check in
# execute.py step 2). tech-plan option added to advance paths for architectural
# lookbacks, mirroring the former exec-review transitions in initiative.
_INITIATIVE_EXECUTE_GUIDANCE = (
    "## Initiative inline review context\n"
    "\n"
    "Execution is complete. The deviation report was returned by the\n"
    "koan_set_phase('execute', plan_file='plan-milestone-N.md') call that\n"
    "entered this phase.\n"
    "\n"
    "Your task: verify conformance (run bash checks, read brief.md, tech-plan.md,\n"
    "plan-milestone-N.md, and milestones.md), append conformance notes to\n"
    "plan-milestone-N.review.md via koan_artifact_edit, then branch.\n"
    "\n"
    "## Outcome paths (initiative workflow)\n"
    "\n"
    "- CLEAN: apply the milestones.md UPDATE (mark milestone [done], append\n"
    "  four-subsection Outcome, advance the next [pending] milestone to\n"
    "  [in-progress], preserve all prior [done] Outcomes). Then yield:\n"
    "  pick `plan` for the next milestone, `curation` if all milestones are\n"
    "  done, `milestone` for a manual RE-DECOMPOSE, or `tech-plan` for an\n"
    "  architectural lookback.\n"
    "- NON-CONFORMING (base plan): call koan_set_phase('plan'), write\n"
    "  plan-milestone-N-remediation-1.md folding the failure signal, re-execute.\n"
    "- NON-CONFORMING (already a remediation): escalate via koan_ask_question.\n"
)

# M6: _INITIATIVE_EXEC_REVIEW_GUIDANCE removed -- exec-review collapsed into the
# inline conformance review in the execute phase (M5).


# -- Initiative workflow -------------------------------------------------------
# intake -> core-flows -> tech-plan -> milestone -> plan -> execute -> (loop | curation)
# M6: tech-plan-review, milestone-review, plan-review, exec-review removed
# (mechanical reviewer + inline execute review).

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
        "tech-plan": PhaseBinding(
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
            # M6: next_phase=milestone -- TECH_PLAN_REVIEWER runs mechanically
            # on write; producer reconciles inline, then advances to milestone.
            next_phase="milestone",
        ),
        "milestone": PhaseBinding(
            module=milestone_spec,
            description="Decompose the initiative into ordered milestones",
            guidance=_INITIATIVE_MILESTONE_SPEC_GUIDANCE,
            retrieval_directive=(
                "Architectural decisions and constraints relevant to milestone"
                " scope and ordering."
            ),
            # M6: next_phase=None -- MILESTONE_REVIEWER runs mechanically on write;
            # producer reconciles inline, then advances to plan (step instructions).
            next_phase=None,
        ),
        "plan": PhaseBinding(
            module=plan_spec,
            description="Write a technical implementation plan for the current milestone",
            guidance=_INITIATIVE_PLAN_SPEC_GUIDANCE,
            retrieval_directive=(
                "Implementation decisions, procedures, and conventions that"
                " constrain how changes are made in this codebase."
            ),
            # M6: next_phase=None -- PLAN_REVIEWER runs mechanically on write;
            # producer reconciles inline, then names the plan for execution.
            next_phase=None,
        ),
        "execute": PhaseBinding(
            module=execute_phase,
            description="Execute the milestone plan and review conformance inline",
            guidance=_INITIATIVE_EXECUTE_GUIDANCE,
            retrieval_directive=(
                "Procedures, conventions, and past lessons related to the"
                " subsystems being modified."
            ),
            # M5/M6: next_phase=None -- review outcome determines path.
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
    # M6 final transitions (brief 5.4): intake->core-flows->tech-plan->milestone->
    # plan->execute->(loop|curation). tech-plan also reachable from execute for
    # architectural lookbacks.
    transitions={
        "intake":     ["core-flows", "tech-plan"],
        "core-flows": ["tech-plan", "core-flows"],
        "tech-plan":  ["milestone"],
        "milestone":  ["plan"],
        "plan":       ["execute"],
        "execute":    ["plan", "curation", "milestone", "tech-plan"],
        "curation":   [],
    },
)

# -- Discovery workflow guidance constants -------------------------------------

_DISCOVERY_FRAME_GUIDANCE = (
    "## Discovery workflow context\n"
    "\n"
    "You are in the standalone `discovery` workflow. This workflow is a single\n"
    "phase (`frame`) with no other phases and no fixed artifact. It is a\n"
    "general-purpose stepping stone: the user may bring feature design questions,\n"
    "bug hunting and troubleshooting sessions, or any general question. Refuse\n"
    "nothing. Use `koan_ask_question` to clarify intent, `koan_reflect` and\n"
    "`koan_search` to surface prior context, and investigate the codebase directly\n"
    "when the question calls for it. Always end each turn with a plain-text\n"
    "message and no tool call -- that hands control back to the user.\n"
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
        "Single-phase, open-ended exploration -- feature design, bug hunting,"
        " or general questions. The agent helps with whatever the user brings;"
        " exit is user-driven."
    ),
    phases={
        "frame": PhaseBinding(
            module=frame,
            description=(
                "Open-ended exploration -- design questions, bug hunting and"
                " troubleshooting, or general questions -- with user-driven exit"
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


def build_phase_suggestions(workflow: Workflow, phase: str) -> list[dict]:
    """Build {id, label, command} hand-back suggestions for the yield UI.

    Derived deterministically from the workflow's suggested next phases for the
    current phase, plus a terminal "done" option -- this replaces the structured
    suggestions koan_yield used to carry, now that the in-process loop's
    terminal-text turn is the hand-back (M5b removed koan_yield; M7.5 restores
    the YieldPanel options without requiring the model to call a tool).
    """
    suggestions: list[dict] = []
    for p in get_suggested_phases(workflow, phase):
        label = p.replace("-", " ").replace("_", " ").title()
        suggestions.append({
            "id": p,
            "label": label,
            "command": f"Proceed to the {p} phase.",
        })
    suggestions.append({
        "id": "done",
        "label": "End workflow",
        "command": "The workflow is complete.",
    })
    return suggestions


def is_valid_transition(workflow: Workflow, from_phase: str, to_phase: str) -> bool:
    """Any phase in the workflow is reachable from any other (except self-transition).

    The user drives macro-level progression; transitions guides defaults
    but does not constrain choices.
    """
    return to_phase in workflow.available_phases and to_phase != from_phase
