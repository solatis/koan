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
    CachingPolicy,
    ModelSpec,
    ModelTier,
    ThinkingMode,
)
from .base import AgentDiagnostic, AgentError

if TYPE_CHECKING:
    from ..config import KoanConfig
    from ..credentials import CredentialStore
    from ..types import ConfiguredModel, Connection, SubagentRole

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


# -- build_resolved_model ------------------------------------------------------

def build_resolved_model(
    conn: "Connection",
    cm: "ConfiguredModel",
    thinking: ThinkingMode,
    caching: CachingPolicy,
    embedding_dim: "int | None",
    api_key: "str | None",
) -> ModelSpec:
    """Build a fully resolved ModelSpec from a Connection + ConfiguredModel.

    Calls resolve_capabilities once to clamp thinking to what the model
    supports and to compute caching settings. The resolved thinking + caching
    settings are baked into ModelSpec.settings so no per-spawn capability
    lookup is needed. base_url, region, embedding_dim, and api_key are inlined
    from the Connection, ConfiguredModel, and credential store at flatten time.

    api_key is the credential baked in at flatten time from the caller's
    credential store. It is in-memory only and must never be serialized.

    This is the single flatten function: called by resolve_model_spec (per-role
    agent resolution) and by build_memory_models / api_start_run's eager-flatten
    for tier slots.
    """
    from .adapter import _caching_settings, map_thinking
    from .capability_resolver import resolve_capabilities

    caps = resolve_capabilities(conn.type, cm.model_id)
    clamped = _best_supported_thinking(frozenset(caps.thinking_modes), thinking)
    if clamped != thinking:
        log.info(
            "thinking mode clamped for model '%s': requested '%s' -> supported '%s'",
            cm.model_id, thinking, clamped,
        )

    # Bake thinking + caching settings once so build_model_settings is trivial.
    settings: dict = {}
    settings.update(map_thinking(conn.type, caps, clamped))
    settings.update(_caching_settings(caching, caps))

    return ModelSpec(
        provider=conn.type,
        model=cm.model_id,
        thinking=clamped,
        settings=settings,
        caching=caching,
        connection_id=conn.id,
        base_url=conn.base_url,
        region=conn.region,
        embedding_dim=embedding_dim,
        api_key=api_key,
    )


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
        credential_store: "CredentialStore | None",
    ) -> ModelSpec:
        """Resolve a ModelSpec for a role via the active preset's slot mapping.

        Maps role -> ModelTier slot -> SlotAssignment -> ConfiguredModel ->
        Connection -> ModelSpec via build_resolved_model.  Raises
        AgentError(code='unconfigured') when the active preset, the slot
        assignment, the ConfiguredModel, or the Connection is missing.  No
        default model is ever substituted (brief D12).

        credential_store is used to resolve the api_key baked into the returned
        ModelSpec at flatten time. Pass None for keyless providers or test paths.
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

        api_key = (
            credential_store.resolve(conn.id)
            if (credential_store and conn.id)
            else None
        )
        return build_resolved_model(conn, cm, slot.thinking, slot.caching, cm.embedding_dim, api_key)


# compute_builtin_profiles and compute_balanced_profile removed in M5:
# built-in profiles were already stubs (brief D12); the shim deletion
# removes the last reference path (plan-milestone-5.md).
