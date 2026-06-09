# Unit tests for koan.agents.registry -- AgentRegistry and compute_balanced_profile.
#
# NOTE: TestGetInstallation, TestResolveInstallation, TestResolveAgentConfigThinking,
# and TestComputeBalancedProfile removed in M4 -- their subjects (ProbeResult,
# AgentInstallation, ModelInfo, get_installation, resolve_installation,
# resolve_agent_config, compute_balanced_profile probe path) are all deleted.
# Replacement coverage lives in tests/test_provider_config.py.

import asyncio

import pytest
import yaml

from koan.agents.base import AgentError
from koan.agents.registry import AgentRegistry, _best_supported_thinking
from koan.config import KoanConfig, save_koan_config


# -- _best_supported_thinking --------------------------------------------------

class TestBestSupportedThinking:
    def test_desired_is_supported(self):
        assert _best_supported_thinking(frozenset({"disabled", "high"}), "high") == "high"

    def test_clamp_to_highest_below(self):
        assert _best_supported_thinking(frozenset({"disabled", "low"}), "high") == "low"

    def test_disabled_only(self):
        assert _best_supported_thinking(frozenset({"disabled"}), "high") == "disabled"

    def test_exact_medium(self):
        assert _best_supported_thinking(frozenset({"disabled", "low", "medium"}), "medium") == "medium"




# -- resolve_model_spec thinking clamp ----------------------------------------

class TestResolveModelSpecThinkingClamp:
    """Verify that resolve_model_spec clamps over-requested thinking modes and logs."""

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

    def test_thinking_clamped_when_above_supported_set(self, caplog):
        """resolve_model_spec clamps 'xhigh' to 'high' for claude-opus-4-0 (max supported)."""
        import logging
        registry = AgentRegistry()
        config = self._make_config(thinking="xhigh")
        with caplog.at_level(logging.INFO, logger="koan.agent_registry"):
            spec = registry.resolve_model_spec("orchestrator", config)
        # claude-opus-4-0 thinking_modes from MODEL_CAPABILITIES = ["medium", "high"]
        assert spec.thinking == "high"
        assert "clamped" in caplog.text

    def test_no_clamp_when_mode_is_supported(self, caplog):
        """resolve_model_spec passes through 'medium' unchanged for claude-opus-4-0."""
        import logging
        registry = AgentRegistry()
        config = self._make_config(thinking="medium")
        with caplog.at_level(logging.INFO, logger="koan.agent_registry"):
            spec = registry.resolve_model_spec("orchestrator", config)
        assert spec.thinking == "medium"
        assert "clamped" not in caplog.text

    def test_disabled_always_allowed(self):
        """resolve_model_spec allows 'disabled' even when model has non-empty thinking_modes."""
        registry = AgentRegistry()
        config = self._make_config(thinking="disabled")
        spec = registry.resolve_model_spec("orchestrator", config)
        assert spec.thinking == "disabled"

    def test_variant_context_window_used_when_advertised(self):
        """resolve_model_spec uses slot.context_window when it matches an advertised variant."""
        # Temporarily inject a variant for the test model so we can verify selection.
        from koan.agents import model_catalog
        original = dict(model_catalog.CONTEXT_WINDOW_VARIANTS)
        model_catalog.CONTEXT_WINDOW_VARIANTS[("anthropic", "claude-opus-4-0")] = [1_000_000]
        try:
            from koan.types import CachingPolicy, ConfiguredModel, Connection, Preset, SlotAssignment
            from koan.config import KoanConfig
            conn = Connection(id="test-conn2", type="anthropic")
            cm = ConfiguredModel(id="test-cm2", connection_id="test-conn2", model_id="claude-opus-4-0")
            slot = SlotAssignment(
                configured_model_id="test-cm2",
                thinking="disabled",
                caching=CachingPolicy(),
                context_window=1_000_000,
            )
            config = KoanConfig(
                connections=[conn],
                configured_models=[cm],
                presets={"$last": Preset(slots={"strong": slot})},
                active="$last",
            )
            registry = AgentRegistry()
            spec = registry.resolve_model_spec("orchestrator", config)
            assert spec.context_window == 1_000_000
        finally:
            model_catalog.CONTEXT_WINDOW_VARIANTS.clear()
            model_catalog.CONTEXT_WINDOW_VARIANTS.update(original)

    def test_base_context_window_used_when_no_variant(self):
        """resolve_model_spec falls back to the resolved base context window."""
        registry = AgentRegistry()
        config = self._make_config(thinking="disabled")
        spec = registry.resolve_model_spec("orchestrator", config)
        # claude-opus-4-0 has 200_000 base context window in MODEL_CAPABILITIES.
        assert spec.context_window == 200_000


# -- save_koan_config write lock -----------------------------------------------

class TestWriteLock:
    def test_sequential_writes(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        # Reset module-level lock so it gets created fresh
        monkeypatch.setattr("koan.config._config_write_lock", None)

        config1 = KoanConfig(scout_concurrency=4)
        config2 = KoanConfig(scout_concurrency=16)

        async def run():
            await asyncio.gather(
                save_koan_config(config1),
                save_koan_config(config2),
            )

        asyncio.run(run())

        result = yaml.safe_load(config_path.read_text("utf-8"))
        # Both writes completed; final value is one of {4, 16}
        assert result["scout_concurrency"] in (4, 16)
        # File is valid JSON (not corrupted by concurrent writes)
        assert isinstance(result, dict)
