# Unit tests for koan.memory.bindings: Voyage embedding catalog, resolver helpers,
# resolve_memory_binding, set_active_provider_config, and error cases.
#
# Hard cutover: EMBEDDING_DIMS and embedding_dim_for were removed and replaced by
# the VoyageEmbeddingModel catalog.  This file covers the new catalog API and
# includes a negative-presence test to guard against accidental re-introduction.

from __future__ import annotations

import pytest

from koan.config import KoanConfig
from koan.credentials import CredentialStore, FileKeyBackend, set_active_credential_store
from koan.memory.bindings import (
    VOYAGE_EMBEDDING_MODELS,
    ResolvedMemoryModel,
    VoyageEmbeddingModel,
    is_recognized_voyage_model,
    resolve_memory_binding,
    resolve_voyage_embedding_dim,
    set_active_provider_config,
    voyage_dimension_options,
    voyage_embedding_models,
)
from koan.types import (
    Connection,
    ConfiguredModel,
    MemoryBinding,
    MemoryBindings,
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

    def test_each_model_has_context_window_32000(self):
        for entry in VOYAGE_EMBEDDING_MODELS.values():
            assert entry.context_window == 32_000

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

def _setup_active_config(
    tmp_path,
    monkeypatch,
    *,
    voyage_key: str | None = "voyage-api-key",
    google_key: str | None = "google-api-key",
    embedding_dim: int | None = None,
) -> tuple[KoanConfig, CredentialStore]:
    """Build and activate a config with voyage + google connections and MemoryBindings."""
    key_path = tmp_path / "master.key"
    monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)

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
    backend = FileKeyBackend()
    store = CredentialStore(config, backend)
    if voyage_key:
        store.set("voyage-1", voyage_key)
    if google_key:
        store.set("google-1", google_key)
    set_active_credential_store(store)
    set_active_provider_config(config)
    return config, store


# ---------------------------------------------------------------------------
# resolve_memory_binding -- happy paths
# ---------------------------------------------------------------------------

class TestResolveMemoryBinding:
    def test_embedding_returns_voyage_rmm(self, tmp_path, monkeypatch):
        """resolve_memory_binding('embedding') returns voyage provider + model + key."""
        _setup_active_config(tmp_path, monkeypatch)
        rmm = resolve_memory_binding("embedding")
        assert isinstance(rmm, ResolvedMemoryModel)
        assert rmm.provider_type == "voyage"
        assert rmm.model_id == "voyage-4-large"
        assert rmm.api_key == "voyage-api-key"

    def test_embedding_resolves_dim_from_catalog_default(self, tmp_path, monkeypatch):
        """embedding binding with no explicit dim resolves to catalog default (1024)."""
        _setup_active_config(tmp_path, monkeypatch, embedding_dim=None)
        rmm = resolve_memory_binding("embedding")
        assert rmm.embedding_dim == 1024

    def test_embedding_respects_explicit_dim(self, tmp_path, monkeypatch):
        """embedding binding with explicit dim=512 resolves to 512."""
        _setup_active_config(tmp_path, monkeypatch, embedding_dim=512)
        rmm = resolve_memory_binding("embedding")
        assert rmm.embedding_dim == 512

    def test_memory_llm_returns_google_rmm(self, tmp_path, monkeypatch):
        """resolve_memory_binding('memory_llm') returns google provider + model + key."""
        _setup_active_config(tmp_path, monkeypatch)
        rmm = resolve_memory_binding("memory_llm")
        assert rmm.provider_type == "google"
        assert rmm.model_id == "gemini-flash-lite-latest"
        assert rmm.api_key == "google-api-key"

    def test_reflect_llm_returns_google_rmm(self, tmp_path, monkeypatch):
        """resolve_memory_binding('reflect_llm') returns google provider + model + key."""
        _setup_active_config(tmp_path, monkeypatch)
        rmm = resolve_memory_binding("reflect_llm")
        assert rmm.provider_type == "google"
        assert rmm.model_id == "gemini-flash-latest"
        assert rmm.api_key == "google-api-key"

    def test_missing_credential_returns_none_api_key(self, tmp_path, monkeypatch):
        """api_key is None when no credential is stored for the connection."""
        _setup_active_config(tmp_path, monkeypatch, voyage_key=None)
        rmm = resolve_memory_binding("embedding")
        assert rmm.api_key is None
        assert rmm.provider_type == "voyage"


