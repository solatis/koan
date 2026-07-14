# Capabilities: layered, provenanced, honest (design §5).

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal


# -- Provenance ---------------------------------------------------------------

@dataclass(frozen=True)
class Provenance:
    """Provenance for one capability field -- where the fact came from and when.

    Ranked by authority (T7): profile > curated(src,date) > inferred-from-name > unknown.
    The provenance is per-field so a merged capability record can mix sources
    (e.g. intrinsics curated, prompt_caching from the route overlay).
    """

    source: Literal["curated", "profile", "inferred", "unknown"]
    date: str | None = None
    detail: str | None = None


# -- Capability field types ---------------------------------------------------

@dataclass(frozen=True)
class ThinkingSupport:
    """Whether a model supports thinking/reasoning and the modes it accepts.

    `shape` is the substrate's concern (budget/effort/adaptive) -- koan passes a
    unified ThinkingLevel through to pydantic-ai, which translates per profile. We
    carry it only so the Settings display can show the substrate's thinking form.
    """

    supported: bool
    modes: tuple[str, ...]
    shape: Literal["budget", "effort", "adaptive", "none"]


CacheSupport = Literal["none", "explicit", "automatic"]
"""Prompt caching on this route: none, koan-managed explicit (5m/1h), or automatic server-side."""


@dataclass(frozen=True)
class StructuredSupport:
    """Structured-output support: JSON-schema outputs and forced tool choice."""

    json_schema: bool
    forced_tool_choice: bool


@dataclass(frozen=True)
class Capabilities:
    """Effective capability = model intrinsics ⊕ route overrides ⊕ profile facts.

    Every field carries provenance. Unknown is a value, never silently absorbed
    into False (T2): an Unresolved offering surfaces conservative caps with
    provenance `unknown` and `resolved=False`, visible in Settings and telemetry.
    """

    # intrinsics (vendor axis)
    context_window: int
    max_output: int
    input_modalities: frozenset[str]
    thinking: ThinkingSupport
    cache_minimum_tokens: int
    # availability (route axis)
    prompt_caching: CacheSupport
    native_tools: frozenset[str]
    batches: bool
    files_api: bool
    input_sources: frozenset[str]
    structured_outputs: StructuredSupport
    listing: bool
    # embedding intrinsics (empty/None for chat models)
    embedding_dims: tuple[int, ...]
    embedding_default_dim: int | None
    # meta
    provenance: dict[str, Provenance]
    resolved: bool


# The capability fields that participate in the merge and carry per-field provenance.
_CAPABILITY_FIELDS: tuple[str, ...] = (
    "context_window", "max_output", "input_modalities", "thinking",
    "cache_minimum_tokens", "prompt_caching", "native_tools", "batches",
    "files_api", "input_sources", "structured_outputs", "listing",
    "embedding_dims", "embedding_default_dim",
)


# -- Conservative defaults ----------------------------------------------------

# Conservative intrinsics for an unknown/unresolved model: the safe floor. Used for
# Unresolved refs (provenance `unknown`) and as the base when a resolved identity is
# not in the curated catalog (provenance `inferred`).
_CONTEXT_UNKNOWN = 200_000
_MAX_OUTPUT_UNKNOWN = 32_768
_CACHE_MIN_UNKNOWN = 1024


def _conservative_caps(resolved: bool, prov_source: Literal["curated", "inferred", "unknown"]) -> Capabilities:
    """Build the conservative-default Capabilities used as a merge base.

    All route-axis fields start at their safe floor (caching off, no native tools,
    no batches/files); the route overlay and profile raise them where the route/model
    actually supports them.
    """
    prov = Provenance(source=prov_source)
    return Capabilities(
        context_window=_CONTEXT_UNKNOWN,
        max_output=_MAX_OUTPUT_UNKNOWN,
        input_modalities=frozenset({"text"}),
        thinking=ThinkingSupport(supported=False, modes=(), shape="none"),
        cache_minimum_tokens=_CACHE_MIN_UNKNOWN,
        prompt_caching="none",
        native_tools=frozenset(),
        batches=False,
        files_api=False,
        input_sources=frozenset(),
        structured_outputs=StructuredSupport(json_schema=False, forced_tool_choice=False),
        listing=False,
        embedding_dims=(),
        embedding_default_dim=None,
        provenance={k: prov for k in _CAPABILITY_FIELDS},
        resolved=resolved,
    )


