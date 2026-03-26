# Token Streaming

How koan streams LLM token deltas from subagent processes to the browser in
realtime.

> Parent doc: [architecture.md](./architecture.md)

---

## Overview

Koan receives incremental token output from subagent CLI processes by parsing
their stdout line-by-line via `runner.parse_stream_event(line)` in
`koan/subagent.py`. The runner normalizes provider-specific formats into
`StreamEvent` objects. Token deltas flow directly to connected browsers via
SSE -- bypassing the audit system entirely.

**Design invariant:** Token streaming flows through runner stdout parsing, not
through the audit pipeline or file-based communication.

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

Koan has two data paths from subagents to the browser:

1. **Audit pipeline** -- durable, tool-call-level. Use for state that must
   survive restarts, participate in `fold()`, and be replayed on reconnect.
2. **Stdout pipeline** -- ephemeral, token-level, pushed directly to SSE. Use
   for high-frequency display data with no persistence value.

Token streaming uses the stdout pipeline:

```
CLI stdout -> line parser -> runner.parse_stream_event(line)
  -> StreamEvent with delta
  -> push SSE "token-delta" event to connected browsers
```

This path bypasses the audit pipeline intentionally. Going through audit would
require appending events to `events.jsonl` and running `fold()` per token --
hundreds of cycles per second for ephemeral display data.

### Replay on reconnect

The web server maintains accumulated streaming text. On browser reconnect,
a single `token-delta` event containing the full accumulated text is sent.
When the subagent completes, the accumulated text is cleared.

---

## Frontend

The frontend (`koan/web/static/js/koan.js`) receives SSE `token-delta` events
and appends the delta text to the streaming display area. The HTMX SSE
integration handles connection and reconnection.

Server-rendered HTML fragments from `koan/web/templates/` provide the
structural layout. The JavaScript in `koan.js` handles only the incremental
text accumulation for streaming display.

---

## What Is Not Streamed

| Signal                 | Why excluded                                                  |
| ---------------------- | ------------------------------------------------------------- |
| Thinking blocks        | Not visible to users in current UI                            |
| Tool execution updates | Handled by audit projection -> SSE events                     |
| Scout output           | Scouts push their own audit events; no token streaming needed |
