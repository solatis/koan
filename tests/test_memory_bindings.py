# Unit tests for koan.memory.bindings: Voyage embedding catalog, build_memory_models,
# require_memory_model, and the resolver helpers.
#
# Hard cutover: EMBEDDING_DIMS and embedding_dim_for were removed and replaced by
# the VoyageEmbeddingModel catalog.  ResolvedMemoryModel was removed and replaced
# by ModelSpec (unified resolved construct).  resolve_memory_binding and
# set_active_provider_config will be deleted in Step 19 (de-globalization).
#
# This file covers the new pure API: build_memory_models and require_memory_model,
# plus the catalog helpers (unchanged).  Negative-presence tests guard against
# accidental re-introduction of removed symbols.

from __future__ import annotations

import pytest

from koan.config import KoanConfig
from koan.credentials import CredentialStore, FileKeyBackend
from koan.memory.bindings import (
    VOYAGE_EMBEDDING_MODELS,
    VoyageEmbeddingModel,
    build_memory_models,
    is_recognized_voyage_model,
    require_memory_model,
    resolve_voyage_embedding_dim,
    voyage_dimension_options,
    voyage_embedding_models,
)
from koan.types import (
    Connection,
    ConfiguredModel,
    MemoryBinding,
    MemoryBindings,
    ModelSpec,
)


# ---------------------------------------------------------------------------
# Negative-presence test: removed symbols must not exist
# ---------------------------------------------------------------------------

class TestRemovedSymbols:
    def test_embedding_dims_not_exported(self):
        """EMBEDDING_DIMS must not exist in koan.memory.bindings (hard cutover)."""
        import koan.memory.bindings as mod
        assert not hasattr(mod, "EMBEDDING_DIMS"), (
            "EMBEDDING_DIMS was re-introduced; hard cutover requires permanent removal"
        )

    def test_embedding_dim_for_not_exported(self):
        """embedding_dim_for must not exist in koan.memory.bindings (hard cutover)."""
        import koan.memory.bindings as mod
        assert not hasattr(mod, "embedding_dim_for"), (
            "embedding_dim_for was re-introduced; hard cutover requires permanent removal"
        )

    def test_resolved_memory_model_not_exported(self):
        """ResolvedMemoryModel must not exist in koan.memory.bindings (hard cutover)."""
        import koan.memory.bindings as mod
        assert not hasattr(mod, "ResolvedMemoryModel"), (
            "ResolvedMemoryModel was re-introduced; hard cutover requires permanent removal"
        )


# ---------------------------------------------------------------------------
# VoyageEmbeddingModel catalog
# ---------------------------------------------------------------------------

class TestVoyageEmbeddingCatalog:
    def test_catalog_contains_exactly_three_models(self):
        """VOYAGE_EMBEDDING_MODELS has exactly the three whitelisted models."""
        assert set(VOYAGE_EMBEDDING_MODELS) == {"voyage-4-large", "voyage-4", "voyage-4-lite"}

    def test_each_model_is_voyage_embedding_model_instance(self):
        """Every entry in VOYAGE_EMBEDDING_MODELS is a VoyageEmbeddingModel."""
        for entry in VOYAGE_EMBEDDING_MODELS.values():
            assert isinstance(entry, VoyageEmbeddingModel)

    def test_each_model_default_dimension_is_1024(self):
        for entry in VOYAGE_EMBEDDING_MODELS.values():
            assert entry.default_dimension == 1024

    def test_each_model_dimensions_include_256_512_1024_2048(self):
        for entry in VOYAGE_EMBEDDING_MODELS.values():
            assert set(entry.dimensions) == {256, 512, 1024, 2048}

    def test_voyage_embedding_models_helper_returns_all(self):
        assert set(voyage_embedding_models()) == set(VOYAGE_EMBEDDING_MODELS.values())


# ---------------------------------------------------------------------------
# is_recognized_voyage_model
# ---------------------------------------------------------------------------

class TestIsRecognizedVoyageModel:
    @pytest.mark.parametrize("model_id", ["voyage-4-large", "voyage-4", "voyage-4-lite"])
    def test_recognized_models_return_true(self, model_id):
        assert is_recognized_voyage_model(model_id) is True

    @pytest.mark.parametrize("model_id", [
        "voyage-unknown",
        "voyage-3",
        "voyage-4-pro",
        "text-embedding-3-small",
        "",
        "VOYAGE-4-LARGE",
    ])
    def test_unrecognized_models_return_false(self, model_id):
        assert is_recognized_voyage_model(model_id) is False


# ---------------------------------------------------------------------------
# voyage_dimension_options
# ---------------------------------------------------------------------------

