# Tests for koan.models.routes.

from __future__ import annotations

import pytest

from koan.models.codecs import CODECS
from koan.models.routes import ROUTES, Route, get_route, route_ids


_KNOWN_DIALECTS = {
    "anthropic-messages", "openai-chat", "google-genai", "bedrock-converse", "voyage-embeddings",
}


class TestRoutesRegistry:
    def test_routes_is_nonempty_tuple(self) -> None:
        """ROUTES is a non-empty tuple of Route instances."""
        assert isinstance(ROUTES, tuple)
        assert len(ROUTES) > 0
        assert all(isinstance(r, Route) for r in ROUTES)

    def test_unique_ids(self) -> None:
        """Every route has a unique id."""
        ids = [r.id for r in ROUTES]
        assert len(ids) == len(set(ids))

    def test_get_route_known(self) -> None:
        """get_route returns the correct route for each known id."""
        for route in ROUTES:
            assert get_route(route.id) is route

    def test_get_route_unknown_raises(self) -> None:
        """get_route raises KeyError for an unknown id."""
        with pytest.raises(KeyError):
            get_route("nonexistent")

    def test_route_ids_returns_all(self) -> None:
        """route_ids() returns every id in registry order."""
        assert route_ids() == tuple(r.id for r in ROUTES)


class TestRouteFieldValidity:
    def test_naming_keys_exist_in_codecs(self) -> None:
        """Every route's naming key exists in the CODECS table."""
        for route in ROUTES:
            assert route.naming in CODECS, f"route {route.id} names unknown codec {route.naming!r}"

    def test_dialects_are_known(self) -> None:
        """Every route's dialect is one of the known dialect strings."""
        for route in ROUTES:
            assert route.dialect in _KNOWN_DIALECTS, f"route {route.id} has unknown dialect {route.dialect!r}"

    def test_auth_is_valid(self) -> None:
        """Every route's auth is a valid AuthScheme value."""
        valid_auth = {"api_key", "bearer", "aws_sigv4", "none"}
        for route in ROUTES:
            assert route.auth in valid_auth, f"route {route.id} has invalid auth {route.auth!r}"


class TestRouteSpec:
    def test_anthropic_route(self) -> None:
        """The anthropic route matches the specification table."""
        r = get_route("anthropic")
        assert r.operator == "anthropic"
        assert r.dialect == "anthropic-messages"
        assert r.auth == "api_key"
        assert r.listing == "native"
        assert r.capability_overlay == "anthropic"
        assert r.price_source == "anthropic"
        assert r.localities == ("global",)

    def test_bedrock_converse_route(self) -> None:
        """The bedrock-converse route carries the geo locality set and no listing."""
        r = get_route("bedrock-converse")
        assert r.operator == "aws"
        assert r.dialect == "bedrock-converse"
        assert r.listing is None
        assert r.price_source == "aws"
        assert r.localities == ("us", "eu", "apac", "jp", "au", "ca", "global", "us-gov")

    def test_voyage_route(self) -> None:
        """The voyage route is an embedding route with no listing and no price source."""
        r = get_route("voyage")
        assert r.dialect == "voyage-embeddings"
        assert r.listing is None
        assert r.price_source is None
        assert r.capability_overlay == "voyage"

    def test_ollama_cloud_endpoint(self) -> None:
        """The ollama-cloud route carries its endpoint template."""
        r = get_route("ollama-cloud")
        assert r.endpoint_template == "https://ollama.com/v1"
        assert r.price_source is None
    def test_bedrock_mantle_route(self) -> None:
        """The bedrock-mantle route uses the anthropic-messages dialect with a regional endpoint template."""
        r = get_route("bedrock-mantle")
        assert r.operator == "aws"
        assert r.dialect == "anthropic-messages"
        assert r.auth == "bearer"
        assert r.endpoint_template == "https://bedrock-mantle.{region}.api.aws/anthropic"
        assert r.naming == "bedrock-mantle"
        assert r.localities == ("us", "eu", "apac", "jp", "au", "ca", "global", "us-gov")
        assert r.listing is None
        assert r.capability_overlay == "bedrock-mantle"
        assert r.price_source == "aws"