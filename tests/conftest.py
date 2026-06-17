# Test-suite configuration and hooks.

import os

import pytest


def _build_integration_cred_components(tmp_path, monkeypatch):
    """Build KoanConfig + CredentialStore for integration tests.

    Shared by real_credential_store and real_memory_models fixtures.
    Seeds connection-id keyed credentials from well-known env vars.
    Returns (config, store).
    """
    from koan.config import KoanConfig
    from koan.credentials import CredentialStore, FileKeyBackend
    from koan.types import Connection, ConfiguredModel, MemoryBinding, MemoryBindings

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

    _INTEGRATION_ENV_KEYS: dict[str, str] = {
        "GOOGLE_API_KEY": "google-1",
        "GEMINI_API_KEY": "google-1",
        "VOYAGE_API_KEY": "voyage-1",
        "ANTHROPIC_API_KEY": "anthropic-1",
        "OPENAI_API_KEY": "openai-1",
    }
    for env_var, conn_id in _INTEGRATION_ENV_KEYS.items():
        val = os.environ.get(env_var)
        if val and not store.has(conn_id):
            store.set(conn_id, val)

    return config, store


@pytest.fixture(autouse=False)
def _real_cred_components(tmp_path, monkeypatch):
    return _build_integration_cred_components(tmp_path, monkeypatch)


@pytest.fixture(autouse=False)
def real_credential_store(_real_cred_components):
    """Return a CredentialStore seeded from env for integration tests.

    Use store.has("google-1") / store.has("voyage-1") to check key presence.
    M4: credentials are keyed by connection id, not provider type string.
    """
    _, store = _real_cred_components
    return store


@pytest.fixture(autouse=False)
def real_memory_models(_real_cred_components):
    """Return a MemoryModels bundle for integration tests.

    Built from real credentials seeded from env.  Fields are None when the
    corresponding env var is absent (e.g. no VOYAGE_API_KEY -> embedding=None).
    """
    from koan.memory.bindings import build_memory_models
    config, store = _real_cred_components
    return build_memory_models(config, store)
