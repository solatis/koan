# Naming codecs: one per route. parse is total (never raises); render is partial.

from __future__ import annotations

import re
from typing import Protocol

from .identity import ModelIdentity, ModelRef, Unresolved


class NamingCodec(Protocol):
    """One codec per route.

    `parse` is TOTAL: every string parses to a ref plus optional locality. Never raises.
    `render` is PARTIAL: best-effort; returns None when the route form is not derivable
    (e.g. o-series OpenAI models have no gpt- family form to render back to).
    """

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        ...

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        ...


# -- Vendored pydantic-ai bedrock splitter -------------------------------------
# Vendored from pydantic_ai.providers._bedrock_model_names (pydantic-ai 2.0.0).
# Vendoring (per D12) bounds the blast radius of pydantic-ai upgrades; one contract
# test pins the profile field names koan reads.

# Known geo prefixes for cross-region inference profile IDs.
_BEDROCK_GEO_PREFIXES: tuple[str, ...] = (
    "us", "eu", "apac", "jp", "au", "ca", "global", "us-gov",
)

_VERSION_SUFFIX_RE = re.compile(r"(.+)-v\d+(?::\d+)?$")


def remove_bedrock_geo_prefix(model_name: str) -> str:
    """Remove the cross-region inference geographic prefix from a model ID if present.

    Example: `us.amazon.titan-embed-text-v2:0` -> `amazon.titan-embed-text-v2:0`.
    """
    for prefix in _BEDROCK_GEO_PREFIXES:
        if model_name.startswith(f"{prefix}."):
            return model_name.removeprefix(f"{prefix}.")
    return model_name


def split_bedrock_model_id(model_id: str) -> tuple[str | None, str]:
    """Split a Bedrock model ID into its `<provider>` segment and the bare model name.

    Strips any cross-region inference geo prefix and `-v<n>(:<m>)?` version suffix.
    Example: `us.anthropic.claude-haiku-4-5-20251001-v1:0` -> `('anthropic', 'claude-haiku-4-5-20251001')`.
    """
    provider, _, name = remove_bedrock_geo_prefix(model_id).partition(".")
    if not name:  # no `<provider>.` segment
        return None, model_id
    if version_match := _VERSION_SUFFIX_RE.match(name):
        name = version_match.group(1)
    return provider, name


# -- Regex patterns for per-route naming conventions (originally in recognition.py,
# now native to this module after the M2 backend cutover deleted recognition.py) --
# Patterns are compiled once at import time. Recognized forms produce ModelIdentity;
# everything else degrades to Unresolved (T1: parse is total, never raises).

_RE_CLAUDE_NEW = re.compile(
    r"^claude-(?P<family>opus|sonnet|haiku|3-haiku|fable)-(?P<version>\d+[-\d]*)$"
)
_RE_CLAUDE_OLD = re.compile(
    r"^claude-(?P<version>\d[-\d]*?)-(?P<family>opus|sonnet|haiku)(?:-.*)?$"
)
_RE_GEMINI = re.compile(
    r"^gemini-(?P<version>\d+\.\d+)-(?P<family>flash-lite|flash|pro)(?:-.*)?$"
)
_RE_GPT = re.compile(
    r"^(?P<family>gpt-4o-mini|gpt-4o|gpt-4\.1-nano|gpt-4\.1-mini|gpt-4\.1)(?P<version>-.*)?$"
)
# OpenAI o-series has no koan family entry -- always Unresolved.
_RE_O_SERIES = re.compile(r"^o\d+")
# Amazon Bedrock native models (handled inline by BedrockConverseCodec).
# `split_bedrock_model_id` already strips the `amazon.` prefix and the `-v1:0`
# inference-profile suffix, so the bare name we match here is just `nova-pro` etc.
# The inference-profile version is always 1, so we do not read it from the id.
_RE_NOVA_BARE = re.compile(r"^(?P<family>nova-pro|nova-lite|nova-micro)$")


# Family-name maps for the Anthropic codec (parse -> identity family; render -> wire short).
_ANTHROPIC_FAMILY_TO_ID = {
    "opus": "claude-opus",
    "sonnet": "claude-sonnet",
    "haiku": "claude-haiku",
    "3-haiku": "claude-haiku",
    "fable": "claude-fable",
}
_ANTHROPIC_ID_TO_SHORT = {
    "claude-opus": "opus",
    "claude-sonnet": "sonnet",
    "claude-haiku": "haiku",
    "claude-fable": "fable",
}

_GOOGLE_FAMILY_TO_ID = {
    "flash-lite": "gemini-flash-lite",
    "flash": "gemini-flash",
    "pro": "gemini-pro",
}
_GOOGLE_ID_TO_SHORT = {
    "gemini-flash-lite": "flash-lite",
    "gemini-flash": "flash",
    "gemini-pro": "pro",
}


