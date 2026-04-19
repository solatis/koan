# Shared type literals and constants for the koan orchestrator.
# Python port of src/planner/types.ts -- kept in sync manually.

from dataclasses import dataclass, field
from typing import Literal

WorkflowPhase = Literal[
    # Legacy workflow phases (kept as dead code; no active workflow uses these)
    "intake",
    "brief-generation",
    "core-flows",
    "tech-plan",
    "ticket-breakdown",
    "cross-artifact-validation",
    "execution",
    "implementation-validation",
    "completed",
    # Plan workflow phases
    "plan-spec",
    "plan-review",
    "execute",
    # Curation (memory maintenance) -- reusable across workflows
    "curation",
]

SubagentRole = Literal[
    "intake",
    "scout",
    "orchestrator",
    "planner",
    "executor",
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


BUILTIN_PROFILE_NAMES: frozenset[str] = frozenset({"balanced", "frontier"})


@dataclass
class AgentInstallation:
    alias: str
    runner_type: str
    binary: str
    extra_args: list[str] = field(default_factory=list)


ROLE_MODEL_TIER: dict[SubagentRole, ModelTier] = {
    "intake": "strong",
    "scout": "cheap",
    "orchestrator": "strong",
    "planner": "strong",
    "executor": "standard",
}
