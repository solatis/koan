# AgentRegistry -- maps agent types to Agent instances and resolves
# agent configuration (installation, model, thinking mode) for a role.
# Replaces koan/runners/registry.py; the runner-level types (RunnerRegistry,
# compute_balanced_profile, compute_builtin_profiles) move here.

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
from .base import Agent, AgentDiagnostic, AgentError
from .command_line import CommandLineAgent

if TYPE_CHECKING:
    from ..config import KoanConfig
    from ..state import AppState
    from ..types import SubagentRole


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


# -- AgentRegistry -------------------------------------------------------------

class AgentRegistry:
    """Resolves agent configuration and constructs Agent instances for a role.

    Replaces RunnerRegistry from koan/runners/registry.py. The public interface
    is unchanged except for naming: get_runner -> get_agent, RunnerError ->
    AgentError, RunnerDiagnostic -> AgentDiagnostic (runner= field -> agent=).
    """

    def get_agent(
        self,
        runner_type: str,
        subagent_dir: str,
        app_state: AppState | None = None,
    ) -> Agent:
        """Construct and return an Agent for the given runner_type.

        runner_type identifies the agent class for this profile tier. The name
        is historical (predates the M2 Runner -> Agent rename) and is preserved
        for config-schema stability. Current mapping:
          'claude'  -> ClaudeSDKAgent (drives the Claude Agent SDK directly)
          'codex'   -> CommandLineAgent(CodexRunner)
          'gemini'  -> CommandLineAgent(GeminiRunner)

        In M2 the 'claude' branch resolves to ClaudeSDKAgent; codex and gemini
        still resolve to CommandLineAgent wrapping their respective Runner.
        ClaudeSDKAgent requires app_state for the steering PostToolUse hook
        closure -- pass it from spawn_subagent. CommandLineAgent ignores it.

        Runner and agent classes are imported lazily inside each branch to avoid
        the circular import that arises at module load time: koan/runners/__init__.py
        eagerly imports codex/gemini, which import AgentDiagnostic/AgentError
        from koan/agents/base.py, which triggers koan/agents/__init__.py, which
        evaluates koan/agents/registry.py. A module-level import here would
        re-enter those modules mid-init and fail with AttributeError.

        Raises AgentError with code 'unknown_runner_type' for unrecognized types.
        Raises AgentError with code 'missing_app_state' when claude is requested
        without app_state (required for the PostToolUse hook closure).
        """
        if runner_type == "claude":
            from .claude import ClaudeSDKAgent  # lazy -- see docstring
            if app_state is None:
                raise AgentError(AgentDiagnostic(
                    code="missing_app_state",
                    agent="claude",
                    stage="get_agent",
                    message="ClaudeSDKAgent requires app_state for the PostToolUse hook closure.",
                ))
            return ClaudeSDKAgent(subagent_dir=subagent_dir, app_state=app_state)
        elif runner_type == "codex":
            from ..runners.codex import CodexRunner  # lazy -- see docstring
            runner = CodexRunner()
        elif runner_type == "gemini":
            from ..runners.gemini import GeminiRunner  # lazy -- see docstring
            runner = GeminiRunner(subagent_dir=subagent_dir)
        else:
            raise AgentError(AgentDiagnostic(
                code="unknown_runner_type",
                agent=runner_type,
                stage="get_agent",
                message=f"Unknown runner type: {runner_type}",
            ))
        return CommandLineAgent(runner=runner, subagent_dir=subagent_dir)

    def get_installation(
        self,
        runner_type: str,
        config: KoanConfig,
        run_installations: dict[str, str] | None = None,
    ) -> AgentInstallation:
        """Return the AgentInstallation for runner_type, optionally scoped to a run alias.

        Raises AgentError with code 'no_installation' if no matching installation
        is found in config.agent_installations.
        """
        alias = (run_installations or {}).get(runner_type)
        if alias:
            for inst in config.agent_installations:
                if inst.alias == alias and inst.runner_type == runner_type:
                    return inst
            raise AgentError(AgentDiagnostic(
                code="no_installation",
                agent=runner_type,
                stage="get_installation",
                message=f"Installation alias '{alias}' not found for agent '{runner_type}'",
                details={"runner_type": runner_type, "alias": alias},
            ))

        # No alias specified -- fall back to first installation of this type.
        for inst in config.agent_installations:
            if inst.runner_type == runner_type:
                return inst

        raise AgentError(AgentDiagnostic(
            code="no_installation",
            agent=runner_type,
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
        Raises AgentError if the installation is missing or the binary is not found.
        """
        inst = self.get_installation(runner_type, config, run_installations)
        if not Path(inst.binary).exists():
            raise AgentError(AgentDiagnostic(
                code="binary_not_found",
                agent=runner_type,
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
        """Resolve (installation, model_alias, thinking_mode) for the given role.

        Reads the active profile from config, selects the tier for role, and
        resolves the installation. Raises AgentError on any resolution failure.
        """
        tier = ROLE_MODEL_TIER.get(role, "standard")

        # Back-compat: wrap legacy balanced_profile into builtin_profiles dict.
        if builtin_profiles is None and balanced_profile is not None:
            builtin_profiles = {"balanced": balanced_profile}

        # Resolve active profile.
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
                stage="resolve_agent_config",
                message=f"Profile '{config.active_profile}' not found",
            ))

        profile_tier = profile.tiers.get(tier)
        if profile_tier is None:
            raise AgentError(AgentDiagnostic(
                code="no_profile",
                agent="",
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
    """Compute all built-in profiles (balanced, frontier, ...) from probe results."""
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
