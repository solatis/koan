# AgentRegistry -- maps agent types to Agent instances and resolves
# agent configuration (model spec) for a role.
# Replaces koan/runners/registry.py; the runner-level types (RunnerRegistry,
# compute_balanced_profile, compute_builtin_profiles) move here.
#
# M1: resolve_model_spec rewritten to resolve role -> slot -> configured model
# -> connection into a ModelSpec.  Built-in Gemini profile constants and
# compute_builtin_profiles static profiles removed (brief D12 -- koan ships
# no default models; unconfigured state fails fast with a clear error).
# M2: build_resolved_model uses resolve_offering + dialects; thinking clamping
# deleted (D4: substrate thinking vocabulary, substrate budget values).

from __future__ import annotations


from ..logger import get_logger
from ..types import (
    ROLE_MODEL_TIER,
    CacheTier,
    CachingPolicy,
    ModelSpec,
    ThinkingMode,
    cache_tier_for_role,
)
from .base import AgentDiagnostic, AgentError

from ..config import KoanConfig
from ..credentials import CredentialStore
from ..types import ConfiguredModel, Connection, SubagentRole
log = get_logger("agent_registry")


# -- build_resolved_model ------------------------------------------------------

def build_resolved_model(
    conn: Connection,
    cm: ConfiguredModel,
    thinking: ThinkingMode,
    caching: CachingPolicy,
    embedding_dim: int | None,
    api_key: str | None,
    cache_tier: CacheTier = "long",
) -> ModelSpec:
    """Build a fully resolved ModelSpec from a Connection + ConfiguredModel.

    M2: resolves an Offering via resolve_offering (the models package), then bakes
    thinking + caching settings via the dialects module. The offering carries
    the route, wire_id, ref, caps, price, and locality. provider/model are
    delegating properties on ModelSpec (offering.route.id / offering.wire_id).

    Thinking mode is passed through to pydantic-ai's unified ``thinking`` setting
    via ``apply_thinking`` -- koan no longer clamps to what the model supports
    (D4). Cache settings are emitted via ``emit_cache_settings`` which dispatches
    on the route's dialect. The resolved max_tokens output budget comes from
    ``offering.caps.max_output``.

    cache_tier is the koan-level cache duration class (default 'long'), selected
    by the caller from the agent role via cache_tier_for_role or set explicitly
    for memory LLM operations.  It is resolved here once and baked into settings,
    preserving the byte-stable cacheable-prefix invariant (the class must not
    change between turns).

    api_key is the credential baked in at flatten time from the caller's
    credential store. It is in-memory only and must never be serialized.

    This is the single flatten function: called by resolve_model_spec (per-role
    agent resolution) and by build_memory_models / api_start_run's eager-flatten
    for tier slots.
    """
    from koan.agents.dialects import apply_thinking, emit_cache_settings, emit_reasoning_off
    from koan.models.offering import resolve_offering

    offering = resolve_offering(conn.type, cm.model_id)

    settings: dict = {}
    settings.update(apply_thinking(thinking))
    settings.update(emit_reasoning_off(offering.route.id, thinking))
    if caching.mode != "off":
        settings.update(emit_cache_settings(offering.route.dialect, offering.caps, cache_tier))
    settings["max_tokens"] = offering.caps.max_output

    return ModelSpec(
        offering=offering,
        thinking=thinking,
        settings=settings,
        caching=caching,
        connection_id=conn.id,
        base_url=conn.base_url,
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
        role: SubagentRole,
        config: KoanConfig,
        credential_store: CredentialStore | None,
    ) -> ModelSpec:
        """Resolve a ModelSpec for a role via the active preset's slot mapping.

        Maps role -> ModelTier slot -> SlotAssignment -> ConfiguredModel ->
        Connection -> ModelSpec via build_resolved_model.  Raises
        AgentError(code='unconfigured') when the active preset, the slot
        assignment, the ConfiguredModel, or the Connection is missing.  No
        default model is ever substituted (brief D12).

        The cache tier is derived from the role via cache_tier_for_role
        (orthogonal to the model tier from ROLE_MODEL_TIER): orchestrator and
        executor are 'long'; reviewer and scout are 'short'.

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
        return build_resolved_model(
            conn, cm, slot.thinking, slot.caching, cm.embedding_dim, api_key,
            cache_tier=cache_tier_for_role(role),
        )


# compute_builtin_profiles and compute_balanced_profile removed in M5:
# built-in profiles were already stubs (brief D12); the shim deletion
# removes the last reference path (plan-milestone-5.md).