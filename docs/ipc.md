# In-Process Communication

How the koan backend coordinates between the orchestrator, subagents, and the
user through in-process asyncio primitives.

> Parent doc: [architecture.md](./architecture.md)
>
> Subagents are asyncio tasks inside the single backend process. Tool calls are
> in-process function calls -- there is no HTTP MCP transport. See
> [architecture.md -- Directory-as-contract](./architecture.md#6-directory-as-contract).

---

## Overview

Subagent tasks (orchestrator, scouts, executors) run as asyncio coroutines
inside the koan backend. When a tool core needs to block on an external
response, it does so via `asyncio.Future` objects stored in `AppState`.

Three interactions involve blocking -- the tool core `await`s a future while
the backend event loop handles other tasks:

| Mechanism               | What blocks                        | Who responds                   |
| ----------------------- | ---------------------------------- | ------------------------------ |
| `koan_ask_question`     | User input needed                  | User via web UI                |
| `koan_request_scouts`   | Scout subagents running            | Loop (after scouts complete)   |
| Phase-boundary hand-back | Phase complete, awaiting direction | User via `POST /api/chat`      |

User-facing tool calls (`koan_ask_question`) go through the `PendingInteraction`
queue on `AppState`. The tool core creates an `asyncio.Future`, stores it in
`AgentState.pending_tool`, enqueues a `PendingInteraction` on `AppState`, and
`await`s the future. The backend loop stays responsive; the orchestrator's
current turn is blocked until the user responds.

`koan_request_scouts` is handled entirely inline: `request_scouts_core` spawns
scouts via `asyncio.gather` of `spawn_subagent` calls (bounded by a semaphore),
collects their results, and returns directly. No `PendingInteraction` is created.

`koan_request_executor` spawns a single executor subagent and awaits its
completion. Like scouts, it is handled inline with no `PendingInteraction`.

The phase-boundary hand-back is not a tool call. When the turn-outcome resolver
determines that steps are exhausted for a primary agent, `run_agent_loop`
emits `yield_started` and `await`s `AppState.yield_future`, which is resolved
when the user sends a message via `POST /api/chat`.

There is no polling and no intermediate files for any of these flows.

---

## Blocking Interaction Model

### `asyncio.Future` resolution (user-facing interactions)

When a user-facing blocking tool is called:

1. Tool core creates `asyncio.Future`, stores it in `AgentState.pending_tool`,
   and enqueues a `PendingInteraction` on `AppState.interaction_queue`
2. If no interaction is currently active, the interaction is promoted to
   `AppState.active_interaction` and an SSE event is pushed to browsers
   (question form)
3. Tool core `await`s the Future -- the orchestrator turn is suspended
4. User fills the form in the web UI and submits:
   - `POST /api/answer` resolves the Future for `koan_ask_question`
5. Tool core returns the resolved value; the next queued interaction (if any)
   is promoted to active

```
tool core: koan_ask_question({ questions: [...] })
  -> create Future
  -> store Future in AgentState.pending_tool
  -> enqueue PendingInteraction on AppState
  -> push SSE "ask" event to browser
  -> await Future

                          user fills form <---+
                          POST /api/answer ---+
                                             |
                                             +-- resolve Future with answer
                                             |
tool core receives resolved value
  -> clears AgentState.pending_tool
  -> activates next queued interaction (if any)
  -> formats answer as structured text
  -> returns to caller (koan_ask_question registered function)
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
blocked call on that agent (not the `PendingInteraction` object itself).

### Constraints

- **Global FIFO queue** -- `AppState.interaction_queue` is a single queue
  shared across all agents. At most one interaction is active at a time; up to
  8 additional interactions may be queued (`interaction_queue_max = 8`). A
  call that would exceed the cap (9 total: 1 active + 8 queued) raises
  `interaction_queue_full`.
- **No polling** -- resolution is immediate when the external actor responds.
- **The agent turn is suspended** while the Future is pending. The agent cannot
  call other tools until the response arrives.

---

## Ask Flow

```
koan_ask_question({ questions: [...] })
  -> creates asyncio.Future, stores in AgentState.pending_tool
  -> enqueues PendingInteraction { type: "ask" } on AppState
  -> if no active interaction: promotes to active, pushes SSE `questions_asked` event to browsers
  -> awaits Future

user sees question form in web UI
  -> fills form, clicks Submit
  -> POST /api/answer -> resolves Future with user's selection

tool core receives resolved value
  -> clears AgentState.pending_tool
  -> activates next queued interaction (if any)
  -> formats answer as structured text
  -> returns as tool result to agent
```

The "Other" option is appended server-side -- the LLM never includes it.

---

## Scout Flow

```
koan_request_scouts({ questions: [...] })
  -> no PendingInteraction created

  request_scouts_core runs inline via asyncio.gather (semaphore-bounded concurrency):
    -> for each scout task:
        -> assign scout agent_id
        -> ensure subagent directory
        -> spawn scout as asyncio task via spawn_subagent()
        -> scout runs its step sequence in-process and exits
        -> SubagentResult collected (exit_code, final_response)
    -> all scouts run concurrently up to scout_concurrency limit
    -> asyncio.gather returns list of results

tool core processes results
  -> collects non-None final_response values as findings
  -> returns concatenated findings as tool result to agent
```

### Scout pool behavior

All scouts are submitted concurrently with a configurable concurrency limit
(default: 4). The pool:

- **Runs all items to completion** regardless of individual failures
- **Reports progress** via SSE events (`scout_queued` emitted before gather)
- **Does not implement timeouts** -- timeout logic belongs in the caller

### Scout success determination

Scout success is derived from the subagent's exit code and final response:

```python
result = await spawn_subagent(scout_task, _app_state)
succeeded = result.exit_code == 0
findings = result.final_response or None
```

### Failed scouts are non-fatal

Scouts that exit non-zero return `None` findings and are omitted from the
concatenated output. The tool result notes any missing scouts:

`"No findings returned."` (if all fail) or silently omits failed scouts.

---

## Executor Flow

```
koan_request_executor({ artifacts: [...], instructions: "..." })
  -> no PendingInteraction created
  -> ensures subagent directory, writes task.json with artifacts + instructions
  -> spawns executor as asyncio task via spawn_subagent()
  -> executor runs its step sequence in-process and exits
  -> tool core collects SubagentResult (exit_code, final_response)
  -> returns success/failure summary as tool result to orchestrator
```

The orchestrator reports the result to the user in chat and then ends its turn
in terminal text to hand back (after calling `koan_suggest_next`).

---

## Phase-Boundary Hand-Back

The hand-back is a terminal-text turn -- not a tool call. When the
turn-outcome resolver determines that a primary agent's steps are exhausted,
`run_agent_loop` parks on a loop-owned `asyncio.Future` stored in
`AppState.yield_future`:

```
Resolver: steps exhausted, primary agent -> hand back
  -> push_event("yield_started", {suggestions: [...]})
     -> fold: appends YieldEntry to agent conversation, sets run.active_yield
     -> browser renders suggestion pills
  -> create asyncio.Future
  -> AppState.yield_future = future
  -> await future              # loop is parked

user types in chat or clicks a suggestion pill
  -> POST /api/chat { message: "..." }
  -> api_chat: yield_future is set -> append to user_message_buffer -> set_result(True)
  -> yield_future resolves

loop resumes
  -> AppState.yield_future = None
  -> user message becomes the next turn's prompt
  -> agent continues, eventually calls koan_set_phase or "done"
```

**Multi-turn conversation:** The loop parks after each terminal-text hand-back
and resumes on the next user message. The orchestrator may continue the
conversation across multiple turns before committing a phase transition.

**If messages are already buffered** (user sent a message before the loop
parked): the loop drains them immediately -- no Future is created.

**Key asyncio invariant:** `api_chat` and the loop's yield path run in the same
asyncio event loop. `api_chat` appends to `user_message_buffer` before calling
`set_result()`. When the loop resumes, `drain_user_messages()` finds the
message in the buffer. No threads or locks are needed.

---

## Chat Message Delivery

User messages are routed based on whether the loop is parked at a hand-back:

```
user types in chat input
  -> POST /api/chat { message: "..." }
  -> ChatMessage created with content + timestamp_ms
  -> push_event("user_message", ...) -- appears in activity feed
  -> if app_state.yield_future is set and not done:
       user_message_buffer.append(msg)
       yield_future.set_result(True)   -- unblocks the parked loop
  -> else:
       steering_queue.append(msg)
       push_event("steering_queued", ...) -- shown in SteeringBar above input
  -> returns { ok: true }
```

**Phase-boundary messages** (sent while the loop is parked): routed to
`user_message_buffer`, delivered as the next turn's prompt.

**Steering messages** (sent while the agent is mid-turn): routed to
`steering_queue`, injected between graph nodes (after `CallToolsNode`) via
`agent_run.enqueue()`. The LLM integrates them without abandoning the current
step.

The two queues are drained independently to prevent double-delivery:
`drain_user_messages()` and `drain_steering_messages()` each clear their own
list atomically.

---

## Sequence Diagrams

### Phase-boundary hand-back

```
Orchestrator (loop)           Backend                   Web UI
  |                              |                        |
  | end turn in terminal text    |                        |
  +--(resolver: hand back)------>|                        |
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
  |  next turn prompt (msg text) |                        |
  |<-(loop resumes)--------------|                        |
  |  (agent responds, calls      |                        |
  |   koan_set_phase)            |                        |
```

### Scout flow (inline, no PendingInteraction)

```
Backend (orchestrator turn)    Scout task             Web UI
  |                                |                     |
  |  koan_request_scouts           |                     |
  |  emit scout_queued events      |                     |
  |  asyncio.gather (semaphore)    |                     |
  |  spawn scout tasks------------>|                     |
  |                               (scout runs steps,     |
  |                                ends turn, terminates)|
  |  gather collects results       |                     |
  |  return findings to agent      |                     |
```

### User interaction flow (blocking via PendingInteraction queue)

```
Orchestrator (tool core)      Backend                   Web UI
  |                              |                        |
  |  koan_ask_question---------->|                        |
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
