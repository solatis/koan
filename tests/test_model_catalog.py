# Validating tests for koan/agents/model_catalog.py.
#
# Enforces two invariants:
#   1. Every (provider, model) in MODEL_CAPABILITIES resolves in the genai-prices
#      bundled snapshot -- price_for_usage succeeds and returns a positive Decimal.
#   2. build_model_registry() returns one ModelRegistryEntry per capability entry.
#
# context_window removed (hard cutover): koan does not enforce a context budget;
# the provider errors if context is exceeded (accepted behavior).

from __future__ import annotations

from decimal import Decimal

import pytest

from koan.agents.model_catalog import (
    MODEL_CAPABILITIES,
    PROVIDER_ID_MAP,
    build_model_registry,
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

    def test_openrouter_price_resolves(self) -> None:
        """price_for_usage resolves cost for an openrouter model via PROVIDER_ID_MAP.

        openrouter maps to the bundled 'openrouter' genai-prices provider which
        resolves namespaced vendor/model ids (e.g. 'anthropic/claude-3.5-sonnet').
        No MODEL_CAPABILITIES entry is required -- the snapshot handles it.
        """
        result = price_for_usage(
            "openrouter", "anthropic/claude-3.5-sonnet",
            input_tokens=1000, output_tokens=500,
        )
        assert isinstance(result, Decimal)
        assert result > 0


# -- Model registry tests -----------------------------------------------------

class TestBuildModelRegistry:
    def test_returns_one_entry_per_capability(self) -> None:
        """build_model_registry returns exactly one ModelRegistryEntry per MODEL_CAPABILITIES entry."""
        registry = build_model_registry()
        assert len(registry) == len(MODEL_CAPABILITIES), (
            f"Expected {len(MODEL_CAPABILITIES)} entries, got {len(registry)}"
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


# -- supports_prompt_caching tests --------------------------------------------

class TestSupportsPromptCaching:
    def test_anthropic_returns_true(self) -> None:
        """Anthropic Claude models support explicit prompt-caching settings."""
        from koan.agents.model_catalog import supports_prompt_caching
        for _provider, model in _all_offered_models():
            if _provider == "anthropic":
                assert supports_prompt_caching("anthropic", model) is True

    def test_non_anthropic_returns_false(self) -> None:
        """Google, OpenAI, openrouter, and voyage return False for any model."""
        from koan.agents.model_catalog import supports_prompt_caching
        for provider in ("google", "openai", "openrouter", "voyage"):
            assert supports_prompt_caching(provider, "any-model") is False

    def test_unknown_provider_returns_false(self) -> None:
        """Unknown provider returns False (graceful fallthrough, brief D5)."""
        from koan.agents.model_catalog import supports_prompt_caching
        assert supports_prompt_caching("unknown-provider", "some-model") is False

    def test_bedrock_claude_returns_true(self) -> None:
        """Bedrock-hosted Claude models return True (family-scoped, transport-aware)."""
        from koan.agents.model_catalog import supports_prompt_caching
        assert supports_prompt_caching("bedrock", "anthropic.claude-opus-4-0") is True

    def test_bedrock_nova_returns_false(self) -> None:
        """Bedrock-hosted Nova models return False (not in _EXPLICIT_CACHE_FAMILIES)."""
        from koan.agents.model_catalog import supports_prompt_caching
        assert supports_prompt_caching("bedrock", "amazon.nova-pro-v1:0") is False

    def test_cache_read_expected(self) -> None:
        """cache_read_expected covers all four caching-capable routes and excludes the rest."""
        from koan.agents.model_catalog import cache_read_expected
        # Explicit-caching routes (koan-managed).
        assert cache_read_expected("anthropic", "claude-sonnet-4-5") is True
        assert cache_read_expected("bedrock", "anthropic.claude-opus-4-0") is True
        # Automatic server-side caching routes.
        assert cache_read_expected("google", "gemini-3.5-flash") is True
        assert cache_read_expected("openai", "gpt-4o") is True
        # Excluded routes.
        assert cache_read_expected("openrouter", "anthropic/claude-3.5-sonnet") is False
        assert cache_read_expected("bedrock", "amazon.nova-pro-v1:0") is False


# -- Hard-cutover: removed symbols must not exist -----------------------------

class TestRemovedSymbols:
    def test_lmstudio_default_context_window_not_importable(self) -> None:
        """LMSTUDIO_DEFAULT_CONTEXT_WINDOW must not exist in koan.agents.model_catalog."""
        import importlib
        catalog = importlib.import_module("koan.agents.model_catalog")
        assert not hasattr(catalog, "LMSTUDIO_DEFAULT_CONTEXT_WINDOW"), (
            "LMSTUDIO_DEFAULT_CONTEXT_WINDOW was re-introduced; "
            "this symbol was removed as a hard cutover"
        )

    def test_context_window_for_not_importable(self) -> None:
        """context_window_for must not exist in koan.agents.model_catalog (hard cutover)."""
        import importlib
        catalog = importlib.import_module("koan.agents.model_catalog")
        assert not hasattr(catalog, "context_window_for"), (
            "context_window_for was re-introduced; hard cutover requires permanent removal"
        )

    def test_context_window_variants_for_not_importable(self) -> None:
        """context_window_variants_for must not exist in koan.agents.model_catalog (hard cutover)."""
        import importlib
        catalog = importlib.import_module("koan.agents.model_catalog")
        assert not hasattr(catalog, "context_window_variants_for"), (
            "context_window_variants_for was re-introduced; hard cutover requires permanent removal"
        )

    def test_context_window_variants_not_importable(self) -> None:
        """CONTEXT_WINDOW_VARIANTS must not exist in koan.agents.model_catalog (hard cutover)."""
        import importlib
        catalog = importlib.import_module("koan.agents.model_catalog")
        assert not hasattr(catalog, "CONTEXT_WINDOW_VARIANTS"), (
            "CONTEXT_WINDOW_VARIANTS was re-introduced; hard cutover requires permanent removal"
        )