class AnthropicCodec:
    """Codec for the `anthropic` route (direct Anthropic API, claude-* naming)."""

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Parse `claude-{family}-{major}-{minor}[-{snapshot}]` (new) or
        `claude-{major}-{minor}-{family}[-{snapshot}]` (old).

        Locality is always None for the anthropic route (no geo prefixes here).
        Returns Unresolved for unrecognized forms -- never raises.
        """
        if not wire_id:
            return Unresolved(wire_id, "anthropic"), None
        norm = wire_id.lower()
        # Snapshot: optional trailing date-stamp like -20250929 (>=6 digits) or -latest.
        m = _RE_CLAUDE_NEW.match(norm)
        if m:
            fam = m.group("family")
            family_key = _ANTHROPIC_FAMILY_TO_ID[fam]
            version, snapshot = _split_claude_version(m.group("version"))
            return ModelIdentity("anthropic", family_key, version, snapshot), None
        m = _RE_CLAUDE_OLD.match(norm)
        if m:
            family_key = f"claude-{m.group('family')}"
            version, snapshot = _split_claude_version(m.group("version"))
            return ModelIdentity("anthropic", family_key, version, snapshot), None
        return Unresolved(wire_id, "anthropic"), None

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Render `claude-{family_short}-{major}-{minor}[-{snapshot}]` for Claude identities.

        Returns None when the identity is not a Claude model.
        """
        short = _ANTHROPIC_ID_TO_SHORT.get(ident.family)
        if short is None or ident.vendor != "anthropic":
            return None
        # The canonical identity version uses dots (`4.5`); the Anthropic wire form uses
        # dashes (`4-5`). Convert when rendering back to the wire.
        out = f"claude-{short}-{ident.version.replace('.', '-')}"
        if ident.snapshot:
            out = f"{out}-{ident.snapshot}"
        return out


def _split_claude_version(version_field: str) -> tuple[str, str | None]:
    """Split a Claude version group into (version, snapshot).

    The new-naming version group is `{major}-{minor}` optionally followed by a
    snapshot like `-20250929` or `-latest`. We keep the first two numeric segments
    as `version` (joined by `.`) and treat the rest as the snapshot.
    """
    parts = version_field.split("-")
    if len(parts) <= 2:
        # No snapshot: join major.minor with a dot for the canonical version form.
        return ".".join(parts), None
    version = ".".join(parts[:2])
    snapshot = "-".join(parts[2:])
    return version, snapshot or None


class BedrockConverseCodec:
    """Codec for the `bedrock-converse` route (legacy Converse, geo + vendor + -v1:0)."""

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Parse `{geo}.{vendor}.{bare}` Bedrock Converse ids.

        Uses the vendored `split_bedrock_model_id` to extract vendor and bare name and
        to strip the `-v1:0` inference-profile suffix. Locality is the geo prefix (or
        None when absent). Delegates family/version parsing to the vendor codec:
        AnthropicCodec for `anthropic`, and an inline amazon regex for `amazon` (nova
        has no dedicated codec class -- handled here for catalog coverage). Returns
        `(ModelIdentity(...), locality)` for recognized forms, `(Unresolved(...), locality)`
        for unrecognized.
        """
        if not wire_id:
            return Unresolved(wire_id, "bedrock-converse"), None
        # Extract locality from the geo prefix before splitting.
        locality = _detect_bedrock_locality(wire_id)
        vendor, bare = split_bedrock_model_id(wire_id)
        if vendor == "anthropic":
            ref, _ = AnthropicCodec().parse(bare)
            if isinstance(ref, ModelIdentity):
                return ref, locality
            return Unresolved(wire_id, "bedrock-converse"), locality
        if vendor == "amazon":
            m = _RE_NOVA_BARE.match(bare)
            if m:
                family_key = f"amazon-{m.group('family')}"
                # The inference-profile version (-v1:0) is always 1 and was already
                # stripped by split_bedrock_model_id; record it as version "1".
                return ModelIdentity("amazon", family_key, "1"), locality
            return Unresolved(wire_id, "bedrock-converse"), locality
        return Unresolved(wire_id, "bedrock-converse"), locality

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Render `{geo}.{vendor}.{family_short}-{major}-{minor}[-{snapshot}]-v1:0`.

        The `-v1:0` inference-profile suffix is always appended -- it is required by the
        legacy Bedrock Converse route (Constraint 12). Returns None for vendors we cannot
        render (e.g. amazon nova -- the picker is M2b's concern; render is partial).
        """
        if ident.vendor == "anthropic":
            short = _ANTHROPIC_ID_TO_SHORT.get(ident.family)
            if short is None:
                return None
            # Canonical version uses dots; the Bedrock wire form uses dashes.
            base = f"claude-{short}-{ident.version.replace('.', '-')}"
            if ident.snapshot:
                base = f"{base}-{ident.snapshot}"
            geo = f"{locality}." if locality else ""
            return f"{geo}anthropic.{base}-v1:0"
        return None