class TestVoyageDimensionOptions:
    def test_returns_tuple_of_valid_dims(self):
        opts = voyage_dimension_options("voyage-4-large")
        assert 256 in opts
        assert 512 in opts
        assert 1024 in opts
        assert 2048 in opts

    def test_raises_for_unrecognized_model(self):
        with pytest.raises(ValueError, match="Unrecognized Voyage embedding model"):
            voyage_dimension_options("voyage-unknown")


# ---------------------------------------------------------------------------
# resolve_voyage_embedding_dim
# ---------------------------------------------------------------------------

class TestResolveVoyageEmbeddingDim:
    def test_none_selected_returns_default(self):
        """None selected -> use the catalog default (1024)."""
        assert resolve_voyage_embedding_dim("voyage-4-large", None) == 1024

    def test_valid_dimension_returned_unchanged(self):
        assert resolve_voyage_embedding_dim("voyage-4-large", 256) == 256
        assert resolve_voyage_embedding_dim("voyage-4-large", 512) == 512
        assert resolve_voyage_embedding_dim("voyage-4-large", 2048) == 2048

    def test_invalid_dimension_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid embedding dimension"):
            resolve_voyage_embedding_dim("voyage-4-large", 999)

    def test_unrecognized_model_raises_value_error(self):
        with pytest.raises(ValueError, match="Unrecognized Voyage embedding model"):
            resolve_voyage_embedding_dim("voyage-unknown", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_store(
    koan_home,
    *,
    voyage_key: str | None = "voyage-api-key",
    google_key: str | None = "google-api-key",
    embedding_dim: int | None = None,
) -> tuple[KoanConfig, CredentialStore]:
    """Build a KoanConfig + CredentialStore with voyage + google connections."""
    config = KoanConfig(
        connections=[
            Connection(id="google-1", type="google"),
            Connection(id="voyage-1", type="voyage"),
        ],
        configured_models=[
            ConfiguredModel(id="google-llm", connection_id="google-1", model_id="gemini-flash-lite-latest"),
            ConfiguredModel(id="google-reflect", connection_id="google-1", model_id="gemini-flash-latest"),
            ConfiguredModel(
                id="voyage-embed",
                connection_id="voyage-1",
                model_id="voyage-4-large",
                embedding_dim=embedding_dim,
            ),
        ],
        memory=MemoryBindings(
            embedding=MemoryBinding(configured_model_id="voyage-embed"),
            memory_llm=MemoryBinding(configured_model_id="google-llm"),
            reflect_llm=MemoryBinding(configured_model_id="google-reflect"),
        ),
    )
    backend = FileKeyBackend(koan_home)
    store = CredentialStore(config, backend)
    if voyage_key:
        store.set("voyage-1", voyage_key)
    if google_key:
        store.set("google-1", google_key)
    return config, store


# ---------------------------------------------------------------------------
# build_memory_models
# ---------------------------------------------------------------------------

class TestBuildMemoryModels:
    def test_embedding_returns_voyage_model_spec(self, koan_home):
        """build_memory_models resolves embedding to a ModelSpec for voyage."""
        config, store = _build_store(koan_home)
        models = build_memory_models(config, store)
        assert models.embedding is not None
        assert isinstance(models.embedding, ModelSpec)
        assert models.embedding.provider == "voyage"
        assert models.embedding.model == "voyage-4-large"
        assert models.embedding.api_key == "voyage-api-key"

    def test_embedding_resolves_dim_from_catalog_default(self, koan_home):
        """embedding binding with no explicit dim resolves to catalog default (1024)."""
        config, store = _build_store(koan_home, embedding_dim=None)
        models = build_memory_models(config, store)
        assert models.embedding is not None
        assert models.embedding.embedding_dim == 1024

    def test_embedding_respects_explicit_dim(self, koan_home):
        """embedding binding with explicit dim=512 resolves to 512."""
        config, store = _build_store(koan_home, embedding_dim=512)
        models = build_memory_models(config, store)
        assert models.embedding is not None
        assert models.embedding.embedding_dim == 512

    def test_memory_llm_returns_google_model_spec(self, koan_home):
        """build_memory_models resolves memory_llm to a ModelSpec for google."""
        config, store = _build_store(koan_home)
        models = build_memory_models(config, store)
        assert models.memory_llm is not None
        assert isinstance(models.memory_llm, ModelSpec)
        assert models.memory_llm.provider == "google"
        assert models.memory_llm.model == "gemini-flash-lite-latest"
        assert models.memory_llm.api_key == "google-api-key"

    def test_reflect_llm_returns_google_model_spec(self, koan_home):
        """build_memory_models resolves reflect_llm to a ModelSpec for google."""
        config, store = _build_store(koan_home)
        models = build_memory_models(config, store)
        assert models.reflect_llm is not None
        assert isinstance(models.reflect_llm, ModelSpec)
        assert models.reflect_llm.provider == "google"
        assert models.reflect_llm.model == "gemini-flash-latest"
        assert models.reflect_llm.api_key == "google-api-key"

    def test_missing_credential_produces_none_api_key(self, koan_home):
        """api_key is None when no credential is stored for a connection."""
        config, store = _build_store(koan_home, voyage_key=None)
        models = build_memory_models(config, store)
        assert models.embedding is not None
        assert models.embedding.api_key is None

    def test_no_memory_block_returns_empty_bundle(self, koan_home):
        """config.memory=None -> all three fields None."""
        config = KoanConfig(memory=None)
        store = CredentialStore(config, FileKeyBackend(koan_home))
        models = build_memory_models(config, store)
        assert models.embedding is None
        assert models.memory_llm is None
        assert models.reflect_llm is None

    def test_missing_configured_model_returns_none_field(self, koan_home):
        """Binding pointing to a nonexistent configured_model_id -> None field."""
        config = KoanConfig(
            configured_models=[],
            memory=MemoryBindings(
                embedding=MemoryBinding(configured_model_id="nonexistent"),
            ),
        )
        store = CredentialStore(config, FileKeyBackend(koan_home))
        models = build_memory_models(config, store)
        assert models.embedding is None

    def test_missing_connection_returns_none_field(self, koan_home):
        """ConfiguredModel with nonexistent connection_id -> None field."""
        config = KoanConfig(
            connections=[],
            configured_models=[
                ConfiguredModel(id="embed", connection_id="missing-conn", model_id="voyage-4-large"),
            ],
            memory=MemoryBindings(
                embedding=MemoryBinding(configured_model_id="embed"),
            ),
        )
        store = CredentialStore(config, FileKeyBackend(koan_home))
        models = build_memory_models(config, store)
        assert models.embedding is None

    def test_none_credential_store_produces_none_api_keys(self, koan_home):
        """credential_store=None -> api_key=None on all specs."""
        config, _ = _build_store(koan_home)
        models = build_memory_models(config, None)
        assert models.embedding is not None
        assert models.embedding.api_key is None
        assert models.memory_llm is not None
        assert models.memory_llm.api_key is None


# ---------------------------------------------------------------------------
# require_memory_model
# ---------------------------------------------------------------------------

class TestRequireMemoryModel:
    def test_returns_spec_when_not_none(self):
        """require_memory_model returns the spec unchanged when it is not None."""
        spec = ModelSpec(
            provider="voyage",
            model="voyage-4-large",
            thinking="disabled",
            connection_id="voyage-1",
        )
        result = require_memory_model(spec, "embedding")
        assert result is spec

    def test_raises_runtime_error_when_none(self):
        """require_memory_model raises RuntimeError when spec is None."""
        with pytest.raises(RuntimeError, match="not configured"):
            require_memory_model(None, "embedding")

    def test_error_message_includes_kind(self):
        """The error message names the missing binding kind."""
        with pytest.raises(RuntimeError, match="reflect_llm"):
            require_memory_model(None, "reflect_llm")


# ---------------------------------------------------------------------------
# Negative-presence: deleted globals must not exist in bindings module
# ---------------------------------------------------------------------------

class TestDeletedBindingsGlobals:
    def test_active_config_global_absent(self):
        """_ACTIVE_CONFIG must not exist in bindings after de-globalization."""
        import koan.memory.bindings as b
        assert not hasattr(b, "_ACTIVE_CONFIG"), (
            "_ACTIVE_CONFIG must not exist after de-globalization"
        )

    def test_active_frozen_models_global_absent(self):
        """_ACTIVE_FROZEN_MODELS must not exist in bindings after de-globalization."""
        import koan.memory.bindings as b
        assert not hasattr(b, "_ACTIVE_FROZEN_MODELS"), (
            "_ACTIVE_FROZEN_MODELS must not exist after de-globalization"
        )

    def test_set_active_provider_config_absent(self):
        """set_active_provider_config must not exist in bindings."""
        import koan.memory.bindings as b
        assert not hasattr(b, "set_active_provider_config"), (
            "set_active_provider_config must not exist after de-globalization"
        )

    def test_active_config_fn_absent(self):
        """_active_config must not exist in bindings."""
        import koan.memory.bindings as b
        assert not hasattr(b, "_active_config"), (
            "_active_config must not exist after de-globalization"
        )

    def test_resolve_memory_binding_absent(self):
        """resolve_memory_binding must not exist in bindings."""
        import koan.memory.bindings as b
        assert not hasattr(b, "resolve_memory_binding"), (
            "resolve_memory_binding must not exist after de-globalization"
        )
