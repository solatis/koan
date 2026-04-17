# Phase types and protocol -- shared across all phase modules.
#
# StepGuidance: per-step instructions returned by each module's step_guidance().
# PhaseContext: mutable per-agent state carried across steps within a phase.
# PhaseModule: structural protocol that every phase module must satisfy.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class StepGuidance:
    title: str
    instructions: list[str]
    invoke_after: str | None = None


@dataclass
class PhaseContext:
    run_dir: str
    subagent_dir: str
    project_dir: str = ""
    task_description: str = ""
    workflow_name: str = ""              # populated from task["workflow"]
    phase_instructions: str | None = None
    executor_artifacts: list[str] = field(default_factory=list)  # for executor subagent
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
    SCOPE: str
    TOTAL_STEPS: int
    PHASE_ROLE_CONTEXT: str

    def step_guidance(self, step: int, ctx: PhaseContext) -> StepGuidance: ...
    def get_next_step(self, step: int, ctx: PhaseContext) -> int | None: ...
    def validate_step_completion(self, step: int, ctx: PhaseContext) -> str | None: ...
    async def on_loop_back(self, from_step: int, to_step: int, ctx: PhaseContext) -> None: ...


# -- Subagent module registry --------------------------------------------------
# Maps SubagentRole strings to phase modules for non-orchestrator subagent
# spawns (scouts, executors). Orchestrator phase dispatch uses
# Workflow.get_module() instead -- see koan/lib/workflows.py.

from . import executor, scout

PHASE_MODULE_MAP: dict[str, Any] = {
    "scout": scout,
    "executor": executor,
}
