# Memory-binding seam for the memory subsystem.
#
# The memory subsystem has no app_state; it uses module-level active stores.
# This module provides a parallel active-provider-config seam (set once at
# process startup, parallel to set_active_credential_store in credentials.py)
# and a resolver that maps a MemoryBinding -> configured model -> connection ->
# credential (by connection id).
#
# Entrypoints (cli/run.py and cli/memory.py) must call set_active_provider_config
# right after set_active_credential_store so all memory operations can resolve
# their models from config.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..config import KoanConfig

from ..credentials import active_credential_store

_ACTIVE_CONFIG: "KoanConfig | None" = None


def set_active_provider_config(config: "KoanConfig") -> None:
    """Set the process-wide active provider config for the memory subsystem.

    Called once per process entrypoint (cli/run.py, cli/memory.py) right
    after set_active_credential_store.  Without this call, any memory
    operation that resolves a model binding raises RuntimeError.
    """
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = config


def _active_config() -> "KoanConfig":
    """Return the active provider config, raising RuntimeError if unset.

    Mirrors active_credential_store() -- intentionally early and loud so
    misconfigured startup is caught at the first operation that needs it.
    """
    if _ACTIVE_CONFIG is None:
        raise RuntimeError(
            "Active provider config is not initialized. "
            "Call set_active_provider_config() at process startup before "
            "using any memory or provider operations."
        )
    return _ACTIVE_CONFIG


# ---------------------------------------------------------------------------
# Static Voyage embedding model catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VoyageEmbeddingModel:
    """One entry in the koan-owned static Voyage embedding model catalog.

    Carries the fixed context window and the set of selectable output
    dimensions for each recognized Voyage embedding model.  All three
    current models share the same dimension options and default.
    """

    model_id: str
    context_window: int
    # Selectable output dimensions (ascending order).
    dimensions: tuple[int, ...]
    default_dimension: int


# Three recognized Voyage embedding models; dimensions ascending, default 1024.
# Context window is 32,000 tokens for all three (display/metadata only;
# Voyage truncates server-side via embed(truncation=True)).
VOYAGE_EMBEDDING_MODELS: dict[str, VoyageEmbeddingModel] = {
    "voyage-4-large": VoyageEmbeddingModel("voyage-4-large", 32_000, (256, 512, 1024, 2048), 1024),
    "voyage-4":       VoyageEmbeddingModel("voyage-4",       32_000, (256, 512, 1024, 2048), 1024),
    "voyage-4-lite":  VoyageEmbeddingModel("voyage-4-lite",  32_000, (256, 512, 1024, 2048), 1024),
}


def voyage_embedding_models() -> list[VoyageEmbeddingModel]:
    """Return the catalog values; used by the projection surface and the whitelist."""
    return list(VOYAGE_EMBEDDING_MODELS.values())


def is_recognized_voyage_model(model_id: str) -> bool:
    """Return True when model_id is in the recognized Voyage embedding catalog."""
    return model_id in VOYAGE_EMBEDDING_MODELS


def voyage_dimension_options(model_id: str) -> tuple[int, ...]:
    """Return the selectable output dimensions for a recognized Voyage embedding model.

    Raises ValueError for an unrecognized model_id.
    """
    entry = VOYAGE_EMBEDDING_MODELS.get(model_id)
    if entry is None:
        raise ValueError(
            f"Unrecognized Voyage embedding model: {model_id!r}. "
            f"Known models: {sorted(VOYAGE_EMBEDDING_MODELS)}."
        )
    return entry.dimensions


def resolve_voyage_embedding_dim(model_id: str, selected: int | None) -> int:
    """Resolve the effective output dimension for a Voyage embedding model.

    If selected is None, returns the model's default_dimension.
    If selected is in the model's dimensions tuple, returns it.
    Raises ValueError when model_id is unrecognized or selected is not a valid option.
    """
    entry = VOYAGE_EMBEDDING_MODELS.get(model_id)
    if entry is None:
        raise ValueError(
            f"Unrecognized Voyage embedding model: {model_id!r}. "
            f"Known models: {sorted(VOYAGE_EMBEDDING_MODELS)}."
        )
    if selected is None:
        return entry.default_dimension
    if selected not in entry.dimensions:
        raise ValueError(
            f"Invalid embedding dimension {selected} for model {model_id!r}. "
            f"Valid options: {entry.dimensions}."
        )
    return selected


