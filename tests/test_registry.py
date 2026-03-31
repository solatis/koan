# Unit tests for koan.runners.registry -- RunnerRegistry and compute_balanced_profile.

import asyncio
import json

import pytest

from koan.config import KoanConfig, save_koan_config
from koan.probe import ProbeResult
from koan.runners.base import RunnerError
from koan.runners.registry import RunnerRegistry, compute_balanced_profile, _best_supported_thinking
from koan.types import AgentInstallation, ModelInfo, Profile, ProfileTier


# -- compute_balanced_profile --------------------------------------------------

# -- helpers for building probe results with models ---------------------------

def _codex_models() -> list[ModelInfo]:
    return [
        ModelInfo(alias="gpt-5", display_name="GPT-5", thinking_modes=frozenset({"disabled"}), tier_hint="strong"),
        ModelInfo(alias="gpt-5-mini", display_name="GPT-5 Mini", thinking_modes=frozenset({"disabled"}), tier_hint="cheap"),
    ]

def _claude_models() -> list[ModelInfo]:
    all_modes = frozenset({"disabled", "low", "medium", "high", "xhigh"})
    return [
        ModelInfo(alias="opus", display_name="Opus", thinking_modes=all_modes, tier_hint="strong"),
        ModelInfo(alias="sonnet", display_name="Sonnet", thinking_modes=all_modes, tier_hint="standard"),
        ModelInfo(alias="haiku", display_name="Haiku", thinking_modes=frozenset({"disabled", "low"}), tier_hint="cheap"),
    ]

def _gemini_models() -> list[ModelInfo]:
    return [
        ModelInfo(alias="gemini-pro", display_name="Gemini Pro", thinking_modes=frozenset({"disabled", "low", "medium", "high"}), tier_hint="strong"),
        ModelInfo(alias="gemini-flash", display_name="Gemini Flash", thinking_modes=frozenset({"disabled", "low"}), tier_hint="cheap"),
    ]


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


# -- compute_balanced_profile --------------------------------------------------

class TestComputeBalancedProfile:
    def test_all_available_with_models(self):
        probes = [
            ProbeResult(runner_type="claude", available=True, models=_claude_models()),
            ProbeResult(runner_type="codex", available=True, models=_codex_models()),
            ProbeResult(runner_type="gemini", available=True, models=_gemini_models()),
        ]
        p = compute_balanced_profile(probes)
        assert p.name == "balanced"
        assert p.tiers["strong"].runner_type == "claude"
        assert p.tiers["strong"].model == "opus"
        assert p.tiers["strong"].thinking == "high"
        assert p.tiers["standard"].runner_type == "claude"
        assert p.tiers["standard"].model == "sonnet"
        assert p.tiers["standard"].thinking == "medium"
        assert p.tiers["cheap"].runner_type == "claude"
        assert p.tiers["cheap"].model == "haiku"
        assert p.tiers["cheap"].thinking == "disabled"

    def test_all_available_without_models_uses_defaults(self):
        """When probe results lack model info, default thinking is kept."""
        probes = [
            ProbeResult(runner_type="claude", available=True),
            ProbeResult(runner_type="codex", available=True),
            ProbeResult(runner_type="gemini", available=True),
        ]
        p = compute_balanced_profile(probes)
        assert p.tiers["strong"].runner_type == "claude"
        assert p.tiers["strong"].thinking == "high"  # no model info -> default

    def test_only_claude_available(self):
        probes = [
            ProbeResult(runner_type="claude", available=True, models=_claude_models()),
            ProbeResult(runner_type="codex", available=False),
            ProbeResult(runner_type="gemini", available=False),
        ]
        p = compute_balanced_profile(probes)
        assert p.tiers["strong"].runner_type == "claude"
        assert p.tiers["strong"].model == "opus"
        assert p.tiers["strong"].thinking == "high"  # claude/opus supports high
        assert p.tiers["standard"].runner_type == "claude"
        assert p.tiers["standard"].model == "sonnet"
        assert p.tiers["cheap"].runner_type == "claude"
        assert p.tiers["cheap"].model == "haiku"

    def test_only_gemini_available(self):
        probes = [
            ProbeResult(runner_type="claude", available=False),
            ProbeResult(runner_type="codex", available=False),
            ProbeResult(runner_type="gemini", available=True),
        ]
        p = compute_balanced_profile(probes)
        for tier in ("strong", "standard", "cheap"):
            assert p.tiers[tier].runner_type == "gemini"

    def test_no_runners_available(self):
        probes = [
            ProbeResult(runner_type="claude", available=False),
            ProbeResult(runner_type="codex", available=False),
            ProbeResult(runner_type="gemini", available=False),
        ]
        p = compute_balanced_profile(probes)
        assert p.name == "balanced"
        assert p.tiers == {}

    def test_claude_preferred_for_strong(self):
        probes = [
            ProbeResult(runner_type="claude", available=True, models=_claude_models()),
            ProbeResult(runner_type="codex", available=True, models=_codex_models()),
        ]
        p = compute_balanced_profile(probes)
        assert p.tiers["strong"].runner_type == "claude"
        assert p.tiers["strong"].model == "opus"

    def test_claude_preferred_for_standard(self):
        probes = [
            ProbeResult(runner_type="claude", available=True, models=_claude_models()),
            ProbeResult(runner_type="codex", available=True, models=_codex_models()),
        ]
        p = compute_balanced_profile(probes)
        assert p.tiers["standard"].runner_type == "claude"


