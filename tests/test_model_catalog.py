# Validating tests for koan/agents/model_catalog.py.
#
# Enforces two invariants:
#   1. Every (provider, model) in MODEL_CAPABILITIES resolves in the genai-prices
#      bundled snapshot -- price_for_usage succeeds and returns a positive Decimal.
#   2. build_model_registry() returns one ModelRegistryEntry per capability entry,
#      each with a positive (never null) context_window.
#
# M1: _GEMINI_TIER_SPECS and _GEMINI_FRONTIER_SPECS removed from registry.py
# (built-in profiles deleted, brief D12).  The test_builtin_profile_model_price_resolves
# parametrize that imported those constants is deleted.  context_window_for is added.

from __future__ import annotations

from decimal import Decimal

import pytest

from koan.agents.model_catalog import (
    MODEL_CAPABILITIES,
    PROVIDER_ID_MAP,
    build_model_registry,
    context_window_for,
    price_for_usage,
)


# -- Helpers ------------------------------------------------------------------

def _all_offered_models() -> list[tuple[str, str]]:
    """Enumerate every (provider, model) in MODEL_CAPABILITIES."""
    return list(MODEL_CAPABILITIES.keys())


# -- Price resolution tests ---------------------------------------------------

class TestPriceForUsage:
    @pytest.mark.parametrize("provider,model", _all_offered_models())
    def test_offered_model_price_resolves(self, provider: str, model: str) -> None:
        """price_for_usage succeeds and returns a positive Decimal for every catalog model."""
        result = price_for_usage(provider, model, input_tokens=1000, output_tokens=500)
        assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"
        assert result > 0, f"Expected positive price for {provider}/{model}, got {result}"

    def test_cache_tokens_accepted(self) -> None:
        """price_for_usage accepts cache_read_tokens and cache_write_tokens without error."""
        result = price_for_usage(
            "google", "gemini-3.1-pro-preview",
            input_tokens=1000, output_tokens=500,
            cache_read_tokens=200, cache_write_tokens=100,
        )
        assert result > 0


# -- Model registry tests -----------------------------------------------------

class TestBuildModelRegistry:
    def test_returns_one_entry_per_capability(self) -> None:
        """build_model_registry returns exactly one ModelRegistryEntry per MODEL_CAPABILITIES entry."""
        registry = build_model_registry()
        assert len(registry) == len(MODEL_CAPABILITIES), (
            f"Expected {len(MODEL_CAPABILITIES)} entries, got {len(registry)}"
        )

    def test_every_entry_has_positive_context_window(self) -> None:
        """Every registry entry has a context_window > 0 (never null, never zero)."""
        registry = build_model_registry()
        for e in registry:
            assert e.context_window > 0, (
                f"{e.provider}/{e.model} has non-positive context_window={e.context_window}"
            )

    def test_every_entry_has_display_name(self) -> None:
        """Every registry entry has a non-empty display_name."""
        registry = build_model_registry()
        for e in registry:
            assert e.display_name, f"{e.provider}/{e.model} has empty display_name"

    def test_provider_id_map_covers_all_providers(self) -> None:
        """PROVIDER_ID_MAP contains every provider referenced in MODEL_CAPABILITIES."""
        catalog_providers = {p for p, _ in MODEL_CAPABILITIES}
        for provider in catalog_providers:
            assert provider in PROVIDER_ID_MAP, (
                f"Provider '{provider}' in MODEL_CAPABILITIES but missing from PROVIDER_ID_MAP"
            )

    def test_entries_match_capabilities(self) -> None:
        """Registry entries correspond 1:1 with MODEL_CAPABILITIES (provider+model match)."""
        registry = build_model_registry()
        registry_pairs = {(e.provider, e.model) for e in registry}
        capability_pairs = set(MODEL_CAPABILITIES.keys())
        assert registry_pairs == capability_pairs, (
            f"Registry/capabilities mismatch: extra={registry_pairs - capability_pairs}, "
            f"missing={capability_pairs - registry_pairs}"
        )


# -- context_window_for tests -------------------------------------------------

class TestContextWindowFor:
    def test_known_catalog_model_returns_positive_window(self) -> None:
        """context_window_for returns a positive int for a catalog-known model."""
        result = context_window_for("google", "gemini-3.1-pro-preview")
        assert isinstance(result, int)
        assert result > 0

    def test_known_anthropic_model(self) -> None:
        """context_window_for returns a positive int for a known Anthropic model."""
        result = context_window_for("anthropic", "claude-opus-4-0")
        assert result > 0

    def test_unknown_model_returns_zero(self) -> None:
        """context_window_for returns 0 for a model not in any source."""
        result = context_window_for("google", "this-model-does-not-exist-xyz")
        assert result == 0

    def test_unknown_provider_returns_zero(self) -> None:
        """context_window_for returns 0 for an unknown provider."""
        result = context_window_for("unknown-provider", "some-model")
        assert result == 0

    @pytest.mark.parametrize("provider,model", _all_offered_models())
    def test_all_catalog_models_have_positive_window(self, provider: str, model: str) -> None:
        """context_window_for returns > 0 for every MODEL_CAPABILITIES entry."""
        result = context_window_for(provider, model)
        assert result > 0, (
            f"Expected positive context_window for {provider}/{model}, got {result}"
        )


# -- context_window_variants_for tests ----------------------------------------

class TestContextWindowVariantsFor:
    def test_returns_empty_list_for_unknown_model(self) -> None:
        """context_window_variants_for returns [] for a model not in CONTEXT_WINDOW_VARIANTS."""
        from koan.agents.model_catalog import context_window_variants_for
        assert context_window_variants_for("anthropic", "some-unknown-model") == []

    def test_returns_empty_list_for_current_catalog_models(self) -> None:
        """No current catalog model advertises a context-window variant."""
        from koan.agents.model_catalog import context_window_variants_for
        for provider, model in _all_offered_models():
            result = context_window_variants_for(provider, model)
            assert isinstance(result, list)

    def test_reflects_injected_variant(self) -> None:
        """context_window_variants_for returns the variant list when one is injected."""
        from koan.agents import model_catalog
        original = dict(model_catalog.CONTEXT_WINDOW_VARIANTS)
        model_catalog.CONTEXT_WINDOW_VARIANTS[("anthropic", "test-model")] = [1_000_000]
        try:
            result = model_catalog.context_window_variants_for("anthropic", "test-model")
            assert result == [1_000_000]
        finally:
            model_catalog.CONTEXT_WINDOW_VARIANTS.clear()
            model_catalog.CONTEXT_WINDOW_VARIANTS.update(original)


# -- supports_prompt_caching tests --------------------------------------------

class TestSupportsPromptCaching:
    def test_anthropic_returns_true(self) -> None:
        """Anthropic supports explicit prompt-caching settings."""
        from koan.agents.model_catalog import supports_prompt_caching
        for _provider, model in _all_offered_models():
            if _provider == "anthropic":
                assert supports_prompt_caching("anthropic", model) is True

    def test_non_anthropic_returns_false(self) -> None:
        """Google, OpenAI, Bedrock, lmstudio, and voyage return False."""
        from koan.agents.model_catalog import supports_prompt_caching
        for provider in ("google", "openai", "bedrock", "lmstudio", "voyage"):
            assert supports_prompt_caching(provider, "any-model") is False

    def test_unknown_provider_returns_false(self) -> None:
        """Unknown provider returns False (graceful fallthrough, brief D5)."""
        from koan.agents.model_catalog import supports_prompt_caching
        assert supports_prompt_caching("unknown-provider", "some-model") is False
