# Token Streaming

How koan streams LLM token deltas from the in-process agent loop to the browser
in realtime.

> Parent doc: [architecture.md](./architecture.md)

---

## Overview

`PydanticAIAgent.run(options)` (`koan/agents/pydantic_ai.py`) yields
`StreamEvent` objects in the 8-type vocabulary defined in
`koan/agents/events.py`. The `spawn_subagent` event fan-out in `koan/subagent.py`
consumes these events and routes token deltas to connected browsers via SSE
through the projection system.

**Design invariant:** Token streaming flows through the in-process `StreamEvent`
path, then through `ProjectionStore.push_event("stream_delta", ...)`. See the
SSE Path section for details.

---

## The 8-Type StreamEvent Vocabulary

| Event type        | Emitted when                                                       | Carries                     |
| ----------------- | ------------------------------------------------------------------ | --------------------------- |
| `token_delta`     | Model emits a text delta mid-stream                                | `content: str`              |
| `turn_complete`   | A turn ends (graph reaches End node)                               | `usage: RequestUsage`       |
| `thinking`        | Model emits a thinking delta                                       | `content: str, is_thinking` |
| `assistant_text`  | A complete assistant text block is available                       | `content: str`              |
| `tool_start`      | A tool call begins                                                 | `tool_name, tool_use_id`    |
| `tool_input_delta`| A tool call's input is streaming                                   | `content: str`              |
| `tool_stop`       | A tool call's input stream ends                                    | `tool_use_id`               |
| `tool_result`     | A tool call's result is available                                  | `tool_name, content, metrics, attachments` |

`turn_complete` carries the `RequestUsage` (input_tokens, output_tokens,
cache_read_tokens, cache_write_tokens) from pydantic-ai. This is the usage
figure accumulated by the projection fold into the per-agent `Conversation`.

All event types are produced by `PydanticAIAgent.run()` and consumed uniformly
by the event fan-out in `spawn_subagent`. No runner-specific parsing is needed.

---

## SSE Path

Token deltas flow through the projection system:

```
PydanticAIAgent.run() yields StreamEvent(type="token_delta", content="...")
  -> spawn_subagent event fan-out
  -> push_event("stream_delta", {"agent_id": ..., "delta": "..."})
  -> ProjectionStore: append to log, fold appends delta to agent.conversation.pending_text
  -> compute JSON Patch: [{op: "replace", path: "/run/agents/{id}/conversation/pendingText", value: "..."}]
  -> broadcast patch to SSE subscribers
  -> browser receives: event: patch / data: {"version": N, "patch": [...]}
  -> applyPatch(store, patch) -- store.run.agents[id].conversation.pendingText updated
```

`stream_delta` events go through `ProjectionStore` like all other events. The
fold step is in-memory only (updating `agent.conversation.pending_text`) -- there
is no disk I/O per delta. This is distinct from the audit pipeline, which
writes to disk after each event.

When a turn ends, `turn_complete` is processed by the fan-out:

```
StreamEvent(type="turn_complete", usage=RequestUsage(...))
  -> fan-out accumulates usage (input, output, cache_read, cache_write)
  -> push_event("stream_cleared", {"agent_id": ...})
  -> fold flushes pending_text to TextEntry, resets pending_text = ""
  -> (usage is accumulated on AgentState; emitted via agent_exited at agent exit)
```

---

## Replay on Reconnect

When a client connects or reconnects, the server sends a `snapshot` event. The
snapshot includes the current state of each agent's conversation -- including
`pendingText` (accumulated stream output not yet committed to an entry) and
`entries` (any `TextEntry` objects from completed text blocks).

```
event: snapshot
data: {"version": 142, "state": {"run": {"agents": {"abc": {"conversation": {"pendingText": "accumulated text...", ...}}}}}}
```

The reconnecting client receives the complete accumulated state in a single
snapshot. Individual `stream_delta` events are not replayed -- the snapshot
represents their accumulated effect.

All reconnect scenarios send a snapshot: page reload, brief disconnect, and
server restart are handled identically.

See [projections.md -- SSE Protocol](./projections.md#sse-protocol)
for the full reconnect protocol.

---

## Frontend

The frontend has no fold logic. The Zustand store is updated by applying JSON
Patches received from the server:

```typescript
// patch event for a stream_delta:
// [{op: "replace", path: "/run/agents/abc/conversation/pendingText", value: "accumulated..."}]
storeState = applyPatch(storeState, patch, false, false).newDocument
set({ ...storeState })
```

The `ActivityFeed` component reads `conversation.pendingText` from the focused
agent and renders it as the in-flight streaming text. When `stream_cleared`
causes the fold to flush `pendingText` into a `TextEntry`, the patch reflects
that: `pendingText` becomes `""` and a new entry appears in `entries`.

---

## What Is Not Streamed

| Signal                 | Why excluded from pendingText                                             |
| ---------------------- | ------------------------------------------------------------------------- |
| Thinking tokens        | Go through `thinking` events into `conversation.pendingThinking`, not `pendingText` |
| Tool execution updates | Handled via `tool_called`/`tool_completed` projection events              |
| Scout output           | Scouts push their own audit events; no token streaming needed             |
| Usage figures          | Accumulated on `AgentState`; emitted once via `agent_exited`              |
