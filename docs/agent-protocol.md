# Agent Protocol

The Agent abstraction: how koan drives an in-process LLM model via PydanticAI.

> Parent doc: [architecture.md](./architecture.md)
> Related: [subagents.md](./subagents.md), [ipc.md](./ipc.md), [state.md](./state.md)

---

## What the Agent abstraction is

`koan/agents/` is the public surface that `spawn_subagent` and `run_agent_loop`
use to run a model for one agent lifetime. The slim `Agent` Protocol in
`koan/agents/base.py` decouples the spawn machinery from the specific in-process
model runner. One implementation satisfies the Protocol in production:
`PydanticAIAgent` (`koan/agents/pydantic_ai.py`). A `FakeAgent` is used in
tests.

All tools -- both koan tools and built-in file/bash tools -- are in-process
`FunctionToolset`s composed per (role, phase) by
`koan/tools/tool_policy.py:compose_toolset`. There is no subprocess, no CLI
binary, and no HTTP transport.

---

## The `Agent` Protocol

```python
@runtime_checkable
class Agent(Protocol):
    name: str  # 'pydantic_ai' or 'fake' in tests

    async def run(self, options: AgentOptions) -> AsyncIterator[StreamEvent]: ...
    async def interrupt(self) -> None: ...
    async def compact(self) -> None: ...
```

Contract per primitive:

- `name` -- the agent type identifier; `"pydantic_ai"` in production,
  `"fake"` in tests.
- `run(options)` -- async generator; yields `StreamEvent`s in the 8-type
  vocabulary defined in `koan/agents/events.py` (`tool_start`,
  `tool_input_delta`, `tool_stop`, `token_delta`, `thinking`,
  `assistant_text`, `tool_result`, `turn_complete`); terminates when the
  PydanticAI graph reaches its end node. The consumer (`run_agent_loop`) drives
  one turn per `agent.iter()` call; the loop itself manages the multi-turn
  conversation.
- `interrupt()` -- best-effort; raises `NotImplementedError` when not supported.
- `compact()` -- raises `NotImplementedError` on every current implementation.

`StreamEvent` lives in `koan/agents/events.py`. The same module defines
`KOAN_MCP_TOOLS`, the frozenset of koan tool names the projection fold uses to
classify koan tool calls in the activity feed.

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
    project_dir: str = ""
    run_dir: str = ""
    additional_dirs: list[str] = field(default_factory=list)
    cwd: str = ""
    extras: dict[str, Any] = field(default_factory=dict)
```

Field descriptions (source: `koan/agents/base.py` docstring):

- `role` -- subagent role (orchestrator, executor, scout).
- `agent_id` -- UUID string identifying this agent instance in the registry.
- `model` -- model id resolved from the active profile's `ModelSpec` (e.g.
  `"gemini-2.5-pro-preview-06-05"`). `None` defers to the adapter's default.
- `thinking` -- thinking mode (`disabled` / `low` / `medium` / `high` /
  `xhigh`). `None` defers to the adapter's default. Resolved from
  `ProfileTier.thinking`; clamped by the adapter against the model's advertised
  `thinking_modes` before the model is constructed.
- `system_prompt` -- role-specific system prompt; prepended to the first turn
  via `_step_phase_handshake_core` when the loop bootstraps.
- `project_dir` -- project root directory; mounted as an additional file-access
  path for built-in file tools.
- `run_dir` -- koan run directory; used by context-file and artifact tools.
- `additional_dirs` -- extra directories requested at run start.
- `cwd` -- working directory context for bash tool calls.
- `extras` -- per-agent-class escape hatch for implementation-specific overrides.

Removed in M4/M6: `mcp_url`, `available_tools`, `allowed_tools`,
`installation`, `boot_prompt`. The HTTP MCP transport and CLI/SDK agent path
are deleted; the in-process path uses `compose_toolset` and model_spec directly.

---

## `AgentDiagnostic` and `AgentError`

```python
@dataclass(kw_only=True)
class AgentDiagnostic:
    code: str
    agent: str        # 'pydantic_ai' or 'fake' in tests
    stage: str        # 'spawn', 'stream', 'handshake'
    message: str
    details: dict | None = None


class AgentError(RuntimeError):
    def __init__(self, diagnostic: AgentDiagnostic) -> None: ...
