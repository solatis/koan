# IPC Protocol

File-based inter-process communication between parent and subagent processes.

> Parent doc: [architecture.md](./architecture.md)
>
> `ipc.json` is one of three well-known files in the subagent directory.
> See [architecture.md § Directory-as-contract](./architecture.md#6-directory-as-contract)
> for how it relates to `task.json` (input) and `state.json` (observation).

---

## Overview

Subagent `pi -p` processes cannot communicate with the parent via stdin (it is
`"ignore"`). Instead, they share a single `ipc.json` file in the subagent
directory. The subagent writes a request; the parent polls, handles it, and
writes the response back. The subagent polls for the response.

```
subagent: writeIpcFile(dir, { response: null })       ← atomic write creates request
subagent: poll loop (500ms): readIpcFile(dir)          ← blocks LLM turn
parent:   poll loop (300ms): readIpcFile(dir)          ← detects request
parent:   handles request (web server or scout pool)   ← does work
parent:   writeIpcFile(dir, { ..., response: data })   ← atomic write with response
subagent: readIpcFile → response !== null              ← breaks poll loop
subagent: deleteIpcFile(dir)                           ← cleanup
```

### Why file-based IPC

- **Cross-process simplicity** — no socket management, no connection lifecycle
- **Debuggable** — `cat ipc.json` shows the current state
- **Atomic via rename** — tmp file → `fs.rename()` prevents partial reads
- **Cross-platform** — no POSIX-specific constructs

### Constraints

- **One request at a time** per subagent directory. Tools check
  `ipcFileExists(dir)` before writing and return an error if a request is
  already pending.
- **Polling, not push** — inherent latency of poll intervals (300ms parent,
  500ms subagent).
- **The subagent's LLM turn is blocked** while polling. The tool's `execute`
  function is in a `sleep(500)` loop — the LLM cannot do other work until
  the response arrives.

---

## Message Types

The protocol supports exactly two request types, discriminated by the `type`
field:

### `ask` — User questions

The subagent needs human input. The request contains one question with
options; the response contains the user's selection.

```typescript
interface AskIpcFile {
  type: "ask";
  id: string;                    // UUID, for response correlation
  createdAt: string;
  payload: {
    id: string;
    question: string;
    context?: string;            // optional multi-paragraph background
    options: Array<{ label: string }>;
    multi?: boolean;
    recommended?: number;        // 0-indexed
  };
  response: AskResponse | null;  // null = pending, non-null = answered
}
```

### `scout-request` — Parallel codebase exploration

The subagent needs codebase context. The request contains scout task
definitions; the response contains file paths to findings.

```typescript
interface ScoutIpcFile {
  type: "scout-request";
  id: string;
  createdAt: string;
  scouts: Array<{
    id: string;       // e.g., "auth-patterns"
    role: string;     // e.g., "security auditor"
    prompt: string;   // e.g., "Find all auth middleware in src/"
  }>;
  response: { findings: string[]; failures: string[] } | null;
}
```

---

## Atomic Writes

All IPC file operations use atomic tmp-rename:

```typescript
// Write: .ipc.tmp.json → rename → ipc.json
async function writeIpcFile(dir, data) {
  const tmp = path.join(dir, ".ipc.tmp.json");
  const target = path.join(dir, "ipc.json");
  await fs.writeFile(tmp, JSON.stringify(data, null, 2) + "\n", "utf8");
  await fs.rename(tmp, target);
}

// Read: returns null on missing file OR parse error
// Parse errors are treated as "not ready" — handles partial writes on non-POSIX systems
async function readIpcFile(dir): IpcFile | null {
  try {
    const raw = await fs.readFile(path.join(dir, "ipc.json"), "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

// Delete: removes both ipc.json and .ipc.tmp.json, swallows ENOENT
async function deleteIpcFile(dir) { ... }
```

---

## Poll Timing

| Poller | Interval | Purpose |
|--------|----------|---------|
| **Parent IPC responder** | 300ms | Detect subagent requests quickly |
| **Subagent tool** | 500ms | Wait for parent response |
| **Web server agent polling** | 50ms | Update agent status in UI |

The parent polls slightly faster than the subagent to ensure it picks up
requests promptly. Both intervals are low enough for interactive feel.

---

## Parent-Side IPC Responder

`runIpcResponder()` starts concurrently with the child process (when a web
server handle is available) and terminates when the `AbortSignal` fires
(child process exit → abort).

```
while (!signal.aborted) {
  sleep(300ms)
  ipc = readIpcFile(subagentDir)
  if ipc === null or ipc.response !== null → continue
  if ipc.type === "ask"           → handleAskRequest(...)
  if ipc.type === "scout-request" → handleScoutRequest(...)
}
```

### Error handling

The poll loop swallows **all** errors. Transient filesystem issues (e.g.,
file being renamed) must not abort the parent session. The next poll cycle
will pick up the file successfully.

### Idempotence guard

Before writing a response, the responder re-reads `ipc.json` and validates:
- The file still exists
- The `type` matches the expected request type
- The `id` matches the original request ID
- `response` is still `null`

This prevents writing a response to a stale or replaced request.

### Circular import avoidance

The IPC responder needs to spawn scouts, but importing from `subagent.ts`
would create a circular dependency. Instead, `subagent.ts` injects a
`ScoutSpawnContext` interface at startup:

```typescript
interface ScoutSpawnContext {
  epicDir: string;
  spawnScout(task: ScoutTask, scoutDir: string, outputFile: string): Promise<number>;
}
```

---

## Ask Flow

```
intake-llm calls koan_ask_question({ id, question, context?, options, ... })
  → tool writes AskIpcFile { type: "ask", response: null }
  → tool enters 500ms poll loop (LLM turn blocked)

ipc-responder detects { type: "ask", response: null }
  → appends "Other" option to the question
  → calls webServer.requestAnswer(question, signal)
    → creates Promise in pendingInputs map
    → SSE "ask" event → browser renders QuestionForm
    → user fills form, clicks Submit
    → POST /api/answer → resolves Promise
  → maps answer to AskAnswerPayload
  → writes AskResponse to ipc.json (atomic)

tool poll detects response !== null
  → breaks loop
  → deleteIpcFile(dir)
  → formats answer as structured text
  → returns to LLM
```

The "Other" option is appended server-side — the LLM never includes it.

---

## Scout Flow

```
intake-llm calls koan_request_scouts({ scouts: [...] })
  → tool writes ScoutIpcFile { type: "scout-request", response: null }
  → tool enters 500ms poll loop (LLM turn blocked)

ipc-responder detects { type: "scout-request", response: null }
  → computes scoutDir + outputFile for each task
  → webServer.registerAgent(...) for each scout (UI tracking)
  → pool(taskIds, concurrency=4, worker):
      for each scout (up to 4 concurrent):
        → mkdir(scoutDir, { recursive: true })
        → spawnScout(task, scoutDir, outputFile)
            → full subagent lifecycle: boot → step 1 → work → complete → exit
        → readProjection(scoutDir) → check status === "completed"
        → if succeeded: findings.push(outputFile)
        → if failed: failures.push(taskId)
        → webServer.completeAgent(taskId)
  → writes ScoutResponse { findings: [paths], failures: [ids] } to ipc.json

tool poll detects response !== null
  → breaks loop
  → deleteIpcFile(dir)
  → reads each findings.md file verbatim (inline, not just paths)
  → returns concatenated content to LLM
```

### Scout pool behavior

The pool uses a semaphore with limit 4. All scouts are submitted to
`Promise.all` simultaneously; the semaphore gates actual execution. The pool:

- **Runs all items to completion** regardless of individual failures
- **Reports progress** via optional callback (done/total/active/queued)
- **Does not implement timeouts** — timeout logic belongs in the worker closure

### Scout success determination

Scout success is derived from the JSON audit projection, not file existence:

```typescript
const projection = await readProjection(scoutDir);
succeeded = projection?.status === "completed";
```

A scout can write a partial `findings.md` and then crash. File existence is
not proof of completion.

### Failed scouts are non-fatal

The tool result tells the LLM:
`"Failed scouts (non-fatal, proceed without them): task-id-1, task-id-2"`

The LLM must proceed with whatever findings are available.

---

## Audit Integration

The audit system (`lib/audit.ts`) runs inside each subagent process and
provides the observability bridge between subagent work and parent/UI polling.

### Event-sourced design

- `events.jsonl` — append-only truth (one JSON object per line)
- `state.json` — eagerly materialized projection, written atomically after
  every event

The parent polls `state.json` (cheap file read) instead of parsing the event
log. `fold()` is a pure function so the projection can be rebuilt from the raw
log for testing and crash recovery.

### Event types

| Event | Trigger | Key data |
|-------|---------|----------|
| `phase_start` | `BasePhase.begin()` | totalSteps |
| `step_transition` | `handleStepComplete()` | step number, name, total |
| `tool_call` | pi `tool_call` hook | toolCallId, name, input |
| `tool_result` | pi `tool_result` hook | toolCallId, summarized metrics (not full content) |
| `usage` | pi `turn_end` hook | input/output/cacheRead/cacheWrite tokens |
| `heartbeat` | 10s timer | (keeps `updatedAt` fresh during long tool calls) |
| `phase_end` | phase completion | "completed" |

### Projection fields consumed by parent

| Field | Consumer | Purpose |
|-------|----------|---------|
| `status` | IPC responder, web server | Scout success, agent completion |
| `step` | Web server | Intake sub-phase derivation |
| `currentToolCallId` | Web server | "doing X" vs "done with X" in UI |
| `completionSummary` | Web server | Scout card summary (500-char prefix of `thoughts`) |
| `tokensSent/Received` | Web server | Token usage display |
| `model` | Web server | Model display |

### Serialization

`EventLog.append()` calls are serialized via a promise chain. The heartbeat
timer and `tool_result` handler both call `append()` concurrently — without
serialization, two `writeState()` calls race on the shared `.tmp.json` file,
causing ENOENT on rename.
