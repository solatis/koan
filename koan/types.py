# Shared type literals and constants for the koan orchestrator.
# Python port of src/planner/types.ts -- kept in sync manually.

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from koan.models.offering import Offering
WorkflowPhase = Literal[
    # Final 8-phase set (brief 5.4, M6 cutover).
    # M1: legacy literals removed (plan-spec, milestone-spec, tech-plan-spec,
    # execution, implementation-validation, ticket-breakdown,
    # cross-artifact-validation).
    # M6: *-review literals removed (plan-review, milestone-review,
    # tech-plan-review, exec-review) -- collapsed into the mechanical reviewer
    # (M3) and inline execute review (M5).
    "intake",
    "core-flows",
    "tech-plan",
    "milestone",
    "plan",
    "execute",
    "curation",
    "frame",
]

SubagentRole = Literal[
    "intake",
    "scout",
    "orchestrator",
    "planner",
    "executor",
    "reviewer",
]

ModelTier = Literal["strong", "standard", "cheap"]

# Two-level cache duration classification used to select provider TTLs.
# short = agents that complete quickly (reviewers, scouts);
# long = agents that may wait between turns (orchestrator, executor).
CacheTier = Literal["short", "long"]

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

ThinkingMode = Literal["disabled", "minimal", "low", "medium", "high", "xhigh"]


# ModelInfo removed in M4: the CLI binary probe that populated it is deleted.
# The all-providers model catalog is the curated _BASE_CATALOG in
# koan/models/capabilities.py (M2: ModelRegistryEntry deleted; offerings are
# computed from the catalog via settings_listed).


# -- Provider availability (M2) -----------------------------------------------
# Defined before ProfileTier (book order: dependencies before use).


@dataclass
class ConnectionStatus:
    """Per-connection availability, replacing the legacy per-type ProviderStatus (M5).

    Keyed by connection_id so multiple connections of the same type (e.g. two
    anthropic accounts) are distinguished independently.  connection_type is
    included for display grouping without a config lookup.
    """

    connection_id: str
    connection_type: str
    available: bool


# ModelRegistryEntry removed in M2: the model_registry_listed event was
# absorbed into settings_listed; offerings_by_connection is computed from the
# curated catalog (koan.models.capabilities._BASE_CATALOG), not from a registry.


@dataclass
class ProviderModel:
    """One entry in the per-connection dynamic model overlay, retrieved live.

    Returned by list_provider_models for the connection Test endpoint
    (api_config_connection_list_models). Not projected to the frontend; the
    projection uses offerings_by_connection from the curated catalog instead.
    """

    provider: str
    model: str
    display_name: str




# -- Provider config types (M1: config schema reshape) ------------------------
# Defined before ProfileTier (book order: dependencies before use).


@dataclass
class CachingPolicy:
    """Per-provider caching on/off switch resolved by the adapter into request settings.

    Carries only the mode (auto/off) axis -- the orthogonal duration axis
    (short/long cache tier) is derived from the agent role at flatten time
    and is no longer user-configurable here.  mode is load-bearing for the
    cache guard (cache_guard.py) and the adapter (_caching_settings).
    """

    mode: Literal["auto", "off"] = "auto"


@dataclass
class ModelSpec:
    """Unified denormalized resolved-model construct for one provider+model selection.

    M2: carries the Offering object (route, wire_id, ref, caps, price, locality) plus
    delegating provider/model properties so existing call sites compile unchanged. Thinking
    and caching settings are baked into 'settings' at construction time via the dialects
    module. base_url and embedding_dim are inlined from the Connection/ConfiguredModel at
    flatten time. region is no longer stored -- the offering carries locality.

    api_key is the credential resolved at flatten time from the per-run frozen
    credential store. It is in-memory only and must never be serialized, logged,
    or written to run-config.yaml, subagent task.json, or any projection event.
    """

    # The resolved Offering from koan.models.offering. Set at flatten time by
    # build_resolved_model. Carries route, wire_id, ref, caps, price, locality.
    offering: Any = field(default=None)  # Offering from koan.models.offering
    thinking: ThinkingMode = "disabled"
    settings: dict = field(default_factory=dict)
    caching: CachingPolicy = field(default_factory=CachingPolicy)
    # connection_id is the credential-store key; empty string for legacy paths.
    connection_id: str = ""
    # Inlined endpoint settings from the Connection, set at flatten time.
    base_url: str | None = None
    # Resolved embedding output dimension; None for non-embedding models.
    embedding_dim: int | None = None
    # Resolved credential, baked once at flatten time from the per-run frozen
    # credential store. None for keyless providers and test paths.
    api_key: str | None = None

    @property
    def provider(self) -> str:
        """Route id from the offering (delegating property for backward compat)."""
        return self.offering.route.id if self.offering else ""

    @property
    def model(self) -> str:
        """Wire id from the offering (delegating property for backward compat)."""
        return self.offering.wire_id if self.offering else ""

    @property
    def cache_expectation(self) -> str:
        """Cache expectation consistent with emit_cache_settings' actual output.

        Returns 'explicit', 'automatic', or 'none'.  When the route dialect has no
        _CACHE_TIER_TTL entry (google-genai, openai-chat, voyage-embeddings),
        emit_cache_settings returns {} regardless of caps.prompt_caching, so this
        property also returns 'none' to stay consistent.  Read by the cache guard
        (cache_guard.py) instead of the deleted cache_read_expected function.
        """
        if self.offering is None:
            return "none"
        pc = self.offering.caps.prompt_caching
        if pc == "none":
            return "none"
        # Lazy import: koan.types is imported by koan.agents.base, so a module-level
        # import would cycle. _CACHE_TIER_TTL is the authoritative set of dialects
        # for which flatten emits cache settings (emit_cache_settings returns {} for
        # dialects not in this map), so cache_expectation must mirror that gate.
        from koan.agents.dialects import _CACHE_TIER_TTL
        if self.offering.route.dialect not in _CACHE_TIER_TTL:
            return "none"
        return pc


