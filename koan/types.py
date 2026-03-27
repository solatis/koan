# Shared type literals and constants for the koan orchestrator.
# Python port of src/planner/types.ts -- kept in sync manually.

from dataclasses import dataclass, field
from typing import Literal

EpicPhase = Literal[
    "intake",
    "brief-generation",
    "core-flows",
    "tech-plan",
    "ticket-breakdown",
    "cross-artifact-validation",
    "execution",
    "implementation-validation",
    "completed",
]

SubagentRole = Literal[
    "intake",
    "scout",
    "decomposer",
    "orchestrator",
    "planner",
    "executor",
    "brief-writer",
    "workflow-orchestrator",
    "ticket-breakdown",
    "cross-artifact-validator",
]

ModelTier = Literal["strong", "standard", "cheap"]

ALL_MODEL_TIERS: tuple[ModelTier, ...] = ("strong", "standard", "cheap")

StoryStatus = Literal[
    "pending",
    "selected",
    "planning",
    "executing",
    "verifying",
    "done",
    "retry",
    "skipped",
]

DEFAULT_MAX_RETRIES = 2

ThinkingMode = Literal["disabled", "low", "medium", "high", "xhigh"]


@dataclass
class ModelInfo:
    alias: str
    display_name: str
    thinking_modes: frozenset[ThinkingMode]
    tier_hint: ModelTier | None


@dataclass
class ProfileTier:
    runner_type: str
    model: str
    thinking: ThinkingMode


@dataclass
class Profile:
    name: str
    tiers: dict[ModelTier, ProfileTier] = field(default_factory=dict)


@dataclass
class AgentInstallation:
    alias: str
    runner_type: str
    binary: str
    extra_args: list[str] = field(default_factory=list)


ROLE_MODEL_TIER: dict[SubagentRole, ModelTier] = {
    "intake": "strong",
    "scout": "cheap",
    "decomposer": "strong",
    "brief-writer": "strong",
    "orchestrator": "strong",
    "planner": "strong",
    "executor": "standard",
    "workflow-orchestrator": "strong",
    "ticket-breakdown": "strong",
    "cross-artifact-validator": "strong",
}
