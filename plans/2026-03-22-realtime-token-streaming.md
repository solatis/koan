# Realtime Token Streaming from Subagents to Web UI

Stream LLM token deltas from subagent processes to the browser in realtime,
giving the user instant visibility into what the LLM is producing instead of
waiting for a turn to complete.

---

## Design Decisions

### Use `--mode json` stdout parsing, not extension hooks or file polling

Pi ships a designed integration surface for external UIs: `--mode json -p`
emits every session event as a JSONL line on stdout. Pi's own subagent
extension (`examples/extensions/subagent/index.ts`) already uses this exact
pattern with `["--mode", "json", "-p"]` and a line-buffer parser on
`proc.stdout`.

Koan currently spawns with `["-p"]` and pipes stdout to a log file. Switching
to `["--mode", "json", "-p"]` gives the parent process a structured stream of
typed events, including `message_update` with `text_delta` deltas, without
modifying the koan extension or the pi codebase.

Alternatives considered and rejected:

| Alternative                                   | Reason                                                                                         |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Extension `message_update` hook + file append | More code, file I/O per token, still needs polling, adds new file to directory-as-contract     |
| Extension + HTTP POST per token               | Need to pass server port to extension, HTTP overhead per token, reliability concerns           |
| Switch to RPC mode                            | Requires bidirectional stdin/stdout, fundamentally changes spawn pattern (stdin is `"ignore"`) |
| Tail stdout.log in `-p` mode                  | Raw text, not structured — can't distinguish token deltas from tool output                     |
| SDK embedding (`createAgentSession`)          | Destroys process isolation (core architectural invariant)                                      |

### Forward only `text_delta` events, filter everything else

`--mode json` emits all session events (tool execution, turns, compaction,
etc.). The parent's JSONL parser filters to `message_update` events where
`assistantMessageEvent.type === "text_delta"`, discarding the rest. This keeps
the SSE channel lean — the existing 50ms polling of `state.json` continues to
handle tool-call-level status updates.

### Send incremental deltas, not accumulated state

Each SSE event carries a `delta` string (the new tokens), not the full
accumulated text. The frontend accumulates. This minimizes bandwidth and
matches how the provider stream works internally. The frontend clears the
accumulator on `subagent-idle` (already emitted when a subagent finishes).

### Preserve the stdout log file

The JSONL parser runs alongside the existing `stdoutLog.write(data)` call.
The log file continues to capture everything for post-mortem debugging.
No behavioral change to existing diagnostics.

---

## Scope

### In scope

- Spawn flag change (`-p` → `--mode json -p`)
- JSONL line-buffer parser in `subagent.ts`
- New `pushTokenDelta` method on `WebServerHandle`
- New `token-delta` SSE event type in the web server
- Frontend store state + SSE handler for accumulating deltas
- A visible streaming text area in the activity feed / subagent panel

### Out of scope

- Streaming for scouts (they have no web server handle today)
- Thinking block streaming (`thinking_delta` — could be added later with the same mechanism)
- Tool execution streaming (`tool_execution_update` — same mechanism)
- Backpressure / throttling (LLM generation speed is the bottleneck, not parsing)

---

## Implementation

### Step 1 — Extend `WebServerHandle` interface

**File:** `src/planner/web/server-types.ts`

Add one method to the `WebServerHandle` interface:

```typescript
/**
 * Push a streaming token delta from a subagent to all SSE clients.
 *
 * Parameterless because only one subagent is tracked at a time (via
 * trackSubagent / clearSubagent). There is no ambiguity about which
 * subagent the delta belongs to — only the tracked subagent generates tokens.
 */
pushTokenDelta(delta: string): void;
```

This is scoped to the currently-tracked subagent (set by `trackSubagent()`).
No need to pass a directory — only one subagent is tracked at a time.

### Step 2 — Implement SSE push and replay accumulation in web server

**File:** `src/planner/web/server.ts`

Add a server-side accumulator alongside the existing `currentSubagent`,
`currentPhase`, etc.:

```typescript
// Server-side accumulator for token streaming. Holds the full text produced
// by the current subagent so reconnecting clients can catch up. Cleared on
// subagent transitions (trackSubagent / clearSubagent).
let streamingText = "";
```

Implement `pushTokenDelta` on the server handle object:

```typescript
pushTokenDelta(delta: string): void {
  // Accumulate server-side for replay on client reconnect. Without this,
  // a client that reconnects mid-stream would see an empty streaming area
  // with no error signal — a silent failure.
  streamingText += delta;
  // Push only the delta (not accumulated text) to already-connected clients.
  // This matches the provider stream's own framing and minimizes SSE payload.
  pushEvent("token-delta", { delta });
},
```

Add the replay write inside `replayState()`:

```typescript
// Replay accumulated streaming text as a single delta event. The frontend's
// appendTokenDelta handles this transparently — it accumulates from zero
// after each clear, so receiving the full text as one "delta" produces the
// correct state.
if (streamingText) {
  write("token-delta", { delta: streamingText });
}
```

Reset the accumulator in `trackSubagent()` and `clearSubagent()`:

```typescript
// In trackSubagent(): new subagent starts, discard previous text
streamingText = "";

// In clearSubagent(): subagent finished, discard text
streamingText = "";
```

### Step 3 — Switch spawn args and parse stdout JSONL

**File:** `src/planner/subagent.ts`

Three changes:

