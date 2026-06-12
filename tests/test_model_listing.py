# Unit tests for koan/agents/model_listing.py.
#
# Testing philosophy (per project lesson): pure helper functions (_is_chat_model_id,
# payload parsing) are tested directly with sample data -- the legitimate unit target.
# Network-touching helpers are tested with real LM Studio when it is running locally
# and with a lightweight stub for the ModelListingError / unsupported-provider paths.
# No mock injection points exist solely for substitution; test seams are minimal.

from __future__ import annotations

import types

import pytest


# -- _is_chat_model_id -------------------------------------------------------


def test_is_chat_model_id_accepts_gpt():
    """gpt-4 / gpt-3.5 class ids and slash-prefixed vlm ids are chat models."""
    from koan.agents.model_listing import _is_chat_model_id
    assert _is_chat_model_id("gpt-4")
    assert _is_chat_model_id("gpt-4o")
    assert _is_chat_model_id("gpt-3.5-turbo")
    assert _is_chat_model_id("o1-mini")
    assert _is_chat_model_id("qwen/qwen3.6-35b-a3b")
    assert _is_chat_model_id("qwen/qwen3.6-27b")


def test_is_chat_model_id_rejects_non_chat():
    """Known non-chat families are filtered out."""
    from koan.agents.model_listing import _is_chat_model_id
    assert not _is_chat_model_id("text-embedding-ada-002")
    assert not _is_chat_model_id("text-embedding-nomic-embed-text-v1.5")
    assert not _is_chat_model_id("whisper-1")
    assert not _is_chat_model_id("tts-1")
    assert not _is_chat_model_id("dall-e-3")
    assert not _is_chat_model_id("omni-moderation-latest")
    assert not _is_chat_model_id("gpt-4o-realtime-preview")
    assert not _is_chat_model_id("gpt-4o-audio-preview")
    assert not _is_chat_model_id("gpt-4o-transcribe")


# -- _list_openai_compatible_models (unit: filter + provider label) -----------


@pytest.mark.asyncio
async def test_list_openai_compatible_models_filters_and_labels(monkeypatch):
    """_list_openai_compatible_models keeps chat ids, excludes embeddings, stamps provider.

    Uses the three live LM Studio model ids to confirm vlm-style chat ids pass
    and the text-embedding-* id is excluded. Monkeypatches openai.AsyncOpenAI so
    no real server is required. Asserts context_window is 0 (hard cutover from
    the removed LMSTUDIO_DEFAULT_CONTEXT_WINDOW constant).
    """
    live_ids = [
        "qwen/qwen3.6-35b-a3b",
        "qwen/qwen3.6-27b",
        "text-embedding-nomic-embed-text-v1.5",
    ]

    class _FakeModelList:
        data = [types.SimpleNamespace(id=mid) for mid in live_ids]

    class _FakeModels:
        async def list(self):
            return _FakeModelList()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.models = _FakeModels()

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    from koan.agents.model_listing import _list_openai_compatible_models

    result = await _list_openai_compatible_models(
        "lmstudio", "lm-studio", "http://localhost:1234/v1", 5.0
    )

    assert len(result) == 2
    returned_ids = {m.model for m in result}
    assert "qwen/qwen3.6-35b-a3b" in returned_ids
    assert "qwen/qwen3.6-27b" in returned_ids
    assert "text-embedding-nomic-embed-text-v1.5" not in returned_ids
    assert all(m.provider == "lmstudio" for m in result)
    # context_window is 0 for all listed models: the /v1/models response carries
    # no context-length field; window is configured per ConfiguredModel (hard cutover).
    assert all(m.context_window == 0 for m in result)


@pytest.mark.asyncio
async def test_list_openai_compatible_models_openai_keeps_zero_context(monkeypatch):
    """_list_openai_compatible_models stamps context_window=0 for provider='openai'.

    Negative test: the lmstudio-specific context window must not bleed into the
    shared OpenAI listing path, which has no context-length field in its response.
    """
    model_ids = ["gpt-4o", "gpt-4o-mini"]

    class _FakeModelList:
        data = [types.SimpleNamespace(id=mid) for mid in model_ids]

    class _FakeModels:
        async def list(self):
            return _FakeModelList()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.models = _FakeModels()

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    from koan.agents.model_listing import _list_openai_compatible_models

    result = await _list_openai_compatible_models(
        "openai", "sk-test", None, 5.0
    )

    assert len(result) == 2
    assert all(m.context_window == 0 for m in result)


