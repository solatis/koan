# Tests for koan.models.offering.

from __future__ import annotations

import pytest

from koan.models.identity import ModelIdentity, Unresolved
from koan.models.offering import Offering, resolve_offering


class TestResolveOffering:
    def test_anthropic_resolved(self) -> None:
        """resolve_offering returns a resolved anthropic offering with merged caps."""
        o = resolve_offering("anthropic", "claude-sonnet-4-5")
        assert isinstance(o, Offering)
        assert o.route.id == "anthropic"
        assert o.ref == ModelIdentity("anthropic", "claude-sonnet", "4.5")
        assert o.caps.resolved is True
        # Route overlay applied: anthropic-direct gets explicit caching + native tools.
        assert o.caps.prompt_caching == "explicit"
        assert "web_search" in o.caps.native_tools
        assert o.locality is None

    def test_bedrock_converse_eu_locality(self) -> None:
        """resolve_offering extracts the eu locality from a bedrock-converse id."""
        o = resolve_offering("bedrock-converse", "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert o.route.id == "bedrock-converse"
        assert o.ref == ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929")
        assert o.locality == "eu"
        # Bedrock strips native tools (route-aware profile) and keeps explicit caching.
        assert o.caps.native_tools == frozenset()
        assert o.caps.prompt_caching == "explicit"
        # D4 behavior change: Bedrock-Anthropic gains thinking.
        assert o.caps.thinking.supported is True
    def test_bedrock_mantle_resolved(self) -> None:
        """resolve_offering resolves anthropic.claude-sonnet-4-5 on the bedrock-mantle route."""
        o = resolve_offering("bedrock-mantle", "anthropic.claude-sonnet-4-5")
        assert o.route.id == "bedrock-mantle"
        assert o.route.dialect == "anthropic-messages"
        from koan.models.identity import ModelIdentity
        assert isinstance(o.ref, ModelIdentity)
        assert o.ref.vendor == "anthropic"
        assert o.ref.family == "claude-sonnet"
        assert o.ref.version == "4.5"
        assert o.caps.prompt_caching == "explicit"
        # native_tools: the overlay sets frozenset() but the anthropic profile
        # (loaded via anthropic-messages dialect) overrides it with tool classes.
        # This is a confirmed outcome (see Key Decision 3), not a bug.
        assert o.caps.native_tools is not None
        assert o.caps.resolved is True
        assert o.locality is None

    def test_bedrock_mantle_strips_v1_suffix(self) -> None:
        """resolve_offering strips -v1 and resolves the underlying Claude identity."""
        o = resolve_offering("bedrock-mantle", "anthropic.claude-sonnet-4-6-v1")
        from koan.models.identity import ModelIdentity
        assert isinstance(o.ref, ModelIdentity)
        assert o.ref.family == "claude-sonnet"
        assert o.ref.version == "4.6"

    def test_openrouter_resolved(self) -> None:
        """resolve_offering resolves an OpenRouter namespaced id."""
        o = resolve_offering("openrouter", "anthropic/claude-sonnet-4.5")
        assert o.route.id == "openrouter"
        assert o.ref == ModelIdentity("anthropic", "claude-sonnet", "4.5")
        assert o.caps.resolved is True
        # OpenRouter overlay: prompt_caching none, listing True.
        assert o.caps.prompt_caching == "none"
        assert o.caps.listing is True

    def test_unrecognized_model_is_unresolved(self) -> None:
        """An unrecognized model string yields an Unresolved ref with resolved=False caps."""
        o = resolve_offering("anthropic", "totally-unknown-model")
        assert isinstance(o.ref, Unresolved)
        assert o.caps.resolved is False
        # Conservative defaults with unknown provenance.
        assert o.caps.prompt_caching == "none"
        assert o.caps.provenance["prompt_caching"].source == "unknown"

    def test_unknown_route_raises(self) -> None:
        """An unknown route id raises KeyError (registry is the sole validation source)."""
        with pytest.raises(KeyError):
            resolve_offering("nonexistent-route", "claude-sonnet-4-5")

    def test_voyage_embedding_offering(self) -> None:
        """resolve_offering returns an embedding offering for a voyage model."""
        o = resolve_offering("voyage", "voyage-4-large")
        assert o.route.id == "voyage"
        assert isinstance(o.ref, ModelIdentity)
        assert o.ref.kind == "embedding"
        assert o.caps.embedding_dims == (256, 512, 1024, 2048)
        assert o.caps.embedding_default_dim == 1024
        # Chat fields stay conservative; voyage has no listing/caching.
        assert o.caps.prompt_caching == "none"
        assert o.caps.listing is False
class TestAdapterBaseUrl:
    """Tests for the generic endpoint_template {region} substitution in build_model."""

    def test_base_url_from_template_with_region(self) -> None:
        """build_model constructs base_url from endpoint_template with {region} substituted."""
        from koan.agents.adapter import build_model
        from koan.models.offering import resolve_offering
        from koan.types import ModelSpec
        from unittest.mock import patch, MagicMock

        offering = resolve_offering("bedrock-mantle", "anthropic.claude-sonnet-4-5")
        spec = ModelSpec(offering=offering, settings={})

        with patch("pydantic_ai.models.anthropic.AnthropicModel") as mock_model, \
             patch("pydantic_ai.providers.anthropic.AnthropicProvider") as mock_provider:
            mock_model.return_value = MagicMock()
            build_model(spec, api_key="test-key", region="eu")

            # AnthropicProvider should receive the template-substituted base_url.
            call_kwargs = mock_provider.call_args
            assert call_kwargs.kwargs["base_url"] == "https://bedrock-mantle.eu.api.aws/anthropic"

    def test_base_url_from_template_with_connection_locality(self) -> None:
        """build_model substitutes {region} from the region param (connection locality)."""
        from koan.agents.adapter import build_model
        from koan.models.offering import resolve_offering
        from koan.types import ModelSpec
        from unittest.mock import patch, MagicMock

        offering = resolve_offering("bedrock-mantle", "anthropic.claude-sonnet-4-5")
        spec = ModelSpec(offering=offering, settings={})

        with patch("pydantic_ai.models.anthropic.AnthropicModel") as mock_model, \
             patch("pydantic_ai.providers.anthropic.AnthropicProvider") as mock_provider:
            mock_model.return_value = MagicMock()
            # Pass region="us" to simulate connection locality.
            build_model(spec, api_key="test-key", region="us")

            call_kwargs = mock_provider.call_args
            assert call_kwargs.kwargs["base_url"] == "https://bedrock-mantle.us.api.aws/anthropic"

    def test_explicit_base_url_overrides_template(self) -> None:
        """When base_url is explicitly set, the template is not used."""
        from koan.agents.adapter import build_model
        from koan.models.offering import resolve_offering
        from koan.types import ModelSpec
        from unittest.mock import patch, MagicMock

        offering = resolve_offering("bedrock-mantle", "anthropic.claude-sonnet-4-5")
        spec = ModelSpec(offering=offering, settings={})

        with patch("pydantic_ai.models.anthropic.AnthropicModel") as mock_model, \
             patch("pydantic_ai.providers.anthropic.AnthropicProvider") as mock_provider:
            mock_model.return_value = MagicMock()
            build_model(spec, api_key="test-key", region="eu", base_url="https://custom.example.com")

            call_kwargs = mock_provider.call_args
            assert call_kwargs.kwargs["base_url"] == "https://custom.example.com"

    def test_missing_region_raises_for_template_route(self) -> None:
        """build_model raises missing_region when endpoint_template has {region} but no locality."""
        from koan.agents.adapter import build_model
        from koan.agents.base import AgentError
        from koan.models.offering import resolve_offering
        from koan.types import ModelSpec

        offering = resolve_offering("bedrock-mantle", "anthropic.claude-sonnet-4-5")
        spec = ModelSpec(offering=offering, settings={})

        with pytest.raises(AgentError) as exc:
            build_model(spec, api_key="test-key", region=None)
        assert exc.value.diagnostic.code == "missing_region"

    def test_anthropic_direct_route_not_affected(self) -> None:
        """The anthropic direct route (endpoint_template=None) is not affected by the template logic."""
        from koan.agents.adapter import build_model
        from koan.models.offering import resolve_offering
        from koan.types import ModelSpec
        from unittest.mock import patch, MagicMock

        offering = resolve_offering("anthropic", "claude-sonnet-4-5")
        spec = ModelSpec(offering=offering, settings={})

        with patch("pydantic_ai.models.anthropic.AnthropicModel") as mock_model, \
             patch("pydantic_ai.providers.anthropic.AnthropicProvider") as mock_provider:
            mock_model.return_value = MagicMock()
            build_model(spec, api_key="test-key")

            # No base_url should be passed (endpoint_template is None for anthropic direct).
            call_kwargs = mock_provider.call_args
            assert "base_url" not in call_kwargs.kwargs or call_kwargs.kwargs.get("base_url") is None