1. Add `"--mode", "json"` to the spawn args array (before `-p`).

   ```typescript
   // --mode json makes pi emit structured JSONL on stdout instead of human-
   // readable text. Combined with -p (non-interactive), this is the designed
   // integration surface for external UIs. Pi's own subagent extension uses
   // the identical flag pair — ["--mode", "json", "-p"] — confirming this is
   // the supported composition.
   const args = ["--mode", "json", "-p", "-e", extensionPath, "--koan-dir", subagentDir, ...];
   ```

2. Replace the simple `proc.stdout.on("data")` handler with a JSONL
   line-buffer parser. The pattern is identical to pi's own subagent
   extension:

   ```typescript
   let buffer = "";
   proc.stdout.on("data", (data: Buffer) => {
     // Write raw bytes first — log file receives the full JSONL output
     // regardless of what the parser does. Diagnostics are unaffected.
     stdoutLog.write(data);

     // Accumulate into buffer because a single "data" event may contain
     // a partial line (TCP-style framing — no guarantee of line boundaries).
     buffer += data.toString();

     // Split on newlines. lines[0..n-2] are complete; lines[n-1] may be a
     // partial line — keep it in buffer for the next "data" event.
     const lines = buffer.split("\n");
     buffer = lines.pop() || ""; // trailing partial line (or "" if data ended with \n)

     for (const line of lines) {
       if (!line.trim()) continue;
       try {
         const event = JSON.parse(line);
         // Filter to text_delta only. --mode json emits all session events
         // (tool execution, turn boundaries, compaction, etc.). Only
         // text_delta carries the incremental tokens we want to stream.
         // Everything else is handled by the existing state.json polling path.
         if (
           event.type === "message_update" &&
           event.assistantMessageEvent?.type === "text_delta" &&
           typeof event.assistantMessageEvent.delta === "string"
         ) {
           opts.webServer?.pushTokenDelta(event.assistantMessageEvent.delta);
         }
       } catch {
         // Malformed line (e.g. stderr bleed or partial JSONL during
         // buffer flush). Skip — the log file has the full bytes.
       }
     }
   });
   ```

3. Merge buffer flushing into the **existing** `proc.on("close")` handler.
   The existing handler calls `abortIpc()`, `stdoutLog.end()`, and
   `resolve()`. Insert the buffer flush **before** `resolve()` so the
   final token delta is pushed before `spawnSubagent()` resolves and the
   driver calls `clearSubagent()`:

   ```typescript
   proc.on("close", (code) => {
     abortIpc?.();
     stdoutLog.end();
     stderrLog.end();

     // Flush any partial JSONL line still in the buffer. Under normal
     // operation the buffer is empty at close, but a process killed
     // mid-line (e.g., SIGKILL) would otherwise lose the last event.
     // This must happen before resolve() so the delta arrives before
     // the driver calls clearSubagent() → pushEvent("subagent-idle").
     if (buffer.trim()) {
       try {
         const event = JSON.parse(buffer);
         if (
           event.type === "message_update" &&
           event.assistantMessageEvent?.type === "text_delta" &&
           typeof event.assistantMessageEvent.delta === "string"
         ) {
           opts.webServer?.pushTokenDelta(event.assistantMessageEvent.delta);
         }
       } catch {
         // Ignore malformed trailing content — log file has the raw bytes.
       }
     }

     const exitCode = code ?? 1;
     log(`${task.role} subagent exited`, { exitCode });
     resolve({ exitCode, stderr, subagentDir });
   });
   ```

### Step 4 — Frontend: store + SSE handler

**File:** `js/store.js`

Add state and actions to the Zustand store:

```javascript
streamingText: "",
appendTokenDelta: (delta) => set((s) => ({ streamingText: s.streamingText + delta })),
clearStreamingText: () => set({ streamingText: "" }),
```

**File:** `js/sse.js`

Add the event handler:

```javascript
case "token-delta":
  store.getState().appendTokenDelta(data.delta);
  break;
```

Clear the streaming text when a subagent finishes (on `subagent-idle`):

```javascript
case "subagent-idle":
  store.getState().clearStreamingText();
  // ... existing handler
  break;
```

### Step 5 — Frontend: render streaming text

**File:** `js/components/ActivityFeed.jsx` (or a new `StreamingOutput.jsx`)

Add a component that renders `streamingText` when non-empty. This appears
below or alongside the activity feed, showing what the LLM is currently
producing. Auto-scroll to bottom as text grows. Fade/clear when
`subagent-idle` fires.

Exact placement and styling are design decisions for the UI — the mechanism
is the same regardless.

---

## Verification

- Start a koan pipeline and observe the browser's DevTools Network tab for
  `token-delta` SSE events arriving in realtime during LLM generation.
- Confirm the `stdout.log` file still contains the full JSONL output.
- Confirm `state.json` polling and all existing SSE events (`subagent`,
  `logs`, `agents`, etc.) are unaffected.
- Confirm the koan extension's audit system (`events.jsonl`) still records
  tool calls, usage, and thinking blocks as before.
- Reconnect the EventSource mid-stream and verify replay includes accumulated
  streaming text.

---

## Invariant Compliance

| Invariant                | Impact                                                      |
| ------------------------ | ----------------------------------------------------------- |
| File boundary            | No change — LLMs still write markdown only                  |
| Step-first workflow      | No change — boot prompt unchanged                           |
| Driver determinism       | No change — routing still uses exit codes + state files     |
| Directory-as-contract    | No change — `task.json`, `state.json`, `ipc.json` untouched |
| Default-deny permissions | No change — permission fence untouched                      |
| Need-to-know prompts     | No change — prompt content unchanged                        |
