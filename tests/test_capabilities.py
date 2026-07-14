# Tests for koan.models.capabilities.

from __future__ import annotations

import pytest

from pydantic_ai.profiles.anthropic import anthropic_model_profile

from koan.models.capabilities import (
    Capabilities,
    _BASE_CATALOG,
    _ROUTE_OVERLAYS,
    embedding_capabilities,
    merge_capabilities,
    profile_to_caps,
)
from koan.models.routes import ROUTES
from koan.models.capabilities import _conservative_caps


def _base() -> Capabilities:
    """A simple curated base Capabilities for merge tests."""
    from koan.models.capabilities import Provenance, StructuredSupport, ThinkingSupport
    fields = (
        "context_window", "max_output", "input_modalities", "thinking",
        "cache_minimum_tokens", "prompt_caching", "native_tools", "batches",
        "files_api", "input_sources", "structured_outputs", "listing",
        "embedding_dims", "embedding_default_dim",
    )
    return Capabilities(
        context_window=200_000, max_output=32_768,
        input_modalities=frozenset({"text"}),
        thinking=ThinkingSupport(True, ("low", "medium"), "adaptive"),
        cache_minimum_tokens=1024,
        prompt_caching="none",
        native_tools=frozenset(),
        batches=False, files_api=False, input_sources=frozenset(),
        structured_outputs=StructuredSupport(True, True),
        listing=False, embedding_dims=(), embedding_default_dim=None,
        provenance={k: Provenance("curated") for k in fields},
        resolved=True,
    )


class TestMergeCapabilities:
    def test_base_only(self) -> None:
        """merge with no overlay/profile keeps base fields with curated provenance."""
        base = _base()
        merged = merge_capabilities(base, None, None, resolved=True)
        assert merged.prompt_caching == "none"
        assert merged.provenance["prompt_caching"].source == "curated"

    def test_base_plus_overlay(self) -> None:
        """Overlay fields override base; provenance reflects the overlay (curated)."""
        base = _base()
        overlay = {"prompt_caching": "explicit", "native_tools": frozenset({"web_search"})}
        merged = merge_capabilities(base, overlay, None, resolved=True)
        assert merged.prompt_caching == "explicit"
        assert merged.native_tools == frozenset({"web_search"})
        assert merged.provenance["prompt_caching"].source == "curated"
        assert merged.provenance["prompt_caching"].detail == "overlay:prompt_caching"

    def test_base_plus_overlay_plus_profile(self) -> None:
        """Profile facts override overlay where present (last-writer-wins)."""
        base = _base()
        overlay = {"prompt_caching": "explicit", "native_tools": frozenset({"web_search"})}
        profile = {"native_tools": frozenset({"web_search", "code_execution"})}
        merged = merge_capabilities(base, overlay, profile, resolved=True)
        # Profile overrides the overlay's native_tools.
        assert merged.native_tools == frozenset({"web_search", "code_execution"})
        assert merged.provenance["native_tools"].source == "profile"
        # Overlay still wins for fields the profile does not touch.
        assert merged.prompt_caching == "explicit"

    def test_profile_thinking_does_not_clobber_base_modes(self) -> None:
        """Profile ThinkingSupport refines supported/shape; the base catalog owns modes.

        pydantic-ai profiles never enumerate modes, so a supported=True profile
        arrives with modes=(). A whole-field replacement would silently erase
        the curated levels for every profiled model (claude, gemini).
        """
        from koan.models.capabilities import ThinkingSupport
        base = _base()  # curated modes: ("low", "medium"), shape "adaptive"
        profile = {"thinking": ThinkingSupport(True, (), "effort")}
        merged = merge_capabilities(base, None, profile, resolved=True)
        assert merged.thinking.supported is True
        assert merged.thinking.shape == "effort"       # profile refinement kept
        assert merged.thinking.modes == ("low", "medium")  # curated modes kept
        # A profile that declares thinking unsupported still wins outright.
        off = {"thinking": ThinkingSupport(False, (), "none")}
        merged_off = merge_capabilities(base, None, off, resolved=True)
        assert merged_off.thinking.supported is False
        assert merged_off.thinking.modes == ()

    def test_resolved_false_uses_conservative_defaults(self) -> None:
        """With resolved=False, caps stay conservative with unknown provenance."""
        base = _conservative_caps(resolved=False, prov_source="unknown")
        merged = merge_capabilities(base, {"prompt_caching": "explicit"}, None, resolved=False)
        # Unresolved: overlays are ignored; conservative defaults stand.
        assert merged.prompt_caching == "none"
        assert merged.resolved is False
        assert merged.provenance["prompt_caching"].source == "unknown"


