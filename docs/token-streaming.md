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
  -> ProjectionStore: append to log, fold projection.stream_buffer += delta
  -> broadcast versioned event to SSE subscribers
  -> browser receives: event: stream_delta / data: {"version": N, ...}
  -> frontend fold: store.streamBuffer += event.delta
```

`stream_delta` events go through `ProjectionStore` like all other events. The
fold step is in-memory only (appending to `projection.stream_buffer`) — there
is no disk I/O per delta. This is distinct from the audit pipeline, which
writes to disk after each event.

When a subagent finishes streaming, the caller emits:

```
push_event("stream_cleared", {"agent_id": ...})
```

The fold sets `projection.stream_buffer = ""`. The frontend clears its
`streamBuffer` slice accordingly.

---

## Replay on Reconnect

When a client connects or reconnects with `?since=0`, the server sends a
`snapshot` event. The snapshot includes the current `stream_buffer` value —
the full accumulated text from all `stream_delta` events since the buffer was
last cleared.

```
event: snapshot
data: {"version": 142, "state": {"stream_buffer": "accumulated text...", ...}}
```

The reconnecting client receives the complete buffer in a single snapshot field.
Individual `stream_delta` events are not replayed on reconnect — the snapshot
`stream_buffer` represents their accumulated effect.

When reconnecting with `?since=N` (brief disconnect), the client replays only
the `stream_delta` events it missed and folds them incrementally, same as any
other event type.

See [projections.md -- Version-negotiated catch-up](./projections.md#sse-protocol)
for the full reconnect protocol.

---

## Frontend

The frontend Zustand store has a `streamBuffer: string` slice. The `applyEvent`
fold handler for `stream_delta` appends the delta:

```typescript
case 'stream_delta':
  return { streamBuffer: state.streamBuffer + event.delta }
case 'stream_cleared':
  return { streamBuffer: '' }
```

`applySnapshot` sets `streamBuffer` from the snapshot's `stream_buffer` field.

The `ActivityFeed` component renders `streamBuffer` as the in-flight streaming
text area. When `stream_cleared` fires, the buffer empties and the streaming
display resets for the next agent.

---

## What Is Not Streamed

| Signal                 | Why excluded from stream_buffer                               |
| ---------------------- | ------------------------------------------------------------- |
| Thinking tokens        | Go through `thinking` events into `activity_log`, not `stream_buffer` |
| Tool execution updates | Handled via `tool_called`/`tool_completed` projection events  |
| Scout output           | Scouts push their own audit events; no token streaming needed |