def _curated(
    *,
    context_window: int,
    max_output: int,
    thinking_modes: tuple[str, ...],
    cache_minimum_tokens: int = 1024,
    input_modalities: frozenset[str] = frozenset({"text"}),
) -> Capabilities:
    """Build a curated base-catalog entry (vendor intrinsics, provenance `curated`).

    Route-axis fields stay at conservative defaults here; the route overlay supplies
    route-scoped truth (prompt_caching, native_tools, batches, ...).
    """
    supported = len(thinking_modes) > 0
    prov = Provenance(source="curated")
    return Capabilities(
        context_window=context_window,
        max_output=max_output,
        input_modalities=input_modalities,
        thinking=ThinkingSupport(supported=supported, modes=thinking_modes, shape="adaptive" if supported else "none"),
        cache_minimum_tokens=cache_minimum_tokens,
        prompt_caching="none",
        native_tools=frozenset(),
        batches=False,
        files_api=False,
        input_sources=frozenset(),
        structured_outputs=StructuredSupport(json_schema=True, forced_tool_choice=True),
        listing=False,
        embedding_dims=(),
        embedding_default_dim=None,
        provenance={k: prov for k in _CAPABILITY_FIELDS},
        resolved=True,
    )


def embedding_capabilities(dims: tuple[int, ...], default_dim: int) -> Capabilities:
    """Factory for embedding-model capabilities.

    Sets `embedding_dims` and `embedding_default_dim`; all chat fields at conservative
    defaults. Provenance `curated` (the dims are a curated intrinsic fact). Used both to
    build catalog entries and (in M2b) to construct caps for uncataloged embedding models.
    """
    prov = Provenance(source="curated")
    caps = _conservative_caps(resolved=True, prov_source="curated")
    return replace(
        caps,
        embedding_dims=dims,
        embedding_default_dim=default_dim,
        provenance={**caps.provenance, "embedding_dims": prov, "embedding_default_dim": prov},
    )


def _embedding_catalog(*, dims: tuple[int, ...], default_dim: int) -> Capabilities:
    """Build a curated base-catalog entry for an embedding model (Voyage).

    Re-homes the per-model data previously in `VOYAGE_EMBEDDING_MODELS`.
    """
    return embedding_capabilities(dims, default_dim)


# -- Base catalog (curated intrinsics) ----------------------------------------