class TestEmbeddingCapabilities:
    def test_factory_sets_embedding_fields(self) -> None:
        """embedding_capabilities sets dims and default; chat fields stay conservative."""
        caps = embedding_capabilities((256, 512, 1024, 2048), 1024)
        assert caps.embedding_dims == (256, 512, 1024, 2048)
        assert caps.embedding_default_dim == 1024
        # Chat fields at conservative defaults.
        assert caps.prompt_caching == "none"
        assert caps.native_tools == frozenset()
        assert caps.resolved is True
        assert caps.provenance["embedding_dims"].source == "curated"


class TestProfileToCaps:
    def test_extracts_fields_from_real_profile(self) -> None:
        """_profile_to_caps extracts thinking/structured/tools from a real anthropic profile."""
        profile = anthropic_model_profile("claude-sonnet-4-5")
        d = profile.model_dump() if hasattr(profile, "model_dump") else profile
        caps = profile_to_caps(d)
        assert caps["thinking"].supported is True
        assert caps["thinking"].shape in ("adaptive", "effort", "budget")
        assert "native_tools" in caps
        # Anthropic supports web_search/web_fetch/code_execution natively.
        assert "web_search" in caps["native_tools"]
        assert "structured_outputs" in caps
        assert caps["structured_outputs"].json_schema is True


class TestBaseCatalogCoverage:
    def test_all_catalog_entries_parseable_by_codec(self) -> None:
        """Every (vendor, family, version) in _BASE_CATALOG is parseable by some codec.

        M2: MODEL_CAPABILITIES is deleted; this test now verifies that every base
        catalog identity can be produced by parsing a wire id through the codec for
        its vendor route. For vendors where render is partial (amazon nova), a
        hardcoded wire id is used to verify the parse path.
        """
        from koan.models.codecs import CODECS
        from koan.models.identity import ModelIdentity

        vendor_to_route = {
            "google": "google",
            "anthropic": "anthropic",
            "openai": "openai",
            "amazon": "bedrock-converse",
            "voyage": "voyage",
            # Ollama Cloud curated vendors: only the ollama-cloud codec knows them.
            "zai": "ollama-cloud",
            "deepseek": "ollama-cloud",
            "minimax": "ollama-cloud",
            "qwen": "ollama-cloud",
        }
        # Hardcoded wire ids for vendors where render is partial (returns None).
        hardcoded_wire = {
            ("amazon", "amazon-nova-pro", "1"): "us.amazon.nova-pro-v1:0",
            ("amazon", "amazon-nova-lite", "1"): "us.amazon.nova-lite-v1:0",
            ("amazon", "amazon-nova-micro", "1"): "us.amazon.nova-micro-v1:0",
        }
        # gpt-oss carries vendor "openai" but is not served by the OpenAI API;
        # its wire ids live on the ollama-cloud route.
        entry_route_override = {
            ("openai", "gpt-oss-20b", "1"): "ollama-cloud",
            ("openai", "gpt-oss-120b", "1"): "ollama-cloud",
        }
        unresolvable: list[tuple[str, str, str]] = []
        for (vendor, family, version), _caps in _BASE_CATALOG.items():
            route_id = entry_route_override.get((vendor, family, version)) or vendor_to_route.get(vendor)
            if route_id is None:
                unresolvable.append((vendor, family, version))
                continue
            codec = CODECS.get(route_id)
            if codec is None:
                unresolvable.append((vendor, family, version))
                continue
            ident = ModelIdentity(vendor=vendor, family=family, version=version)
            wire = hardcoded_wire.get((vendor, family, version))
            if wire is None:
                wire = codec.render(ident, None)
            if wire is None:
                unresolvable.append((vendor, family, version))
                continue
            ref, _ = codec.parse(wire)
            if not isinstance(ref, ModelIdentity):
                unresolvable.append((vendor, family, version))
                continue
            if (ref.vendor, ref.family, ref.version) != (vendor, family, version):
                unresolvable.append((vendor, family, version))
        assert not unresolvable, f"catalog entries unparseable by codec: {unresolvable}"


class TestRouteOverlays:
    def test_overlays_exist_for_routes_with_overlay(self) -> None:
        """Every route with a non-None capability_overlay has an _ROUTE_OVERLAYS entry."""
        for route in ROUTES:
            if route.capability_overlay is not None:
                assert route.capability_overlay in _ROUTE_OVERLAYS, (
                    f"route {route.id} names missing overlay {route.capability_overlay!r}"
                )