# resolve_runner -- legacy shim for backward compatibility.
# Supports both legacy model_tiers and profile-based config schemas.
# DEPRECATED: replaced by RunnerRegistry in T13. Kept for mcp_endpoint callers.

from __future__ import annotations

from ..config import KoanConfig
from ..types import AgentInstallation, ROLE_MODEL_TIER, SubagentRole, ThinkingMode
from .base import RunnerDiagnostic, RunnerError, StreamEvent
from .claude import ClaudeRunner
from .codex import CodexRunner
from .gemini import GeminiRunner


# -- Codex alias predicate ----------------------------------------------------

_CODEX_PREFIXES = ("codex", "o", "gpt-5")


def _is_codex_model(model: str) -> bool:
    return any(model.startswith(p) for p in _CODEX_PREFIXES)


# -- Legacy adapter -----------------------------------------------------------

class _LegacyRunnerAdapter:
    """Wraps a new-signature Runner so callers using either the old 3-arg
    build_command(boot_prompt, mcp_url, model) or the new 5-arg
    build_command(boot_prompt, mcp_url, installation, model, thinking) work."""

    def __init__(self, inner: ClaudeRunner | CodexRunner | GeminiRunner) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def supported_thinking_modes(self) -> frozenset[ThinkingMode]:
        return self._inner.supported_thinking_modes

    def list_models(self, binary: str):
        return self._inner.list_models(binary)

    def parse_stream_event(self, line: str) -> list[StreamEvent]:
        return self._inner.parse_stream_event(line)

    def build_command(
        self,
        boot_prompt: str,
        mcp_url: str,
        installation_or_model: AgentInstallation | str | None = None,
        model: str | None = None,
        thinking: ThinkingMode = "disabled",
    ) -> list[str]:
        # New 5-arg style: (boot_prompt, mcp_url, installation, model, thinking)
        if isinstance(installation_or_model, AgentInstallation):
            return self._inner.build_command(
                boot_prompt, mcp_url, installation_or_model,
                model or self._inner.name, thinking,
            )
        # Legacy 3-arg style: (boot_prompt, mcp_url, model_str)
        legacy_model = installation_or_model if isinstance(installation_or_model, str) else None
        installation = AgentInstallation(
            alias=self._inner.name,
            runner_type=self._inner.name,
            binary=self._inner.name,
            extra_args=[],
        )
        return self._inner.build_command(
            boot_prompt, mcp_url, installation,
            legacy_model or self._inner.name, "disabled",
        )


# -- Runner factory by model prefix -------------------------------------------

def _make_runner(model: str, subagent_dir: str, role: SubagentRole, tier: str) -> _LegacyRunnerAdapter:
    if model.startswith("claude"):
        return _LegacyRunnerAdapter(ClaudeRunner(subagent_dir=subagent_dir))
    if _is_codex_model(model):
        return _LegacyRunnerAdapter(CodexRunner())
    if model.startswith("gemini"):
        return _LegacyRunnerAdapter(GeminiRunner(subagent_dir=subagent_dir))

    raise RunnerError(RunnerDiagnostic(
        code="unknown_provider",
        runner="",
        stage="resolve_runner",
        message=f"Unknown provider for model '{model}' (role={role}, tier={tier})",
    ))


# -- Main entry point ---------------------------------------------------------

def resolve_runner(role: SubagentRole, config: KoanConfig, subagent_dir: str) -> _LegacyRunnerAdapter:
    """DEPRECATED: use RunnerRegistry.resolve_agent_config instead.

    Supports both legacy model_tiers (when present) and profile-based config.
    """
    tier = ROLE_MODEL_TIER[role]

    # Legacy path: config still carries model_tiers
    model_tiers = getattr(config, "model_tiers", None)
    if model_tiers is not None:
        model = getattr(model_tiers, tier, None)
        if not model:
            raise RunnerError(RunnerDiagnostic(
                code="no_model_for_tier",
                runner="",
                stage="resolve_runner",
                message=f"No model configured for tier '{tier}'",
            ))
        return _make_runner(model, subagent_dir, role, tier)

    # Profile-based path: derive runner/model from active profile
    profile = None
    for p in config.profiles:
        if p.name == config.active_profile:
            profile = p
            break

    if profile is None:
        raise RunnerError(RunnerDiagnostic(
            code="no_profile",
            runner="",
            stage="resolve_runner",
            message=f"Profile '{config.active_profile}' not found and no legacy model_tiers configured",
        ))

    profile_tier = profile.tiers.get(tier)
    if profile_tier is None:
        raise RunnerError(RunnerDiagnostic(
            code="no_tier_in_profile",
            runner="",
            stage="resolve_runner",
            message=f"Profile '{profile.name}' has no tier '{tier}' (role={role})",
        ))

    return _make_runner(profile_tier.model, subagent_dir, role, tier)
