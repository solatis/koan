# Flatten snapshot tests for build_resolved_model (M2).
#
# Golden-byte tests that call build_resolved_model for representative inputs and
# snapshot the resulting ModelSpec.settings. These pin the flatten output so any
# future change to thinking values or cache settings is visible in a diff.
#
# Intentional behavior changes (D4):
#   - Thinking values now use pydantic-ai's unified `thinking` key instead of
#     per-provider keys (google_thinking_config, anthropic_thinking, etc.).
#   - Bedrock-Anthropic now gains thinking (the old code returned {} for bedrock).
#   - Thinking mode is no longer clamped (koan trusts the substrate to validate).

from __future__ import annotations

from koan.agents.registry import build_resolved_model
from koan.types import CachingPolicy, ConfiguredModel, Connection


def _conn(route_id: str, locality: str | None = None) -> Connection:
    """Build a minimal Connection for the given route id."""
    return Connection(id=f"test-{route_id}", type=route_id, locality=locality)


def _cm(model_id: str) -> ConfiguredModel:
    """Build a minimal ConfiguredModel for the given model id."""
    return ConfiguredModel(id=f"cm-{model_id}", connection_id="", model_id=model_id)


def test_flatten_anthropic_sonnet() -> None:
    """Anthropic sonnet with medium thinking + auto caching + long tier."""
    conn = _conn("anthropic")
    cm = _cm("claude-sonnet-4-5")
    spec = build_resolved_model(conn, cm, "medium", CachingPolicy(mode="auto"), None, "test-key", "long")
    assert spec.settings == {
        "thinking": "medium",
        "anthropic_cache": "5m",
        "anthropic_cache_instructions": "1h",
        "anthropic_cache_tool_definitions": "1h",
        "max_tokens": 32768,
    }


def test_flatten_bedrock_sonnet() -> None:
    """Bedrock-converse Anthropic sonnet gains thinking (D4 behavior change).

    The old code returned {} for bedrock thinking; the new code emits
    {'thinking': 'medium'} via apply_thinking for all dialects.
    """
    conn = _conn("bedrock-converse", locality="eu")
    cm = _cm("eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
    spec = build_resolved_model(conn, cm, "medium", CachingPolicy(mode="auto"), None, "test-key", "long")
    assert spec.settings == {
        "thinking": "medium",
        "bedrock_cache_messages": "5m",
        "bedrock_cache_instructions": "1h",
        "bedrock_cache_tool_definitions": "1h",
        "max_tokens": 32768,
    }


def test_flatten_openai_gpt4o() -> None:
    """OpenAI gpt-4o: no thinking (disabled), no cache keys (automatic caching, no koan emission)."""
    conn = _conn("openai")
    cm = _cm("gpt-4o")
    spec = build_resolved_model(conn, cm, "disabled", CachingPolicy(mode="auto"), None, "test-key", "long")
    assert spec.settings == {
        "max_tokens": 16384,
    }


def test_flatten_google_flash() -> None:
    """Google gemini-3.5-flash with medium thinking: unified thinking key, no cache keys."""
    conn = _conn("google")
    cm = _cm("gemini-3.5-flash")
    spec = build_resolved_model(conn, cm, "medium", CachingPolicy(mode="auto"), None, "test-key", "long")
    assert spec.settings == {
        "thinking": "medium",
        "max_tokens": 65536,
    }


def test_flatten_voyage() -> None:
    """Voyage embedding model: no thinking, no cache keys, embedding_dim passed through."""
    conn = _conn("voyage")
    cm = _cm("voyage-4-large")
    spec = build_resolved_model(conn, cm, "disabled", CachingPolicy(mode="auto"), 2048, "test-key", "long")
    assert spec.settings == {
        "max_tokens": 32768,  # conservative default for embedding models
    }
    assert spec.embedding_dim == 2048
    assert spec.provider == "voyage"
    assert spec.model == "voyage-4-large"


def test_flatten_disabled_thinking() -> None:
    """Thinking='disabled' omits the thinking key from settings entirely."""
    conn = _conn("anthropic")
    cm = _cm("claude-sonnet-4-5")
    spec = build_resolved_model(conn, cm, "disabled", CachingPolicy(mode="auto"), None, "test-key", "long")
    assert "thinking" not in spec.settings


def test_flatten_caching_off() -> None:
    """CachingPolicy(mode='off') suppresses all cache settings."""
    conn = _conn("anthropic")
    cm = _cm("claude-sonnet-4-5")
    spec = build_resolved_model(conn, cm, "medium", CachingPolicy(mode="off"), None, "test-key", "long")
    assert not any(k.startswith("anthropic_cache") for k in spec.settings)


def test_flatten_xhigh_on_haiku() -> None:
    """xhigh on a model with empty thinking modes (claude-haiku-3.5) is passed through (D4).

    The old code clamped xhigh to the highest supported mode; the new code passes
    the raw mode through to pydantic-ai via apply_thinking. If pydantic-ai rejects
    this at call time, that is the substrate's responsibility.
    """
    conn = _conn("anthropic")
    cm = _cm("claude-3-5-haiku-latest")
    spec = build_resolved_model(conn, cm, "xhigh", CachingPolicy(mode="auto"), None, "test-key", "long")
    # No clamping: xhigh passes through unchanged.
    assert spec.settings.get("thinking") == "xhigh"
    # Haiku has a lower max_output (8192) and higher cache_minimum_tokens (4096).
    assert spec.settings["max_tokens"] == 8192


def test_flatten_short_tier_all_keys_5m() -> None:
    """Short-tier (scout/reviewer) anthropic: all cache keys are '5m' (uniform short)."""
    conn = _conn("anthropic")
    cm = _cm("claude-sonnet-4-5")
    spec = build_resolved_model(conn, cm, "medium", CachingPolicy(mode="auto"), None, "test-key", "short")
    assert spec.settings["anthropic_cache"] == "5m"
    assert spec.settings["anthropic_cache_instructions"] == "5m"
    assert spec.settings["anthropic_cache_tool_definitions"] == "5m"