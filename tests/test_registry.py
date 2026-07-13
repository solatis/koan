# Unit tests for koan.agents.registry -- AgentRegistry.
#
# M2: _best_supported_thinking and thinking clamping are deleted (D4: substrate
# thinking vocabulary). Tests updated to verify passthrough behavior (no clamping).
# max_tokens now comes from offering.caps.max_output.

import asyncio

import pytest
import yaml

from koan.agents.base import AgentError
from koan.agents.registry import AgentRegistry
from koan.config import KoanConfig, save_koan_config


# -- resolve_model_spec thinking passthrough -----------------------------------

class TestResolveModelSpecThinking:
    """Verify that resolve_model_spec passes thinking modes through without clamping (D4)."""

    def _make_config(self, thinking: str, model_id: str = "claude-opus-4-0", provider_type: str = "anthropic"):
        """Build a minimal KoanConfig with one connection, one model, and one slot."""
        from koan.types import (
            CachingPolicy, ConfiguredModel, Connection, Preset, SlotAssignment,
        )
        conn = Connection(id="test-conn", type=provider_type)
        cm = ConfiguredModel(id="test-cm", connection_id="test-conn", model_id=model_id)
        slot = SlotAssignment(
            configured_model_id="test-cm",
            thinking=thinking,
            caching=CachingPolicy(),
        )
        from koan.config import KoanConfig
        return KoanConfig(
            connections=[conn],
            configured_models=[cm],
            presets={"$last": Preset(slots={"strong": slot})},
            active="$last",
        )

    def test_thinking_passthrough_xhigh(self):
        """resolve_model_spec passes 'xhigh' through unchanged (no clamping, D4).

        The old code clamped xhigh to the highest supported mode; the new code
        passes the raw mode through to pydantic-ai via apply_thinking.
        """
        registry = AgentRegistry()
        config = self._make_config(thinking="xhigh")
        spec = registry.resolve_model_spec("orchestrator", config, None)
        # claude-opus-4-0 supports up to high in the old catalog, but D4 says
        # koan no longer clamps -- the substrate validates at call time.
        assert spec.thinking == "xhigh"
        assert spec.settings.get("thinking") == "xhigh"

    def test_no_clamp_when_mode_is_supported(self):
        """resolve_model_spec passes through 'medium' unchanged for claude-opus-4-0."""
        registry = AgentRegistry()
        config = self._make_config(thinking="medium")
        spec = registry.resolve_model_spec("orchestrator", config, None)
        assert spec.thinking == "medium"
        assert spec.settings.get("thinking") == "medium"

    def test_disabled_always_allowed(self):
        """resolve_model_spec allows 'disabled' even when model has thinking modes."""
        registry = AgentRegistry()
        config = self._make_config(thinking="disabled")
        spec = registry.resolve_model_spec("orchestrator", config, None)
        assert spec.thinking == "disabled"
        assert "thinking" not in spec.settings

    def test_max_tokens_for_opus(self):
        """spec.settings['max_tokens'] is the caps.max_output for claude-opus-4-0."""
        registry = AgentRegistry()
        config = self._make_config(thinking="medium", model_id="claude-opus-4-0")
        spec = registry.resolve_model_spec("orchestrator", config, None)
        # claude-opus-4-0 has max_output=32000 in the base catalog.
        assert spec.settings["max_tokens"] == 32000

    def test_max_tokens_for_sonnet(self):
        """spec.settings['max_tokens'] is the caps.max_output for claude-sonnet-4-5."""
        registry = AgentRegistry()
        config = self._make_config(thinking="medium", model_id="claude-sonnet-4-5")
        spec = registry.resolve_model_spec("orchestrator", config, None)
        # claude-sonnet-4-5 has max_output=32768 in the base catalog.
        assert spec.settings["max_tokens"] == 32768

    def test_bedrock_anthropic_gains_thinking(self):
        """Bedrock-Anthropic now gains thinking (D4 intentional behavior change).

        The old code returned {} for bedrock thinking; the new code emits
        {'thinking': mode} via apply_thinking for all dialects.
        """
        registry = AgentRegistry()
        config = self._make_config(
            thinking="medium",
            model_id="eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
            provider_type="bedrock-converse",
        )
        spec = registry.resolve_model_spec("orchestrator", config, None)
        assert spec.settings.get("thinking") == "medium"
        assert spec.provider == "bedrock-converse"


# -- save_koan_config write lock -----------------------------------------------

class TestWriteLock:
    def test_sequential_writes(self, koan_home, monkeypatch):
        # Reset module-level lock so it gets created fresh
        monkeypatch.setattr("koan.config._config_write_lock", None)

        config1 = KoanConfig(scout_concurrency=4)
        config2 = KoanConfig(scout_concurrency=16)

        async def run():
            await asyncio.gather(
                save_koan_config(config1, koan_home),
                save_koan_config(config2, koan_home),
            )

        asyncio.run(run())

        result = yaml.safe_load((koan_home / "config.yaml").read_text("utf-8"))
        # Both writes completed; final value is one of {4, 16}
        assert result["scout_concurrency"] in (4, 16)
        # File is valid JSON (not corrupted by concurrent writes)
        assert isinstance(result, dict)