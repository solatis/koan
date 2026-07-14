# Tests for koan.models.codecs.

from __future__ import annotations

import pytest

from pydantic_ai.providers._bedrock_model_names import split_bedrock_model_id as real_split

from koan.models.codecs import CODECS, split_bedrock_model_id
from koan.models.identity import ModelIdentity, Unresolved


# -- Analysis §3.2 round-trip fixtures ----------------------------------------

# (route_id, wire_id, expected identity or Unresolved, locality). Drives the
# round-trip property test: parse then render reproduces the wire_id where render
# is derivable (None where it is not, e.g. Unresolved or o-series).
ROUND_TRIP_FIXTURES = [
    ("anthropic", "claude-sonnet-4-5-20250929",
     ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929"), None),
    ("bedrock-converse", "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
     ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929"), "eu"),
    ("openrouter", "anthropic/claude-sonnet-4.5",
     ModelIdentity("anthropic", "claude-sonnet", "4.5"), None),
    ("bedrock-mantle", "anthropic.claude-sonnet-4-5-20250929",
     ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929"), None),
]


class TestAnthropicCodec:
    def test_parse_sonnet_with_snapshot(self) -> None:
        """AnthropicCodec parses claude-sonnet-4-5-20250929 into the canonical identity."""
        ref, loc = CODECS["anthropic"].parse("claude-sonnet-4-5-20250929")
        assert ref == ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929")
        assert loc is None

    def test_parse_opus(self) -> None:
        """AnthropicCodec parses claude-opus-4-0."""
        ref, _ = CODECS["anthropic"].parse("claude-opus-4-0")
        assert ref == ModelIdentity("anthropic", "claude-opus", "4.0")

    def test_parse_old_haiku_latest(self) -> None:
        """AnthropicCodec parses old-naming claude-3-5-haiku-latest to claude-haiku/3.5."""
        ref, _ = CODECS["anthropic"].parse("claude-3-5-haiku-latest")
        assert ref == ModelIdentity("anthropic", "claude-haiku", "3.5")

    def test_parse_fable(self) -> None:
        """AnthropicCodec parses claude-fable-5."""
        ref, _ = CODECS["anthropic"].parse("claude-fable-5")
        assert ref == ModelIdentity("anthropic", "claude-fable", "5")

    def test_render_round_trips(self) -> None:
        """render reproduces the wire_id for recognized Claude identities."""
        codec = CODECS["anthropic"]
        for wire in ["claude-sonnet-4-5-20250929", "claude-opus-4-0", "claude-fable-5"]:
            ref, _ = codec.parse(wire)
            assert isinstance(ref, ModelIdentity)
            assert codec.render(ref, None) == wire


class TestBedrockConverseCodec:
    def test_parse_eu_sonnet_with_snapshot(self) -> None:
        """BedrockConverseCodec parses the eu inference-profile id, extracting locality."""
        ref, loc = CODECS["bedrock-converse"].parse("eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert ref == ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929")
        assert loc == "eu"

    def test_parse_us_opus(self) -> None:
        """BedrockConverseCodec extracts the 'us' locality from an opus id."""
        ref, loc = CODECS["bedrock-converse"].parse("us.anthropic.claude-opus-4-0")
        assert ref == ModelIdentity("anthropic", "claude-opus", "4.0")
        assert loc == "us"

    def test_parse_global_fable(self) -> None:
        """BedrockConverseCodec extracts the 'global' locality from a fable id."""
        ref, loc = CODECS["bedrock-converse"].parse("global.anthropic.claude-fable-5")
        assert ref == ModelIdentity("anthropic", "claude-fable", "5")
        assert loc == "global"

    def test_render_round_trips_with_locality(self) -> None:
        """render reproduces the geo-prefixed -v1:0 form for recognized ids."""
        codec = CODECS["bedrock-converse"]
        wire = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
        ref, loc = codec.parse(wire)
        assert isinstance(ref, ModelIdentity)
        assert codec.render(ref, loc) == wire

    def test_parse_nova_pro(self) -> None:
        """BedrockConverseCodec resolves amazon nova-pro (handled inline; no Amazon codec)."""
        ref, _ = CODECS["bedrock-converse"].parse("amazon.nova-pro-v1:0")
        assert ref == ModelIdentity("amazon", "amazon-nova-pro", "1")

class TestBedrockMantleCodec:
    def test_parse_sonnet_with_anthropic_prefix(self) -> None:
        """BedrockMantleCodec strips anthropic. prefix and delegates to AnthropicCodec."""
        ref, loc = CODECS["bedrock-mantle"].parse("anthropic.claude-sonnet-4-5-20250929")
        assert ref == ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929")
        assert loc is None

    def test_parse_strips_v1_suffix(self) -> None:
        """BedrockMantleCodec strips -v1 inference-profile suffix before delegating."""
        ref, _ = CODECS["bedrock-mantle"].parse("anthropic.claude-sonnet-4-6-v1")
        assert ref == ModelIdentity("anthropic", "claude-sonnet", "4.6")

    def test_parse_opus(self) -> None:
        """BedrockMantleCodec parses anthropic.claude-opus-4-0."""
        ref, _ = CODECS["bedrock-mantle"].parse("anthropic.claude-opus-4-0")
        assert ref == ModelIdentity("anthropic", "claude-opus", "4.0")

    def test_parse_empty_returns_unresolved(self) -> None:
        """Empty string returns Unresolved -- never raises."""
        ref, _ = CODECS["bedrock-mantle"].parse("")
        assert isinstance(ref, Unresolved)

    def test_parse_unrecognized_returns_unresolved(self) -> None:
        """Unrecognized forms return Unresolved -- never raises."""
        ref, _ = CODECS["bedrock-mantle"].parse("anthropic.unknown-model")
        assert isinstance(ref, Unresolved)

    def test_render_round_trips(self) -> None:
        """render reproduces the anthropic.claude-* form for recognized Claude identities."""
        codec = CODECS["bedrock-mantle"]
        for wire in ["anthropic.claude-sonnet-4-5-20250929", "anthropic.claude-opus-4-0", "anthropic.claude-fable-5"]:
            ref, _ = codec.parse(wire)
            assert isinstance(ref, ModelIdentity)
            assert codec.render(ref, None) == wire

    def test_render_returns_none_for_non_anthropic(self) -> None:
        """render returns None for non-anthropic identities (vendor filter for offerings)."""
        ident = ModelIdentity("google", "gemini-flash", "3.5")
        assert CODECS["bedrock-mantle"].render(ident, None) is None

    def test_render_no_v1_suffix(self) -> None:
        """render does not append -v1 (the endpoint accepts the unsuffixed form)."""
        ref, _ = CODECS["bedrock-mantle"].parse("anthropic.claude-sonnet-4-6-v1")
        assert isinstance(ref, ModelIdentity)
        rendered = CODECS["bedrock-mantle"].render(ref, None)
        assert rendered == "anthropic.claude-sonnet-4-6"
        assert "-v1" not in rendered


class TestOpenAICodec:
    def test_parse_gpt_4o(self) -> None:
        """OpenAICodec parses gpt-4o with implicit version 1."""
        ref, _ = CODECS["openai"].parse("gpt-4o")
        assert ref == ModelIdentity("openai", "gpt-4o", "1")

    def test_parse_gpt_4o_mini(self) -> None:
        """OpenAICodec parses gpt-4o-mini."""
        ref, _ = CODECS["openai"].parse("gpt-4o-mini")
        assert ref == ModelIdentity("openai", "gpt-4o-mini", "1")

    def test_parse_gpt_4_1_nano(self) -> None:
        """OpenAICodec parses gpt-4.1-nano."""
        ref, _ = CODECS["openai"].parse("gpt-4.1-nano")
        assert ref == ModelIdentity("openai", "gpt-4.1-nano", "1")

    def test_o_series_unresolved(self) -> None:
        """o-series has no koan family entry -> Unresolved."""
        ref, _ = CODECS["openai"].parse("o3")
        assert isinstance(ref, Unresolved)

    def test_render_round_trips(self) -> None:
        """render reproduces gpt family ids; o-series renders to None."""
        codec = CODECS["openai"]
        for wire in ["gpt-4o", "gpt-4o-mini", "gpt-4.1-nano"]:
            ref, _ = codec.parse(wire)
            assert isinstance(ref, ModelIdentity)
            assert codec.render(ref, None) == wire


class TestGoogleCodec:
    def test_parse_flash(self) -> None:
        """GoogleCodec parses gemini-3.5-flash."""
        ref, _ = CODECS["google"].parse("gemini-3.5-flash")
        assert ref == ModelIdentity("google", "gemini-flash", "3.5")

    def test_parse_pro_preview(self) -> None:
        """GoogleCodec parses gemini-3.1-pro-preview, dropping the qualifier."""
        ref, _ = CODECS["google"].parse("gemini-3.1-pro-preview")
        assert ref == ModelIdentity("google", "gemini-pro", "3.1")

    def test_parse_flash_lite(self) -> None:
        """GoogleCodec parses gemini-3.1-flash-lite."""
        ref, _ = CODECS["google"].parse("gemini-3.1-flash-lite")
        assert ref == ModelIdentity("google", "gemini-flash-lite", "3.1")

    def test_render_round_trips(self) -> None:
        """render reproduces the gemini-{version}-{family} form (qualifier dropped)."""
        codec = CODECS["google"]
        for wire, expected_render in [
            ("gemini-3.5-flash", "gemini-3.5-flash"),
            ("gemini-3.1-flash-lite", "gemini-3.1-flash-lite"),
        ]:
            ref, _ = codec.parse(wire)
            assert isinstance(ref, ModelIdentity)
            assert codec.render(ref, None) == expected_render


class TestOpenRouterCodec:
    def test_parse_anthropic_dots_to_dashes(self) -> None:
        """OpenRouterCodec converts dots to dashes before delegating to AnthropicCodec."""
        ref, _ = CODECS["openrouter"].parse("anthropic/claude-sonnet-4.5")
        assert ref == ModelIdentity("anthropic", "claude-sonnet", "4.5")

    def test_parse_openai(self) -> None:
        """OpenRouterCodec delegates openai/gpt-4o to OpenAICodec."""
        ref, _ = CODECS["openrouter"].parse("openai/gpt-4o")
        assert ref == ModelIdentity("openai", "gpt-4o", "1")

    def test_render_dots_in_version(self) -> None:
        """render uses dots in the version per OpenRouter convention."""
        codec = CODECS["openrouter"]
        ref, _ = codec.parse("anthropic/claude-sonnet-4.5")
        assert isinstance(ref, ModelIdentity)
        assert codec.render(ref, None) == "anthropic/claude-sonnet-4.5"

    def test_render_openai(self) -> None:
        """render reproduces openai/gpt-4o."""
        codec = CODECS["openrouter"]
        ref, _ = codec.parse("openai/gpt-4o")
        assert isinstance(ref, ModelIdentity)
        assert codec.render(ref, None) == "openai/gpt-4o"

    def test_unknown_vendor_unresolved(self) -> None:
        """An unknown vendor on OpenRouter is Unresolved."""
        ref, _ = CODECS["openrouter"].parse("unknown-vendor/some-model")
        assert isinstance(ref, Unresolved)


class TestOllamaCloudCodec:
    def test_parse_uncurated_string_unresolved(self) -> None:
        """Ids outside the curated table stay opaque -> Unresolved (still invocable)."""
        ref, _ = CODECS["ollama-cloud"].parse("llama3.3:70b")
        assert isinstance(ref, Unresolved)

    def test_render_uncurated_identity_none(self) -> None:
        """render is the vendor filter: identities without a curated cloud tag render to None."""
        ident = ModelIdentity("ollama", "llama3.3:70b", "1")
        assert CODECS["ollama-cloud"].render(ident, None) is None
        # Foreign-vendor identities do not leak onto the ollama route either.
        claude = ModelIdentity("anthropic", "claude-sonnet", "4.5")
        assert CODECS["ollama-cloud"].render(claude, None) is None

    def test_parse_curated_cloud_tags(self) -> None:
        """Every curated :cloud tag resolves to its ModelIdentity."""
        from koan.models.codecs import _OLLAMA_CLOUD_IDENTITIES
        for wire_id, expected in _OLLAMA_CLOUD_IDENTITIES.items():
            ref, locality = CODECS["ollama-cloud"].parse(wire_id)
            assert ref == expected, wire_id
            assert locality is None

    def test_curated_round_trip(self) -> None:
        """render(parse(wire_id)) reproduces the wire_id for every curated tag."""
        from koan.models.codecs import _OLLAMA_CLOUD_IDENTITIES
        for wire_id, ident in _OLLAMA_CLOUD_IDENTITIES.items():
            assert CODECS["ollama-cloud"].render(ident, None) == wire_id

    def test_parse_glm_cloud(self) -> None:
        ref, _ = CODECS["ollama-cloud"].parse("glm-5.2:cloud")
        assert ref == ModelIdentity("zai", "glm", "5.2")

    def test_curated_tags_have_catalog_entries(self) -> None:
        """Every curated cloud tag is backed by a curated _BASE_CATALOG entry."""
        from koan.models.capabilities import _BASE_CATALOG
        from koan.models.codecs import _OLLAMA_CLOUD_IDENTITIES
        for wire_id, i in _OLLAMA_CLOUD_IDENTITIES.items():
            assert (i.vendor, i.family, i.version) in _BASE_CATALOG, wire_id


class TestVoyageCodec:
    def test_parse_voyage_4_large(self) -> None:
        """VoyageCodec resolves voyage-4-large to an embedding identity."""
        ref, _ = CODECS["voyage"].parse("voyage-4-large")
        assert ref == ModelIdentity("voyage", "voyage-4-large", "1", kind="embedding")

    def test_parse_voyage_4(self) -> None:
        """VoyageCodec resolves voyage-4."""
        ref, _ = CODECS["voyage"].parse("voyage-4")
        assert ref == ModelIdentity("voyage", "voyage-4", "1", kind="embedding")

    def test_parse_voyage_4_lite(self) -> None:
        """VoyageCodec resolves voyage-4-lite."""
        ref, _ = CODECS["voyage"].parse("voyage-4-lite")
        assert ref == ModelIdentity("voyage", "voyage-4-lite", "1", kind="embedding")

    def test_parse_unknown_unresolved(self) -> None:
        """An unknown voyage id is Unresolved."""
        ref, _ = CODECS["voyage"].parse("unknown-voyage-model")
        assert isinstance(ref, Unresolved)

    def test_render_family_verbatim(self) -> None:
        """render returns the identity's family field verbatim (voyage ids ARE the family)."""
        ident = ModelIdentity("voyage", "voyage-4-large", "1", kind="embedding")
        assert CODECS["voyage"].render(ident, None) == "voyage-4-large"


class TestSplitterParity:
    @pytest.mark.parametrize("model_id", [
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic.claude-haiku-4-5",
        "claude-haiku-4-5",
        "us.amazon.titan-embed-text-v2:0",
        "amazon.nova-pro-v1:0",
    ])
    def test_vendored_matches_installed(self, model_id: str) -> None:
        """The vendored split_bedrock_model_id matches the installed pydantic-ai copy."""
        assert split_bedrock_model_id(model_id) == real_split(model_id)


class TestUnrecognizedNeverRaises:
    @pytest.mark.parametrize("route_id", list(CODECS.keys()))
    def test_garbage_returns_unresolved(self, route_id: str) -> None:
        """Every codec returns Unresolved for garbage input and never raises."""
        ref, _ = CODECS[route_id].parse("")
        assert isinstance(ref, Unresolved)
        ref2, _ = CODECS[route_id].parse("!!!garbage!!!")
        assert isinstance(ref2, Unresolved)


class TestRoundTrip:
    @pytest.mark.parametrize("route_id,wire_id,expected_ref,locality", ROUND_TRIP_FIXTURES)
    def test_parse_and_render_round_trip(
        self, route_id: str, wire_id: str, expected_ref: object, locality: object
    ) -> None:
        """Parse-then-render reproduces the wire_id for the analysis §3.2 fixtures."""
        codec = CODECS[route_id]
        ref, loc = codec.parse(wire_id)
        assert ref == expected_ref
        assert loc == locality
        if isinstance(ref, ModelIdentity):
            assert codec.render(ref, loc) == wire_id

class TestCatalogRenderParseRoundTrip:
    def test_every_catalog_entry_renders_resolvable_or_none(self) -> None:
        """Offerings are resolved-by-construction: for every catalog entry and
        every route codec, render either returns None (not offered on that
        route) or a wire_id whose own codec parses it back to a resolved
        identity. A codec that renders ids it cannot recognize would emit
        unresolved offerings -- the exact contradiction behind the
        settings_listed identity=None incident.
        """
        from koan.models.capabilities import _BASE_CATALOG

        for (vendor, family, version), caps in _BASE_CATALOG.items():
            kind = "embedding" if caps.embedding_dims else "chat"
            ident = ModelIdentity(vendor, family, version, kind=kind)
            for route_naming, codec in CODECS.items():
                # Mirror the offerings kind filter: the voyage route only
                # renders embedding entries; chat routes only chat entries.
                if (route_naming == "voyage") != (kind == "embedding"):
                    continue
                wire_id = codec.render(ident, None)
                if wire_id is None:
                    continue
                ref, _ = codec.parse(wire_id)
                assert isinstance(ref, ModelIdentity), (
                    f"{route_naming} renders {wire_id!r} for {vendor}/{family}-{version} "
                    f"but cannot parse it back"
                )
