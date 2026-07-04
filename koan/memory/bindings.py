# Memory-binding seam for the memory subsystem.
#
# Pure builder API: no module-level globals.
#
#   build_memory_models(config, credential_store) -> MemoryModels
#       Resolve all three memory bindings from config + credentials in one
#       shot.  Returns a frozen MemoryModels bundle.  Called once per run
#       start; the bundle is stored in RunState.memory_models and threaded
#       explicitly to every subsystem that needs it.
#
#   require_memory_model(spec, kind) -> ModelSpec
#       Guard helper: raises RuntimeError if spec is None, otherwise
#       returns the spec unchanged.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..config import KoanConfig
    from ..credentials import CredentialStore

from ..types import CachingPolicy, ModelSpec, ThinkingMode


# ---------------------------------------------------------------------------
# Static Voyage embedding model catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoyageEmbeddingModel:
    """One entry in the koan-owned static Voyage embedding model catalog.

    Carries the set of selectable output dimensions for each recognized
    Voyage embedding model.
    """

    model_id: str
    # Selectable output dimensions (ascending order).
    dimensions: tuple[int, ...]
    default_dimension: int


# Three recognized Voyage embedding models; dimensions ascending, default 1024.
VOYAGE_EMBEDDING_MODELS: dict[str, VoyageEmbeddingModel] = {
    "voyage-4-large": VoyageEmbeddingModel("voyage-4-large", (256, 512, 1024, 2048), 1024),
    "voyage-4":       VoyageEmbeddingModel("voyage-4",       (256, 512, 1024, 2048), 1024),
    "voyage-4-lite":  VoyageEmbeddingModel("voyage-4-lite",  (256, 512, 1024, 2048), 1024),
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
# MemoryModels bundle and pure builder
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryModels:
    """Self-contained per-run memory model bundle.

    Contains only the embedding ModelSpec; its api_key is baked from the
    per-run frozen credential store. LLM tiers (cheap/standard) are resolved
    from frozen_models on RunState, not stored here.
    """

    embedding: ModelSpec | None = None


def build_memory_models(
    config: "KoanConfig",
    credential_store: "CredentialStore | None",
) -> MemoryModels:
    """Build a MemoryModels bundle by resolving only the embedding binding.

    Pure: resolves the embedding binding from explicit config + credential_store,
    never reads a module global. Returns MemoryModels(embedding=None) when
    unconfigured — does NOT raise on missing config so the CLI can call this
    even with no bindings configured.

    The credential_store may be None (degraded boot or keyless provider);
    api_key is None on all specs in that case.

    LLM bindings (memory_llm, reflect_llm) were removed; callers resolve
    cheap/standard from frozen_models (in-run) or directly from the active
    preset's slot assignments (out-of-run).
    """
    if config.memory is None:
        return MemoryModels()

    specs: dict[str, ModelSpec | None] = {}

    for kind in ("embedding",):
        binding = getattr(config.memory, kind, None)
        if binding is None:
            specs[kind] = None
            continue

        cm_id = binding.configured_model_id
        cm = next((c for c in config.configured_models if c.id == cm_id), None)
        if cm is None:
            specs[kind] = None
            continue

        conn_id = cm.connection_id
        conn = next((c for c in config.connections if c.id == conn_id), None)
        if conn is None:
            specs[kind] = None
            continue

        api_key = (
            credential_store.resolve(conn.id)
            if credential_store and conn.id
            else None
        )

        if kind == "embedding":
            # Build ModelSpec directly for embedding: voyage embedding models are
            # not in the capability recognition table so build_resolved_model would
            # emit spurious 'unrecognized model id' warnings for every embed call.
            embedding_dim: int | None = None
            if conn.type == "voyage" and is_recognized_voyage_model(cm.model_id):
                embedding_dim = resolve_voyage_embedding_dim(cm.model_id, cm.embedding_dim)
            specs[kind] = ModelSpec(
                provider=conn.type,
                model=cm.model_id,
                thinking="disabled",
                settings={},
                caching=binding.caching,
                connection_id=conn.id,
                base_url=conn.base_url,
                region=conn.region,
                embedding_dim=embedding_dim,
                api_key=api_key,
            )

    return MemoryModels(embedding=specs.get("embedding"))


def require_memory_model(spec: "ModelSpec | None", kind: str) -> "ModelSpec":
    """Return spec when non-None; otherwise raise RuntimeError.

    Preserves today's error contract at point of use: callers that need a
    specific binding call this and get a clear error when unconfigured.
    """
    if spec is None:
        raise RuntimeError(
            f"Memory binding {kind!r} is not configured. "
            f"Add the binding to the 'memory:' block in ~/.koan/config.yaml."
        )
    return spec


