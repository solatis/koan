# Agent Protocol

The Agent abstraction: how koan talks to LLM coding agents.

> Parent doc: [architecture.md](./architecture.md)
> Related: [subagents.md](./subagents.md), [ipc.md](./ipc.md), [state.md](./state.md)

---

## What the Agent abstraction is

`koan/agents/` is the public surface every subagent process speaks to the
driver through. The `Agent` Protocol decouples koan's spawn machinery from the
specific transport for driving a model. Two implementations satisfy the
Protocol: `ClaudeSDKAgent` (drives the `claude-agent-sdk` Python library) and
`CommandLineAgent` (wraps a `koan.runners.base.Runner` instance for codex and
gemini). `koan/runners/` is an internal implementation detail of
`CommandLineAgent` -- the public surface for agent integration is
`koan.agents.*`.

---

## The `Agent` Protocol

```python
@runtime_checkable
class Agent(Protocol):
    name: str  # 'claude', 'codex', 'gemini', or 'fake' in tests

    async def run(self, options: AgentOptions) -> AsyncIterator[StreamEvent]: ...
    async def interrupt(self) -> None: ...
    async def compact(self) -> None: ...

    def register_process(self, registry: dict, agent_id: str) -> None: ...

    @property
    def exit_code(self) -> int | None: ...

    @property
    def stderr_output(self) -> str: ...

    @classmethod
    def list_models(cls, installation: AgentInstallation) -> list[ModelInfo]: ...
```

Contract per primitive:

- `name` -- the agent type identifier; consumers gate behavior on this string
  (`"claude"`, `"codex"`, `"gemini"`, or `"fake"` in tests).
- `run(options)` -- async generator; yields `StreamEvent`s in the vocabulary
  defined in `koan/runners/base.py` (`tool_start`, `tool_input_delta`,
  `tool_stop`, `token_delta`, `thinking`, `assistant_text`, `tool_result`,
  `turn_complete`); terminates on the agent's terminal signal (`ResultMessage`
  for SDK agents, EOF for subprocess agents). After termination, `exit_code`
  and `stderr_output` are populated.
- `interrupt()` -- best-effort; agents that cannot interrupt raise
  `NotImplementedError`. `ClaudeSDKAgent` delegates to
  `ClaudeSDKClient.interrupt()`; `CommandLineAgent` raises.
- `compact()` -- raises `NotImplementedError` on every implementation -- the
  Claude Agent SDK does not currently expose a programmatic compact surface.
- `register_process(registry, agent_id)` -- registers the underlying process
  handle into a shared registry (used by `app_state._active_processes` for
  shutdown cancellation). `CommandLineAgent` populates the registry as soon as
  the subprocess is spawned inside `run()`. `ClaudeSDKAgent` implements this as
  a no-op because the SDK manages its CLI subprocess internally.
- `exit_code` / `stderr_output` -- properties populated after iteration ends;
  consumed by `koan/subagent.py:spawn_subagent` for the exit-code error path.
- `list_models` -- classmethod; called by `koan/probe.py` without
  instantiating an agent. Claude returns a hardcoded list; codex and gemini
  shell out to the binary.

`StreamEvent` lives in `koan/runners/base.py`, not `koan/agents/base.py`. The
split prevents an import cycle between agents and runners; consumers import
`StreamEvent` directly from `koan.runners.base`.

---

## `AgentOptions` schema

```python
@dataclass(kw_only=True)
class AgentOptions:
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
```

Field descriptions (source: `koan/agents/base.py` docstring):

- `role` -- subagent role (orchestrator, executor, scout).
- `agent_id` -- UUID string used in the MCP URL query string.
- `model` -- model alias resolved by the registry (e.g. `"sonnet"`,
  `"gpt-5"`). `None` defers to the agent's default.
- `thinking` -- thinking mode (`disabled` / `low` / `medium` / `high` /
  `xhigh`). `None` defers to the agent's default.
- `system_prompt` -- role-specific system prompt.
- `boot_prompt` -- one-sentence boot directive (step-first protocol).
- `mcp_url` -- full HTTP MCP URL including `?agent_id=` query string.
- `available_tools` -- role-curated tool whitelist passed as Claude's `--tools`
  flag. Restricts which tools are visible to the model. Deliberately separate
  from `allowed_tools`.
