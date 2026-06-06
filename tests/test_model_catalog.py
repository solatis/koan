# Validating tests for koan/agents/model_catalog.py.
#
# Enforces two invariants introduced in Milestone 2:
#   1. Every (provider, model) in MODEL_CAPABILITIES AND every model referenced
#      by the built-in profiles (_GEMINI_TIER_SPECS + _GEMINI_FRONTIER_SPECS)
#      resolves in the genai-prices bundled snapshot -- price_for_usage succeeds
#      and returns a positive Decimal (brief decision 4, "validate it").
#   2. build_model_registry() returns one ModelRegistryEntry per capability entry,
#      each with a positive (never null) context_window.
#
# If either invariant fails, the executor MUST replace the offending model ID with
# a snapshot-resolvable ID for the same tier before shipping.

from __future__ import annotations

from decimal import Decimal

import pytest

from koan.agents.model_catalog import (
    MODEL_CAPABILITIES,
    PROVIDER_ID_MAP,
    build_model_registry,
    price_for_usage,
)
from koan.agents.registry import (
    _GEMINI_FRONTIER_SPECS,
    _GEMINI_TIER_SPECS,
)


# -- Helpers ------------------------------------------------------------------

def _all_offered_models() -> list[tuple[str, str]]:
    """Enumerate every (provider, model) in MODEL_CAPABILITIES."""
    return list(MODEL_CAPABILITIES.keys())


def _all_builtin_profile_models() -> list[tuple[str, str]]:
    """Enumerate every (provider, model) referenced by the built-in Gemini profiles."""
    pairs: list[tuple[str, str]] = []
    for model_id, _thinking, _ctx in _GEMINI_TIER_SPECS.values():
        pairs.append(("google", model_id))
    for model_id, _thinking, _ctx in _GEMINI_FRONTIER_SPECS.values():
        pairs.append(("google", model_id))
    return pairs


# -- Price resolution tests ---------------------------------------------------

class TestPriceForUsage:
    @pytest.mark.parametrize("provider,model", _all_offered_models())
    def test_offered_model_price_resolves(self, provider: str, model: str) -> None:
        """price_for_usage succeeds and returns a positive Decimal for every catalog model."""
        result = price_for_usage(provider, model, input_tokens=1000, output_tokens=500)
        assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"
        assert result > 0, f"Expected positive price for {provider}/{model}, got {result}"

    @pytest.mark.parametrize("provider,model", _all_builtin_profile_models())
    def test_builtin_profile_model_price_resolves(self, provider: str, model: str) -> None:
        """price_for_usage succeeds and returns a positive Decimal for every built-in profile model."""
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
