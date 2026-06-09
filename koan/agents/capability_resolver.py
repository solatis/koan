# Capability resolver: wraps and extends the PydanticAI model profile (brief D4/D5).
#
# Split of responsibility:
#   - PydanticAI profile    -> thinking-shape, web-search, tool/json support
#   - koan bundled catalog  -> context-window, context-window variants, prompt-caching
#   - koan recognition      -> family / tier_hint / version
#
# resolve_capabilities is a pure function over (provider_type, model_id).  It is
# cheap enough to call on every model build; results may optionally be memoized
# by the caller (e.g. in ProviderConfigState) for repeated lookups.
#
# An unrecognized model id or a missing profile field degrades to conservative
# defaults + a logged warning -- never a hard failure (brief D5).

from __future__ import annotations

from typing import Literal

from ..logger import get_logger
from ..types import ModelTier, ResolvedCapabilities, ThinkingMode

log = get_logger("capability_resolver")

# All koan ThinkingModes in rank order (mirrors registry._THINKING_RANK).
_ALL_THINKING_MODES: list[ThinkingMode] = ["disabled", "low", "medium", "high", "xhigh", "max"]

# Conservative default set for models that support thinking but whose catalog
# entry does not enumerate supported modes.  Excludes xhigh/max because those
# require explicit per-model confirmation.
_DEFAULT_THINKING_MODES: list[ThinkingMode] = ["low", "medium", "high"]


# -- Profile resolution -------------------------------------------------------

def _get_pydantic_ai_profile(provider_type: str, model_id: str) -> dict:
    """Get the merged PydanticAI ModelProfile dict for a given (provider, model).

    Uses per-provider profile functions (no `infer_model_profile` in the
    installed package).  For bedrock, strips the vendor prefix and delegates to
    the underlying family's profile function.  Returns {} on any import/runtime
    error so callers degrade gracefully (brief D5).
    """
    try:
        if provider_type == "anthropic":
            from pydantic_ai.profiles.anthropic import anthropic_model_profile
            return anthropic_model_profile(model_id) or {}

        if provider_type == "google":
            from pydantic_ai.profiles.google import google_model_profile
            return google_model_profile(model_id) or {}

        if provider_type == "openai" or provider_type == "lmstudio":
            # lmstudio is an OpenAI-compatible server; use the OpenAI profile for
            # web-search / tool capability flags but it has no thinking support.
            from pydantic_ai.profiles.openai import openai_model_profile
            return openai_model_profile(model_id) or {}

        if provider_type == "bedrock":
            # Bedrock hosts models from multiple vendors; delegate to the vendor
            # profile based on the model id prefix so thinking / tool caps are
            # correctly resolved for the underlying model family.
            if model_id.startswith("anthropic."):
                from pydantic_ai.profiles.anthropic import anthropic_model_profile
                underlying = model_id[len("anthropic."):]
                return anthropic_model_profile(underlying) or {}
            if model_id.startswith("amazon."):
                from pydantic_ai.profiles.amazon import amazon_model_profile
                return amazon_model_profile(model_id) or {}
            # Other bedrock families (meta, cohere, ...) fall through to empty.
            return {}

        # voyage and unrecognized providers have no thinking or web-search profile.
        return {}

    except Exception as exc:
        log.warning("failed to load pydantic_ai profile for %s/%s: %s", provider_type, model_id, exc)
        return {}


# -- Thinking shape derivation ------------------------------------------------

def _derive_thinking_shape(
    provider_type: str,
    profile: dict,
) -> Literal["budget", "effort", "adaptive", "none"]:
    """Derive the thinking_shape for a (provider, profile) pair.

    - anthropic: adaptive > effort > budget (per profile flags, brief D4)
    - openai: effort when openai_supports_reasoning, else none
    - google: budget (pydantic_ai maps thinking_budget to thinking_level internally
              for Gemini 3+ models, so budget is the correct koan-level shape)
    - bedrock: inherit from the underlying provider; defaults to none for non-
               anthropic bedrock models where the profile is returned as-is
    - lmstudio / voyage / unknown: none
    """
    if not profile.get("supports_thinking", False):
        return "none"

    if provider_type in ("anthropic",) or (
        provider_type == "bedrock" and profile.get("anthropic_supports_adaptive_thinking") is not None
    ):
        if profile.get("anthropic_supports_adaptive_thinking", False):
            return "adaptive"
        if profile.get("anthropic_supports_effort", False):
            return "effort"
        return "budget"

    if provider_type == "openai":
        if profile.get("openai_supports_reasoning", False):
            return "effort"
        return "none"

    if provider_type == "google":
        return "budget"

    return "none"


