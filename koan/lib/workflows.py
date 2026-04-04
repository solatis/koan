# Workflow definitions for the koan orchestrator.
#
# A Workflow defines the phases available to the orchestrator, their suggested
# transition order, phase descriptions shown at boundaries, and per-phase
# guidance injected into step 1 instructions.
#
# Design notes:
#   - frozen=True prevents field reassignment after construction (mutation protection).
#   - frozen=True does NOT make Workflow hashable — dict fields are unhashable.
#     Do not use Workflow as a dict key or set member.
#   - Workflows are defined as module-level constants (PLAN_WORKFLOW, etc.).
#   - Phase transition validation: any phase in available_phases is reachable
#     from any other (user-directed), except self-transitions.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Workflow:
    """Immutable workflow definition.

    Attributes:
        name: Short identifier (e.g. "plan", "milestones").
        description: Human-readable description shown in the UI.
        available_phases: All phases the user can transition to in this workflow.
        initial_phase: Phase the orchestrator starts in.
        suggested_transitions: Per-phase ordered list of suggested next phases.
            Guides the orchestrator's boundary response; user can override.
        phase_descriptions: One-line description of each phase shown at boundaries.
        phase_guidance: Per-phase scope framing injected at the top of step 1
            guidance. Controls investigation depth, question posture, etc.
    """
    name: str
    description: str
    available_phases: tuple[str, ...]
    initial_phase: str
    suggested_transitions: dict[str, list[str]]
    phase_descriptions: dict[str, str]
    phase_guidance: dict[str, str]


# -- Plan workflow -------------------------------------------------------------
# intake → plan-spec → plan-review → execute
# Lightweight focused-change pipeline. Single executor spawn.

PLAN_WORKFLOW = Workflow(
    name="plan",
    description="Plan an implementation approach, review it, then execute",
    available_phases=("intake", "plan-spec", "plan-review", "execute"),
    initial_phase="intake",
    suggested_transitions={
        "intake":       ["plan-spec", "execute"],
        "plan-spec":    ["plan-review", "execute"],
        "plan-review":  ["plan-spec", "execute"],
        "execute":      ["plan-review"],
    },
    phase_descriptions={
        "intake":      "Explore the codebase and align on requirements through Q&A",
        "plan-spec":   "Write a technical implementation plan grounded in the codebase",
        "plan-review": "Evaluate the plan for completeness, correctness, and risks",
        "execute":     "Hand off the plan to an executor agent for implementation",
    },
    phase_guidance={
        "intake": (
            "## Scope\n"
            "This is a **plan** workflow \u2014 a focused change touching a bounded\n"
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
            "- If you dispatch scouts, 1\u20133 is typical for a plan workflow.\n"
            "\n"
            "## Question posture\n"
            "- Always ask at least one round of questions. Even well-specified tasks\n"
            "  benefit from confirming assumptions and surfacing implicit decisions.\n"
            "- A plan workflow needs 2\u20134 targeted questions covering: approach\n"
            "  confirmation, constraint verification, and scope boundaries.\n"
            "- The user wants to be consulted \u2014 asking questions is a feature, not a\n"
            "  burden. When in doubt, ask.\n"
            "\n"
            "## User override\n"
            "The user can always ask you to go deeper, dispatch more scouts, or ask\n"
            "more questions. Follow their lead over these defaults."
        ),
        "execute": (
            "## What to hand off\n"
            "Call `koan_request_executor` with:\n"
            "- **artifacts**: `[\"plan.md\"]` \u2014 the implementation plan.\n"
            "- **instructions**: Key decisions from plan-review, user clarifications,\n"
            "  or constraints. Do NOT repeat plan.md contents \u2014 the executor reads\n"
            "  it directly. Instructions are for context that isn't in the files.\n"
            "\n"
            "## After execution\n"
            "Report the result. If the executor failed or asked questions, relay\n"
            "the situation to the user and suggest next steps."
        ),
    },
)


# -- Milestones workflow (stub) -----------------------------------------------
# Runs intake only. Phase boundary reports the workflow is not yet implemented.

MILESTONES_WORKFLOW = Workflow(
    name="milestones",
    description="Break work into milestones with phased delivery (coming soon)",
    available_phases=("intake",),
    initial_phase="intake",
    suggested_transitions={"intake": []},
    phase_descriptions={
        "intake": "Explore the codebase and align on requirements through Q&A",
    },
    phase_guidance={
        "intake": (
            "## Scope\n"
            "This is a **milestones** workflow \u2014 a broad initiative spanning\n"
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
            "  and adjacent areas that might be affected. 3\u20135 scouts is typical.\n"
            "- **Also read directly** \u2014 verify key scout findings against the actual\n"
            "  code, especially integration points and conventions.\n"
            "\n"
            "## Question posture\n"
            "- Ask multiple rounds of questions. For broad initiatives, 2\u20133 rounds\n"
            "  of 3\u20136 questions is typical.\n"
            "- Surface assumptions early. Each answer may reveal new areas to probe.\n"
            "- Probe cross-cutting concerns: shared patterns, naming conventions,\n"
            "  error handling strategies, test coverage expectations.\n"
            "\n"
            "## User override\n"
            "The user can always tell you to narrow scope or skip questions.\n"
            "Follow their lead over these defaults."
        ),
    },
)


# -- Registry -----------------------------------------------------------------

WORKFLOWS: dict[str, Workflow] = {
    "plan": PLAN_WORKFLOW,
    "milestones": MILESTONES_WORKFLOW,
}


def get_workflow(name: str) -> Workflow:
    """Return the Workflow for the given name, or raise ValueError."""
    wf = WORKFLOWS.get(name)
    if wf is None:
        raise ValueError(f"Unknown workflow: {name!r}. Valid: {list(WORKFLOWS)}")
    return wf


def get_suggested_phases(workflow: Workflow, phase: str) -> list[str]:
    """Return the ordered suggested next phases for the current phase."""
    return list(workflow.suggested_transitions.get(phase, []))


def is_valid_transition(workflow: Workflow, from_phase: str, to_phase: str) -> bool:
    """Any phase in the workflow is reachable from any other (except self-transition).

    The user drives macro-level progression; suggested_transitions guides defaults
    but does not constrain choices.
    """
    return to_phase in workflow.available_phases and to_phase != from_phase
