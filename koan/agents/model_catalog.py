# All-providers model catalog: capability table, registry builder, and price mapping.
#
# Design:
#   - MODEL_CAPABILITIES is the koan-owned source of which models are offered and their
#     thinking modes. Every entry must resolve in the genai-prices bundled
#     snapshot (the validating test enforces this).
#   - build_model_registry() joins MODEL_CAPABILITIES with the genai-prices bundled
#     snapshot to get display_name. It never triggers network access or UpdatePrices;
#     fold determinism requires bundled-snapshot-only pricing.
#   - price_for_usage() is the single cost-derivation entry point for Milestone 5's
#     usage gauges. Pure function: bundled snapshot, no network.
#   - koan does not track per-model context windows; each provider enforces its own context limit.

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from ..types import ModelRegistryEntry, ThinkingMode
from .recognition import parse_model_id

# koan provider id -> genai-prices provider id.
# "bedrock" maps to "aws" because genai-prices names the Amazon Bedrock provider "aws".
# "openrouter" maps to "openrouter": the bundled snapshot carries an openrouter
# provider that resolves namespaced vendor/model ids directly (no curated entries
# needed; cost derivation works via the snapshot's full model list).
PROVIDER_ID_MAP: dict[str, str] = {
    "google":      "google",
    "anthropic":   "anthropic",
    "openai":      "openai",
    "bedrock":     "aws",
    "openrouter":  "openrouter",
}

# Capability table: (provider, model) -> (thinking_modes, fallback_display_name).
#
# Every entry here MUST resolve in the genai-prices bundled snapshot; the test in
# tests/test_model_catalog.py enforces this. If a model does not resolve, replace it
# with a snapshot-resolvable ID for that tier before shipping.
#
# fallback_display_name is used when the snapshot entry has no name (or an ugly
# auto-generated name). snapshot m.name takes precedence when non-empty.
#
MODEL_CAPABILITIES: dict[
    tuple[str, str],
    tuple[list[ThinkingMode], str],
] = {
    # Google -- model IDs here must be genai-prices-resolvable (versioned form).
    ("google", "gemini-3.1-pro-preview"): (["medium", "high"], "Gemini 3.1 Pro Preview"),
    ("google", "gemini-3.5-flash"):       (["low", "medium"],  "Gemini 3.5 Flash"),
    ("google", "gemini-3.1-flash-lite"):  ([],                 "Gemini 3.1 Flash Lite"),
    # Anthropic -- extended thinking supported on Opus and Sonnet tiers.
    ("anthropic", "claude-opus-4-0"):         (["medium", "high"], "Claude Opus 4"),
    ("anthropic", "claude-sonnet-4-5"):       (["low", "medium"],  "Claude Sonnet 4.5"),
    # Sonnet 5: budget-based thinking (same shape as 4.5); intro pricing $2/$10 per M tokens.
    ("anthropic", "claude-sonnet-5"):         (["low", "medium"],  "Claude Sonnet 5"),
    # Fable 5: adaptive thinking only (effort/xhigh in profile); $10/$50 per M tokens.
    ("anthropic", "claude-fable-5"):          (["low", "medium", "high", "xhigh"], "Claude Fable 5"),
    ("anthropic", "claude-3-5-haiku-latest"): ([],                 "Claude Haiku 3.5"),
    # OpenAI -- no koan thinking modes (o-series reasoning is opaque to the adapter).
    ("openai", "gpt-4o"):      ([], "GPT-4o"),
    ("openai", "gpt-4o-mini"): ([], "GPT-4o Mini"),
    ("openai", "gpt-4.1-nano"):([], "GPT-4.1 Nano"),
    # Bedrock (AWS) -- thinking is profile-driven per underlying model; no koan modes.
    ("bedrock", "amazon.nova-pro-v1:0"):   ([], "Amazon Nova Pro"),
    ("bedrock", "amazon.nova-lite-v1:0"):  ([], "Amazon Nova Lite"),
    ("bedrock", "amazon.nova-micro-v1:0"): ([], "Amazon Nova Micro"),
}


