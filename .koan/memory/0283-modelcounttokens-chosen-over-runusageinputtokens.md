---
title: Model.count_tokens() chosen over run_usage.input_tokens for context-size measurement
  in the agent loop
type: decision
created: '2026-07-04T08:27:53Z'
modified: '2026-07-04T08:27:53Z'
---

koan agent loop (`koan/agents/loop.py:run_agent_loop`) — Leon chose pydantic-ai's `Model.count_tokens()` to measure the current context size (total tokens in the full message history) for per-agent token telemetry, rejecting the free alternative of using `run_usage.input_tokens` from the just-completed turn.

Rationale: `run_usage.input_tokens` counts only the input tokens for the most recent model request, not the full conversation history. On tool-call turns, the model request carries only the tool-result messages, so `input_tokens` undercounts the true context. After history manipulation — context-file injection via `koan/agents/context.py`, phase resets via `reset_phase_context` — `input_tokens` reflects the manipulated slice, not the full history. `Model.count_tokens(messages, model_settings, model_request_parameters)` makes a dedicated API call to tokenize the complete `agent_state.message_history`, giving an accurate context-size measurement regardless of turn structure or history manipulation.

Alternatives rejected: using `run_usage.input_tokens` — free (no extra API call) but inaccurate for the reasons above; using a character-length heuristic — the pre-June-2026 approach, abandoned when the PydanticAI migration enabled real token accounting via `RequestUsage` and `RunUsage`.

The accepted cost is one extra provider API call per turn. The call is wrapped in try/except with fail-open semantics: on any exception (including `NotImplementedError` from test models such as `TestModel` and `FunctionModel`) or when `agent_run.ctx.state.last_model_request_parameters` is `None`, a warning is logged on the `"loop"` logger and the `token_telemetry` projection event is skipped for that turn.

Decision surfaced during implementation of per-agent token telemetry — debug logging of context size, cumulative cache read/write, and cumulative output tokens after each turn's End node.