# Keyed on (vendor, family, version) -- the identity, not the route. The same model on
# three routes shares one base entry; the route overlay and profile add the route-scoped
# deltas. Curation is UX, not truth (D6): this table survives as picker curation and
# intrinsic facts (context window, max output, thinking modes, cache minimums), NOT as
# the capability source for route-scoped facts.
_BASE_CATALOG: dict[tuple[str, str, str], Capabilities] = {
    # Google
    ("google", "gemini-pro", "3.1"): _curated(
        context_window=2_000_000, max_output=65_536,
        thinking_modes=("medium", "high"),
    ),
    ("google", "gemini-flash", "3.5"): _curated(
        context_window=1_000_000, max_output=65_536,
        thinking_modes=("low", "medium"),
    ),
    ("google", "gemini-flash-lite", "3.1"): _curated(
        context_window=1_000_000, max_output=65_536,
        thinking_modes=(),
    ),
    # Anthropic
    ("anthropic", "claude-opus", "4.0"): _curated(
        context_window=200_000, max_output=32_000,
        thinking_modes=("medium", "high"),
    ),
    ("anthropic", "claude-sonnet", "4.5"): _curated(
        context_window=200_000, max_output=32_768,
        thinking_modes=("low", "medium"),
    ),
    ("anthropic", "claude-sonnet", "5"): _curated(
        context_window=200_000, max_output=32_768,
        thinking_modes=("low", "medium"),
    ),
    ("anthropic", "claude-fable", "5"): _curated(
        context_window=200_000, max_output=32_768,
        thinking_modes=("low", "medium", "high", "xhigh"),
    ),
    ("anthropic", "claude-haiku", "3.5"): _curated(
        context_window=200_000, max_output=8_192,
        thinking_modes=(),
        cache_minimum_tokens=4096,  # Haiku requires a larger cache minimum than other Claude models.
    ),
    # OpenAI
    ("openai", "gpt-4o", "1"): _curated(
        context_window=128_000, max_output=16_384, thinking_modes=(),
    ),
    ("openai", "gpt-4o-mini", "1"): _curated(
        context_window=128_000, max_output=16_384, thinking_modes=(),
    ),
    ("openai", "gpt-4.1-nano", "1"): _curated(
        context_window=1_000_000, max_output=32_768, thinking_modes=(),
    ),
    # Amazon Bedrock native (nova). No thinking; small output caps.
    ("amazon", "amazon-nova-pro", "1"): _curated(
        context_window=300_000, max_output=5_120, thinking_modes=(),
    ),
    ("amazon", "amazon-nova-lite", "1"): _curated(
        context_window=300_000, max_output=5_120, thinking_modes=(),
    ),
    ("amazon", "amazon-nova-micro", "1"): _curated(
        context_window=300_000, max_output=5_120, thinking_modes=(),
    ),
    # Ollama Cloud (curated :cloud tags; wire ids in codecs._OLLAMA_CLOUD_IDENTITIES,
    # kept in lockstep -- the round-trip test in test_codecs.py enforces the pairing).
    # Context windows are decoded from ollama.com's binary-K display (976K ->
    # 1,000,000; 1M -> 1,048,576; 198K -> 202,752; 256K -> 262,144; 128K ->
    # 131,072). max_output is not published on ollama.com: 32,768 is a curation
    # assumption, not a verified spec. Thinking: gpt-oss and deepseek-v4-pro
    # document discrete effort levels; the others expose on/off thinking,
    # modeled as the single "medium" mode.
    ("zai", "glm", "5.2"): _curated(
        context_window=1_000_000, max_output=32_768,
        thinking_modes=("medium",),
    ),
    ("deepseek", "deepseek-pro", "4"): _curated(
        context_window=1_048_576, max_output=32_768,
        thinking_modes=("low", "medium", "high"),
    ),
    ("deepseek", "deepseek-flash", "4"): _curated(
        context_window=1_048_576, max_output=32_768,
        thinking_modes=("medium",),
    ),
    ("minimax", "minimax-m", "2.5"): _curated(
        context_window=202_752, max_output=32_768,
        thinking_modes=("medium",),
    ),
    ("qwen", "qwen", "3.5"): _curated(
        context_window=262_144, max_output=32_768,
        thinking_modes=("medium",),
        input_modalities=frozenset({"text", "image"}),
    ),
    ("openai", "gpt-oss-20b", "1"): _curated(
        context_window=131_072, max_output=32_768,
        thinking_modes=("low", "medium", "high"),
    ),
    ("openai", "gpt-oss-120b", "1"): _curated(
        context_window=131_072, max_output=32_768,
        thinking_modes=("low", "medium", "high"),
    ),
    # Voyage embedding models: chat fields at conservative defaults, embedding dims set.
    ("voyage", "voyage-4-large", "1"): _embedding_catalog(
        dims=(256, 512, 1024, 2048), default_dim=1024,
    ),
    ("voyage", "voyage-4", "1"): _embedding_catalog(
        dims=(256, 512, 1024, 2048), default_dim=1024,
    ),
    ("voyage", "voyage-4-lite", "1"): _embedding_catalog(
        dims=(256, 512, 1024, 2048), default_dim=1024,
    ),
}


# -- Route overlays -----------------------------------------------------------

