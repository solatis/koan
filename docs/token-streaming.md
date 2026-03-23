# Token Streaming

How koan streams LLM token deltas from subagent processes to the browser in
realtime.

> Parent doc: [architecture.md](./architecture.md)

---

## Overview

Koan receives incremental token output from subagent `pi` processes by parsing
the JSONL stream on their stdout. Token deltas flow directly to connected
browsers via SSE — bypassing the audit system and the file-based IPC protocol
entirely.

**Design invariant:** Token streaming flows through stdout JSONL parsing, not
through the extension event system or file-based IPC.

---

## Pi's Streaming Architecture

Pi exposes a three-layer streaming pipeline:

```
Provider stream   (HTTP chunked response from the LLM API)
      ↓
Agent layer       (assembles chunks into messages, emits typed session events)
      ↓
Session output    (--mode json → JSONL on stdout; default → human-readable text)
```

The transition from provider chunks to typed session events happens inside pi.
Koan does not intercept provider chunks. It hooks into the **session output
layer** by launching pi with `--mode json -p`.

### `--mode json` and `-p` compose

- `-p` (non-interactive / print mode): pi runs to completion and exits without
  waiting for stdin. This is koan's spawn mode.
- `--mode json`: instead of printing human-readable text, pi emits every
  session event as a JSONL line on stdout.

The two flags compose cleanly. Pi's own subagent extension
(`examples/extensions/subagent/index.ts`) uses the identical combination —
`["--mode", "json", "-p"]` — confirming this is the supported integration
surface for external processes that spawn pi as a subprocess.

### Session event types on stdout

With `--mode json`, each stdout line is a JSON object with a `type` field.
Relevant event types for token streaming:

| Event type | When emitted | Relevant subfield |
|---|---|---|
| `message_update` | Each streamed token during generation | `assistantMessageEvent.type === "text_delta"` |
| `message_update` | Other message lifecycle events | `assistantMessageEvent.type` is not `text_delta` |
| `tool_execution_update` | Tool call lifecycle | — (not used for streaming) |
| `turn_end` | LLM turn finished | — |
| others | Compaction, session events, etc. | — |

Only `message_update` events where `assistantMessageEvent.type === "text_delta"`
carry new tokens. All other event types are discarded by the token streaming
parser. The existing `state.json` polling path handles tool-call-level status.

---

## Stdout JSONL Parser

The parser runs inside `spawnSubagent()` in `src/planner/subagent.ts`,
alongside the existing `stdoutLog.write(data)` call.

### Why preserve the log file

The log file write happens before any parsing. `--mode json` changes the
format of stdout (text → JSONL), but the log file still captures the complete
raw output for post-mortem debugging. The parser is an additional consumer of
the same bytes; it does not replace or modify the log path.

### Line-buffer pattern

Node.js `"data"` events do not respect line boundaries — a single event may
contain multiple complete lines, a partial line, or both. The parser maintains
a `buffer` string across events:

```
buffer += incoming bytes
lines = buffer.split("\n")
buffer = lines.pop()          ← keep trailing partial line for next event
process lines[0..n-2]         ← only complete lines
```

The trailing partial line **must** be kept in `buffer`. Parsing it prematurely
would produce a JSON parse error and silently drop the event.

On process close, the buffer is flushed in case the process exited mid-line
(e.g., SIGKILL). Under normal operation the buffer is empty at close. The
flush is merged into the existing `proc.on("close")` handler, before
`resolve()`, so any final delta arrives before the driver calls
`clearSubagent()` → `pushEvent("subagent-idle")`.

### Why filter to `text_delta` only

`--mode json` is verbose — it emits events for every tool execution, turn
boundary, and compaction cycle. Forwarding all events to SSE clients would
add noise and bandwidth with no UI benefit. Tool execution status is already
tracked via the audit projection (`state.json` polling → `agents` SSE event).
Only `text_delta` events carry information the streaming display needs.

---

## SSE Path

Koan has two data paths from subagents to the browser:

1. **Audit pipeline** — durable, tool-call-level, polled via `state.json`. Use
   for state that must survive restarts, participate in `fold()`, and be
   replayed in full on reconnect.
2. **Stdout pipeline** — ephemeral, token-level, pushed directly to SSE. Use
   for high-frequency display data with no persistence value.

