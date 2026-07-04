# Test-suite configuration and hooks.

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def koan_home(tmp_path, monkeypatch) -> Path:
    """Redirect every test away from the developer's real ~/.koan.

    Patches Path.home() to return tmp_path so that both the ServerConfig
    default_factory (Path.home() / ".koan") and the resolve_koan_home default
    branch resolve into the temp tree.  This means no test can read or write
    the real ~/.koan even via a programmatically constructed AppState that
    never explicitly sets server.koan_home.

    Returns the derived temp home (tmp_path / ".koan"), which tests that call
    threaded functions (load_koan_config, FileKeyBackend, etc.) should pass
    as the home argument.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    home = Path.home() / ".koan"  # == tmp_path / ".koan"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _build_integration_cred_components(koan_home: Path):
    """Build KoanConfig + CredentialStore for integration tests.

    Shared by real_credential_store and real_memory_models fixtures.
    Seeds connection-id keyed credentials from well-known env vars.
    Returns (config, store).
    """
    from koan.config import KoanConfig
    from koan.credentials import CredentialStore, FileKeyBackend
    from koan.types import Connection, ConfiguredModel, MemoryBinding, MemoryBindings

    config = KoanConfig(
        connections=[
            Connection(id="google-1", type="google"),
            Connection(id="voyage-1", type="voyage"),
        ],
        configured_models=[
            # google-llm / google-reflect removed: memory LLMs now resolve from
            # the active preset's cheap/standard slots. google-1 connection is
            # kept for test_pydantic_ai_agent's live Gemini smoke test.
            ConfiguredModel(
                id="voyage-embed",
                connection_id="voyage-1",
                model_id="voyage-4-large",
            ),
        ],
        memory=MemoryBindings(
            embedding=MemoryBinding(configured_model_id="voyage-embed"),
        ),
    )
    backend = FileKeyBackend(koan_home)
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
def _real_cred_components(koan_home):
    """Build real credential components for integration tests."""
    return _build_integration_cred_components(koan_home)


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