class BedrockMantleCodec:
    """Codec for the `bedrock-mantle` route (Anthropic API via AWS Bedrock Mantle endpoint).

    Model IDs use the `anthropic.claude-{family}-{version}` form (no geo prefix,
    no -v1:0 inference-profile suffix). The geo/region lives in the endpoint URL
    ({region} in endpoint_template), not in the model ID. This codec strips the
    `anthropic.` prefix and an optional `-v\\d+` suffix, then delegates to
    AnthropicCodec for family/version parsing.
    """

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Parse `anthropic.claude-{family}-{version}[-{snapshot}][-v\\d+]`.

        Strips the `anthropic.` prefix and an optional `-v\\d+` inference-profile
        suffix, then delegates to AnthropicCodec. Locality is always None -- the
        region lives in the endpoint URL, not the model ID. Returns Unresolved for
        unrecognized forms -- never raises.
        """
        if not wire_id:
            return Unresolved(wire_id, "bedrock-mantle"), None
        bare = wire_id.removeprefix("anthropic.")
        # Strip optional -v1 inference-profile suffix (bedrock-mantle model ids
        # may carry -v1; the endpoint accepts both forms per Assumption 5).
        if m := _VERSION_SUFFIX_RE.match(bare):
            bare = m.group(1)
        return AnthropicCodec().parse(bare)

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Render `anthropic.claude-{family_short}-{version}[-{snapshot}]`.

        Delegates to AnthropicCodec.render and prepends `anthropic.`. Returns None
        when the identity is not a Claude model. The locality parameter is not used --
        the region lives in the endpoint URL, not the model ID.
        """
        rendered = AnthropicCodec().render(ident, None)
        if rendered is None:
            return None
        return f"anthropic.{rendered}"


def _detect_bedrock_locality(wire_id: str) -> str | None:
    """Return the geo prefix of a Bedrock id, or None when absent."""
    for prefix in _BEDROCK_GEO_PREFIXES:
        if wire_id.startswith(f"{prefix}."):
            return prefix
    return None


class OpenAICodec:
    """Codec for the `openai` route (gpt-* and o-series naming)."""

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Parse `gpt-{family}[-{snapshot}]` and `o{N}` forms.

        GPT families carry an implicit version of "1" (the model id has no version
        segment). o-series has no koan family entry -> Unresolved. Locality is None.
        """
        if not wire_id:
            return Unresolved(wire_id, "openai"), None
        norm = wire_id.lower()
        if _RE_O_SERIES.match(norm):
            return Unresolved(wire_id, "openai"), None
        m = _RE_GPT.match(norm)
        if m:
            family_key = m.group("family")
            # GPT ids have no version segment; treat as version "1".
            return ModelIdentity("openai", family_key, "1"), None
        return Unresolved(wire_id, "openai"), None

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Render `gpt-{family}` (no snapshot). Returns None for o-series / non-openai."""
        if ident.vendor != "openai":
            return None
        if ident.family.startswith("gpt-"):
            return ident.family
        return None


class GoogleCodec:
    """Codec for the `google` route (gemini-{major}.{minor}-{family}[-qualifier])."""

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Parse `gemini-{major}.{minor}-{family}[-{qualifier}]`.

        Family tokens map to `gemini-flash-lite`, `gemini-flash`, `gemini-pro`. The
        trailing qualifier (e.g. `-preview`) is dropped from the identity. Locality None.
        """
        if not wire_id:
            return Unresolved(wire_id, "google"), None
        norm = wire_id.lower()
        m = _RE_GEMINI.match(norm)
        if m:
            family_key = _GOOGLE_FAMILY_TO_ID[m.group("family")]
            return ModelIdentity("google", family_key, m.group("version")), None
        return Unresolved(wire_id, "google"), None

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Render `gemini-{major}.{minor}-{family_short}`. Returns None for non-gemini."""
        if ident.vendor != "google":
            return None
        short = _GOOGLE_ID_TO_SHORT.get(ident.family)
        if short is None:
            return None
        return f"gemini-{ident.version}-{short}"