# Default per-request OUTPUT-token budget (max_tokens). Set explicitly because
# pydantic-ai applies a low provider default when it is unset -- notably a
# hardcoded 4096 for Anthropic (pydantic_ai/models/anthropic.py) -- which an
# adaptive-thinking model can exhaust on thinking alone, producing zero response
# text. 32768 leaves ample room after thinking; it is clamped per model below
# where a model's hard cap is lower. This is the OUTPUT ceiling, unrelated to the
# input context window.
DEFAULT_MAX_OUTPUT_TOKENS = 32768

# Per-model hard output-token caps, listed ONLY for models whose maximum output
# is below DEFAULT_MAX_OUTPUT_TOKENS. Providers reject (HTTP 400) a max_tokens
# above the model cap, so these values must never exceed the true cap. Any
# (provider, model) not listed here -- including uncataloged or dynamic ids
# (openrouter, ollama-cloud) -- takes DEFAULT_MAX_OUTPUT_TOKENS. Values verified
# against provider docs (see plan.md decision 5).
MODEL_MAX_OUTPUT_TOKENS: dict[tuple[str, str], int] = {
    ("anthropic", "claude-3-5-haiku-latest"): 8192,
    ("anthropic", "claude-opus-4-0"):         32000,
    ("openai",    "gpt-4o"):                  16384,
    ("openai",    "gpt-4o-mini"):             16384,
    ("bedrock",   "amazon.nova-pro-v1:0"):    5120,
    ("bedrock",   "amazon.nova-lite-v1:0"):   5120,
    ("bedrock",   "amazon.nova-micro-v1:0"):  5120,
}


def max_output_tokens_for(provider: str, model: str) -> int:
    """Return the max_tokens output budget for (provider, model), clamped to the model cap.

    Returns min(DEFAULT_MAX_OUTPUT_TOKENS, cap), where cap is the model's hard
    output limit from MODEL_MAX_OUTPUT_TOKENS, or DEFAULT_MAX_OUTPUT_TOKENS when
    the pair is not listed (the model supports at least the default, or koan has
    no cap data for it -- e.g. openrouter / ollama-cloud / uncataloged ids).
    Pure function: no I/O, deterministic per (provider, model) so the value is
    stable across turns and never perturbs the cacheable prompt prefix.
    """
    cap = MODEL_MAX_OUTPUT_TOKENS.get((provider, model), DEFAULT_MAX_OUTPUT_TOKENS)
    return min(DEFAULT_MAX_OUTPUT_TOKENS, cap)


def _snapshot_model_info(provider: str, model: str) -> str | None:
    """Look up (provider, model) in the genai-prices bundled snapshot.

    Returns the snapshot model name, or None if absent.
    Raises ValueError when the model is not found; the caller decides how to handle it.
    Uses the bundled snapshot only; never triggers network access or UpdatePrices.
    """
    from genai_prices.data_snapshot import get_snapshot
    genai_provider = PROVIDER_ID_MAP.get(provider, provider)
    snap = get_snapshot()
    snap_provider, snap_model = snap.find_provider_model(model, None, genai_provider, None)
    return snap_model.name


def build_model_registry() -> list[ModelRegistryEntry]:
    """Build the all-providers model registry from MODEL_CAPABILITIES + genai-prices snapshot.

    For each capability entry, looks up display_name in the bundled genai-prices snapshot.
    display_name resolves as: snapshot model name when non-empty, else the
    fallback_display_name from MODEL_CAPABILITIES.

    Never triggers network access or UpdatePrices (bundled snapshot only, fold determinism).
    Returns one ModelRegistryEntry per capability entry; never silently skips entries.
    """
    entries: list[ModelRegistryEntry] = []
    for (provider, model), (thinking_modes, display_fallback) in MODEL_CAPABILITIES.items():
        snap_name = _snapshot_model_info(provider, model)

        # Prefer snapshot display name; fall back to koan-authoritative fallback.
        display_name = snap_name if snap_name else display_fallback

        entries.append(ModelRegistryEntry(
            provider=provider,
            model=model,
            display_name=display_name,
            thinking_modes=list(thinking_modes),
        ))
    return entries


