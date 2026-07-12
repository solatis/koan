# Agent Protocol, AgentOptions, AgentDiagnostic, and AgentError.
# Public API for the koan.agents package.
#
# M4: AgentInstallation, ModelInfo, list_models, mcp_url, available_tools,
# allowed_tools, and installation removed -- the legacy CLI/SDK agent path is
# deleted; the in-process PydanticAI path uses model_spec directly.
# StreamEvent lives in koan.agents.events (relocated from koan.runners.base).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

from ..types import SubagentRole, ThinkingMode

if TYPE_CHECKING:
    from .events import StreamEvent


# -- Diagnostic types ----------------------------------------------------------

@dataclass(kw_only=True)
class AgentDiagnostic:
    """Structured diagnostic emitted when an agent fails at any lifecycle stage.

    Fields:
        code: machine-readable error code (e.g. bootstrap_failure)
        agent: agent type name -- 'pydantic_ai' or 'fake' in tests
        stage: lifecycle stage where the failure occurred (spawn, stream, handshake)
        message: human-readable description
        details: optional free-form dict for extra context
    """

    code: str
    agent: str
    stage: str
    message: str
    details: dict | None = None


class AgentError(RuntimeError):
    """Raised by Agent implementations and AgentRegistry on unrecoverable failures.

    Wraps an AgentDiagnostic so callers can inspect structured fields without
    parsing the message string. The string representation is diagnostic.message.
    """

    def __init__(self, diagnostic: AgentDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


# -- AgentOptions --------------------------------------------------------------

@dataclass(kw_only=True)
class AgentOptions:
    """All configuration needed to run one agent for its full lifetime.

    Constructed by spawn_subagent from the resolved profile, role, and run
    state. Consumed once by Agent.run(); never mutated.

    M4: mcp_url, available_tools, allowed_tools, and installation removed --
    the HTTP MCP transport and CLI/SDK agent path are deleted. PydanticAIAgent
    reads model_spec directly and has no use for these fields.

    Fields:
        role: subagent role (orchestrator, executor, scout)
        agent_id: UUID string identifying this agent instance
        model: model id resolved from the active profile's ModelSpec
        thinking: thinking mode (disabled / low / medium / high / xhigh)
        system_prompt: role-specific system prompt
        project_dir: project root directory
        run_dir: koan run directory
        additional_dirs: extra directories requested at run start
        cwd: working directory context
        extras: per-agent-class escape hatch for implementation-specific overrides

    boot_prompt removed in M6: the loop bootstrap calls _step_phase_handshake_core
    directly as the first turn's prompt; no one-sentence boot directive is needed.
    """

    role: SubagentRole
    agent_id: str
    model: str | None
    thinking: ThinkingMode | None
    system_prompt: str
    project_dir: str = ""
    run_dir: str = ""
    additional_dirs: list[str] = field(default_factory=list)
    cwd: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


# -- Agent Protocol ------------------------------------------------------------

@runtime_checkable
class Agent(Protocol):
    """Contract every agent implementation must satisfy.

    An agent manages the full lifetime of one in-process model run.
    spawn_subagent calls run(options) once per agent lifetime and iterates
    the returned async iterator until it terminates.

    Unsupported primitives raise NotImplementedError. Callers that wish to
    interrupt or compact must be prepared for NotImplementedError.

    M4: list_models removed -- the probe path that called it is deleted.
    The in-process path resolves the model catalog via model_catalog.py, not
    by shelling out to a binary.
    """

    name: str  # 'pydantic_ai' or 'fake' in tests

    async def run(self, options: AgentOptions) -> AsyncIterator[StreamEvent]:
        """Run the agent and stream events until the terminal signal.

        Yields StreamEvents in the 9-type vocabulary (tool_start, tool_input_delta,
        tool_stop, token_delta, thinking, assistant_text, tool_result, tool_failed,
        turn_complete).
        Downstream consumers (spawn_subagent's event fan-out) do not care which agent
        class produced the event.
        """
        ...

    async def interrupt(self) -> None:
        """Interrupt the agent's current generation.

        Raises NotImplementedError when the agent does not support interruption.
        """
        ...

    async def compact(self) -> None:
        """Trigger a context compaction.

        Raises NotImplementedError when the agent does not support compaction.
        """
        ...
