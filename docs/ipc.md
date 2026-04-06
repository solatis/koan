# Inter-Process Communication

HTTP MCP-based communication between the driver and subagent processes.

> Parent doc: [architecture.md](./architecture.md)
>
> The MCP endpoint at `http://localhost:{port}/mcp?agent_id={id}` is the sole
> communication channel between parent and child. See
> [architecture.md -- Directory-as-contract](./architecture.md#6-directory-as-contract).

---

## Overview

Subagent CLI processes (`claude`, `codex`, `gemini`) communicate with the
driver via HTTP MCP tool calls. The driver runs a single Starlette HTTP server
that handles both the web dashboard and the MCP tool endpoint. When a tool call
arrives, the server looks up the agent's state by `agent_id` in an in-process
registry and handles the call directly.

Three interactions involve blocking -- the HTTP request is held open while the
driver awaits an external response:

| Mechanism               | What blocks                        | Who responds                   |
| ----------------------- | ---------------------------------- | ------------------------------ |
| `koan_ask_question`     | User input needed                  | User via web UI                |
| `koan_request_scouts`   | Scout subagents running            | Driver (after scouts complete) |
| `koan_yield`            | Phase complete, awaiting direction | User via `POST /api/chat`      |

User-facing tool calls (`koan_ask_question`) go through the `PendingInteraction`
queue on `AppState`. The MCP handler creates an `asyncio.Future`, stores it in
`AgentState.pending_tool`, enqueues a `PendingInteraction` on `AppState`, and
awaits the Future. The HTTP connection stays open until the Future resolves.

`koan_request_scouts` is handled entirely inline: the handler spawns scouts via
`asyncio.gather` of `spawn_subagent` calls (bounded by a semaphore), collects
their results, and returns directly. No `PendingInteraction` is created; the
HTTP connection is held open only by the `await asyncio.gather(...)` call.

`koan_request_executor` spawns a single executor subagent and blocks until it
exits. Like scouts, it is handled inline with no `PendingInteraction`.

`koan_yield` uses `AppState.yield_future` directly (not `PendingInteraction`).
See [koan_yield Blocking](#koan_yield-blocking).

There is no polling and no intermediate files for any of these flows.

---

## Blocking Interaction Model

### `asyncio.Future` resolution (user-facing interactions)

When a user-facing blocking tool is called:

1. MCP endpoint receives tool call with `agent_id`
2. Handler creates `asyncio.Future`, stores it in `AgentState.pending_tool`,
   and enqueues a `PendingInteraction` on `AppState.interaction_queue`
3. If no interaction is currently active, the interaction is promoted to
   `AppState.active_interaction` and an SSE event is pushed to browsers
   (question form)
4. Handler `await`s the Future -- HTTP connection stays open
5. User fills the form in the web UI and submits:
   - `POST /api/answer` resolves the Future for `koan_ask_question`
6. Handler returns the resolved value as the MCP tool result; the next queued
   interaction (if any) is promoted to active

```
subagent ---POST /mcp koan_ask_question---> driver
                                             |
                                             +-- create Future
                                             +-- store Future in AgentState.pending_tool
                                             +-- enqueue PendingInteraction on AppState
                                             +-- push SSE "ask" event to browser
                                             +-- await Future
                                             |
                          user fills form <---+
                          POST /api/answer ---+
                                             |
                                             +-- resolve Future with answer
                                             |
subagent <---tool result (answer)----------- +
```

### `PendingInteraction`

The `PendingInteraction` object stored in `AppState.active_interaction` (or
queued in `AppState.interaction_queue`):

- `type` -- `"ask"`
- `agent_id` -- the agent that issued the blocking call
- `token` -- UUID for SSE correlation
- `payload` -- type-specific request data
- `future` -- the `asyncio.Future` awaiting resolution

`AgentState.pending_tool` holds the raw `asyncio.Future` for the currently
blocked MCP call on that agent (not the `PendingInteraction` object itself).

### Constraints

- **Global FIFO queue** -- `AppState.interaction_queue` is a single queue
  shared across all agents. At most one interaction is active at a time; up to
  8 additional interactions may be queued (`interaction_queue_max = 8`). A
  call that would exceed the cap (9 total: 1 active + 8 queued) raises
  `interaction_queue_full`.
- **No polling** -- resolution is immediate when the external actor responds.
- **The subagent's LLM turn is blocked** while the Future is pending. The MCP
  HTTP connection is held open; the LLM cannot call other tools until the
  response arrives.

---

## Ask Flow

```
subagent calls koan_ask_question({ questions: [...] })
  -> MCP endpoint checks permissions
  -> creates asyncio.Future, stores in AgentState.pending_tool
  -> enqueues PendingInteraction { type: "ask" } on AppState
  -> if no active interaction: promotes to active, pushes SSE `questions_asked` event to browsers
  -> awaits Future

user sees question form in web UI
  -> fills form, clicks Submit
  -> POST /api/answer -> resolves Future with user's selection

MCP handler receives resolved value
  -> clears AgentState.pending_tool
  -> activates next queued interaction (if any)
  -> formats answer as structured text
  -> returns as MCP tool result to subagent
```

The "Other" option is appended server-side -- the LLM never includes it.

---

## Scout Flow

```
subagent calls koan_request_scouts({ questions: [...] })
  -> MCP endpoint checks permissions
  -> no PendingInteraction created

  handler runs inline via asyncio.gather (semaphore-bounded concurrency):
    -> for each scout task:
        -> assign scout agent_id
        -> ensure subagent directory
        -> spawn scout CLI process via spawn_subagent()
        -> scout connects to /mcp?agent_id={scout_id}
        -> scout calls koan_complete_step, does work, completes
        -> SubagentResult collected (exit_code, final_response)
    -> all scouts run concurrently up to scout_concurrency limit
    -> asyncio.gather returns list of results

MCP handler processes results
  -> collects non-None final_response values as findings
  -> returns concatenated findings as MCP tool result to subagent
  (HTTP connection was held open by await asyncio.gather for the duration)
```

### Scout pool behavior

All scouts are submitted concurrently with a configurable concurrency limit
(default: 4). The pool:

- **Runs all items to completion** regardless of individual failures
- **Reports progress** via SSE events (`scout_queued` emitted before gather)
- **Does not implement timeouts** -- timeout logic belongs in the caller

### Scout success determination

Scout success is derived from the subagent's exit code and final response, not
file existence:

```python
result = await spawn_subagent(scout_task, _app_state)
succeeded = result.exit_code == 0
findings = result.final_response or None
```

### Failed scouts are non-fatal

Scouts that exit non-zero return `None` from `run_scout()` and are omitted from
findings. The tool result notes any missing scouts:

`"No findings returned."` (if all fail) or silently omits failed scouts from
the concatenated output.

---

## Executor Flow

```
orchestrator calls koan_request_executor({ artifacts: [...], instructions: "..." })
  -> MCP endpoint checks permissions (execute or execution phase only)
  -> no PendingInteraction created
  -> ensures subagent directory, writes task.json with artifacts + instructions
  -> spawns executor CLI process via spawn_subagent()
  -> executor connects to /mcp?agent_id={executor_id}
  -> executor calls koan_complete_step, reads artifacts, plans, implements
  -> executor calls koan_complete_step at each step boundary
  -> executor process exits when done
  -> MCP handler collects SubagentResult (exit_code, final_response)
  -> returns success/failure summary as MCP tool result to orchestrator
  (HTTP connection held open for the duration of execution)
```

The orchestrator reports the result to the user in chat and then calls
`koan_yield` to present follow-up options.

---

## koan_yield Blocking

`koan_yield` is the generic conversation primitive — the orchestrator calls it
whenever it needs to yield control to the user for open-ended chat. It uses
`AppState.yield_future` directly, not the `PendingInteraction` queue.

```
orchestrator calls koan_yield({ suggestions: [...] })
  -> push_event("yield_started", {suggestions: [...]})
     -> fold: appends YieldEntry to conversation, sets run.active_yield
     -> browser renders suggestion pills
  -> drain_user_messages(app_state)
  -> if buffer empty:
       future = asyncio.get_running_loop().create_future()
       app_state.yield_future = future
       await future              # HTTP connection held open
     app_state.yield_future = None
  -> messages = drain_user_messages(app_state)
  -> returns format_user_messages(messages)
```

The Future is resolved when the user sends a message via `POST /api/chat`.

**Multi-turn conversation:** The orchestrator calls `koan_yield` repeatedly
for as long as the user wants to chat. Each call blocks, waits for one message,
returns it. No new `yield_started` event is emitted on subsequent calls unless
the orchestrator provides updated suggestions; the `active_yield` pills remain
visible.

**If messages are already buffered** (user sent a message before the tool was
called): `koan_yield` drains them and returns immediately — no Future is
created.

**Key asyncio invariant:** `api_chat` and `koan_yield` run in the same asyncio
event loop. `api_chat` appends to `user_message_buffer` before calling
`set_result()`. When `koan_yield` resumes, `drain_user_messages()` finds the
message in the buffer. No threads or locks are needed.

**`yield_future` vs `PendingInteraction`:** `koan_yield` bypasses the
interaction queue because it is not a structured question with a UI form — it
is free-form chat. The PendingInteraction mechanism renders a specific UI widget
(`koan_ask_question`); `koan_yield` renders suggestion pills via the projection
(`yield_started` event). Both resolve via `asyncio.Future` but through
independent code paths.

---

## Chat Message Delivery

User messages are routed based on whether the orchestrator is waiting for them.

```
user types in chat input
  -> POST /api/chat { message: "..." }
  -> ChatMessage created with content + timestamp_ms
  -> push_event("user_message", ...) — appears in activity feed
  -> if app_state.yield_future is set and not done:
       user_message_buffer.append(msg)
       yield_future.set_result(True)   -- unblocks koan_yield
  -> else:
       steering_queue.append(msg)
       push_event("steering_queued", ...) -- shown in SteeringBar above input
  -> returns { ok: true }
```

**Phase-boundary messages** (sent while `koan_yield` is blocking): routed to
`user_message_buffer`, delivered as the koan_yield return value.

**Steering messages** (sent while the orchestrator is mid-step): routed to
`steering_queue`, appended to the next tool response via
`_drain_and_append_steering()`. The LLM integrates them without abandoning
the current step.

The two queues are drained independently to prevent double-delivery:
`drain_user_messages()` and `drain_steering_messages()` each clear their own
list atomically.

---

## Sequence Diagrams

### koan_yield flow (phase boundary)

```
Orchestrator                  Driver                    Web UI
  |                              |                        |
  |--koan_yield(suggestions)--->|                        |
  |                              |  push yield_started   |
  |                              |--SSE patch----------->|
  |                              |  (pills render)       |
  |                              |  create yield_future  |
  |                              |  await yield_future   |
  |                              |                        | user clicks pill
  |                              |                        | setChatDraft(cmd)
  |                              |                        | user presses Enter
  |                              |<-POST /api/chat--------|
  |                              |  buffer + set_result   |
  |<-tool result (msg text)------|                        |
  |  (converses with user)       |                        |
  |--koan_set_phase("plan-spec")->|                       |
  |                              |  push yield_cleared   |
  |                              |  push phase_started   |
  |                              |--SSE patches--------->|
  |<-"Phase set to plan-spec."---|                        |
```

### Scout flow (inline blocking, no PendingInteraction)

```
Driver                         Scout CLI              Web UI
  |                                |                     |
  |<--koan_request_scouts---------|                     |
  |  emit scout_queued events     |                     |
  |  asyncio.gather (semaphore)   |                     |
  |  spawn scout processes------->|                     |
  |                               |--koan_complete_step->|
  |                               |<-step 1 guidance----|
  |                               |  (does work)        |
  |                               |--koan_complete_step->|
  |                               |<-"Phase complete."--|
  |  scout exits (exit_code 0)    |                     |
  |  gather collects results      |                     |
  |--tool result (findings)------>|                     |
```

### User interaction flow (blocking via PendingInteraction queue)

```
Orchestrator                  Driver                    Web UI
  |                              |                        |
  |--koan_ask_question---------->|                        |
  |                              |  create Future         |
  |                              |  enqueue interaction   |
  |                              |--SSE "ask" event------>|
  |                              |                        | user sees form
  |                              |                        | user submits
  |                              |<-POST /api/answer------|
  |                              |  resolve Future        |
  |                              |  activate next queued  |
  |<-tool result (answer)--------|                        |
```
