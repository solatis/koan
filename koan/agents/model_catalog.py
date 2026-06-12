# All-providers model catalog: capability table, registry builder, and price mapping.
#
# Design:
#   - MODEL_CAPABILITIES is the koan-owned source of which models are offered and their
#     thinking modes / tier hints. Every entry must resolve in the genai-prices bundled
#     snapshot (the validating test enforces this).
#   - build_model_registry() joins MODEL_CAPABILITIES with the genai-prices bundled
#     snapshot to get context_window and display_name. It never triggers network access
#     or UpdatePrices; fold determinism requires bundled-snapshot-only pricing.
#   - price_for_usage() is the single cost-derivation entry point for Milestone 5's
#     usage gauges. Pure function: bundled snapshot, no network.

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from ..types import ModelRegistryEntry, ModelTier, ThinkingMode

# koan provider id -> genai-prices provider id.
# "bedrock" maps to "aws" because genai-prices names the Amazon Bedrock provider "aws".
PROVIDER_ID_MAP: dict[str, str] = {
    "google":    "google",
    "anthropic": "anthropic",
    "openai":    "openai",
    "bedrock":   "aws",
}

# Capability table: (provider, model) -> (thinking_modes, tier_hint, context_window_fallback, fallback_display_name).
#
# Every entry here MUST resolve in the genai-prices bundled snapshot; the test in
# tests/test_model_catalog.py enforces this. If a model does not resolve, replace it
# with a snapshot-resolvable ID for that tier before shipping.
#
# context_window_fallback is used when the snapshot entry has a null context_window
# (genai-prices ModelInfo.context_window is nullable). For Gemini tiers the fallback
# matches _GEMINI_TIER_SPECS (1_000_000). For other providers it is a known-good value
# sourced from official provider documentation.
#
# fallback_display_name is used when the snapshot entry has no name (or an ugly
# auto-generated name). snapshot m.name takes precedence when non-empty.
MODEL_CAPABILITIES: dict[
    tuple[str, str],
    tuple[list[ThinkingMode], "ModelTier | None", int, str],
] = {
    # Google -- model IDs here must be genai-prices-resolvable (versioned form).
    # gemini-3.1-pro-preview has a null context_window in the 0.0.64 snapshot, so
    # the 1_000_000 koan-owned fallback is required (the registry test asserts > 0).
    ("google", "gemini-3.1-pro-preview"): (["medium", "high"], "strong",   1_000_000, "Gemini 3.1 Pro Preview"),
    ("google", "gemini-3.5-flash"):       (["low", "medium"],  "standard", 1_000_000, "Gemini 3.5 Flash"),
    ("google", "gemini-3.1-flash-lite"):  ([],                 "cheap",    1_000_000, "Gemini 3.1 Flash Lite"),
    # Anthropic -- extended thinking supported on Opus and Sonnet tiers.
    ("anthropic", "claude-opus-4-0"):         (["medium", "high"], "strong",   200_000,   "Claude Opus 4"),
    ("anthropic", "claude-sonnet-4-5"):       (["low", "medium"],  "standard", 1_000_000, "Claude Sonnet 4.5"),
    ("anthropic", "claude-3-5-haiku-latest"): ([],                 "cheap",    200_000,   "Claude Haiku 3.5"),
    # OpenAI -- no koan thinking modes (o-series reasoning is opaque to the adapter).
    ("openai", "gpt-4o"):      ([], "strong",   128_000,   "GPT-4o"),
    ("openai", "gpt-4o-mini"): ([], "standard", 128_000,   "GPT-4o Mini"),
    ("openai", "gpt-4.1-nano"):([], "cheap",    1_000_000, "GPT-4.1 Nano"),
    # Bedrock (AWS) -- thinking is profile-driven per underlying model; no koan modes.
    ("bedrock", "amazon.nova-pro-v1:0"):   ([], "strong",   128_000, "Amazon Nova Pro"),
    ("bedrock", "amazon.nova-lite-v1:0"):  ([], "standard", 32_000,  "Amazon Nova Lite"),
    ("bedrock", "amazon.nova-micro-v1:0"): ([], "cheap",    32_000,  "Amazon Nova Micro"),
}


def _snapshot_model_info(provider: str, model: str):
    """Look up (provider, model) in the genai-prices bundled snapshot.

    Returns (m.name, m.context_window) -- both may be None if absent.
    Raises ValueError when the model is not found; the caller decides how to handle it.
    Uses the bundled snapshot only; never triggers network access or UpdatePrices.
    """
    from genai_prices.data_snapshot import get_snapshot
    genai_provider = PROVIDER_ID_MAP.get(provider, provider)
    snap = get_snapshot()
    snap_provider, snap_model = snap.find_provider_model(model, None, genai_provider, None)
    return snap_model.name, snap_model.context_window


