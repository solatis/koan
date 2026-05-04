# Agent Protocol, AgentOptions, AgentDiagnostic, and AgentError.
# Public API for the koan.agents package.
#
# StreamEvent lives in koan.runners.base (it is the long-standing
# runner-to-driver contract). It is NOT imported here at module level to
# avoid a circular import: codex.py and gemini.py import AgentDiagnostic
# from this module, and if this module imported from koan.runners.* it would
# trigger koan/runners/__init__.py which loads codex/gemini before this
# module finishes initializing. Callers import StreamEvent directly from
# koan.runners.base.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

from ..types import AgentInstallation, ModelInfo, SubagentRole, ThinkingMode

if TYPE_CHECKING:
    from ..runners.base import StreamEvent


# -- Diagnostic types ----------------------------------------------------------

@dataclass(kw_only=True)
class AgentDiagnostic:
    """Structured diagnostic emitted when an agent fails at any lifecycle stage.

    Fields:
        code: machine-readable error code (e.g. bootstrap_failure, binary_not_found)
        agent: agent type name -- 'claude', 'codex', 'gemini', or 'fake' in tests
        stage: lifecycle stage where the failure occurred (connect, spawn, stream, handshake)
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

    Constructed by spawn_subagent from the resolved profile, role, run state,
    and MCP server URL. Consumed once by Agent.run(); never mutated.

    Fields:
        role: subagent role (orchestrator, executor, scout)
        agent_id: UUID string used in the MCP URL query string
        model: model alias resolved by the registry (e.g. 'sonnet', 'gpt-5')
        thinking: thinking mode (disabled / low / medium / high / xhigh)
        system_prompt: role-specific system prompt
        boot_prompt: one-sentence boot directive (step-first protocol)
        mcp_url: full HTTP MCP URL including ?agent_id= query string
        available_tools: Claude-side tool whitelist (--tools flag)
        allowed_tools: auto-approved subset (--allowedTools flag)
        project_dir: project root directory; mounted as --add-dir for Claude
        run_dir: koan run directory; mounted as --add-dir for Claude
        additional_dirs: extra directories requested at run start
        cwd: working directory for the spawned subprocess
        permission_mode: 'acceptEdits' for Claude; ignored by other runners
        installation: resolved binary path and extra_args
        extras: per-agent-class escape hatch for implementation-specific overrides
    """

    role: SubagentRole
    agent_id: str
    model: str | None
    thinking: ThinkingMode | None
    system_prompt: str
    boot_prompt: str
    mcp_url: str
    available_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    project_dir: str = ""
    run_dir: str = ""
    additional_dirs: list[str] = field(default_factory=list)
    cwd: str = ""
    permission_mode: str = "acceptEdits"
    installation: AgentInstallation | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# -- Agent Protocol ------------------------------------------------------------

@runtime_checkable
class Agent(Protocol):
    """Contract every agent implementation must satisfy.

    An agent manages the full lifetime of one model process or SDK client.
    The driver calls run(options) once per agent lifetime and iterates the
    returned async iterator until it terminates. The iterator terminates when
    the agent reaches a terminal signal (success or failure).

    Unsupported primitives raise NotImplementedError. This is the explicit
    contract: callers that wish to interrupt or compact must be prepared
    for NotImplementedError if the underlying agent does not support it.

    The register_process, exit_code, and stderr_output members bridge the
    new abstraction with spawn_subagent's existing process-management logic
    (active-process registry, exit-code error path, stderr logging).
    """

    name: str  # 'claude', 'codex', 'gemini', or 'fake' in tests

    async def run(self, options: AgentOptions) -> AsyncIterator[StreamEvent]:
        """Run the agent and stream events until the terminal signal.

        The iterator yields StreamEvents in the same vocabulary as today's
        koan/runners -- tool_start, tool_input_delta, tool_stop, token_delta,
        thinking, assistant_text, tool_result, turn_complete. Downstream
        consumers (spawn_subagent's event fan-out) do not care which agent
        class produced the event.

        The iterator terminates when the agent's underlying transport reaches
        a terminal signal (ResultMessage on the SDK side, EOF on the subprocess
        side). After termination, exit_code and stderr_output are populated.
        """
        ...

    async def interrupt(self) -> None:
        """Interrupt the agent's current generation.

        Raises NotImplementedError on agents that do not support interruption
        (CommandLineAgent, and -- in M1 -- the interim Claude adapter).
        ClaudeSDKAgent (M2) will implement this by calling ClaudeSDKClient.interrupt().
        """
        ...

    async def compact(self) -> None:
        """Trigger a context compaction.

        Raises NotImplementedError everywhere in M1 and on CommandLineAgent.
        The Claude Agent SDK does not yet expose a programmatic compact() surface;
        when it does, ClaudeSDKAgent (M2+) will implement this.
        """
        ...

    def register_process(self, registry: dict, agent_id: str) -> None:
        """Register the agent's underlying subprocess into the active-process registry.

        Called by spawn_subagent before iterating run() so that the shutdown
        path (app_state._active_processes) can cancel the subprocess if needed.
        Command-line agents store the registry reference and populate it as
        soon as the subprocess is spawned inside run(). SDK-style agents
        implement this as a no-op (the SDK manages its own process lifecycle).
        """
        ...

    @property
    def exit_code(self) -> int | None:
        """Exit code of the agent's underlying process or SDK session.

        None until run() completes. Populated by CommandLineAgent from
        proc.wait(); by SDK agents from the ResultMessage status.
        Consumed by spawn_subagent for the exit-code error path.
        """
        ...

    @property
    def stderr_output(self) -> str:
        """Accumulated stderr output from the agent's subprocess.

        Empty string for SDK agents (no separate stderr stream).
        Populated after run() completes. Consumed by spawn_subagent
        to build the error_str for failed runs.
        """
        ...

    @classmethod
    def list_models(cls, installation: AgentInstallation) -> list[ModelInfo]:
        """Return the model list for the given installation.

        Classmethod -- called by the probe path without instantiating a full
        agent (which for command-line agents would require spawning a process).
        Claude returns a hardcoded list; codex and gemini shell out to the binary.
        """
        ...
