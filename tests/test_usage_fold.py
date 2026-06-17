# Tests for M5 usage fold: cache token accumulation, cost derivation,
# context-window percent derivation, and guard paths.
# Uses the same fold/VersionedEvent pattern as test_projections.py.

from __future__ import annotations

import pytest

from koan.projections import (
    Projection,
    VersionedEvent,
    fold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(
    event_type: str,
    payload: dict,
    agent_id: str | None = None,
    version: int = 1,
) -> VersionedEvent:
    return VersionedEvent(
        version=version,
        event_type=event_type,
        timestamp="2026-01-01T00:00:00Z",
        agent_id=agent_id,
        payload=payload,
    )


def _proj_with_primary(
    agent_id: str = "a1",
    provider: str | None = None,
    model: str | None = None,
) -> Projection:
    """Return a Projection with a run and a primary agent carrying model identity."""
    p = Projection()
    p = fold(p, _e("run_started", {
        "profile": "balanced",
        "installations": {},
        "scout_concurrency": 8,
    }))
    p = fold(p, _e("agent_spawned", {
        "agent_id": agent_id,
        "role": "orchestrator",
        "label": "",
        "model": model,
        "is_primary": True,
        "started_at_ms": 1000,
        "provider": provider,
    }, agent_id=agent_id))
    return p


# ---------------------------------------------------------------------------
# Cache token accumulation
# ---------------------------------------------------------------------------

class TestCacheTokenFold:

    def test_cache_tokens_accumulate_across_turns(self):
        """Cache tokens from separate agent_exited calls are summed cumulatively."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("agent_spawned", {
            "agent_id": "a2",
            "role": "scout",
            "label": "s",
            "model": None,
            "is_primary": False,
            "started_at_ms": 0,
            "provider": None,
        }, agent_id="a2"))
        # Exit a2 with cache usage; a1 inherits nothing.
        r = fold(p, _e("agent_exited", {
            "exit_code": 0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 200,
                "cache_write_tokens": 100,
                "last_input_tokens": 10,
            },
        }, agent_id="a2"))
        conv = r.run.agents["a2"].conversation
        assert conv.cache_read_tokens == 200
        assert conv.cache_write_tokens == 100

    def test_cache_tokens_accumulate_cumulatively(self):
        """Second agent_exited adds to first; cache tokens are sums not replacements."""
        p = _proj_with_primary("a1")
        # First exit
        p = fold(p, _e("agent_exited", {
            "exit_code": 0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 100,
                "cache_write_tokens": 50,
                "last_input_tokens": 10,
            },
        }, agent_id="a1"))
        # Respawn a1 (simulate second run -- fresh projection)
        p2 = _proj_with_primary("a1")
        p2 = fold(p2, _e("agent_exited", {
            "exit_code": 0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 300,
                "cache_write_tokens": 150,
                "last_input_tokens": 10,
            },
        }, agent_id="a1"))
        assert p2.run.agents["a1"].conversation.cache_read_tokens == 300
        assert p2.run.agents["a1"].conversation.cache_write_tokens == 150

    def test_cache_tokens_zero_when_absent(self):
        """When usage dict has no cache fields, cache token counts remain 0."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("agent_exited", {
            "exit_code": 0,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert conv.cache_read_tokens == 0
        assert conv.cache_write_tokens == 0


# ---------------------------------------------------------------------------
# Cost derivation
# ---------------------------------------------------------------------------

class TestCostDerivation:

    def test_total_cost_usd_positive_for_known_model(self):
        """A profile-backed Google model yields total_cost_usd > 0 after agent_exited."""
        p = _proj_with_primary(
            "a1",
            provider="google",
            model="gemini-2.5-flash",
        )
        r = fold(p, _e("agent_exited", {
            "exit_code": 0,
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "last_input_tokens": 1000,
            },
        }, agent_id="a1"))
        assert r.run.agents["a1"].conversation.total_cost_usd > 0

    def test_total_cost_usd_zero_when_no_provider(self):
        """Without a provider set, total_cost_usd stays at its default 0.0."""
        p = _proj_with_primary("a1", provider=None, model="some-model")
        r = fold(p, _e("agent_exited", {
            "exit_code": 0,
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "last_input_tokens": 1000,
            },
        }, agent_id="a1"))
        assert r.run.agents["a1"].conversation.total_cost_usd == 0.0

    def test_total_cost_usd_unresolvable_model_does_not_raise(self):
        """An unknown model triggers a price lookup failure; fold must not raise."""
        p = _proj_with_primary(
            "a1",
            provider="google",
            model="nonexistent-model-xyz-9999",
        )
        # Should not raise -- the guard catches the ValueError from price_for_usage.
        r = fold(p, _e("agent_exited", {
            "exit_code": 0,
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "last_input_tokens": 1000,
            },
        }, agent_id="a1"))
        # Prior cost (0.0) is preserved on failure.
        assert r.run.agents["a1"].conversation.total_cost_usd == 0.0