# -- RunnerRegistry.get_installation ------------------------------------------

class TestGetInstallation:
    def _make_config(self, installations, active=None):
        return KoanConfig(
            agent_installations=installations,
            active_installations=active or {},
        )

    def test_active_installation_resolved(self):
        inst = AgentInstallation(alias="my-claude", runner_type="claude", binary="/usr/bin/claude")
        config = self._make_config([inst], active={"claude": "my-claude"})
        reg = RunnerRegistry()
        result = reg.get_installation("claude", config)
        assert result is inst

    def test_fallback_to_first_installation(self):
        inst = AgentInstallation(alias="default-codex", runner_type="codex", binary="/usr/bin/codex")
        config = self._make_config([inst])
        reg = RunnerRegistry()
        result = reg.get_installation("codex", config)
        assert result is inst

    def test_missing_installation_raises(self):
        config = self._make_config([])
        reg = RunnerRegistry()
        with pytest.raises(RunnerError) as exc_info:
            reg.get_installation("claude", config)
        assert exc_info.value.diagnostic.code == "no_installation"

    def test_active_alias_configured_but_missing_raises(self):
        inst = AgentInstallation(alias="real-claude", runner_type="claude", binary="/usr/bin/claude")
        config = self._make_config([inst], active={"claude": "ghost-alias"})
        reg = RunnerRegistry()
        with pytest.raises(RunnerError) as exc_info:
            reg.get_installation("claude", config)
        assert exc_info.value.diagnostic.code == "no_installation"
        assert "ghost-alias" in exc_info.value.diagnostic.message

    def test_fallback_only_when_no_active_alias(self):
        inst = AgentInstallation(alias="default-codex", runner_type="codex", binary="/usr/bin/codex")
        config = self._make_config([inst], active={})
        reg = RunnerRegistry()
        result = reg.get_installation("codex", config)
        assert result is inst


# -- RunnerRegistry.resolve_installation ---------------------------------------

class TestResolveInstallation:
    def _make_config(self, installations, active=None):
        return KoanConfig(
            agent_installations=installations,
            active_installations=active or {},
        )

    def test_returns_active_when_binary_exists(self, tmp_path):
        binary = tmp_path / "claude"
        binary.touch()
        inst = AgentInstallation(alias="my-claude", runner_type="claude", binary=str(binary))
        config = self._make_config([inst], active={"claude": "my-claude"})
        reg = RunnerRegistry()
        result = reg.resolve_installation("claude", config)
        assert result is inst

    def test_falls_back_to_other_installation_when_active_binary_missing(self, tmp_path):
        good_binary = tmp_path / "claude"
        good_binary.touch()
        bad = AgentInstallation(alias="broken", runner_type="claude", binary="/nonexistent/claude")
        good = AgentInstallation(alias="working", runner_type="claude", binary=str(good_binary))
        config = self._make_config([bad, good], active={"claude": "broken"})
        reg = RunnerRegistry()
        result = reg.resolve_installation("claude", config)
        assert result is good

    def test_falls_back_to_which_when_all_binaries_missing(self, monkeypatch):
        inst = AgentInstallation(alias="bad", runner_type="claude", binary="/nonexistent/claude")
        config = self._make_config([inst])
        monkeypatch.setattr("koan.runners.registry.shutil.which", lambda cmd: "/resolved/claude")
        reg = RunnerRegistry()
        result = reg.resolve_installation("claude", config)
        assert result.binary == "/resolved/claude"
        assert result.alias == "claude-resolved"

    def test_raises_when_nothing_works(self, monkeypatch):
        inst = AgentInstallation(alias="bad", runner_type="claude", binary="/nonexistent/claude")
        config = self._make_config([inst])
        monkeypatch.setattr("koan.runners.registry.shutil.which", lambda cmd: None)
        reg = RunnerRegistry()
        with pytest.raises(RunnerError) as exc_info:
            reg.resolve_installation("claude", config)
        assert exc_info.value.diagnostic.code == "no_installation"

    def test_raises_when_no_installations_and_not_on_path(self, monkeypatch):
        config = self._make_config([])
        monkeypatch.setattr("koan.runners.registry.shutil.which", lambda cmd: None)
        reg = RunnerRegistry()
        with pytest.raises(RunnerError) as exc_info:
            reg.resolve_installation("claude", config)
        assert exc_info.value.diagnostic.code == "no_installation"


# -- save_koan_config write lock -----------------------------------------------

class TestWriteLock:
    def test_sequential_writes(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.json"
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

        result = json.loads(config_path.read_text("utf-8"))
        # Both writes completed; final value is one of {4, 16}
        assert result["scoutConcurrency"] in (4, 16)
        # File is valid JSON (not corrupted by concurrent writes)
        assert isinstance(result, dict)