# Per-route capability deltas (route-scoped truth). Applied on top of the base catalog
# for any resolved model on that route. Mirrors the verified feature matrix (analysis §1.2,
# design §5): anthropic-direct gets native tools + batches + files + listing; bedrock-converse
# strips them; caching semantics differ per route.
# Route overlays are endpoint-scoped truths ("this API supports explicit prompt
# caching"), applied to EVERY resolved identity on the route -- including
# inferred (uncatalogued) ones, since they describe the endpoint, not the model.
# They may over-claim per-model exceptions (an old model predating web_fetch
# still gets the route's native_tools); that is acceptable because the
# over-claimable fields are advisory -- koan invokes its own local tools and
# never relies on them for correctness. Model-intrinsic fields (context window,
# thinking modes, cache_minimum_tokens) are never set here; those belong to the
# curated catalog and stay at the conservative floor for inferred identities.
_ROUTE_OVERLAYS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "prompt_caching": "explicit",
        "native_tools": frozenset({"web_search", "web_fetch", "code_execution"}),
        "batches": True,
        "files_api": True,
        "input_sources": frozenset({"url", "files"}),
        "listing": True,
    },
    "openai": {
        "prompt_caching": "automatic",
        "listing": True,
    },
    "google": {
        "prompt_caching": "automatic",
        "listing": True,
    },
    "bedrock-converse": {
        "prompt_caching": "explicit",
        "native_tools": frozenset(),
        "batches": False,
        "files_api": False,
        "input_sources": frozenset(),
        "listing": False,
    },
    # bedrock-mantle: mirrors bedrock-converse -- no server tools, no batches,
    # explicit caching only. The anthropic-messages dialect loads the raw
    # anthropic_model_profile (which carries native_tools); the profile layer
    # overrides the overlay's empty native_tools at merge time. This is a known
    # semantic discrepancy (Key Decision 3) -- informational, not breaking, since
    # koan uses its own local tools, not provider-native ones.
    "bedrock-mantle": {
        "prompt_caching": "explicit",
        "native_tools": frozenset(),
        "batches": False,
        "files_api": False,
        "input_sources": frozenset(),
        "listing": False,
    },
    "openrouter": {
        "prompt_caching": "none",
        "listing": True,
    },
    "ollama-cloud": {
        "prompt_caching": "none",
        "listing": True,
    },
    "voyage": {
        "prompt_caching": "none",
        "listing": False,
    },
}


# -- Profile extraction (pydantic-ai) -----------------------------------------

# Map pydantic-ai native-tool classes to koan's string vocabulary.
_NATIVE_TOOL_NAMES = {
    "WebSearchTool": "web_search",
    "WebFetchTool": "web_fetch",
    "CodeExecutionTool": "code_execution",
    "MemoryTool": "memory",
    "MCPServerTool": "mcp",
    "ToolSearchTool": "tool_search",
}


def _profile_to_dict(profile: object) -> dict:
    """Normalize a pydantic-ai profile object to a plain dict (defensive)."""
    if profile is None:
        return {}
    if isinstance(profile, dict):
        return profile
    dump = getattr(profile, "model_dump", None)
    if callable(dump):
        result = dump()
        if isinstance(result, dict):
            return result
    return vars(profile)


def _profile_to_caps(profile: dict) -> dict[str, Any]:
    """Extract koan capability fields from a pydantic-ai profile dict.

    Reads profile fields defensively with `.get()` so a missing field degrades to a
    conservative default rather than raising (T7: profile is one provenance source
    inside the merge, not the merge itself). The returned dict is the `profile` layer
    passed to merge_capabilities; it overrides base/overlay where present.
    """
    out: dict[str, Any] = {}
    supports_thinking = bool(profile.get("supports_thinking", False))
    # Thinking shape from the substrate's own flags; modes are not enumerated by the
    # profile, so we only refine `shape` and `supported` here (the base catalog owns modes).
    if supports_thinking:
        if profile.get("anthropic_supports_adaptive_thinking") is not None:
            shape: Literal["budget", "effort", "adaptive", "none"] = (
                "adaptive" if profile.get("anthropic_supports_adaptive_thinking", False)
                else ("effort" if profile.get("anthropic_supports_effort", False) else "budget")
            )
        else:
            shape = "adaptive"
        out["thinking"] = ThinkingSupport(supported=True, modes=(), shape=shape)
    else:
        out["thinking"] = ThinkingSupport(supported=False, modes=(), shape="none")

    # Native tools: profile carries a frozenset of tool classes -> koan string vocabulary.
    raw_tools = profile.get("supported_native_tools")
    if raw_tools is not None:
        names: set[str] = set()
        for tool in raw_tools:
            cls_name = getattr(tool, "__name__", str(tool))
            mapped = _NATIVE_TOOL_NAMES.get(cls_name)
            if mapped is not None:
                names.add(mapped)
        out["native_tools"] = frozenset(names)

    # Structured outputs.
    if "supports_json_schema_output" in profile or "anthropic_supports_forced_tool_choice" in profile:
        out["structured_outputs"] = StructuredSupport(
            json_schema=bool(profile.get("supports_json_schema_output", False)),
            forced_tool_choice=bool(profile.get("anthropic_supports_forced_tool_choice", False)),
        )
    return out


