# RunnerRegistry -- maps runner types to runner instances and resolves
# agent configuration (installation, model, thinking mode) for a role.

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..probe import ProbeResult
from ..types import (
    BUILTIN_PROFILE_NAMES,
    ROLE_MODEL_TIER,
    AgentInstallation,
    ModelInfo,
    ModelTier,
    Profile,
    ProfileTier,
    ThinkingMode,
)
from .base import RunnerDiagnostic, RunnerError
from .claude import ClaudeRunner
from .codex import CodexRunner
from .gemini import GeminiRunner

if TYPE_CHECKING:
    from ..config import KoanConfig
    from ..types import SubagentRole
    from .base import Runner


# -- Runner class lookup -------------------------------------------------------

_RUNNER_FACTORIES: dict[str, type] = {
    "claude": ClaudeRunner,
    "codex": CodexRunner,
    "gemini": GeminiRunner,
}

_NEEDS_SUBAGENT_DIR = frozenset({"claude", "gemini"})


# -- Built-in profile definitions ----------------------------------------------

# Balanced: auto-fallback across available runners
_TIER_PRIORITY: dict[ModelTier, list[tuple[str, str]]] = {
    "strong": [("claude", "sonnet"), ("codex", "gpt-5"), ("gemini", "gemini-pro")],
    "standard": [("claude", "sonnet"), ("codex", "gpt-5"), ("gemini", "gemini-pro")],
    "cheap": [("claude", "haiku"), ("codex", "gpt-5-mini"), ("gemini", "gemini-flash")],
}

# Fixed built-in profiles: (runner_type, model) per tier, no fallback logic
_FIXED_PROFILE_SPECS: dict[str, dict[ModelTier, tuple[str, str]]] = {
    "frontier": {
        "strong": ("claude", "opus[1m]"),
        "standard": ("claude", "sonnet"),
        "cheap": ("claude", "haiku"),
    },
}

_TIER_DEFAULT_THINKING: dict[ModelTier, ThinkingMode] = {
    "strong": "high",
    "standard": "medium",
    "cheap": "disabled",
}

_THINKING_RANK: list[ThinkingMode] = ["disabled", "low", "medium", "high", "xhigh"]


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


# -- RunnerRegistry ------------------------------------------------------------

class RunnerRegistry:
    def get_runner(self, runner_type: str, subagent_dir: str) -> Runner:
        cls = _RUNNER_FACTORIES.get(runner_type)
        if cls is None:
            raise RunnerError(RunnerDiagnostic(
                code="unknown_runner_type",
                runner=runner_type,
                stage="get_runner",
                message=f"Unknown runner type: {runner_type}",
            ))
        if runner_type in _NEEDS_SUBAGENT_DIR:
            return cls(subagent_dir=subagent_dir)
        return cls()

    def get_installation(
        self,
        runner_type: str,
        config: KoanConfig,
        run_installations: dict[str, str] | None = None,
    ) -> AgentInstallation:
        alias = (run_installations or {}).get(runner_type)
        if alias:
            for inst in config.agent_installations:
                if inst.alias == alias and inst.runner_type == runner_type:
                    return inst
            raise RunnerError(RunnerDiagnostic(
                code="no_installation",
                runner=runner_type,
                stage="get_installation",
                message=f"Installation alias '{alias}' not found for runner '{runner_type}'",
                details={"runner_type": runner_type, "alias": alias},
            ))

        # No alias specified -- fall back to first installation of this type
        for inst in config.agent_installations:
            if inst.runner_type == runner_type:
                return inst

        raise RunnerError(RunnerDiagnostic(
            code="no_installation",
            runner=runner_type,
            stage="get_installation",
            message=f"No {runner_type} installation configured",
            details={"runner_type": runner_type},
        ))

    def resolve_installation(
        self,
        runner_type: str,
        config: KoanConfig,
        run_installations: dict[str, str] | None = None,
    ) -> AgentInstallation:
        """Resolve a working installation for *runner_type*.

        Returns the installation after validating its binary exists on disk.
        Raises RunnerError if the installation is missing or the binary is not found.
        """
        inst = self.get_installation(runner_type, config, run_installations)
        if not Path(inst.binary).exists():
            raise RunnerError(RunnerDiagnostic(
                code="binary_not_found",
                runner=runner_type,
                stage="resolve_installation",
                message=(
                    f"Binary not found for {runner_type} installation '{inst.alias}': {inst.binary}. "
                    f"Update the installation in Settings or re-detect the binary."
                ),
                details={"runner_type": runner_type, "alias": inst.alias, "binary": inst.binary},
            ))
        return inst

    def resolve_agent_config(
        self,
        role: SubagentRole,
        config: KoanConfig,
        builtin_profiles: dict[str, Profile] | None = None,
        run_installations: dict[str, str] | None = None,
        # DEPRECATED parameter -- ignored if builtin_profiles is provided
        balanced_profile: Profile | None = None,
    ) -> tuple[AgentInstallation, str, ThinkingMode]:
        tier = ROLE_MODEL_TIER.get(role, "standard")

        # Back-compat: wrap legacy balanced_profile into builtin_profiles dict
        if builtin_profiles is None and balanced_profile is not None:
            builtin_profiles = {"balanced": balanced_profile}

        # Resolve active profile
        profile: Profile | None = None
        for p in config.profiles:
            if p.name == config.active_profile:
                profile = p
                break

        if profile is None and builtin_profiles:
            profile = builtin_profiles.get(config.active_profile)

        if profile is None:
            raise RunnerError(RunnerDiagnostic(
                code="no_profile",
                runner="",
                stage="resolve_agent_config",
                message=f"Profile '{config.active_profile}' not found",
            ))

        profile_tier = profile.tiers.get(tier)
        if profile_tier is None:
            raise RunnerError(RunnerDiagnostic(
                code="no_profile",
                runner="",
                stage="resolve_agent_config",
                message=f"Profile '{profile.name}' has no tier '{tier}'",
            ))

        installation = self.resolve_installation(
            profile_tier.runner_type, config, run_installations,
        )
        return installation, profile_tier.model, profile_tier.thinking


