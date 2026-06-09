# Test-suite configuration and hooks.
#
# (The M8 xfail hook that auto-xfailed test_web_flows.py / test_uploads.py
# client-fixture tests is gone: the settings/startup path was reworked onto the
# provider-credential model, so those tests run normally again.)

import pytest


@pytest.fixture(autouse=False)
def real_credential_store(tmp_path, monkeypatch):
    """Initialize the active credential store and provider config for integration tests.

    Sets up a KoanConfig with google-1 and voyage-1 connections, matching
    configured_models, and MemoryBindings for embedding/memory_llm/reflect_llm.
    Seeds credentials from the environment under connection ids ("google-1",
    "voyage-1", etc.) rather than provider-type strings.  Calls both
    set_active_credential_store and set_active_provider_config so memory
    subsystem operations resolve bindings correctly.

    M4: credentials are keyed by connection id.  Use store.has("google-1") or
    store.has("voyage-1") to check whether a key is available, not
    store.has("google") / store.has("voyage").
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

    # Use a tmp master key so we never touch the real ~/.koan/master.key.
    key_path = tmp_path / "master.key"
    monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)

    import os

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

    # Seed credentials under connection ids.  Multiple env vars may provide
    # the same connection's key (e.g. GOOGLE_API_KEY and GEMINI_API_KEY both
    # map to "google-1"); take the first one found.
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

    set_active_credential_store(store)
    set_active_provider_config(config)
    return store