def build_model_registry() -> list[ModelRegistryEntry]:
    """Build the all-providers model registry from MODEL_CAPABILITIES + genai-prices snapshot.

    For each capability entry, looks up context_window and display_name in the bundled
    genai-prices snapshot. context_window resolves as: snapshot value when non-null, else
    the koan-authoritative fallback from MODEL_CAPABILITIES. display_name resolves as:
    snapshot model name when non-empty, else the fallback_display_name from MODEL_CAPABILITIES.

    Never triggers network access or UpdatePrices (bundled snapshot only, fold determinism).
    Returns one ModelRegistryEntry per capability entry; never silently skips entries.
    """
    entries: list[ModelRegistryEntry] = []
    for (provider, model), (thinking_modes, tier_hint, ctx_fallback, display_fallback) in MODEL_CAPABILITIES.items():
        snap_name, snap_ctx = _snapshot_model_info(provider, model)

        # Prefer snapshot values; fall back to koan-authoritative values.
        # context_window must never be null in the registry (the fold depends on it).
        display_name = snap_name if snap_name else display_fallback
        context_window = snap_ctx if snap_ctx is not None else ctx_fallback

        entries.append(ModelRegistryEntry(
            provider=provider,
            model=model,
            display_name=display_name,
            context_window=context_window,
            thinking_modes=list(thinking_modes),
            tier_hint=tier_hint,
        ))
    return entries


# Selectable context-window variants beyond the base window, per (provider, model).
# A non-empty list means the user may opt in to a larger window; the adapter
# emits the provider-specific opt-in (e.g. an Anthropic beta header) when a
# variant is selected (brief D4 / M2 plan step 3).
# Currently empty: no catalog model needs a beta opt-in beyond its native base
# window.  Add entries here when a model gains an opt-in extended context.
CONTEXT_WINDOW_VARIANTS: dict[tuple[str, str], list[int]] = {}


def context_window_variants_for(provider: str, model: str) -> list[int]:
    """Return selectable larger context-window variants for (provider, model).

    Returns an empty list when no variant is available.  Source is the koan-owned
    CONTEXT_WINDOW_VARIANTS table (bundled knowledge, not PydanticAI).  Empty /
    false-on-unknown is the contract -- never raises.
    """
    return list(CONTEXT_WINDOW_VARIANTS.get((provider, model), []))


# Providers where koan manages explicit prompt-caching settings (i.e. the provider
# exposes a cache-control mechanism that koan can turn on/off).  Google and OpenAI
# cache automatically server-side and need no settings; bedrock has no portable
# cache knob; lmstudio/voyage are local/embedding providers.
_PROMPT_CACHING_PROVIDERS: frozenset[str] = frozenset({"anthropic"})


def supports_prompt_caching(provider: str, model: str) -> bool:
    """Return True when koan manages explicit prompt-caching settings for (provider, model).

    Source is the koan-owned _PROMPT_CACHING_PROVIDERS set.  Google/OpenAI cache
    automatically server-side (no settings to emit); bedrock/lmstudio/voyage have
    no portable cache knob.  Returns False for unknown providers (brief D5).
    """
    return provider in _PROMPT_CACHING_PROVIDERS


def context_window_for(provider: str, model: str) -> int:
    """Return the context window size for (provider, model) from the bundled snapshot.

    Resolution order: (1) MODEL_CAPABILITIES koan fallback, (2) bundled
    genai-prices snapshot.  Returns 0 when the model is not found in either
    source.  LM Studio is absent from both sources and therefore resolves to 0;
    an explicit ConfiguredModel.context_window must be supplied by the caller
    for a non-zero window on lmstudio models (hard cutover -- no shim).
    Never triggers network access (fold determinism -- bundled snapshot only).
    """
    # Check koan's capability table first (has authoritative fallbacks for
    # models whose genai-prices snapshot entry has a null context_window).
    cap = MODEL_CAPABILITIES.get((provider, model))
    if cap is not None:
        _thinking_modes, _tier_hint, ctx_fallback, _display = cap
        # Try the snapshot for a non-null value; fall back to koan's fallback.
        try:
            _name, snap_ctx = _snapshot_model_info(provider, model)
            if snap_ctx is not None:
                return int(snap_ctx)
        except Exception:
            pass
        return ctx_fallback

    # Not in capability table -- attempt snapshot lookup only.
    try:
        _name, snap_ctx = _snapshot_model_info(provider, model)
        if snap_ctx is not None:
            return int(snap_ctx)
    except Exception:
        pass

    # Unknown model: return 0; the caller should treat this as "unresolvable".
    return 0


def price_for_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """Calculate cost for a model request from the genai-prices bundled snapshot.

    The single cost-derivation entry point for koan. Pure function: reads the bundled
    snapshot only, never triggers network access or UpdatePrices (fold determinism
    requires reproducible cost computation from the same event data).

    Returns the total price as a Decimal (never negative; raises on unresolvable model).
    """
    import genai_prices
    genai_provider = PROVIDER_ID_MAP[provider]
    usage = genai_prices.Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens if cache_read_tokens else None,
        cache_write_tokens=cache_write_tokens if cache_write_tokens else None,
    )
    result = genai_prices.calc_price(usage, model_ref=model, provider_id=genai_provider)
    return Decimal(str(result.total_price))