# ---------------------------------------------------------------------------
# Resolved memory model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedMemoryModel:
    """Resolved provider + model + credential for one memory binding.

    Produced by resolve_memory_binding; consumed by memory LLM and
    embedding/rerank callers.  Never persisted -- exists only for the
    duration of a model-build or embed call.

    api_key may be None for keyless providers (lmstudio) or when no
    credential is stored for the connection.

    embedding_dim is set for voyage embedding bindings (the resolved output
    dimension, accounting for the user-selected override and the model
    default).  None for all non-embedding or non-voyage bindings.
    """

    provider_type: str
    model_id: str
    api_key: str | None
    base_url: str | None
    region: str | None
    # Resolved embedding output dimension; None for non-voyage or non-embedding.
    embedding_dim: int | None = None


def resolve_memory_binding(
    kind: Literal["embedding", "memory_llm", "reflect_llm"]
) -> ResolvedMemoryModel:
    """Resolve a named memory binding to a provider + model + credential.

    Reads the active provider config (set_active_provider_config must have
    been called at startup).  Resolution chain:

        config.memory.<kind>.configured_model_id
          -> config.configured_models (by id) -> connection_id
          -> config.connections (by id)
          -> active_credential_store().resolve(connection.id) -> api_key

    For voyage embedding bindings, also resolves embedding_dim from the
    model's optional embedding_dim override and the catalog default.

    Raises RuntimeError with a clear message when:
      - The active config is not set
      - config.memory is absent or the binding for <kind> is unset
      - The referenced configured_model_id is not in config.configured_models
      - The referenced connection_id is not in config.connections

    Returns a ResolvedMemoryModel with api_key=None when no credential is
    stored for the connection (caller decides whether that is an error).
    """
    config = _active_config()

    if config.memory is None:
        raise RuntimeError(
            f"Memory binding {kind!r} is not configured: config.memory is absent. "
            "Add a 'memory:' block to ~/.koan/config.yaml."
        )

    binding = getattr(config.memory, kind, None)
    if binding is None:
        raise RuntimeError(
            f"Memory binding {kind!r} is not configured in config.memory. "
            "Add the binding to the 'memory:' block in ~/.koan/config.yaml."
        )

    cm_id = binding.configured_model_id
    cm = next(
        (c for c in config.configured_models if c.id == cm_id),
        None,
    )
    if cm is None:
        raise RuntimeError(
            f"Memory binding {kind!r} references configured_model_id={cm_id!r} "
            "which is not in config.configured_models."
        )

    conn_id = cm.connection_id
    connection = next(
        (c for c in config.connections if c.id == conn_id),
        None,
    )
    if connection is None:
        raise RuntimeError(
            f"Memory binding {kind!r} -> configured_model {cm_id!r} "
            f"references connection_id={conn_id!r} which is not in config.connections."
        )

    # Resolve the embedding dimension for voyage embedding bindings.
    # Non-voyage and non-embedding bindings carry embedding_dim=None.
    embedding_dim: int | None = None
    if kind == "embedding" and connection.type == "voyage":
        selected = getattr(cm, "embedding_dim", None)
        if is_recognized_voyage_model(cm.model_id):
            embedding_dim = resolve_voyage_embedding_dim(cm.model_id, selected)

    api_key = active_credential_store().resolve(connection.id)
    return ResolvedMemoryModel(
        provider_type=connection.type,
        model_id=cm.model_id,
        api_key=api_key,
        base_url=connection.base_url,
        region=connection.region,
        embedding_dim=embedding_dim,
    )
