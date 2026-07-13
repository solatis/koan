# Tests for koan.models.pricing.

from __future__ import annotations

from decimal import Decimal

import pytest

from koan.models.offering import resolve_offering
from koan.models.pricing import PriceRef, price_for


class TestPriceFor:
    def test_known_offering_returns_positive_rates(self) -> None:
        """price_for returns a PriceRef with positive per-million rates for a known model."""
        o = resolve_offering("anthropic", "claude-sonnet-4-5")
        ref = price_for(o)
        assert isinstance(ref, PriceRef)
        assert ref.input_per_million is not None
        assert ref.output_per_million is not None
        assert ref.input_per_million > 0
        assert ref.output_per_million > 0
        assert ref.source == "anthropic"

    def test_price_source_none_returns_unavailable(self) -> None:
        """A route with price_source=None yields an unavailable PriceRef."""
        o = resolve_offering("ollama-cloud", "llama3.3:70b")
        ref = price_for(o)
        assert ref.input_per_million is None
        assert ref.output_per_million is None
        assert ref.source == "unavailable"

    def test_voyage_price_source_none(self) -> None:
        """The voyage route has no price source -> unavailable."""
        o = resolve_offering("voyage", "voyage-4-large")
        ref = price_for(o)
        assert ref.source == "unavailable"

    def test_zero_tokens_handled_gracefully(self) -> None:
        """price_for with zero tokens returns the rate card unchanged (rates are token-independent)."""
        o = resolve_offering("anthropic", "claude-sonnet-4-5")
        ref = price_for(o, input_tokens=0, output_tokens=0)
        # Per-million rates are model-level and do not depend on the request's token mix.
        assert ref.input_per_million is not None
        assert ref.input_per_million > 0

    def test_bedrock_uses_aws_provider(self) -> None:
        """The bedrock-converse route prices via the genai-prices 'aws' provider."""
        o = resolve_offering("bedrock-converse", "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
        ref = price_for(o)
        assert ref.source == "aws"
        if ref.input_per_million is not None:
            assert isinstance(ref.input_per_million, Decimal)