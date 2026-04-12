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
    SYSTEM_PROMPT: str

    def step_guidance(self, step: int, ctx: PhaseContext) -> StepGuidance: ...
    def get_next_step(self, step: int, ctx: PhaseContext) -> int | None: ...
    def validate_step_completion(self, step: int, ctx: PhaseContext) -> str | None: ...
    async def on_loop_back(self, from_step: int, to_step: int, ctx: PhaseContext) -> None: ...


# -- Orchestrator base system prompt ------------------------------------------
# Delivered via --system-prompt at spawn time. Phase-specific role context
# is injected via koan_complete_step's step-1 guidance (SYSTEM_PROMPT prepend).

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the koan workflow orchestrator. You run a coding task planning and"
    " execution pipeline from start to finish in a single continuous session.\n"
    "\n"
    "You work through phases in sequence: each phase has numbered steps. Call"
    " koan_complete_step to advance through steps.\n"
    "\n"
    "When a phase ends, koan_complete_step tells you to summarize and yield.\n"
    "Call koan_yield with a summary and structured suggestions for the user.\n"
    "Each suggestion needs:\n"
    "- id: phase name (e.g. \"plan-spec\") or \"done\"\n"
    "- label: short action label (e.g. \"Write implementation plan\")\n"
    "- command: task-specific sentence pre-filled in the chat input when clicked\n"
    "Always include a \"done\" suggestion so the user can end the workflow.\n"
    "\n"
    "koan_yield blocks until the user sends a message and returns it to you.\n"
    "Respond conversationally. Call koan_yield again to continue the conversation.\n"
    "When the user confirms a direction, call koan_set_phase with the phase name.\n"
    "When the user is done, call koan_set_phase with \"done\".\n"
    "\n"
    "At the start of each phase, koan_complete_step returns your role context for"
    " that phase alongside the first step's instructions.\n"
    "\n"
    "Rules:\n"
    "- Only call koan_set_phase after the user has confirmed the direction.\n"
    "- Use koan_yield for all user interaction at phase boundaries.\n"
    "- Available tools change depending on the current phase."
)


# -- Phase module registry ----------------------------------------------------
# Maps each SubagentRole string to its phase module (for subagent spawn lookup).

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
    execute as execute_phase,
    plan_review,
    plan_spec,
)
PHASE_MODULE_MAP: dict[str, Any] = {
    "intake": intake,
    "scout": scout,
    "orchestrator": orchestrator,
    "planner": planner,
    "executor": executor,
}

# -- Phase guidance map -------------------------------------------------------
# Maps WorkflowPhase strings to the phase module that provides step guidance.
# Used by koan_set_phase to load the module for the new phase.

PHASE_GUIDANCE_MAP: dict[str, Any] = {
    # General-purpose phases (reusable by any workflow)
    "intake":   intake,
    "execute":  execute_phase,
    # Plan workflow phases (SCOPE="plan")
    "plan-spec":   plan_spec,
    "plan-review": plan_review,
    # Legacy phases (SCOPE="legacy" --dead code, available for future workflows)
    "brief-generation":          brief_writer,
    "core-flows":                core_flows,
    "tech-plan":                 planner,
    "ticket-breakdown":          ticket_breakdown,
    "cross-artifact-validation": cross_artifact_validation,
    "execution":                 executor,
    "implementation-validation": cross_artifact_validation,
}