- `allowed_tools` -- auto-approved subset passed as Claude's `--allowedTools`
  flag. Restricts which tools run without interactive approval. Deliberately
  separate from `available_tools`.
- `project_dir` -- project root directory; mounted as `--add-dir` for Claude.
- `run_dir` -- koan run directory; mounted as `--add-dir` for Claude.
- `additional_dirs` -- extra directories requested at run start.
- `cwd` -- working directory for the spawned subprocess.
- `permission_mode` -- `"acceptEdits"` for Claude; ignored by other runners.
- `installation` -- resolved binary path and extra args. `None` defers to the
  agent's default installation.
- `extras` -- per-agent-class escape hatch for implementation-specific
  overrides not covered by the standard fields.

---

## `AgentDiagnostic` and `AgentError`

```python
@dataclass(kw_only=True)
class AgentDiagnostic:
    code: str
    agent: str        # 'claude', 'codex', 'gemini', or 'fake' in tests
    stage: str        # 'connect', 'spawn', 'stream', 'handshake'
    message: str
    details: dict | None = None


class AgentError(RuntimeError):
    def __init__(self, diagnostic: AgentDiagnostic) -> None: ...
```

`AgentError` wraps an `AgentDiagnostic` so callers can inspect structured
fields without parsing the message string. The SDK-error mapping table that
`ClaudeSDKAgent` applies (verified against `koan/agents/claude.py`):

| SDK error                                       | `AgentDiagnostic.code`   | `stage`     |
| ----------------------------------------------- | ------------------------ | ----------- |
| `CLINotFoundError`                              | `binary_not_found`       | `connect`   |
| `CLIConnectionError`                            | `sdk_connect_failed`     | `connect`   |
| `ProcessError`                                  | `agent_process_failed`   | `stream`    |
| `CLIJSONDecodeError`                            | `protocol_decode_failed` | `stream`    |
| (agent exits before first `koan_complete_step`) | `bootstrap_failure`      | `handshake` |

The `bootstrap_failure` row is not caught inside `ClaudeSDKAgent.run()` -- it
is detected by `spawn_subagent`'s handshake check (`agent.handshake_observed`)
after `run()` returns normally.

---

## Unsupported primitives raise

Not every implementation supports every primitive. Agents that do not support
a primitive raise `NotImplementedError`. Callers must handle the raise; the
abstraction does not present pretend-implementations.

Current behavior:

- `CommandLineAgent` -- raises on `interrupt()` and `compact()`.
- `ClaudeSDKAgent` -- raises on `compact()`. `interrupt()` is implemented via
  `ClaudeSDKClient.interrupt()`.

---

## Two implementations

### `ClaudeSDKAgent` (`koan/agents/claude.py`)

Wraps `claude_agent_sdk.ClaudeSDKClient`. Constructor takes `subagent_dir` and
`app_state`; the `app_state` parameter is required because the PostToolUse
steering hook closure constructed inside `run(options)` captures it along with
`agent_id`. The SDK spawns the Claude Code CLI binary internally -- the SDK
does not eliminate the subprocess, it provides a typed Python wrapper around
it. `register_process` is a no-op because the SDK manages its CLI subprocess
internally; koan's `_active_processes` shutdown path does not track Claude
agents.

### `CommandLineAgent` (`koan/agents/command_line.py`)

Wraps a `koan.runners.base.Runner` instance (`CodexRunner` or `GeminiRunner`).
Owns `asyncio.create_subprocess_exec`, the stdout/stderr drain, and per-runner
post-build args helpers. Translates `Runner.parse_stream_event` output into
yielded `StreamEvent`s.

---

## Steering integration

Steering reaches the model via two paths sharing one drain helper.

### Claude PostToolUse hook

