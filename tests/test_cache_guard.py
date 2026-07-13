# Tests for koan.agents.cache_guard -- check_cache_effectiveness.
#
# Covers all early-return conditions and the trip condition so that the guard
# is demonstrated to fire exactly when and only when expected.
#
# M2: the guard now takes a ModelSpec (spec) instead of (provider, model) and
# reads spec.cache_expectation instead of the deleted cache_read_expected.

from __future__ import annotations

import pytest

from koan.agents.base import AgentError
from koan.agents.cache_guard import (
    CACHE_GUARD_MIN_INPUT_TOKENS,
    CACHE_GUARD_MIN_REQUESTS,
    check_cache_effectiveness,
)
from koan.models.offering import resolve_offering
from koan.types import ModelSpec


# -- Helpers ------------------------------------------------------------------


def _make_spec(route_id: str, model_id: str) -> ModelSpec:
    """Build a ModelSpec with a real Offering so cache_expectation is populated."""
    return ModelSpec(offering=resolve_offering(route_id, model_id))


def _check(**kwargs):
    """Call check_cache_effectiveness with sensible defaults, overriding via kwargs.

    Default arguments put the call in the trip condition (would raise) so each
    test only needs to supply the field it wants to probe.
    """
    defaults = dict(
        spec=_make_spec("anthropic", "claude-sonnet-4-5"),
        caching_mode="auto",
        cumulative_input_tokens=CACHE_GUARD_MIN_INPUT_TOKENS + 1,
        cumulative_cache_read_tokens=0,
        cumulative_requests=CACHE_GUARD_MIN_REQUESTS,
    )
    defaults.update(kwargs)
    return check_cache_effectiveness(**defaults)


# -- Trip condition -----------------------------------------------------------

class TestCacheGuardTrips:
    def test_raises_for_anthropic_at_volume(self):
        """Guard raises AgentError when Anthropic shows zero cache reads at volume."""
        with pytest.raises(AgentError) as exc:
            _check(
                spec=_make_spec("anthropic", "claude-sonnet-4-5"),
                caching_mode="auto",
                cumulative_input_tokens=60_000,
                cumulative_cache_read_tokens=0,
                cumulative_requests=3,
            )
        assert exc.value.diagnostic.code == "prompt_cache_ineffective"

    def test_google_not_cache_expected_does_not_raise(self):
        """Google (google-genai dialect) has no _CACHE_TIER_TTL entry; cache_expectation
        is 'none' and the guard is skipped, even though prompt_caching is 'automatic'.

        emit_cache_settings returns {} for google-genai (no koan-emitted cache settings;
        caching is server-side automatic), so cache_expectation must be consistent and
        return 'none'.
        """
        _check(
            spec=_make_spec("google", "gemini-3.5-flash"),
            caching_mode="auto",
            cumulative_input_tokens=80_000,
            cumulative_cache_read_tokens=0,
            cumulative_requests=4,
        )  # must not raise

    def test_diagnostic_message_contains_provider_and_counts(self):
        """AgentError message includes provider/model, request count, and token count."""
        with pytest.raises(AgentError) as exc:
            _check(spec=_make_spec("anthropic", "claude-sonnet-4-5"), cumulative_requests=5)
        msg = exc.value.diagnostic.message
        assert "anthropic" in msg
        assert "claude-sonnet-4-5" in msg
        assert "5" in msg


# -- Early-return conditions --------------------------------------------------

class TestCacheGuardEarlyReturns:
    def test_caching_off_does_not_raise(self):
        """caching_mode='off' always disarms the guard regardless of other values."""
        _check(caching_mode="off")  # must not raise

    def test_cache_reads_present_does_not_raise(self):
        """Any non-zero cache_read_tokens disarms the guard permanently."""
        _check(cumulative_cache_read_tokens=1)  # must not raise

    def test_below_min_requests_does_not_raise(self):
        """Fewer than CACHE_GUARD_MIN_REQUESTS is the warmup window; no raise."""
        _check(cumulative_requests=CACHE_GUARD_MIN_REQUESTS - 1)  # must not raise

    def test_below_min_input_tokens_does_not_raise(self):
        """Below CACHE_GUARD_MIN_INPUT_TOKENS the prefix may be too small; no raise."""
        _check(cumulative_input_tokens=CACHE_GUARD_MIN_INPUT_TOKENS - 1)  # must not raise

    def test_openrouter_not_cache_expected_does_not_raise(self):
        """OpenRouter is not cache-expected; the guard is entirely skipped."""
        _check(
            spec=_make_spec("openrouter", "anthropic/claude-sonnet-4-5"),
            cumulative_input_tokens=100_000,
            cumulative_cache_read_tokens=0,
            cumulative_requests=5,
        )  # must not raise

    def test_bedrock_nova_cache_expected_raises_at_volume(self):
        """Bedrock-Nova is now cache-expected via the route overlay (M2 behavior change).

        The old system excluded nova by family-scoping (_EXPLICIT_CACHE_FAMILIES);
        the new system's bedrock-converse route overlay sets prompt_caching='explicit'
        for all models on the route. The guard fires when zero cache reads occur.
        """
        with pytest.raises(AgentError) as exc:
            _check(
                spec=_make_spec("bedrock-converse", "us.amazon.nova-pro-v1:0"),
                cumulative_input_tokens=100_000,
                cumulative_cache_read_tokens=0,
                cumulative_requests=5,
            )
        assert exc.value.diagnostic.code == "prompt_cache_ineffective"

    def test_bedrock_claude_cache_expected_raises_at_volume(self):
        """Bedrock-Claude IS cache-expected; the guard fires on zero reads at volume."""
        with pytest.raises(AgentError) as exc:
            _check(
                spec=_make_spec("bedrock-converse", "us.anthropic.claude-opus-4-0-v1:0"),
                cumulative_input_tokens=70_000,
                cumulative_cache_read_tokens=0,
                cumulative_requests=3,
            )
        assert exc.value.diagnostic.code == "prompt_cache_ineffective"

    def test_openai_not_cache_expected_does_not_raise(self):
        """OpenAI (openai-chat dialect) has no _CACHE_TIER_TTL entry; cache_expectation
        is 'none' and the guard is skipped, even though prompt_caching is 'automatic'.

        emit_cache_settings returns {} for openai-chat (no koan-emitted cache settings;
        caching is server-side automatic), so cache_expectation must be consistent and
        return 'none'.
        """
        _check(
            spec=_make_spec("openai", "gpt-4o"),
            cumulative_input_tokens=60_000,
            cumulative_cache_read_tokens=0,
            cumulative_requests=2,
        )  # must not raise

    def test_returns_none_on_success(self):
        """check_cache_effectiveness returns None (implicitly) when guard does not fire."""
        result = _check(cumulative_cache_read_tokens=500)
        assert result is None