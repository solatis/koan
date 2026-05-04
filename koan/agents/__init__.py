# Public API for koan.agents -- the Agent abstraction (Protocol) and its
# implementations. The CommandLineAgent wraps Runner instances from
# koan.runners; ClaudeSDKAgent wraps the Claude Agent SDK.

from .base import Agent, AgentDiagnostic, AgentError, AgentOptions
from .claude import ClaudeSDKAgent
from .command_line import CommandLineAgent
from .registry import AgentRegistry, compute_balanced_profile, compute_builtin_profiles

__all__ = [
    "Agent",
    "AgentDiagnostic",
    "AgentError",
    "AgentOptions",
    "ClaudeSDKAgent",
    "CommandLineAgent",
    "AgentRegistry",
    "compute_balanced_profile",
    "compute_builtin_profiles",
]
