# Tests for koan.agents.capability_resolver -- resolve_capabilities.

from __future__ import annotations

import pytest

from koan.agents.capability_resolver import resolve_capabilities


# -- Known (anthropic, claude-*) pairs ----------------------------------------

class TestResolveCapabilitiesAnthropic:
    def test_known_pair_returns_populated_capabilities(self):
        """resolve_capabilities populates all fields for a known (anthropic, claude-*) pair."""
        caps = resolve_capabilities("anthropic", "claude-sonnet-4-5")
        assert isinstance(caps.thinking_modes, list)
        assert caps.thinking_shape in ("budget", "adaptive", "effort", "none")
        assert caps.supports_tools is True
        assert caps.supports_prompt_caching is True
        assert caps.recognized is True
        assert caps.family == "claude-sonnet"

    def test_anthropic_claude_opus_thinking_modes_from_catalog(self):
        """thinking_modes for claude-opus-4-0 come from MODEL_CAPABILITIES = ['medium', 'high']."""
        caps = resolve_capabilities("anthropic", "claude-opus-4-0")
        assert "medium" in caps.thinking_modes
        assert "high" in caps.thinking_modes
        # xhigh is NOT in the catalog entry for claude-opus-4-0.
        assert "xhigh" not in caps.thinking_modes

    def test_anthropic_haiku_has_no_thinking_modes(self):
        """claude-3-5-haiku-latest has an empty thinking_modes list (no thinking support)."""
        caps = resolve_capabilities("anthropic", "claude-3-5-haiku-latest")
        assert caps.thinking_modes == []
        assert caps.thinking_supported is False

    def test_anthropic_claude_opus_budget_shape(self):
        """claude-opus-4-0 does not support adaptive thinking -- shape should be budget."""
        caps = resolve_capabilities("anthropic", "claude-opus-4-0")
        assert caps.thinking_shape == "budget"

    def test_anthropic_prompt_caching_true(self):
        """All anthropic models support explicit prompt caching."""
        caps = resolve_capabilities("anthropic", "claude-sonnet-4-5")
        assert caps.supports_prompt_caching is True


# -- Unknown model ids (graceful fallthrough) ---------------------------------

class TestResolveCapabilitiesUnknown:
    def test_unknown_id_returns_recognized_false(self):
        """An unrecognized model id returns recognized=False without raising."""
        caps = resolve_capabilities("anthropic", "some-hypothetical-model-xyz")
        assert caps.recognized is False
        # Capability fields must still be populated (no None/crash).
        assert isinstance(caps.thinking_modes, list)
        assert isinstance(caps.supports_tools, bool)

    def test_unknown_id_does_not_raise(self):
        """resolve_capabilities never raises for any provider/model combination."""
        for provider, model in [
            ("voyage", "voyage-4-large"),
            ("bedrock", "meta.llama3-8b-instruct-v1:0"),
            ("anthropic", ""),
            ("google", "???"),
        ]:
            result = resolve_capabilities(provider, model)
            assert result is not None


# -- openrouter (conservative defaults, deliberate minimal fidelity) ----------

def test_openrouter_unrecognized_conservative_defaults():
    """resolve_capabilities for openrouter returns conservative defaults without raising.

    openrouter is intentionally absent from the capability resolver (Decision 4):
    curating 500+ models is infeasible, and conservative defaults are acceptable.
    Consequence: no koan-managed thinking control for openrouter models.
    """
    caps = resolve_capabilities("openrouter", "anthropic/claude-3.5-sonnet")
    assert caps.recognized is False
    assert caps.thinking_modes == []
    assert caps.thinking_supported is False


# -- voyage (no thinking) -----------------------------------------------------

class TestResolveCapabilitiesEmbeddingProvider:
    def test_voyage_has_no_thinking(self):
        """voyage is an embeddings-only provider; no thinking support."""
        caps = resolve_capabilities("voyage", "voyage-4-large")
        assert caps.thinking_supported is False
        assert caps.thinking_shape == "none"


# -- Google models ------------------------------------------------------------

class TestResolveCapabilitiesGoogle:
    def test_google_thinking_flash_model(self):
        """Gemini Flash models support thinking (shape=budget)."""
        caps = resolve_capabilities("google", "gemini-3.5-flash")
        assert caps.thinking_supported is True
        assert caps.thinking_shape == "budget"

    def test_google_prompt_caching_false(self):
        """Google models do not have explicit koan-managed prompt caching."""
        caps = resolve_capabilities("google", "gemini-3.1-pro-preview")
        assert caps.supports_prompt_caching is False


# -- Bedrock ------------------------------------------------------------------

class TestResolveCapabilitiesBedrock:
    def test_bedrock_amazon_nova_no_thinking(self):
        """Amazon Nova models on Bedrock have no thinking support."""
        caps = resolve_capabilities("bedrock", "amazon.nova-pro-v1:0")
        assert caps.thinking_supported is False

    def test_bedrock_anthropic_model_thinking_resolved(self):
        """Bedrock-hosted Anthropic models resolve thinking from the Anthropic profile."""
        caps = resolve_capabilities("bedrock", "anthropic.claude-opus-4-0")
        assert caps.thinking_supported is True
        assert caps.thinking_shape == "budget"

    def test_bedrock_anthropic_prompt_caching_true(self):
        """Bedrock-hosted Claude models support explicit prompt caching (family-scoped)."""
        caps = resolve_capabilities("bedrock", "anthropic.claude-opus-4-0")
        assert caps.supports_prompt_caching is True

    def test_bedrock_nova_prompt_caching_false(self):
        """Bedrock-hosted Nova models do not support explicit prompt caching."""
        caps = resolve_capabilities("bedrock", "amazon.nova-pro-v1:0")
        assert caps.supports_prompt_caching is False