class OpenRouterCodec:
    """Codec for the `openrouter` route ({vendor}/{model}, dots in version)."""

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Parse `{vendor}/{model}` form.

        Strips the vendor prefix, converts dots to dashes in the version segment
        (OpenRouter uses `claude-sonnet-4.5` while AnthropicCodec expects `4-5`), then
        delegates to the vendor codec. The result's vendor is the OpenRouter-namespaced
        vendor. Returns Unresolved when the vendor is unknown. Locality None.
        """
        if not wire_id or "/" not in wire_id:
            return Unresolved(wire_id, "openrouter"), None
        vendor, _, model = wire_id.partition("/")
        # OpenRouter uses dots in the version; normalize to dashes for the vendor codec.
        normalized = model.replace(".", "-")
        ref: ModelRef
        if vendor == "anthropic":
            ref, _ = AnthropicCodec().parse(normalized)
        elif vendor == "openai":
            ref, _ = OpenAICodec().parse(normalized)
        elif vendor == "google":
            ref, _ = GoogleCodec().parse(normalized)
        else:
            return Unresolved(wire_id, "openrouter"), None
        if isinstance(ref, ModelIdentity):
            # Preserve the OpenRouter-namespaced vendor for provenance; the underlying
            # identity (family/version) is unchanged from the vendor codec.
            return ref, None
        return Unresolved(wire_id, "openrouter"), None

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Render `{vendor}/{family_short}-{version_dots}` (dots in version per OpenRouter).

        Returns None when the identity's vendor is not known on OpenRouter.
        """
        if ident.vendor == "anthropic":
            short = _ANTHROPIC_ID_TO_SHORT.get(ident.family)
            if short is None:
                return None
            return f"anthropic/claude-{short}-{ident.version.replace('-', '.')}"
        if ident.vendor == "openai" and ident.family.startswith("gpt-"):
            return f"openai/{ident.family}"
        if ident.vendor == "google":
            short = _GOOGLE_ID_TO_SHORT.get(ident.family)
            if short is None:
                return None
            return f"google/gemini-{ident.version}-{short}"
        return None


class OllamaCloudCodec:
    """Codec for the `ollama-cloud` route (opaque family-name ids)."""

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Treat the wire_id as an opaque string. Always Unresolved; locality None."""
        return Unresolved(wire_id, "ollama-cloud"), None

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Return the identity's family field verbatim (ollama ids ARE the family name)."""
        return ident.family


# Voyage identities: vendor=voyage, family=model_id, version=1, kind=embedding.
_VOYAGE_IDENTITIES: dict[str, ModelIdentity] = {
    "voyage-4-large": ModelIdentity("voyage", "voyage-4-large", "1", kind="embedding"),
    "voyage-4": ModelIdentity("voyage", "voyage-4", "1", kind="embedding"),
    "voyage-4-lite": ModelIdentity("voyage", "voyage-4-lite", "1", kind="embedding"),
}


class VoyageCodec:
    """Codec for the `voyage` route (embedding model ids pass through verbatim)."""

    def parse(self, wire_id: str) -> tuple[ModelRef, str | None]:
        """Consult `_VOYAGE_IDENTITIES` for known ids; Unresolved otherwise. Locality None."""
        if wire_id in _VOYAGE_IDENTITIES:
            return _VOYAGE_IDENTITIES[wire_id], None
        return Unresolved(wire_id, "voyage"), None

    def render(self, ident: ModelIdentity, locality: str | None) -> str | None:
        """Return the identity's family field verbatim (voyage ids ARE the family name)."""
        return ident.family


# Module-level mapping from route id to codec instance. Constant data, not a singleton.
CODECS: dict[str, NamingCodec] = {
    "anthropic": AnthropicCodec(),
    "openai": OpenAICodec(),
    "google": GoogleCodec(),
    "bedrock-converse": BedrockConverseCodec(),
    "bedrock-mantle": BedrockMantleCodec(),
    "openrouter": OpenRouterCodec(),
    "ollama-cloud": OllamaCloudCodec(),
    "voyage": VoyageCodec(),
}

# Vendor -> codec, for rendering the vendor-native bare model id (no geo prefix, no
# inference-profile suffix). Used by offering.py to construct the bare id passed to the
# pydantic-ai profile loader: a Claude model on bedrock-converse must load the anthropic
# profile, so the bare id is rendered via AnthropicCodec, not BedrockConverseCodec.
_VENDOR_CODECS: dict[str, NamingCodec] = {
    "anthropic": AnthropicCodec(),
    "openai": OpenAICodec(),
    "google": GoogleCodec(),
    "voyage": VoyageCodec(),
}


def render_bare_id(ident: ModelIdentity) -> str | None:
    """Render the vendor-native bare model id for a resolved identity.

    Returns None when the vendor has no codec (e.g. amazon nova) -- the caller then
    falls back to the wire_id for the profile lookup, which pydantic-ai handles or ignores.
    """
    codec = _VENDOR_CODECS.get(ident.vendor)
    if codec is None:
        return None
    return codec.render(ident, None)