# Connection transports for which koan emits explicit cache-control settings.
# Keyed on transport (not model family) because Bedrock-Claude needs the Bedrock
# keys, not the Anthropic keys -- the transport selects the mechanism.
_EXPLICIT_CACHE_TRANSPORTS: frozenset[str] = frozenset({"anthropic", "bedrock"})

# Model families that support explicit prompt caching (Anthropic Claude family),
# regardless of which transport serves them. Bedrock-Nova is excluded by
# family-scoping: only Claude models get cache-control settings emitted.
_EXPLICIT_CACHE_FAMILIES: frozenset[str] = frozenset(
    {"claude-opus", "claude-sonnet", "claude-haiku", "claude-fable"}
)

# Providers that cache automatically server-side (no koan-emitted settings needed).
# Policed by the runtime guard because they still report cache_read_tokens.
_AUTOMATIC_CACHE_PROVIDERS: frozenset[str] = frozenset({"google", "openai"})


def supports_prompt_caching(provider: str, model: str) -> bool:
    """Return True when koan manages explicit prompt-caching settings for (provider, model).

    Caching capability is keyed on (transport, family) rather than the raw provider
    string so that Bedrock-hosted Claude models are included while Bedrock-Nova,
    Google, OpenAI, and OpenRouter are excluded (brief Decision 5).

    Returns True only when:
      - provider is in _EXPLICIT_CACHE_TRANSPORTS (anthropic or bedrock), AND
      - the parsed model family is in _EXPLICIT_CACHE_FAMILIES (Claude families).

    parse_model_id strips the Bedrock "anthropic." vendor prefix, so
    "anthropic.claude-opus-4-0" resolves to family "claude-opus" correctly.
    Returns False for unknown providers or models not matching a Claude family.
    """
    if provider not in _EXPLICIT_CACHE_TRANSPORTS:
        return False
    return parse_model_id(model).family in _EXPLICIT_CACHE_FAMILIES


def cache_read_expected(provider: str, model: str) -> bool:
    """Return True when this route should produce cache_read_tokens at volume.

    This is the runtime guard's scope predicate (brief Decision 2): covers all
    four first-class caching routes -- koan-managed explicit caching (Anthropic
    and Bedrock-Claude via supports_prompt_caching) AND provider automatic
    server-side caching (Google, OpenAI). OpenRouter and Voyage are excluded
    because they are not cache-expected from koan's perspective. Bedrock-Nova
    is excluded because supports_prompt_caching returns False for it.

    Used by check_cache_effectiveness to decide whether to apply the fail-fast
    guard for a given (provider, model) pair.
    """
    return supports_prompt_caching(provider, model) or provider in _AUTOMATIC_CACHE_PROVIDERS



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
    Providers without a PROVIDER_ID_MAP entry (e.g. ollama-cloud) raise ValueError,
    which the projection fold catches -- cost is kept at 0 for those providers.
    """
    import genai_prices
    genai_provider = PROVIDER_ID_MAP.get(provider)
    if genai_provider is None:
        # Explicit ValueError over an incidental KeyError: makes the intentional
        # absence of pricing for some providers (e.g. ollama-cloud) clear to callers.
        raise ValueError(f"no genai-prices mapping for provider {provider!r}")
    usage = genai_prices.Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens if cache_read_tokens else None,
        cache_write_tokens=cache_write_tokens if cache_write_tokens else None,
    )
    result = genai_prices.calc_price(usage, model_ref=model, provider_id=genai_provider)
    return Decimal(str(result.total_price))
