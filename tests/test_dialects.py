# Tests for koan.agents.dialects.

from __future__ import annotations

import os

import pytest

from koan.agents.dialects import apply_thinking, emit_cache_settings, voyage_embed, cache_ttl_for
from koan.models.capabilities import (
    Capabilities,
    Provenance,
    StructuredSupport,
    ThinkingSupport,
)
from koan.models.offering import resolve_offering


def _caps(prompt_caching: str) -> Capabilities:
    """Build a Capabilities record with the given prompt_caching support."""
    fields = (
        "context_window", "max_output", "input_modalities", "thinking",
        "cache_minimum_tokens", "prompt_caching", "native_tools", "batches",
        "files_api", "input_sources", "structured_outputs", "listing",
        "embedding_dims", "embedding_default_dim",
    )
    return Capabilities(
        context_window=200_000, max_output=32_768,
        input_modalities=frozenset({"text"}),
        thinking=ThinkingSupport(True, ("low", "medium"), "adaptive"),
        cache_minimum_tokens=1024,
        prompt_caching=prompt_caching,
        native_tools=frozenset(), batches=False, files_api=False, input_sources=frozenset(),
        structured_outputs=StructuredSupport(True, True),
        listing=False, embedding_dims=(), embedding_default_dim=None,
        provenance={k: Provenance("curated") for k in fields},
        resolved=True,
    )


class TestApplyThinking:
    def test_disabled_returns_empty(self) -> None:
        """apply_thinking('disabled') returns {} (omit the setting entirely)."""
        assert apply_thinking("disabled") == {}

    def test_high(self) -> None:
        """apply_thinking('high') passes through to pydantic-ai's unified setting."""
        assert apply_thinking("high") == {"thinking": "high"}

    def test_xhigh(self) -> None:
        """apply_thinking('xhigh') passes through xhigh."""
        assert apply_thinking("xhigh") == {"thinking": "xhigh"}

    def test_minimal(self) -> None:
        """apply_thinking('minimal') passes through minimal."""
        assert apply_thinking("minimal") == {"thinking": "minimal"}


class TestEmitCacheSettings:
    def test_anthropic_long_tier_split(self) -> None:
        """anthropic-messages long tier: tail short, stable keys long."""
        settings = emit_cache_settings("anthropic-messages", _caps("explicit"), "long")
        assert settings == {
            "anthropic_cache": "5m",
            "anthropic_cache_instructions": "1h",
            "anthropic_cache_tool_definitions": "1h",
        }

    def test_bedrock_short_tier(self) -> None:
        """bedrock-converse short tier: all keys short TTL."""
        settings = emit_cache_settings("bedrock-converse", _caps("explicit"), "short")
        assert settings == {
            "bedrock_cache_messages": "5m",
            "bedrock_cache_instructions": "5m",
            "bedrock_cache_tool_definitions": "5m",
        }

    def test_caps_none_returns_empty(self) -> None:
        """When caps.prompt_caching is 'none', no cache settings are emitted."""
        assert emit_cache_settings("anthropic-messages", _caps("none"), "long") == {}

    def test_automatic_dialect_returns_empty(self) -> None:
        """google-genai (automatic caching) has no koan cache settings."""
        assert emit_cache_settings("google-genai", _caps("automatic"), "long") == {}

    def test_openai_chat_returns_empty(self) -> None:
        """openai-chat has no koan-managed cache settings (automatic server-side)."""
        assert emit_cache_settings("openai-chat", _caps("automatic"), "long") == {}


class TestEmitCacheSettingsViaOffering:
    def test_anthropic_offering_emits_cache(self) -> None:
        """A resolved anthropic offering's caps drive the cache settings emission."""
        o = resolve_offering("anthropic", "claude-sonnet-4-5")
        settings = emit_cache_settings("anthropic-messages", o.caps, "long")
        assert "anthropic_cache" in settings


class TestVoyageEmbed:
    @pytest.mark.skipif(
        not os.environ.get("VOYAGE_API_KEY"),
        reason="requires VOYAGE_API_KEY to call the real voyageai API",
    )
    @pytest.mark.asyncio
    async def test_voyage_embed_dimensions(self) -> None:
        """voyage_embed returns embeddings whose dimension matches the model default."""
        o = resolve_offering("voyage", "voyage-4-large")
        embeddings = await voyage_embed(
            ["hello world"], model="voyage-4-large",
            api_key=os.environ["VOYAGE_API_KEY"], input_type="document",
        )
        assert len(embeddings) == 1
        assert len(embeddings[0]) == o.caps.embedding_default_dim

# -- cache_ttl_for (relocated from test_provider_adapter.py) -------------------


class TestCacheTtlFor:
    """Tests for the relocated cache_ttl_for gateway function."""

    def test_cache_ttl_for_anthropic_messages_short(self) -> None:
        """cache_ttl_for maps anthropic-messages dialect short->'5m'."""
        assert cache_ttl_for("anthropic-messages", "short") == "5m"

    def test_cache_ttl_for_anthropic_messages_long(self) -> None:
        """cache_ttl_for maps anthropic-messages dialect long->'1h'."""
        assert cache_ttl_for("anthropic-messages", "long") == "1h"

    def test_cache_ttl_for_bedrock_converse_short(self) -> None:
        """cache_ttl_for maps bedrock-converse dialect short->'5m'."""
        assert cache_ttl_for("bedrock-converse", "short") == "5m"

    def test_cache_ttl_for_bedrock_converse_long(self) -> None:
        """cache_ttl_for maps bedrock-converse dialect long->'1h'."""
        assert cache_ttl_for("bedrock-converse", "long") == "1h"

    def test_cache_ttl_for_google_returns_none(self) -> None:
        """cache_ttl_for returns None for google-genai (no koan-managed explicit cache)."""
        assert cache_ttl_for("google-genai", "long") is None

    def test_cache_ttl_for_openai_chat_returns_none(self) -> None:
        """cache_ttl_for returns None for openai-chat (no koan-managed explicit cache)."""
        assert cache_ttl_for("openai-chat", "short") is None