`ClaudeSDKAgent.run()` registers a `PostToolUse` hook with the SDK at run
time. The hook closure captures `(app_state, agent_id)`, calls
`koan/agents/steering.py:drain_for_primary(app_state, agent)` to atomically
pop the steering queue (gated on `agent.is_primary`), renders the messages via
`render_text(messages)`, and returns
`{"hookEventName": "PostToolUse", "additionalContext": text}`. The hook fires
after every tool completion -- built-in (Bash/Read/Edit/...) and koan MCP
tools alike -- so latency to model is bounded by the model's tool-call
cadence, not koan's tool boundaries specifically.

### Codex / Gemini MCP-handler injection

`koan/web/mcp_endpoint.py:_drain_and_append_steering` runs at the end of every
koan MCP tool handler. It bypasses for Claude (gated on
`agent.runner_type == "claude"`) so the queue stays intact for the SDK hook.
For codex/gemini agents, it calls the same `drain_for_primary` helper, then
`render_blocks(messages, app_state, agent)` to produce content-block-shaped
output (envelope-open + per-message blocks + per-message attachments +
envelope-close) appended to the tool result.

`koan/agents/steering.py` is the single source of truth for the drain. The two
formatters differ only in output shape; the gating logic and the queue read
live in one place.

---

## Hooks are a Claude implementation detail

The Agent Protocol does not expose `register_hook(...)`. The closure is
constructed inside `ClaudeSDKAgent.run(options)` and registered with the SDK
client. `CommandLineAgent` has no hook system because codex and gemini have no
hook surface to register against. Adding `register_hook` to the Protocol would
force every caller to handle the unsupported case for codex/gemini, which
provides no benefit.

---

## HTTP MCP for every agent

koan's MCP server in `koan/web/mcp_endpoint.py` runs over HTTP at
`http://localhost:{port}/mcp?agent_id={id}`. Both `ClaudeSDKAgent` and
`CommandLineAgent` consume it via the same URL. The Claude SDK supports an
in-process MCP transport (`McpSdkServerConfig`) but koan does not use it
because: (a) parity with codex/gemini -- they cannot use in-process MCP;
(b) `agent_id`-via-URL is the existing agent-resolution mechanism
(`AgentResolutionMiddleware`); (c) porting koan's 20 MCP tool registrations to
in-process would be substantial rework with no behavioral benefit.

---

## `AgentRegistry.get_agent`'s `app_state` parameter

The Claude branch of `AgentRegistry.get_agent` requires `app_state` for the
PostToolUse hook closure. `koan/subagent.py:spawn_subagent` passes it.
`CommandLineAgent` ignores it. The Claude branch raises
`AgentError(code="missing_app_state")` if `app_state is None`.

---

## Lazy-import discipline

Runner-class imports inside `koan/agents/` (in `AgentRegistry.get_agent` and
`CommandLineAgent.list_models`) and the SDK import inside
`ClaudeSDKAgent.run()` happen at method-body scope, not at module top-level.
This breaks the agents/runners import cycle that arises because
`koan/runners/__init__.py` eagerly imports its submodules and codex/gemini
import diagnostic types from `koan/agents/base.py`. Module-level imports of
runner classes from inside `koan/agents/` re-create the cycle.

---

## Cross-reference index

- `koan/agents/base.py` -- `Agent` Protocol, `AgentOptions`, `AgentDiagnostic`,
  `AgentError`.
- `koan/agents/claude.py` -- `ClaudeSDKAgent`.
- `koan/agents/command_line.py` -- `CommandLineAgent`.
- `koan/agents/registry.py` -- `AgentRegistry`, `compute_balanced_profile`,
  `compute_builtin_profiles`.
- `koan/agents/steering.py` -- `drain_for_primary`, `render_text`,
  `render_blocks`.
- `koan/runners/base.py` -- `Runner` Protocol, `StreamEvent`, `KOAN_MCP_TOOLS`
  (internal to `CommandLineAgent`).
- `koan/runners/codex.py`, `koan/runners/gemini.py` -- `Runner`
  implementations.
- `koan/subagent.py` -- `spawn_subagent` (the agent-spawn function).
- `koan/web/mcp_endpoint.py:_drain_and_append_steering` -- the codex/gemini
  steering injection path.
- `koan/probe.py:_probe_claude` -- SDK availability probe.
