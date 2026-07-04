# Shared fixtures for koan/memory unit tests.
#
# memory_config builds a MemoryModels bundle with voyage + google bindings
# and no real credentials (api_key=None on all specs).  Sufficient for:
#   - Index sync tests that mock _embed_texts
#   - Backend tests that mock voyageai.AsyncClient
#   - Schema dimension resolution (embedding_dim)
#   - provider_type checks
#
# Tests that do real embedding/LLM calls must use real_credential_store and
# real_memory_models (from tests/conftest.py) which seed credentials from env.

import pytest


@pytest.fixture
def memory_config(koan_home):
    """Build a MemoryModels bundle for memory unit tests.

    All specs have api_key=None (no real credentials).  Tests that need to
    call VoyageAI or a real LLM must use real_memory_models instead.
    The koan_home argument comes from the autouse fixture in tests/conftest.py
    which redirects Path.home() so no real ~/.koan is touched.
    """
    from koan.config import KoanConfig
    from koan.credentials import CredentialStore, FileKeyBackend
    from koan.memory.bindings import build_memory_models
    from koan.types import Connection, ConfiguredModel, MemoryBinding, MemoryBindings

    config = KoanConfig(
        connections=[
            Connection(id="voyage-1", type="voyage"),
        ],
        configured_models=[
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
    # No credentials stored: all specs have api_key=None.
    return build_memory_models(config, store)