def _infer_thinking_modes(
    shape: Literal["budget", "effort", "adaptive", "none"],
    catalog_modes: list[ThinkingMode] | None,
) -> list[ThinkingMode]:
    """Derive the koan ThinkingMode list from the thinking shape.

    Uses catalog_modes when available (the precise per-model list from
    MODEL_CAPABILITIES).  Falls back to the conservative default set for
    recognized-but-uncataloged thinking models, and [] for shape="none".
    """
    if catalog_modes is not None:
        return list(catalog_modes)
    if shape == "none":
        return []
    return list(_DEFAULT_THINKING_MODES)


# -- Web-search support -------------------------------------------------------

def _derive_web_search(provider_type: str, profile: dict) -> bool:
    """Derive whether the (provider, model) supports web search.

    Only OpenAI's chat search-preview models expose a profile flag; Anthropic
    supports web search via native tools but the profile carries no boolean flag
    for it.  We return False conservatively for all other providers.
    """
    if provider_type == "openai":
        return bool(profile.get("openai_chat_supports_web_search", False))
    return False


# -- Main entry point ---------------------------------------------------------

def resolve_capabilities(provider_type: str, model_id: str) -> ResolvedCapabilities:
    """Resolve read-only capabilities for a (connection.type, model_id) pair.

    Joins three sources (brief D4/D5):
      1. PydanticAI model profile -- thinking-shape, web-search, tool/json
      2. koan bundled knowledge   -- context-window, variants, prompt-caching
      3. koan recognition parse   -- family / tier_hint / version

    Never raises: an unrecognized model id or a missing profile field degrades
    to conservative defaults and a logged warning (brief D5).

    Args:
        provider_type: koan ProviderType string (e.g. "anthropic", "google").
        model_id:      The pinned model id (e.g. "claude-sonnet-4-5").

    Returns:
        ResolvedCapabilities with all fields populated; recognized=False when
        the model id is not in the recognition table.
    """
    from .model_catalog import (
        MODEL_CAPABILITIES,
        context_window_for,
        context_window_variants_for,
        supports_prompt_caching,
    )
    from .recognition import parse_model_id

    profile = _get_pydantic_ai_profile(provider_type, model_id)
    parsed = parse_model_id(model_id)

    if not parsed.recognized:
        log.warning(
            "unrecognized model id '%s' (provider '%s') -- falling back to conservative defaults",
            model_id,
            provider_type,
        )

    # Thinking shape and modes.
    thinking_shape = _derive_thinking_shape(provider_type, profile)

    # Prefer the catalog's explicit thinking_modes list when available.
    catalog_entry = MODEL_CAPABILITIES.get((provider_type, model_id))
    catalog_modes: list[ThinkingMode] | None = (
        list(catalog_entry[0]) if catalog_entry is not None else None
    )
    thinking_modes = _infer_thinking_modes(thinking_shape, catalog_modes)

    # A model "supports thinking" only when it has at least one positive mode.
    # Catalog entries with an empty thinking_modes list (e.g. claude-3-5-haiku)
    # explicitly have no thinking support even though the profile says otherwise.
    supports_thinking = len(thinking_modes) > 0

    # koan-sourced fields.
    context_window = context_window_for(provider_type, model_id)
    variants = context_window_variants_for(provider_type, model_id)
    caching = supports_prompt_caching(provider_type, model_id)

    return ResolvedCapabilities(
        thinking_supported=supports_thinking,
        thinking_modes=thinking_modes,
        thinking_shape=thinking_shape,
        supports_web_search=_derive_web_search(provider_type, profile),
        supports_tools=bool(profile.get("supports_tools", True)),
        context_window=context_window,
        supports_prompt_caching=caching,
        context_window_variants=variants,
        family=parsed.family,
        tier_hint=parsed.tier_hint,
        version=parsed.version,
        recognized=parsed.recognized,
    )
