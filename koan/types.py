# Shared type literals and constants for the koan orchestrator.
# Python port of src/planner/types.ts -- kept in sync manually.

from dataclasses import dataclass, field
from typing import Literal

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

ThinkingMode = Literal["disabled", "low", "medium", "high", "xhigh", "max"]


# ModelInfo removed in M4: the CLI binary probe that populated it is deleted.
# The all-providers model catalog uses ModelRegistryEntry (koan/types.py) and
# koan/agents/model_catalog.py instead.


# -- Provider availability and model registry (M2) ----------------------------
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


@dataclass
class ModelRegistryEntry:
    """One entry in the all-providers model catalog, surfaced via Settings projection.

    Describes a curated (provider, model) pair with capability annotations.
    Sources: model lists from genai-prices bundled snapshot; thinking_modes and
    tier_hint from the koan capability table in model_catalog.py.
    """

    provider: str
    model: str
    display_name: str
    thinking_modes: list[ThinkingMode] = field(default_factory=list)
    tier_hint: ModelTier | None = None


@dataclass
class ProviderModel:
    """One entry in the per-provider dynamic model overlay, retrieved live.

    Lighter sibling of ModelRegistryEntry: no thinking_modes or tier_hint because
    these models are not in the static catalog. Surfaced via Settings.provider_models
    (projection channel), distinct from the static model_registry.
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

    Used by both workflow agents and the memory subsystem. Built eagerly at run
    start by build_resolved_model (registry.py); capability resolution (thinking
    clamping, caching settings) is baked into 'settings' at construction time so
    no per-spawn capability lookup is needed. base_url, region, and embedding_dim are
    inlined from the Connection/ConfiguredModel at flatten time so the spawn path
    never needs to look up the Connection again.

    api_key is the credential resolved at flatten time from the per-run frozen
    credential store. It is in-memory only and must never be serialized, logged,
    or written to run-config.yaml, subagent task.json, or any projection event.
    """

    provider: str
    model: str
    thinking: ThinkingMode
    settings: dict = field(default_factory=dict)
    caching: CachingPolicy = field(default_factory=CachingPolicy)
    # connection_id is the credential-store key; empty string for legacy paths.
    connection_id: str = ""
    # Inlined endpoint settings from the Connection, set at flatten time.
    base_url: str | None = None
    region: str | None = None
    # Resolved embedding output dimension; None for non-voyage or non-embedding.
    embedding_dim: int | None = None
    # Resolved credential, baked once at flatten time from the per-run frozen
    # credential store. None for keyless providers and test paths.
    api_key: str | None = None


@dataclass(frozen=True)
class ResolvedCapabilities:
    """Resolved per (connection.type, model), read-only, never persisted, never asked (brief D4/D5).

    Assembled from three sources: PydanticAI model profile (thinking-shape, web-search,
    tool/json), koan's bundled knowledge (prompt-caching), and the thin recognition parse
    (family/tier/version). Computed on demand; never stored.
    """

    thinking_supported: bool
    thinking_modes: list[ThinkingMode]
    # "budget"   -> discrete token budget (google, older anthropic)
    # "effort"   -> named effort string (openai reasoning)
    # "adaptive" -> anthropic adaptive form (no explicit budget)
    # "none"     -> provider/model has no thinking knob
    thinking_shape: Literal["budget", "effort", "adaptive", "none"]
    supports_web_search: bool
    supports_tools: bool
    supports_prompt_caching: bool
    # From the recognition parse (recognition.py).
    family: str | None = None
    tier_hint: ModelTier | None = None
    version: str | None = None
    # False when the model id is not in the recognition table -- capabilities
    # are still populated but may be less precise (brief D5 graceful fallthrough).
    recognized: bool = True


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
ROLE_CACHE_TIER: dict[SubagentRole, CacheTier] = {
    "intake":       "long",
    "scout":        "short",
    "orchestrator": "long",
    "planner":      "long",
    "executor":     "long",
    "reviewer":     "short",
}


def cache_tier_for_role(role: SubagentRole) -> CacheTier:
    """Single gateway: resolve an agent role to its cache tier; defaults to long.

    Returns 'long' for any unmapped role so new roles are safe by default
    (a long-tier cache write costs more per write but avoids re-encode on
    the next turn, which is the conservative choice for an unknown role).
    """
    return ROLE_CACHE_TIER.get(role, "long")


# -- New config entity types (M1: connection / configured-model / preset) -----
# Placed after the legacy types they coexist with during the shim period.

# ProviderType drives the adapter dialect, the price/capability lookup, and the
# PydanticAI provider class.  Multiple connections of the same type are allowed.
ProviderType = Literal["google", "anthropic", "openai", "bedrock", "openrouter", "voyage"]

# RoleSlot mirrors ModelTier; kept as a separate alias so the intent is explicit.
RoleSlot = Literal["strong", "standard", "cheap"]

ALL_PROVIDER_TYPES: tuple[ProviderType, ...] = (
    "google", "anthropic", "openai", "bedrock", "openrouter", "voyage"
)

# Keyless providers authenticate via a configured base_url rather than a stored
# secret.  Availability is True when a Connection of that type has a base_url.
# Intentionally empty -- lmstudio removed in M3. Retained (not deleted) as the
# keyless-local seam for a future local-provider re-add (Decision 1).
KEYLESS_PROVIDER_TYPES: frozenset[str] = frozenset()


@dataclass
class Connection:
    """One provider connection instance.  Endpoint settings only -- the secret
    lives in the credential store keyed by this connection's id (brief D3).
    """

    id: str
    type: ProviderType
    base_url: str | None = None
    region: str | None = None          # AWS region (bedrock)
    azure_deployment: str | None = None
    api_version: str | None = None
    timeout: float | None = None


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
    """A memory-subsystem model selection (global, not per-preset; brief D9)."""

    configured_model_id: str
    thinking: ThinkingMode = "disabled"
    caching: CachingPolicy = field(default_factory=CachingPolicy)


@dataclass
class MemoryBindings:
    """Global memory model selections; the reranker is coupled to embedding's connection."""

    embedding: MemoryBinding | None = None
    memory_llm: MemoryBinding | None = None
    reflect_llm: MemoryBinding | None = None