```

`AgentError` wraps an `AgentDiagnostic` so callers can inspect structured
fields without parsing the message string. The bootstrap failure case:

| Condition                                            | `AgentDiagnostic.code` | `stage`     |
| ---------------------------------------------------- | ---------------------- | ----------- |
| Agent exits before first turn reaches the `End` node | `bootstrap_failure`    | `handshake` |

Bootstrap success is detected via `AgentState.first_turn_completed`, set by
`run_agent_loop` when the first turn reaches the `End` node. A failure raised
before that point is classified as `bootstrap_failure` by `spawn_subagent`.

---

## `PydanticAIAgent` -- the sole implementation

`koan/agents/pydantic_ai.py` wraps PydanticAI's `Agent` class. Constructor
takes `subagent_dir`, `app_state`, and the composed toolsets (koan + builtin).
`run(options)` constructs the provider model via `koan/agents/adapter.py`
(`build_model(provider, model_id, thinking)`), then drives a PydanticAI
`ReAct` graph with those toolsets for the agent's full lifetime.

The loop (`run_agent_loop`) calls `agent.iter()` once per turn, passing
`usage_limits=build_usage_limits()` so no turn is bounded by a model-request
count. A turn ends when the graph reaches its `End` node (terminal-text turn
with no outstanding tool calls). The turn-outcome resolver
(`resolve_turn_outcome`) then decides whether to advance to the next step,
re-inject the same step, hand back to the user, or terminate.

---

## Steering integration

User messages sent while the orchestrator is mid-turn are queued on
`AppState.steering_queue` by `POST /api/chat`. The loop drains the queue and
injects steering text between graph nodes (after `CallToolsNode`, before the
next `ModelRequestNode`) via `agent_run.enqueue()`. This satisfies the
tool-call / tool-result adjacency constraint: injected text never lands inside
an open tool call.

For the primary orchestrator, this is the only steering path. Scouts and
executors are non-primary and do not receive steering messages.

---

## Provider adapter (`koan/agents/adapter.py`)

`build_model(provider, model_id, thinking)` constructs a PydanticAI-compatible
`Model` object for the requested provider:

| Provider    | PydanticAI backend             | Notes                                         |
| ----------- | ------------------------------ | --------------------------------------------- |
| `google`    | `google-gla` / `google-vertex` | Gemini; live-verified                         |
| `anthropic` | `anthropic`                    | Targeted; live verification is user-gated     |
| `openai`    | `openai`                       | Targeted; live verification is user-gated     |
| `bedrock`   | `bedrock`                      | Targeted; thinking/caching are no-ops for now |

Provider availability is checked via `ProviderStatus` (env-key presence), not
by probing a binary. A `Validate` action constructs the model object from the
present credential -- a local construction check, never a live provider call.

`build_usage_limits() -> UsageLimits` is the shared usage-limits gate used by
every koan agent invocation: the main loop (`run_agent_loop`), the
`koan_reflect` synthesis loop, and the mechanical memory `generate` call. It
returns `UsageLimits(request_limit=None)`, disabling pydantic_ai's default cap
of 50 model requests per run. That default fails fast with no recovery path
(`classify_provider_error` treats `UsageLimitExceeded` as "unexpected"), which
is the anti-pattern koan avoids. All other usage-limit fields
(`input_tokens_limit`, `output_tokens_limit`, `total_tokens_limit`,
`tool_calls_limit`) remain at their `None` defaults (disabled). The
`koan_reflect` loop retains its own independent `max_iterations`
(`MAX_ITERATIONS = 10`) cap; that is a deliberate reflect-specific guard, not a
request-count budget.

---

## Cross-reference index

- `koan/agents/base.py` -- `Agent` Protocol, `AgentOptions`, `AgentDiagnostic`,
  `AgentError`.
- `koan/agents/pydantic_ai.py` -- `PydanticAIAgent` (sole production impl).
- `koan/agents/events.py` -- `StreamEvent` (8-type vocabulary),
  `KOAN_MCP_TOOLS` (projection fold classifier).
- `koan/agents/adapter.py` -- `build_model` (provider fan-out, caching,
  thinking mode mapping); `build_usage_limits` (shared usage-limits policy gate
  for all agent invocations).
- `koan/agents/loop.py` -- `run_agent_loop`, `resolve_turn_outcome`,
  `build_phase_suggestions`.
- `koan/agents/registry.py` -- `AgentRegistry`, `resolve_model_spec`,
  `compute_builtin_profiles`.
- `koan/agents/model_catalog.py` -- `MODEL_CAPABILITIES`, `build_model_registry`,
  `price_for_usage` (genai-prices bundled snapshot).
- `koan/tools/tool_policy.py` -- `compose_toolset`, `ROLE_PERMISSIONS` and
  the universal allowlist tables.
- `koan/tools/koan_tools.py` -- in-process koan tool cores (`memorize_core`,
  `forget_core`, `suggest_next_core`, `ask_question_core`, etc.).
- `koan/tools/builtin_tools.py` -- `build_builtin_toolset` (file/bash tools).
- `koan/subagent.py` -- `spawn_subagent` (the agent-spawn function).
