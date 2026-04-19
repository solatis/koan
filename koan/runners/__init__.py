# Public API for koan.runners -- runner protocol and concrete adapters.

from .base import Runner, RunnerDiagnostic, RunnerError, StreamEvent
from .claude import ClaudeRunner
from .codex import CodexRunner
from .gemini import GeminiRunner
from .registry import RunnerRegistry, compute_balanced_profile, compute_builtin_profiles
from .resolver import resolve_runner

__all__ = [
    "Runner",
    "StreamEvent",
    "RunnerDiagnostic",
    "RunnerError",
    "ClaudeRunner",
    "CodexRunner",
    "GeminiRunner",
    "RunnerRegistry",
    "compute_balanced_profile",
    "compute_builtin_profiles",
    "resolve_runner",
]
