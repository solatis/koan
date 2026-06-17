# AgentRegistry -- maps agent types to Agent instances and resolves
# agent configuration (model spec) for a role.
# Replaces koan/runners/registry.py; the runner-level types (RunnerRegistry,
# compute_balanced_profile, compute_builtin_profiles) move here.
#
# M1: resolve_model_spec rewritten to resolve role -> slot -> configured model
# -> connection into a ModelSpec.  Built-in Gemini profile constants and
# compute_builtin_profiles static profiles removed (brief D12 -- koan ships
# no default models; unconfigured state fails fast with a clear error).

from __future__ import annotations

from typing import TYPE_CHECKING

from ..logger import get_logger
from ..types import (
    ROLE_MODEL_TIER,
    ModelSpec,
    ModelTier,
    ThinkingMode,
)
from .base import AgentDiagnostic, AgentError

if TYPE_CHECKING:
    from ..config import KoanConfig
    from ..types import SubagentRole

log = get_logger("agent_registry")


# -- Thinking-mode helpers preserved for M2 use --------------------------------

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

    M1: resolve_model_spec resolves role -> slot -> configured model ->
    connection -> ModelSpec via the new presets/connections schema.
    Built-in profile fallback removed (brief D12).
    M5: builtin_profiles parameter removed (compute_builtin_profiles deleted).
    """

    def resolve_model_spec(
        self,
        role: "SubagentRole",
        config: "KoanConfig",
    ) -> ModelSpec:
        """Resolve a ModelSpec for a role via the active preset's slot mapping.

        Maps role -> ModelTier slot -> SlotAssignment -> ConfiguredModel ->
        Connection -> ModelSpec.  Raises AgentError(code='unconfigured') when
        the active preset, the slot assignment, the ConfiguredModel, or the
        Connection is missing.  No default model is ever substituted (brief D12).
        """
        tier = ROLE_MODEL_TIER.get(role, "standard")
        preset = config.presets.get(config.active)
        if preset is None:
            raise AgentError(AgentDiagnostic(
                code="unconfigured",
                agent="",
                stage="resolve_model_spec",
                message=(
                    f"No active preset found (active='{config.active}'). "
                    "Configure at least one slot assignment in the '$last' preset."
                ),
            ))

        slot = preset.slots.get(tier)
        if slot is None:
            raise AgentError(AgentDiagnostic(
                code="unconfigured",
                agent="",
                stage="resolve_model_spec",
                message=(
                    f"No slot assignment for tier '{tier}' in preset '{config.active}'."
                ),
            ))

        # Resolve the configured model by id.
        cm = next(
            (m for m in config.configured_models if m.id == slot.configured_model_id),
            None,
        )
        if cm is None:
            raise AgentError(AgentDiagnostic(
                code="unconfigured",
                agent="",
                stage="resolve_model_spec",
                message=(
                    f"Configured model '{slot.configured_model_id}' (referenced by "
                    f"slot '{tier}' in preset '{config.active}') not found."
                ),
            ))

        # Resolve the connection by id.
        conn = next(
            (c for c in config.connections if c.id == cm.connection_id),
            None,
        )
        if conn is None:
            raise AgentError(AgentDiagnostic(
                code="unconfigured",
                agent="",
                stage="resolve_model_spec",
                message=(
                    f"Connection '{cm.connection_id}' (referenced by configured model "
                    f"'{cm.id}') not found."
                ),
            ))

        # Resolve capabilities and clamp the requested thinking mode to what the
        # model actually supports (the _claude_clamp pattern: deterministic +
        # observable via an INFO log, brief D5 / M2 plan step 6).
        from ..agents.capability_resolver import resolve_capabilities
        caps = resolve_capabilities(conn.type, cm.model_id)
        clamped = _best_supported_thinking(frozenset(caps.thinking_modes), slot.thinking)
        if clamped != slot.thinking:
            log.info(
                "thinking mode clamped for role '%s' model '%s': requested '%s' -> supported '%s'",
                role, cm.model_id, slot.thinking, clamped,
            )

        return ModelSpec(
            provider=conn.type,
            model=cm.model_id,
            thinking=clamped,
            settings={},
            caching=slot.caching,
            connection_id=conn.id,
        )


# compute_builtin_profiles and compute_balanced_profile removed in M5:
# built-in profiles were already stubs (brief D12); the shim deletion
# removes the last reference path (plan-milestone-5.md).