def _get_pydantic_ai_profile(dialect: str, vendor: str, bare_model_id: str) -> dict:
    """Load the pydantic-ai model profile for a (dialect, vendor) pair, defensively.

    Dispatches by (dialect, vendor) -- NOT vendor alone -- because the substrate models
    the bedrock route as a profile wrapper (`bedrock_anthropic_model_profile` strips
    builtin tools and enables prompt caching). Loading the raw anthropic vendor profile
    for a bedrock-converse route would hand Bedrock-Anthropic native tools it does not
    have -- the exact bug the refactor exists to fix (analysis §1.2, §3.3). The design
    doc §5 cites `bedrock_anthropic_model_profile` as prior art for the overlay layer;
    we delegate to it so the substrate's route-aware truth (stripped tools, thinking on
    Bedrock-Anthropic) flows into the merge at the top of the provenance ladder.

    Returns {} on any import/runtime error so callers degrade gracefully (T5/T7).
    """
    try:
        if dialect == "bedrock-converse":
            if vendor == "anthropic":
                from pydantic_ai.providers.bedrock import bedrock_anthropic_model_profile
                return _profile_to_dict(bedrock_anthropic_model_profile(bare_model_id))
            if vendor == "amazon":
                from pydantic_ai.providers.bedrock import bedrock_amazon_model_profile
                return _profile_to_dict(bedrock_amazon_model_profile(bare_model_id))
            return {}
        if vendor == "anthropic":
            from pydantic_ai.profiles.anthropic import anthropic_model_profile
            return _profile_to_dict(anthropic_model_profile(bare_model_id))
        if vendor == "google":
            from pydantic_ai.profiles.google import google_model_profile
            return _profile_to_dict(google_model_profile(bare_model_id))
        if vendor == "openai":
            from pydantic_ai.profiles.openai import openai_model_profile
            return _profile_to_dict(openai_model_profile(bare_model_id))
        if vendor == "amazon":
            from pydantic_ai.profiles.amazon import amazon_model_profile
            return _profile_to_dict(amazon_model_profile(bare_model_id))
        # voyage and unrecognized vendors have no profile.
        return {}
    except Exception:
        return {}


# -- Merge --------------------------------------------------------------------

def merge_capabilities(
    base: Capabilities,
    overlay: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    resolved: bool,
) -> Capabilities:
    """Per-field last-writer-wins merge: base -> overlay -> profile.

    Order matters (T2): base carries vendor intrinsics (curated), overlay carries
    route-scoped truth (curated), profile carries substrate facts (profile). Each
    field's provenance is recorded as the source that last wrote it. When `resolved`
    is False the base is already the conservative-defaults/unknown block and overlay
    + profile are ignored (an unresolved ref has no route-overlay or profile truth).
    """
    if not resolved:
        # Unresolved: conservative defaults, all-unknown provenance, no overlays.
        return base if base.resolved is False else replace(base, resolved=False)

    merged_values: dict[str, Any] = {}
    merged_prov: dict[str, Provenance] = dict(base.provenance)

    if overlay:
        for k, v in overlay.items():
            merged_values[k] = v
            merged_prov[k] = Provenance(source="curated", detail=f"overlay:{k}")
    if profile:
        for k, v in profile.items():
            if k == "thinking" and isinstance(v, ThinkingSupport) and v.supported and not v.modes:
                # The profile refines `supported` and `shape` but never
                # enumerates modes -- the base catalog owns those. Whole-field
                # replacement would clobber curated modes with ().
                v = replace(v, modes=base.thinking.modes)
            merged_values[k] = v
            merged_prov[k] = Provenance(source="profile")

    if not merged_values:
        return base
    return replace(base, **merged_values, provenance=merged_prov)


def base_catalog_lookup(vendor: str, family: str, version: str) -> Capabilities | None:
    """Look up curated base intrinsics by identity. None when the identity is not
    in the curated catalog (the caller then falls back to conservative `inferred` caps)."""
    return _BASE_CATALOG.get((vendor, family, version))


def route_overlay_for(overlay_id: str | None) -> dict[str, Any] | None:
    """Return the route overlay dict for an overlay id, or None."""
    if overlay_id is None:
        return None
    return _ROUTE_OVERLAYS.get(overlay_id)


def get_pydantic_ai_profile(dialect: str, vendor: str, bare_model_id: str) -> dict:
    """Public wrapper over the defensive profile loader (used by offering.py)."""
    return _get_pydantic_ai_profile(dialect, vendor, bare_model_id)


def profile_to_caps(profile: dict) -> dict[str, Any]:
    """Public wrapper over `_profile_to_caps` (used by tests)."""
    return _profile_to_caps(profile)