# -- Built-in profile computation ----------------------------------------------

def _resolve_thinking(
    model_lookup: dict[tuple[str, str], ModelInfo],
    runner_type: str,
    model: str,
    tier_name: ModelTier,
) -> ThinkingMode:
    default_thinking = _TIER_DEFAULT_THINKING[tier_name]
    info = model_lookup.get((runner_type, model))
    if info is not None and default_thinking not in info.thinking_modes:
        return _best_supported_thinking(info.thinking_modes, default_thinking)
    return default_thinking


def _compute_balanced(
    available_runners: set[str],
    model_lookup: dict[tuple[str, str], ModelInfo],
) -> Profile:
    tiers: dict[str, ProfileTier] = {}
    for tier_name in ("strong", "standard", "cheap"):
        priority = _TIER_PRIORITY[tier_name]
        picked = False
        for runner_type, model in priority:
            if runner_type in available_runners:
                thinking = _resolve_thinking(model_lookup, runner_type, model, tier_name)
                tiers[tier_name] = ProfileTier(
                    runner_type=runner_type, model=model, thinking=thinking,
                )
                picked = True
                break
        if not picked and available_runners:
            fallback_rt = next(iter(available_runners))
            fallback_model = fallback_rt
            for rt, m in priority:
                if rt == fallback_rt:
                    fallback_model = m
                    break
            thinking = _resolve_thinking(model_lookup, fallback_rt, fallback_model, tier_name)
            tiers[tier_name] = ProfileTier(
                runner_type=fallback_rt, model=fallback_model, thinking=thinking,
            )
    return Profile(name="balanced", tiers=tiers)


def _compute_fixed(
    name: str,
    spec: dict[ModelTier, tuple[str, str]],
    model_lookup: dict[tuple[str, str], ModelInfo],
) -> Profile:
    tiers: dict[str, ProfileTier] = {}
    for tier_name, (runner_type, model) in spec.items():
        thinking = _resolve_thinking(model_lookup, runner_type, model, tier_name)
        tiers[tier_name] = ProfileTier(
            runner_type=runner_type, model=model, thinking=thinking,
        )
    return Profile(name=name, tiers=tiers)


def compute_builtin_profiles(probe_results: list[ProbeResult]) -> dict[str, Profile]:
    available_runners = {pr.runner_type for pr in probe_results if pr.available}
    model_lookup: dict[tuple[str, str], ModelInfo] = {}
    for pr in probe_results:
        if pr.available:
            for m in pr.models:
                model_lookup[(pr.runner_type, m.alias)] = m

    profiles: dict[str, Profile] = {}
    profiles["balanced"] = _compute_balanced(available_runners, model_lookup)
    for name, spec in _FIXED_PROFILE_SPECS.items():
        profiles[name] = _compute_fixed(name, spec, model_lookup)
    return profiles


def compute_balanced_profile(probe_results: list[ProbeResult]) -> Profile:
    """DEPRECATED: use compute_builtin_profiles instead."""
    return compute_builtin_profiles(probe_results)["balanced"]
