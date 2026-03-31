# RunnerRegistry -- maps runner types to runner instances and resolves
# agent configuration (installation, model, thinking mode) for a role.

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..probe import ProbeResult
from ..types import (
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


# -- Balanced profile priority table -------------------------------------------

_TIER_PRIORITY: dict[ModelTier, list[tuple[str, str]]] = {
    "strong": [("claude", "opus"), ("codex", "gpt-5"), ("gemini", "gemini-pro")],
    "standard": [("claude", "sonnet"), ("codex", "gpt-5"), ("gemini", "gemini-pro")],
    "cheap": [("claude", "haiku"), ("codex", "gpt-5-mini"), ("gemini", "gemini-flash")],
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

    def get_installation(self, runner_type: str, config: KoanConfig) -> AgentInstallation:
        alias = config.active_installations.get(runner_type)
        if alias:
            for inst in config.agent_installations:
                if inst.alias == alias and inst.runner_type == runner_type:
                    return inst
            raise RunnerError(RunnerDiagnostic(
                code="no_installation",
                runner=runner_type,
                stage="get_installation",
                message=f"Active installation alias '{alias}' not found for runner '{runner_type}'",
                details={"runner_type": runner_type, "alias": alias},
            ))

        # No active alias configured -- fall back to first installation of this type
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

    def resolve_installation(self, runner_type: str, config: KoanConfig) -> AgentInstallation:
        """Resolve a working installation for *runner_type*.

        Returns the installation after validating its binary exists on disk.
        Raises RunnerError if the installation is missing or the binary is not found.
        """
        inst = self.get_installation(runner_type, config)
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
        balanced_profile: Profile | None = None,
    ) -> tuple[AgentInstallation, str, ThinkingMode]:
        tier = ROLE_MODEL_TIER.get(role, "standard")

        # Resolve active profile
        profile: Profile | None = None
        for p in config.profiles:
            if p.name == config.active_profile:
                profile = p
                break

        if profile is None and config.active_profile == "balanced":
            profile = balanced_profile

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

        installation = self.resolve_installation(profile_tier.runner_type, config)
        return installation, profile_tier.model, profile_tier.thinking


# -- Balanced profile computation ----------------------------------------------

def compute_balanced_profile(probe_results: list[ProbeResult]) -> Profile:
    available_runners = {pr.runner_type for pr in probe_results if pr.available}

    # Build model lookup: (runner_type, alias) -> ModelInfo
    model_lookup: dict[tuple[str, str], ModelInfo] = {}
    for pr in probe_results:
        if pr.available:
            for m in pr.models:
                model_lookup[(pr.runner_type, m.alias)] = m

    tiers: dict[str, ProfileTier] = {}
    for tier_name in ("strong", "standard", "cheap"):
        priority = _TIER_PRIORITY[tier_name]
        default_thinking = _TIER_DEFAULT_THINKING[tier_name]
        picked = False
        for runner_type, model in priority:
            if runner_type in available_runners:
                # Resolve thinking: clamp to model capabilities when known
                thinking = default_thinking
                model_info = model_lookup.get((runner_type, model))
                if model_info is not None and thinking not in model_info.thinking_modes:
                    thinking = _best_supported_thinking(
                        model_info.thinking_modes, thinking,
                    )
                tiers[tier_name] = ProfileTier(
                    runner_type=runner_type,
                    model=model,
                    thinking=thinking,
                )
                picked = True
                break
        if not picked and available_runners:
            # Safe fallback: first available runner with its first priority-table model
            fallback_rt = next(iter(available_runners))
            fallback_model = fallback_rt
            for rt, m in priority:
                if rt == fallback_rt:
                    fallback_model = m
                    break
            thinking = default_thinking
            fb_info = model_lookup.get((fallback_rt, fallback_model))
            if fb_info is not None and thinking not in fb_info.thinking_modes:
                thinking = _best_supported_thinking(fb_info.thinking_modes, thinking)
            tiers[tier_name] = ProfileTier(
                runner_type=fallback_rt,
                model=fallback_model,
                thinking=thinking,
            )

    return Profile(name="balanced", tiers=tiers)
