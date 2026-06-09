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


@dataclass(frozen=True)
class ResolvedMemoryModel:
    """Resolved provider + model + credential for one memory binding.

    Produced by resolve_memory_binding; consumed by memory LLM and
    embedding/rerank callers.  Never persisted -- exists only for the
    duration of a model-build or embed call.

    api_key may be None for keyless providers (lmstudio) or when no
    credential is stored for the connection.
    """

    provider_type: str
    model_id: str
    api_key: str | None
    base_url: str | None
    region: str | None


# Known embedding model dimensions: (provider_type, model_id) -> dim.
# Changing the embedding model requires a manual vector-store rebuild
# (the dimension is baked into the LanceDB schema; no auto re-index, brief D10).
# Seed: voyage-4-large is the default embedding model (1024 dimensions).
EMBEDDING_DIMS: dict[tuple[str, str], int] = {
    ("voyage", "voyage-4-large"): 1024,
}


def embedding_dim_for(provider_type: str, model_id: str) -> int:
    """Return the embedding dimension for a known (provider_type, model_id) pair.

    Raises ValueError for an unknown pair.  Changing the embedding model
    requires a manual vector-store rebuild since the dimension is baked into
    the LanceDB schema; do NOT build re-index machinery (brief D10).
    To add a new model, extend EMBEDDING_DIMS.
    """
    dim = EMBEDDING_DIMS.get((provider_type, model_id))
    if dim is None:
        raise ValueError(
            f"Unknown embedding dimension for provider={provider_type!r} "
            f"model={model_id!r}. "
            f"Known pairs: {sorted(EMBEDDING_DIMS)}. "
            "Add the (provider_type, model_id) -> dim entry to EMBEDDING_DIMS "
            "and rebuild the vector store manually."
        )
    return dim


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

    api_key = active_credential_store().resolve(connection.id)
    return ResolvedMemoryModel(
        provider_type=connection.type,
        model_id=cm.model_id,
        api_key=api_key,
        base_url=connection.base_url,
        region=connection.region,
    )
