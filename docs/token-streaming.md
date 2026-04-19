# Token Streaming

How koan streams LLM token deltas from subagent processes to the browser in
realtime.

> Parent doc: [architecture.md](./architecture.md)

---

## Overview

Koan receives incremental token output from subagent CLI processes by parsing
their stdout line-by-line via `runner.parse_stream_event(line)` in
`koan/subagent.py`. The runner normalizes provider-specific formats into
`StreamEvent` objects. Token deltas flow to connected browsers via SSE through
the projection system.

**Design invariant:** Token streaming flows through runner stdout parsing, then
through `ProjectionStore.push_event("stream_delta", ...)`. See the SSE Path
section for details.

---

## Runner Streaming Differences

Each runner implementation parses its CLI's stdout format differently:

| Runner                                | Stdout format                               | Streaming behavior                             | Source                                              |
| ------------------------------------- | ------------------------------------------- | ---------------------------------------------- | --------------------------------------------------- |
| **Claude** (`koan/runners/claude.py`) | Stream JSON (`--output-format stream-json`) | Incremental token deltas                       | `text_delta` events in JSONL stream                 |
| **Gemini** (`koan/runners/gemini.py`) | Provider-specific JSON                      | Incremental token deltas                       | Parsed from Gemini CLI output                       |
| **Codex** (`koan/runners/codex.py`)   | Turn-level completion events                | No incremental deltas; "thinking..." indicator | Codex emits completed turns, not token-level events |

All runners implement `parse_stream_event(line) -> StreamEvent | None`. The
method returns a `StreamEvent` with a `delta` string for display, or `None` to
skip the line. The caller (`spawn_subagent()` in `koan/subagent.py`) handles
all events uniformly.

---

## Stdout Line-Buffer Pattern

The subagent process's stdout is read line-by-line. Each complete line is
passed to `runner.parse_stream_event(line)`. A line buffer handles the case
where stdout data arrives split across multiple read calls:

```
buffer += incoming bytes
lines = buffer.split("\n")
buffer = lines[-1]          # keep trailing partial line for next read
process lines[0:-1]         # only complete lines
```

The trailing partial line **must** be kept in the buffer. Parsing it
prematurely would produce a parse error and silently drop the event.

On process exit, the buffer is flushed in case the process exited mid-line.

---

## SSE Path

Token deltas flow through the projection system:

```
CLI stdout -> line parser -> runner.parse_stream_event(line)
  -> StreamEvent with delta
  -> push_event("stream_delta", {"agent_id": ..., "delta": "..."})
  -> ProjectionStore: append to log, fold appends delta to agent.conversation.pending_text
  -> compute JSON Patch: [{op: "replace", path: "/run/agents/{id}/conversation/pendingText", value: "..."}]
  -> broadcast patch to SSE subscribers
  -> browser receives: event: patch / data: {"version": N, "patch": [...]}
  -> applyPatch(store, patch) — store.run.agents[id].conversation.pendingText updated
```

`stream_delta` events go through `ProjectionStore` like all other events. The
fold step is in-memory only (updating `agent.conversation.pending_text`) — there
is no disk I/O per delta. This is distinct from the audit pipeline, which
writes to disk after each event.

When a subagent finishes streaming, the caller emits:

```
push_event("stream_cleared", {"agent_id": ...})
```

The fold flushes `pending_text` to a `TextEntry` in `conversation.entries` and
resets `pending_text = ""`. The JSON Patch carries the resulting state change.

---

## Replay on Reconnect

When a client connects or reconnects, the server sends a `snapshot` event. The
snapshot includes the current state of each agent's conversation — including
`pendingText` (accumulated stream output not yet committed to an entry) and
`entries` (any `TextEntry` objects from completed text blocks).

```
event: snapshot
data: {"version": 142, "state": {"run": {"agents": {"abc": {"conversation": {"pendingText": "accumulated text...", ...}}}}}}
```

The reconnecting client receives the complete accumulated state in a single
snapshot. Individual `stream_delta` events are not replayed — the snapshot
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

| Signal                 | Why excluded from pendingText                                        |
| ---------------------- | ------------------------------------------------------------- |
| Thinking tokens        | Go through `thinking` events into `conversation.pendingThinking`, not `pendingText` |
| Tool execution updates | Handled via `tool_called`/`tool_completed` projection events  |
| Scout output           | Scouts push their own audit events; no token streaming needed |
