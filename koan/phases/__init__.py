# Phase types and protocol -- shared across all phase modules.
#
# StepGuidance: per-step instructions returned by each module's step_guidance().
# PhaseContext: mutable per-agent state carried across steps within a phase.
# PhaseModule: structural protocol that every phase module must satisfy.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class StepGuidance:
    title: str
    instructions: list[str]
    invoke_after: str | None = None


@dataclass
class PhaseContext:
    epic_dir: str
    subagent_dir: str
    project_dir: str = ""
    phase_instructions: str | None = None
    intake_confidence: str | None = None
    intake_iteration: int = 0
    last_review_accepted: bool | None = None
    proposal_made: bool = False
    next_phase_set: bool = False
    step_sequence: str | None = None
    story_id: str | None = None
    retry_context: str | None = None
    completed_phase: str | None = None
    available_phases: list[str] = field(default_factory=list)
    scout_question: str | None = None
    scout_investigator_role: str | None = None


@runtime_checkable
class PhaseModule(Protocol):
    ROLE: str
    TOTAL_STEPS: int
    SYSTEM_PROMPT: str

    def step_guidance(self, step: int, ctx: PhaseContext) -> StepGuidance: ...
    def get_next_step(self, step: int, ctx: PhaseContext) -> int | None: ...
    def validate_step_completion(self, step: int, ctx: PhaseContext) -> str | None: ...
    async def on_loop_back(self, from_step: int, to_step: int, ctx: PhaseContext) -> None: ...


# -- Phase module registry ----------------------------------------------------
# Maps each SubagentRole string to its phase module.

from . import (
    brief_writer,
    core_flows,
    cross_artifact_validation,
    executor,
    intake,
    orchestrator,
    scout,
    tech_plan as planner,
    ticket_breakdown,
    workflow_orchestrator,
)
from typing import Any

PHASE_MODULE_MAP: dict[str, Any] = {
    "intake": intake,
    "scout": scout,
    "brief-writer": brief_writer,
    "decomposer": core_flows,
    "orchestrator": orchestrator,
    "planner": planner,
    "executor": executor,
    "workflow-orchestrator": workflow_orchestrator,
    "ticket-breakdown": ticket_breakdown,
    "cross-artifact-validator": cross_artifact_validation,
}
