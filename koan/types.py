# Shared type literals and constants for the koan orchestrator.
# Python port of src/planner/types.ts -- kept in sync manually.

from dataclasses import dataclass, field
from typing import Literal

WorkflowPhase = Literal[
    # Active workflow phases
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
    # M4: legacy phase literals kept to avoid breaking state.py WorkflowPhase
    # annotation until the phase taxonomy is revisited in M6/M7.
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
    Sources: model lists and context_window from genai-prices bundled snapshot;
    thinking_modes and tier_hint from the koan capability table in model_catalog.py.
    """

    provider: str
    model: str
    display_name: str
    context_window: int
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
    context_window: int = 0


# -- Provider config types (M1: config schema reshape) ------------------------
# Defined before ProfileTier (book order: dependencies before use).


@dataclass
class CachingPolicy:
    """Per-provider caching directives resolved by the adapter into request settings."""

    mode: Literal["auto", "off"] = "auto"
    ttl: Literal["5m", "1h"] = "5m"


@dataclass
class ModelSpec:
    """Resolved provider+model+settings for one role's model selection.

    connection_id (M1) is set by resolve_model_spec so the adapter can resolve
    credentials by connection rather than by provider type.
    """

    provider: str
    model: str
    thinking: ThinkingMode
    settings: dict = field(default_factory=dict)
    caching: CachingPolicy = field(default_factory=CachingPolicy)
    context_window: int = 0
    # M1: connection id for credential lookup (empty string for legacy callers).
    connection_id: str = ""


@dataclass(frozen=True)
class ResolvedCapabilities:
    """Resolved per (connection.type, model), read-only, never persisted, never asked (brief D4/D5).

    Assembled from three sources: PydanticAI model profile (thinking-shape, web-search,
    tool/json), koan's bundled knowledge (context-window, variants, prompt-caching), and
    the thin recognition parse (family/tier/version).  Computed on demand; never stored.
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
    # koan-sourced -- the model engine carries neither of these.
    context_window: int
    supports_prompt_caching: bool
    # Selectable larger windows beyond the base (e.g. the Anthropic 1M beta).
    # Empty when no variant is available for this (provider, model).
    context_window_variants: list[int] = field(default_factory=list)
    # Embedding models only; None for chat/completion models.
    embedding_dim: int | None = None
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
}

# ROLE_EFFORT removed in M4: superseded by the provider adapter's per-provider
# thinking mapping. Only ROLE_MODEL_TIER (above) remains for tier resolution.


# -- New config entity types (M1: connection / configured-model / preset) -----
# Placed after the legacy types they coexist with during the shim period.

# ProviderType drives the adapter dialect, the price/capability lookup, and the
# PydanticAI provider class.  Multiple connections of the same type are allowed.
ProviderType = Literal["google", "anthropic", "openai", "bedrock", "lmstudio", "voyage"]

# RoleSlot mirrors ModelTier; kept as a separate alias so the intent is explicit.
RoleSlot = Literal["strong", "standard", "cheap"]

ALL_PROVIDER_TYPES: tuple[ProviderType, ...] = (
    "google", "anthropic", "openai", "bedrock", "lmstudio", "voyage"
)

# Keyless providers authenticate via a configured base_url rather than a stored
# secret.  Availability is True when a Connection of that type has a base_url.
KEYLESS_PROVIDER_TYPES: frozenset[str] = frozenset({"lmstudio"})


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


@dataclass
class SlotAssignment:
    """Fills one role slot inside a preset: a model reference plus chosen settings."""

    configured_model_id: str
    thinking: ThinkingMode
    caching: CachingPolicy = field(default_factory=CachingPolicy)
    # Selected context-window variant (None = use base window from capabilities).
    context_window: int | None = None


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
    context_window: int | None = None


@dataclass
class MemoryBindings:
    """Global memory model selections; the reranker is coupled to embedding's connection."""

    embedding: MemoryBinding | None = None
    memory_llm: MemoryBinding | None = None
    reflect_llm: MemoryBinding | None = None