@pytest.mark.asyncio
async def test_list_provider_models_lmstudio_delegates(monkeypatch):
    """list_provider_models for lmstudio delegates to _list_openai_compatible_models.

    Verifies the placeholder key "lm-studio" and the default base_url fallback
    are passed correctly when api_key and base_url are both None.
    """
    recorded: list[tuple] = []

    async def _fake_list_openai_compatible_models(provider, api_key, base_url, timeout):
        recorded.append((provider, api_key, base_url, timeout))
        return []

    import koan.agents.model_listing as ml
    monkeypatch.setattr(
        ml,
        "_list_openai_compatible_models",
        _fake_list_openai_compatible_models,
    )

    from koan.agents.model_listing import list_provider_models

    await list_provider_models("lmstudio", api_key=None, base_url=None)

    assert len(recorded) == 1
    provider, api_key, base_url, _timeout = recorded[0]
    assert provider == "lmstudio"
    assert api_key == "lm-studio"
    assert base_url == "http://localhost:1234/v1"


def test_list_lmstudio_models_removed():
    """_list_lmstudio_models has been deleted (hard cutover to OpenAI-compat path)."""
    import koan.agents.model_listing as ml
    assert not hasattr(ml, "_list_lmstudio_models")


# -- list_provider_models unsupported provider --------------------------------


@pytest.mark.asyncio
async def test_list_provider_models_raises_for_unsupported():
    """list_provider_models raises ModelListingError for unsupported providers."""
    from koan.agents.model_listing import list_provider_models, ModelListingError

    with pytest.raises(ModelListingError, match="bedrock"):
        await list_provider_models(
            "bedrock",
            api_key="k",
            base_url=None,
        )

    with pytest.raises(ModelListingError, match="voyage"):
        await list_provider_models(
            "voyage",
            api_key="k",
            base_url=None,
        )


# -- list_models_for_connection -----------------------------------------------


@pytest.mark.asyncio
async def test_list_models_for_connection_listing_capable(monkeypatch):
    """list_models_for_connection returns live ProviderModels for a listing-capable type."""
    from koan.agents.model_listing import list_models_for_connection
    from koan.types import Connection, ProviderModel

    conn = Connection(id="openai-main", type="openai")

    fake_models = [
        ProviderModel(provider="openai", model="gpt-4o", display_name="GPT-4o"),
        ProviderModel(provider="openai", model="gpt-4o-mini", display_name="GPT-4o Mini"),
    ]

    async def fake_list_provider_models(provider, *, api_key, base_url, region=None, timeout=8.0):
        assert provider == "openai"
        return fake_models

    monkeypatch.setattr(
        "koan.agents.model_listing.list_provider_models",
        fake_list_provider_models,
    )

    # Minimal fake credential store: resolve returns a dummy key.
    class _FakeStore:
        def resolve(self, conn_id: str) -> str | None:
            return "fake-key"

    result = await list_models_for_connection(conn, _FakeStore())
    assert result == fake_models


@pytest.mark.asyncio
async def test_list_models_for_connection_non_listing_type_raises(monkeypatch):
    """list_models_for_connection raises ModelListingError for bedrock (non-listing)."""
    from koan.agents.model_listing import ModelListingError, list_models_for_connection
    from koan.types import Connection

    conn = Connection(id="bedrock-main", type="bedrock", region="us-east-1")

    # No monkeypatch needed: list_provider_models already raises for bedrock.
    with pytest.raises(ModelListingError, match="bedrock"):
        await list_models_for_connection(conn, None)


@pytest.mark.asyncio
async def test_list_models_for_connection_voyage_raises(monkeypatch):
    """list_models_for_connection raises ModelListingError for voyage (embedding-only)."""
    from koan.agents.model_listing import ModelListingError, list_models_for_connection
    from koan.types import Connection

    conn = Connection(id="voyage-main", type="voyage")

    with pytest.raises(ModelListingError, match="voyage"):
        await list_models_for_connection(conn, None)


# -- Real LM Studio integration test ------------------------------------------
# Requires a running LM Studio at http://localhost:1234.
# Marked with a custom marker; CI can skip via -m "not lmstudio_live".


@pytest.mark.asyncio
@pytest.mark.lmstudio_live
async def test_list_lmstudio_models_live():
    """Integration: list models from a real LM Studio at localhost:1234.

    Exercises the OpenAI-compat /v1/models path (the native /api/v0/models path
    has been retired). Asserts at least 2 chat models, provider='lmstudio' on
    every result, and that no id containing 'embedding' is returned.
    Skip this test when LM Studio is not running by using -m 'not lmstudio_live'.
    """
    from koan.agents.model_listing import list_provider_models, ModelListingError

    try:
        models = await list_provider_models(
            "lmstudio",
            api_key=None,
            base_url="http://localhost:1234/v1",
            timeout=8.0,
        )
    except ModelListingError as exc:
        pytest.skip(f"LM Studio not available: {exc}")

    assert len(models) >= 2
    for m in models:
        assert m.provider == "lmstudio"
        assert m.model
        assert m.display_name
        assert "embedding" not in m.model.lower()