Token streaming uses the stdout pipeline. Token deltas flow from the parser
directly to SSE clients without touching the audit system or IPC files:

```
pi stdout → JSONL parser → pushTokenDelta(delta) → pushEvent("token-delta", { delta }) → SSE stream
```

This path bypasses the standard five-layer audit pipeline
([architecture.md § SSE Event Lifecycle](./architecture.md#sse-event-lifecycle))
intentionally. Going through the audit system would require:

- Appending a new event type to `events.jsonl` per token (hundreds per second)
- Running `fold()` per token to update `state.json`
- Polling `state.json` at 50ms and detecting changes

That is appropriate for durable, tool-call-level state. For ephemeral token
deltas — which are cleared when the subagent finishes — direct SSE push is
correct.

### `pushTokenDelta` is parameterless

`WebServerHandle.pushTokenDelta(delta)` takes only the delta string. There is
no `subagentDir` or `agentId` parameter because only one subagent is tracked
at a time (`trackSubagent()` / `clearSubagent()`). The server always knows
which subagent is active; no disambiguation is needed.

### Replay on reconnect

The web server maintains a `streamingText` string variable alongside the other
replay state (`currentPhase`, `currentSubagent`, etc.).

**Lifecycle:**

1. `trackSubagent()` — reset `streamingText = ""`
2. `pushTokenDelta(delta)` — append `streamingText += delta`, then `pushEvent()`
3. `replayState(res)` — if `streamingText` is non-empty, write a single
   `token-delta` event containing the full accumulated string. The frontend's
   `handleTokenDeltaEvent` handles this transparently — it accumulates from
   zero after each clear, so receiving the full text as one delta produces the
   correct state.
4. `clearSubagent()` — reset `streamingText = ""`

Without server-side accumulation, a client that reconnects mid-stream would
see an empty streaming area with no error signal — a silent failure that only
surfaces during network interruptions.

---

## Frontend

### Store (`src/planner/web/js/store.js`)

`streamingText` is a plain string in the Zustand store, initialized to `""`.

```
streamingText: ""
```

Two handlers operate on it:

- **`handleTokenDeltaEvent(d)`** — appended on each `token-delta` SSE event:
  `set(s => ({ streamingText: s.streamingText + d.delta }))`

- **`handleSubagentIdleEvent()`** — resets `streamingText: ""` alongside
  `subagent: null`. Clearing is done inside the idle handler rather than as a
  separate `token-delta` teardown because `subagent-idle` is the canonical
  signal that the active subagent has finished; consolidating the reset here
  avoids a second SSE handler registration in `sse.js` and keeps all
  subagent-end side-effects in one place.

### SSE dispatch (`src/planner/web/js/sse.js`)

```
'token-delta'   → handleTokenDeltaEvent
'subagent-idle' → handleSubagentIdleEvent   (also clears streamingText)
```

The frontend accumulates deltas; the server sends only the new tokens each
event. Accumulation on the client matches the provider stream's own framing
and avoids growing SSE payload sizes as text grows.

### Component (`src/planner/web/js/components/StreamingOutput.jsx`)

`StreamingOutput` renders only when `streamingText` is non-empty. It sits
below `<ActivityFeed />` inside `.main-panel` (a flex column). The component
uses `flex-shrink: 0` so it holds a fixed maximum height of 180px while
`.activity-feed` takes the remaining space above. A `useEffect` on
`streamingText` scrolls the body div to the bottom on every token arrival.

---

## What Is Not Streamed

| Signal | Why excluded |
|---|---|
| Thinking blocks (`thinking_delta`) | Not visible to users in current UI; same mechanism could add them later |
| Tool execution updates | Handled by `state.json` polling → `agents` SSE event |
| Scout output | Scouts have no `WebServerHandle`; they are not tracked by `trackSubagent` |

---

## Alternatives Considered

| Alternative | Reason rejected |
|---|---|
| Extension `message_update` hook + file append | File I/O per token; requires polling; adds new file to directory-as-contract |
| Extension + HTTP POST per token | Port must be passed to extension; HTTP overhead per token |
| RPC mode (`--mode rpc`) | Requires bidirectional stdin/stdout; `stdin` is `"ignore"` in koan |
| Tail `stdout.log` in `-p` mode | Raw text — cannot distinguish token deltas from tool output |
| SDK embedding (`createAgentSession`) | Destroys process isolation (core architectural invariant) |
