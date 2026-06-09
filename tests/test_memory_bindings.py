# Unit tests for koan.memory.bindings: resolve_memory_binding,
# embedding_dim_for, set_active_provider_config, and error cases.

from __future__ import annotations

import pytest

from koan.config import KoanConfig
from koan.credentials import CredentialStore, FileKeyBackend, set_active_credential_store
from koan.memory.bindings import (
    EMBEDDING_DIMS,
    ResolvedMemoryModel,
    embedding_dim_for,
    resolve_memory_binding,
    set_active_provider_config,
)
from koan.types import (
    Connection,
    ConfiguredModel,
    MemoryBinding,
    MemoryBindings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_active_config(
    tmp_path,
    monkeypatch,
    *,
    voyage_key: str | None = "voyage-api-key",
    google_key: str | None = "google-api-key",
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
            ConfiguredModel(id="voyage-embed", connection_id="voyage-1", model_id="voyage-4-large"),
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
# embedding_dim_for
# ---------------------------------------------------------------------------

class TestEmbeddingDimFor:
    def test_voyage_4_large_returns_1024(self):
        """embedding_dim_for returns 1024 for the default voyage-4-large model."""
        assert embedding_dim_for("voyage", "voyage-4-large") == 1024

    def test_unknown_pair_raises_value_error(self):
        """embedding_dim_for raises ValueError for an unknown (provider, model) pair."""
        with pytest.raises(ValueError, match="Unknown embedding dimension"):
            embedding_dim_for("voyage", "voyage-unknown-model")

    def test_unknown_provider_raises_value_error(self):
        """embedding_dim_for raises ValueError for an unknown provider type."""
        with pytest.raises(ValueError, match="Unknown embedding dimension"):
            embedding_dim_for("openai", "text-embedding-3-small")

    def test_embedding_dims_seed_entry(self):
        """EMBEDDING_DIMS contains the expected seed entry for voyage-4-large."""
        assert ("voyage", "voyage-4-large") in EMBEDDING_DIMS
        assert EMBEDDING_DIMS[("voyage", "voyage-4-large")] == 1024


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