# ---------------------------------------------------------------------------
# resolve_memory_binding -- error cases (brief D12: unconfigured -> clear error)
# ---------------------------------------------------------------------------

class TestResolveMemoryBindingErrors:
    def test_raises_when_config_not_set(self, monkeypatch):
        """resolve_memory_binding raises RuntimeError when no active config is set."""
        monkeypatch.setattr("koan.memory.bindings._ACTIVE_CONFIG", None)
        with pytest.raises(RuntimeError, match="Active provider config is not initialized"):
            resolve_memory_binding("embedding")

    def test_raises_when_memory_block_absent(self, tmp_path, monkeypatch):
        """resolve_memory_binding raises when config.memory is None."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        config = KoanConfig(memory=None)
        store = CredentialStore(config, FileKeyBackend())
        set_active_credential_store(store)
        set_active_provider_config(config)
        with pytest.raises(RuntimeError, match="config.memory is absent"):
            resolve_memory_binding("embedding")

    def test_raises_when_binding_is_none(self, tmp_path, monkeypatch):
        """resolve_memory_binding raises when the binding field is None."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        config = KoanConfig(
            memory=MemoryBindings(
                embedding=None,
                memory_llm=None,
                reflect_llm=None,
            )
        )
        store = CredentialStore(config, FileKeyBackend())
        set_active_credential_store(store)
        set_active_provider_config(config)
        with pytest.raises(RuntimeError, match="is not configured in config.memory"):
            resolve_memory_binding("embedding")

    def test_raises_when_configured_model_missing(self, tmp_path, monkeypatch):
        """resolve_memory_binding raises when the configured_model_id is not found."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        config = KoanConfig(
            configured_models=[],
            memory=MemoryBindings(
                embedding=MemoryBinding(configured_model_id="nonexistent"),
            ),
        )
        store = CredentialStore(config, FileKeyBackend())
        set_active_credential_store(store)
        set_active_provider_config(config)
        with pytest.raises(RuntimeError, match="configured_model_id="):
            resolve_memory_binding("embedding")

    def test_raises_when_connection_missing(self, tmp_path, monkeypatch):
        """resolve_memory_binding raises when the connection_id is not found."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        config = KoanConfig(
            connections=[],
            configured_models=[
                ConfiguredModel(id="embed", connection_id="missing-conn", model_id="voyage-4-large"),
            ],
            memory=MemoryBindings(
                embedding=MemoryBinding(configured_model_id="embed"),
            ),
        )
        store = CredentialStore(config, FileKeyBackend())
        set_active_credential_store(store)
        set_active_provider_config(config)
        with pytest.raises(RuntimeError, match="connection_id="):
            resolve_memory_binding("embedding")


# ---------------------------------------------------------------------------
# Active config lifecycle
# ---------------------------------------------------------------------------

class TestActiveConfig:
    def test_set_active_provider_config_makes_config_accessible(self, tmp_path, monkeypatch):
        """set_active_provider_config stores the config for resolve_memory_binding."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        config = KoanConfig()
        store = CredentialStore(config, FileKeyBackend())
        set_active_credential_store(store)
        set_active_provider_config(config)
        # Should raise "config.memory is absent" (not "not initialized").
        with pytest.raises(RuntimeError, match="config.memory is absent"):
            resolve_memory_binding("embedding")

    def test_raises_when_active_config_unset(self, monkeypatch):
        """_active_config raises RuntimeError when _ACTIVE_CONFIG is None."""
        monkeypatch.setattr("koan.memory.bindings._ACTIVE_CONFIG", None)
        from koan.memory.bindings import _active_config
        with pytest.raises(RuntimeError, match="Active provider config is not initialized"):
            _active_config()
