# Shared fixtures for koan/memory unit tests.
#
# memory_config sets up an active provider config and credential store with
# voyage + google connections, configured models, and MemoryBindings.  No
# real credentials are needed -- just enough config for binding resolution
# (schema dimension, provider-type checks, model id lookups).
#
# Tests that do real embedding/LLM calls must use real_credential_store
# (from tests/conftest.py) which seeds credentials from the environment.

import pytest


@pytest.fixture
def memory_config(tmp_path, monkeypatch):
    """Set up active provider config and credential store for memory unit tests.

    Creates a KoanConfig with voyage-1 and google-1 connections, matching
    configured_models, and full MemoryBindings.  No real credentials are
    stored; api_key is None on all resolved bindings.  Sufficient for:
      - Schema dimension resolution (VOYAGE_EMBEDDING_MODELS catalog)
      - provider_type checks in _embed_texts and _voyage_rerank
      - model_id lookups in resolve_memory_binding
    """
    from koan.config import KoanConfig
    from koan.credentials import (
        CredentialStore,
        FileKeyBackend,
        set_active_credential_store,
    )
    from koan.memory.bindings import set_active_provider_config
    from koan.types import (
        Connection,
        ConfiguredModel,
        MemoryBinding,
        MemoryBindings,
    )

    key_path = tmp_path / "master.key"
    monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)

    config = KoanConfig(
        connections=[
            Connection(id="google-1", type="google"),
            Connection(id="voyage-1", type="voyage"),
        ],
        configured_models=[
            ConfiguredModel(
                id="google-llm",
                connection_id="google-1",
                model_id="gemini-flash-lite-latest",
            ),
            ConfiguredModel(
                id="google-reflect",
                connection_id="google-1",
                model_id="gemini-flash-latest",
            ),
            ConfiguredModel(
                id="voyage-embed",
                connection_id="voyage-1",
                model_id="voyage-4-large",
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
    set_active_credential_store(store)
    set_active_provider_config(config)
    return config
