# Dialects: the only code seam. Translations from koan's semantic vocabulary to
# each wire protocol's settings form (design §2.2, §4).

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from koan.models.capabilities import Capabilities


def apply_thinking(mode: str) -> dict:
    """Translate koan ThinkingMode to pydantic-ai's unified `thinking` setting.

    Koan's ThinkingMode becomes `disabled|minimal|low|medium|high|xhigh` and is passed
    through to pydantic-ai's unified `ModelSettings.thinking`, which the substrate
    translates per model profile (adaptive vs budget vs effort, xhigh passthrough,
    Bedrock's effort-inside-adaptive restriction). `disabled` maps to omission of the
    setting entirely -- pydantic-ai's equivalent of `off` (D4: substrate thinking
    vocabulary, substrate budget values). `map_thinking` and both budget tables are
    deleted, not adapted.
    """
    if mode == "disabled":
        return {}
    return {"thinking": mode}


# Per-dialect cache tier -> TTL mapping. Anthropic-messages and bedrock-converse use
# the same 5m/1h tiers but different setting-key families (Constraint 10: dispatch on
# dialect, not route_id). This is the single place to change a dialect's mapping.
_CACHE_TIER_TTL: dict[str, dict[str, str]] = {
    "anthropic-messages": {"short": "5m", "long": "1h"},
    "bedrock-converse": {"short": "5m", "long": "1h"},
}


def emit_cache_settings(dialect: str, caps: "Capabilities", cache_tier: str) -> dict:
    """Emit per-dialect cache settings for one request.

    Dispatches on `dialect` (not route_id -- T3: routes are data, dialects are code):
      - `anthropic-messages`: anthropic_cache (tail), anthropic_cache_instructions +
        anthropic_cache_tool_definitions (stable).
      - `bedrock-converse`: bedrock_cache_messages (tail), bedrock_cache_instructions +
        bedrock_cache_tool_definitions (stable).
      - All others (google-genai, openai-chat, voyage-embeddings): no koan-emitted
        cache settings (google/openai cache automatically server-side; voyage has none).

    Per-breakpoint TTL split (unified cache TTL policy):
      - long tier (orchestrator/executor): stable keys get the long TTL ('1h'), the
        growing-tail key gets the short TTL ('5m') -- a long-lived cache for the stable
        prefix, a cheap cache-write for the churning tail.
      - short tier (scout/reviewer): all keys get the short TTL.

    Returns {} when `caps.prompt_caching` is "none" or the dialect has no cache mapping.
    """
    if caps.prompt_caching == "none":
        return {}
    ttls = _CACHE_TIER_TTL.get(dialect)
    if ttls is None:
        return {}
    if cache_tier == "long":
        stable_ttl = ttls["long"]
        tail_ttl = ttls["short"]
    else:
        stable_ttl = ttls["short"]
        tail_ttl = ttls["short"]
    if dialect == "anthropic-messages":
        return {
            "anthropic_cache": tail_ttl,                       # growing conversation tail
            "anthropic_cache_instructions": stable_ttl,        # system prompt (stable)
            "anthropic_cache_tool_definitions": stable_ttl,    # tool schemas (stable)
        }
    if dialect == "bedrock-converse":
        return {
            "bedrock_cache_messages": tail_ttl,                # last-message cachePoint / tail
            "bedrock_cache_instructions": stable_ttl,          # system prompt (stable)
            "bedrock_cache_tool_definitions": stable_ttl,      # tool schemas (stable)
        }
    return {}

def cache_ttl_for(dialect: str, cache_tier: str) -> str | None:
    """Single gateway: map a cache tier to the concrete dialect TTL.

    Returns None when the dialect has no koan-managed explicit cache. Relocated
    from adapter.py so handoff_artifacts.py imports it from here (the adapter
    no longer carries cache-related functions after M2). The dialect-based
    ``_CACHE_TIER_TTL`` is keyed by dialect identifier (``"anthropic-messages"``,
    ``"bedrock-converse"``). For route ids that differ from their dialect
    (e.g. ``"anthropic"`` -> ``"anthropic-messages"``), the route registry is
    consulted to map the route id to its dialect before the lookup.
    dialect id (e.g. ``"bedrock-converse"``) work correctly.
    """
    # Try direct dialect lookup first (covers bedrock-converse where route id == dialect).
    ttls = _CACHE_TIER_TTL.get(dialect)
    if ttls is not None:
        return ttls.get(cache_tier)
    # Fall back: treat the key as a route id and resolve its dialect via the registry.
    try:
        from koan.models.routes import get_route
        route = get_route(dialect)
        ttls = _CACHE_TIER_TTL.get(route.dialect)
        return ttls.get(cache_tier) if ttls else None
    except KeyError:
        return None


async def voyage_embed(
    texts: list[str],
    *,
    model: str,
    api_key: str,
    input_type: str = "document",
    output_dimension: int | None = None,
) -> list[list[float]]:
    """Embed texts via the Voyage AI embedding API.

    Pure re-homing of the call path from memory/retrieval/index.py:_embed_texts -- same
    voyageai.AsyncClient, same embed() call, same `input_type` document/query semantics,
    same `output_dimension` parameter. The wire behavior is identical (Constraint 8);
    existing LanceDB indices remain valid. Re-homed here so the memory subsystem can
    resolve the embedding call via the offering/dialect path in M2b.
    """
    import voyageai

    client = voyageai.AsyncClient(api_key=api_key)
    result = await client.embed(
        texts, model=model, input_type=input_type, output_dimension=output_dimension,
    )
    return result.embeddings