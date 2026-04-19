# DEPRECATED: This file is superseded by koan/lib/workflows.py.
# PHASE_TRANSITIONS, IMPLEMENTED_PHASES, PHASE_DESCRIPTIONS, get_successor_phases,
# is_valid_transition, is_auto_advance, and is_stub_phase are no longer used
# by the active code path. Kept for reference only.
#
# The active code path uses koan/lib/workflows.py for phase transition logic.
# Phase DAG validation has been replaced by workflow membership checks.

from __future__ import annotations

from ..types import WorkflowPhase

# Valid successor phases for each phase. Order = recommendation priority.
# The first entry is the most-recommended default path.
PHASE_TRANSITIONS: dict[WorkflowPhase, list[WorkflowPhase]] = {
    "intake":                    ["brief-generation", "core-flows"],
    "brief-generation":          ["core-flows"],
    "core-flows":                ["tech-plan"],
    "tech-plan":                 ["ticket-breakdown"],
    "ticket-breakdown":          ["cross-artifact-validation"],
    "cross-artifact-validation": ["execution"],
    "execution":                 ["implementation-validation"],
    "implementation-validation": ["completed"],
    "completed":                 [],
}

# Phases that have a real implementation (subagent-backed).
# All other non-terminal phases are stubs that auto-advance when reached.
IMPLEMENTED_PHASES: frozenset[WorkflowPhase] = frozenset({
    "intake",
    "brief-generation",
    "core-flows",
    "tech-plan",
    "ticket-breakdown",
    "cross-artifact-validation",
    "execution",
})

# Human-readable one-line description of each phase.
PHASE_DESCRIPTIONS: dict[WorkflowPhase, str] = {
    "intake":                    "Multi-round codebase exploration and structured Q&A to align on requirements",
    "brief-generation":          "Distill intake context into a compact product-level epic brief",
    "core-flows":                "Define user journeys with sequence diagrams",
    "tech-plan":                 "Specify technical architecture: approach, data model, component design",
    "ticket-breakdown":          "Generate story-sized implementation tickets with dependency diagrams",
    "cross-artifact-validation": "Validate cross-boundary consistency across all spec artifacts",
    "execution":                 "Implement tickets through a supervised batch process with verification",
    "implementation-validation": "Post-execution review evaluating alignment and correctness against specs",
    "completed":                 "Pipeline complete",
}


def get_successor_phases(phase: WorkflowPhase) -> list[WorkflowPhase]:
    return PHASE_TRANSITIONS.get(phase, [])


def is_auto_advance(phase: WorkflowPhase) -> bool:
    return len(get_successor_phases(phase)) == 1


def is_stub_phase(phase: WorkflowPhase) -> bool:
    return phase != "completed" and phase != "implementation-validation" and phase not in IMPLEMENTED_PHASES


def is_valid_transition(from_phase: WorkflowPhase | None, to_phase: WorkflowPhase) -> bool:
    if from_phase is None:
        return False
    return to_phase in get_successor_phases(from_phase)