# ResolvedCapabilities removed in M2: superseded by Capabilities in koan/models/capabilities.py.
# All capability facts now come from offering.caps (the merged, provenance-carrying record).


# ProviderAuth, Profile, ProfileTier, BUILTIN_PROFILE_NAMES removed in M5:
# the boundary-translation shim is deleted; all config reads use the new
# connections/presets schema directly (brief D8, plan-milestone-5.md).
# AgentInstallation removed in M4: the legacy CLI/SDK agent path is deleted.


ROLE_MODEL_TIER: dict[SubagentRole, ModelTier] = {
    "intake": "strong",
    "scout": "cheap",
    "orchestrator": "strong",
    "planner": "strong",
    "executor": "standard",
    # Reviewer runs at the strong tier: review-finding quality gates whether
    # defects reach execution, so the same quality bar as the orchestrator applies.
    "reviewer": "strong",
}

# ROLE_EFFORT removed in M4: superseded by the provider adapter's per-provider
# thinking mapping. Only ROLE_MODEL_TIER (above) remains for tier resolution.

# Single role -> cache-duration policy: short = agents that never trigger a
# long-running operation (reviews, exploration); long = everything else.
# intake/planner are not spawned as subagents but are included for total
# type coverage and are default-aligned (long).
# Keyed `str` (not SubagentRole) to match cache_tier_for_role's defensive
# contract: unknown roles look up cleanly and default to "long".
ROLE_CACHE_TIER: dict[str, CacheTier] = {
    "intake":       "long",
    "scout":        "short",
    "orchestrator": "long",
    "planner":      "long",
    "executor":     "long",
    "reviewer":     "short",
}


def cache_tier_for_role(role: str) -> CacheTier:
    """Single gateway: resolve an agent role to its cache tier; defaults to long.

    `role` is deliberately `str`, not SubagentRole: the documented contract
    below accepts unmapped/future roles and defaults them -- a Literal would
    contradict it.

    Returns 'long' for any unmapped role so new roles are safe by default
    (a long-tier cache write costs more per write but avoids re-encode on
    the next turn, which is the conservative choice for an unknown role).
    """
    return ROLE_CACHE_TIER.get(role, "long")


# -- New config entity types (M1: connection / configured-model / preset) -----
# Placed after the legacy types they coexist with during the shim period.

# ProviderType removed in M2: superseded by route ids from koan.models.routes.
# Connection.type now holds a route id string (e.g. "anthropic", "bedrock-converse").

# RoleSlot mirrors ModelTier; kept as a separate alias so the intent is explicit.
RoleSlot = Literal["strong", "standard", "cheap"]

# ALL_PROVIDER_TYPES removed in M2: route ids come from koan.models.routes.route_ids().

# Keyless providers authenticate via a configured base_url rather than a stored
# secret.  Availability is True when a Connection of that type has a base_url.
# Intentionally empty -- lmstudio removed in M3. Retained (not deleted) as the
# keyless-local seam for a future local-provider re-add (Decision 1).
KEYLESS_PROVIDER_TYPES: frozenset[str] = frozenset()


@dataclass
class Connection:
    """One provider connection instance.  Endpoint settings only -- the secret
    lives in the credential store keyed by this connection's id (brief D3).

    M2: type holds a route id (e.g. "anthropic", "bedrock-converse"); locality
    replaces the old region field. Dead fields (azure_deployment, api_version,
    timeout) are removed.
    """

    id: str
    type: str  # route id from koan.models.routes
    base_url: str | None = None
    # Geo/region locality for this connection (e.g. 'eu' for bedrock-converse).
    # Replaces the old region field.
    locality: str | None = None


@dataclass
class ConfiguredModel:
    """A (connection, model-id) pair -- a model reached through a specific connection.

    Global; referenced by slots and memory bindings.  The same model_id on two
    connections is two distinct ConfiguredModels (brief D3).
    """

    id: str
    connection_id: str
    model_id: str
    # newest-in-family provenance written at config-time (brief D11).
    resolved_from: str | None = None
    # Selected Voyage output dimension; None means use the model default from the
    # static catalog.  Relevant only for voyage embedding models; None for all others.
    embedding_dim: int | None = None


@dataclass
class SlotAssignment:
    """Fills one role slot inside a preset: a model reference plus chosen settings."""

    configured_model_id: str
    thinking: ThinkingMode
    caching: CachingPolicy = field(default_factory=CachingPolicy)


@dataclass
class Preset:
    """A bundle of slot assignments.

    Today only the reserved '$last' preset exists; named presets are a future,
    additive concern (brief D7).
    """

    slots: dict[RoleSlot, SlotAssignment] = field(default_factory=dict)


@dataclass
class MemoryBinding:
    """A memory-subsystem model selection (global, not per-preset; brief D9).

    Contains only configured_model_id and caching. The thinking field was
    removed because the only active binding is embedding, where thinking is
    meaningless (initiative: remove dedicated memory LLM bindings).
    """

    configured_model_id: str
    caching: CachingPolicy = field(default_factory=CachingPolicy)


@dataclass
class MemoryBindings:
    """Global memory model selections. Today only the embedding binding is
    configured here; memory_llm and reflect_llm were removed — LLM tiers
    now resolve from the active preset's cheap/standard slots.
    """

    embedding: MemoryBinding | None = None
