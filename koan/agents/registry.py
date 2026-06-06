# AgentRegistry -- maps agent types to Agent instances and resolves
# agent configuration (model spec) for a role.
# Replaces koan/runners/registry.py; the runner-level types (RunnerRegistry,
# compute_balanced_profile, compute_builtin_profiles) move here.

from __future__ import annotations

from typing import TYPE_CHECKING

from ..logger import get_logger
from ..types import (
    BUILTIN_PROFILE_NAMES,
    ROLE_MODEL_TIER,
    ModelSpec,
    ModelTier,
    Profile,
    ProfileTier,
    ThinkingMode,
)
from .base import AgentDiagnostic, AgentError
# CommandLineAgent removed in M4; get_agent deleted.

if TYPE_CHECKING:
    from ..config import KoanConfig
    from ..types import SubagentRole

log = get_logger("agent_registry")


# -- Built-in Gemini profile definitions (static; probe_results vestigial) ----
#
# Static per-tier Gemini specs: strong/standard/cheap -> model + thinking.
# These are the provider-based replacement for the old runner-priority table.
# Context windows are filled with known values; update when models change.

_GEMINI_TIER_SPECS: dict[ModelTier, tuple[str, ThinkingMode, int]] = {
    # (model_id, thinking, context_window). IDs must be valid google-GLA model
    # names: versioned names take no "-latest" suffix (gemini-3.1-pro-preview, not
    # gemini-3.1-pro-preview-latest -> 404); only unversioned names do (gemini-flash-lite-latest).
    # Note: the cheap tier uses "gemini-3.1-flash-lite" (versioned, resolves in
    # genai-prices snapshot) rather than "gemini-flash-lite-latest" (unversioned alias
    # that does not appear in the genai-prices catalog); both are valid GLA model names.
    "strong":   ("gemini-3.1-pro-preview", "high",     1_000_000),
    "standard": ("gemini-3.5-flash",       "medium",   1_000_000),
    "cheap":    ("gemini-3.1-flash-lite",  "disabled", 1_000_000),
}

_TIER_DEFAULT_THINKING: dict[ModelTier, ThinkingMode] = {
    "strong": "high",
    "standard": "medium",
    "cheap": "disabled",
}

_THINKING_RANK: list[ThinkingMode] = ["disabled", "low", "medium", "high", "xhigh", "max"]


def _best_supported_thinking(
    supported: frozenset[ThinkingMode], desired: ThinkingMode
) -> ThinkingMode:
    """Return the highest supported thinking mode at or below *desired*."""
    desired_idx = _THINKING_RANK.index(desired) if desired in _THINKING_RANK else 0
    best: ThinkingMode = "disabled"
    for mode in _THINKING_RANK:
        if mode in supported and _THINKING_RANK.index(mode) <= desired_idx:
            best = mode
    return best


# -- AgentRegistry -------------------------------------------------------------

class AgentRegistry:
    """Resolves agent configuration for a role.

    M4: get_agent deleted -- the legacy CLI/SDK agent path is removed; spawn_subagent
    always constructs a PydanticAIAgent directly. resolve_model_spec remains as the
    primary resolution path.
    """

    # get_agent removed in M4: CLI/SDK agent path deleted; PydanticAIAgent is
    # always used. get_installation and resolve_installation removed in M1/M4:
    # binary detection retired; provider credentials resolve in adapter.py.

    def resolve_model_spec(
        self,
        role: SubagentRole,
        config: KoanConfig,
        builtin_profiles: dict[str, Profile] | None = None,
    ) -> ModelSpec:
        """Resolve ModelSpec for a role via the active profile's tier mapping.

        Reads ROLE_MODEL_TIER[role] -> tier -> ProfileTier.model (ModelSpec).
        Raises AgentError with code 'no_profile' if the active profile or tier
        is missing from both config.profiles and builtin_profiles.
        """
        tier = ROLE_MODEL_TIER.get(role, "standard")

        profile: Profile | None = None
        for p in config.profiles:
            if p.name == config.active_profile:
                profile = p
                break

        if profile is None and builtin_profiles:
            profile = builtin_profiles.get(config.active_profile)

        if profile is None:
            raise AgentError(AgentDiagnostic(
                code="no_profile",
                agent="",
                stage="resolve_model_spec",
                message=f"Profile '{config.active_profile}' not found",
            ))

        profile_tier = profile.tiers.get(tier)
        if profile_tier is None:
            raise AgentError(AgentDiagnostic(
                code="no_profile",
                agent="",
                stage="resolve_model_spec",
                message=f"Profile '{profile.name}' has no tier '{tier}'",
            ))

        return profile_tier.model

    # _claude_clamp removed -- binary detection retired; provider adapter handles
    # per-provider thinking mapping in koan/agents/adapter.py.


# -- Built-in profile computation ----------------------------------------------

def _compute_balanced() -> Profile:
    """Build the balanced built-in profile with static Gemini ModelSpec tiers."""
    tiers: dict[str, ProfileTier] = {}
    for tier_name in ("strong", "standard", "cheap"):
        model_id, thinking, ctx_window = _GEMINI_TIER_SPECS[tier_name]
        tiers[tier_name] = ProfileTier(model=ModelSpec(
            provider="google",
            model=model_id,
            thinking=thinking,
            context_window=ctx_window,
        ))
    return Profile(name="balanced", tiers=tiers)


def _compute_fixed(name: str, specs: dict[ModelTier, tuple[str, ThinkingMode, int]]) -> Profile:
    """Build a named fixed built-in profile from a static (model, thinking, ctx_window) spec map."""
    tiers: dict[str, ProfileTier] = {}
    for tier_name, (model_id, thinking, ctx_window) in specs.items():
        tiers[tier_name] = ProfileTier(model=ModelSpec(
            provider="google",
            model=model_id,
            thinking=thinking,
            context_window=ctx_window,
        ))
    return Profile(name=name, tiers=tiers)


# Frontier uses larger/more-capable models than balanced across all tiers.
_GEMINI_FRONTIER_SPECS: dict[ModelTier, tuple[str, ThinkingMode, int]] = {
    "strong":   ("gemini-3.1-pro-preview", "high",   1_000_000),
    "standard": ("gemini-3.1-pro-preview", "medium", 1_000_000),
    "cheap":    ("gemini-3.5-flash",       "low",    1_000_000),
}


def compute_builtin_profiles() -> dict[str, Profile]:
    """Compute all built-in profiles (balanced, frontier) as static Gemini ModelSpec profiles.

    Provider profiles are static -- runner probing is retired. The vestigial
    probe_results parameter is removed as part of the M2 ProviderStatus rename;
    callers that passed probe_results should be updated to call with no argument.
    """
    profiles: dict[str, Profile] = {}
    profiles["balanced"] = _compute_balanced()
    profiles["frontier"] = _compute_fixed("frontier", _GEMINI_FRONTIER_SPECS)
    return profiles


def compute_balanced_profile() -> Profile:
    """DEPRECATED: use compute_builtin_profiles instead."""
    return compute_builtin_profiles()["balanced"]
