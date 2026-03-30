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

Three tool calls involve blocking interactions -- the HTTP request is held open
while the driver awaits an external response:

| Tool                   | What blocks             | Who responds                   |
| ---------------------- | ----------------------- | ------------------------------ |
| `koan_ask_question`    | User input needed       | User via web UI                |
| `koan_request_scouts`  | Scout subagents running | Driver (after scouts complete) |
| `koan_review_artifact` | User review needed      | User via web UI                |

For all three, the MCP tool handler creates an `asyncio.Future`, stores it in
`AgentState.pending_tool`, and awaits it. The HTTP connection stays open until
the Future resolves. There is no polling, no intermediate files.

---

## Blocking Interaction Model

### `asyncio.Future` resolution

When a blocking tool is called:

1. MCP endpoint receives tool call with `agent_id`
2. Handler creates `asyncio.Future` and stores it as a `PendingInteraction` in `AgentState`
3. For user-facing interactions: pushes SSE event to browsers (question form, review form)
4. Handler `await`s the Future -- HTTP connection stays open
5. External actor resolves the Future:
   - User interactions: web UI `POST /api/answer` or `POST /api/artifact-review` resolves it
   - Scout requests: driver spawns scouts, awaits completion, resolves Future with findings
6. Handler returns the resolved value as the MCP tool result

```
subagent ---POST /mcp koan_ask_question---> driver
                                             |
                                             +-- create Future
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

The `PendingInteraction` object stored in `AgentState.pending_tool`:

- `type` -- one of `"ask"`, `"scout-request"`, `"artifact-review"`
- `id` -- UUID for correlation
- `payload` -- type-specific request data
- `future` -- the `asyncio.Future` awaiting resolution

### Constraints

- **One pending interaction at a time** per agent. A second blocking tool call
  while one is pending returns an error.
- **No polling** -- resolution is immediate when the external actor responds.
- **The subagent's LLM turn is blocked** while the Future is pending. The MCP
  HTTP connection is held open; the LLM cannot call other tools until the
  response arrives.

---

## Ask Flow

```
subagent calls koan_ask_question({ questions: [...] })
  -> MCP endpoint checks permissions
  -> creates PendingInteraction { type: "ask", future: asyncio.Future() }
  -> stores in AgentState.pending_tool
  -> pushes SSE `questions_asked` event to browsers
  -> awaits Future

user sees question form in web UI
  -> fills form, clicks Submit
  -> POST /api/answer -> resolves Future with user's selection

MCP handler receives resolved value
  -> clears AgentState.pending_tool
  -> formats answer as structured text
  -> returns as MCP tool result to subagent
```

The "Other" option is appended server-side -- the LLM never includes it.

---

## Scout Flow

```
subagent calls koan_request_scouts({ scouts: [...] })
  -> MCP endpoint checks permissions
  -> creates PendingInteraction { type: "scout-request", future: asyncio.Future() }
  -> stores in AgentState.pending_tool

  driver handles scout request in-process:
    -> for each scout task:
        -> assign scout agent_id
        -> register scout in agent registry
        -> write MCP config pointing at same HTTP server
        -> spawn scout CLI process
        -> scout connects to /mcp?agent_id={scout_id}
        -> scout calls koan_complete_step, does work, completes
        -> deregister scout
    -> collect findings from completed scouts
    -> resolve Future with { findings: [paths], failures: [ids] }

MCP handler receives resolved value
  -> clears AgentState.pending_tool
  -> reads each findings.md file verbatim
  -> returns concatenated content as MCP tool result
```

### Scout pool behavior

All scouts are submitted concurrently with a configurable concurrency limit
(default: 4). The pool:

- **Runs all items to completion** regardless of individual failures
- **Reports progress** via SSE events
- **Does not implement timeouts** -- timeout logic belongs in the caller

### Scout success determination

Scout success is derived from the audit projection, not file existence:

```python
projection = read_projection(scout_dir)
succeeded = projection.get("status") == "completed"
```

### Failed scouts are non-fatal

The tool result tells the LLM:
`"Failed scouts (non-fatal, proceed without them): task-id-1, task-id-2"`

---

## Artifact Review Flow

```
subagent calls koan_review_artifact({ path: ".../brief.md" })
  -> MCP endpoint checks permissions
  -> reads file content from path
  -> creates PendingInteraction { type: "artifact-review", future: asyncio.Future() }
  -> pushes SSE `artifact_review_requested` event to browsers (with rendered content)
  -> awaits Future

user sees rendered markdown in web UI
  -> clicks "Accept" or types feedback and clicks "Send Feedback"
  -> POST /api/artifact-review -> resolves Future with feedback string

MCP handler receives resolved value
  -> clears AgentState.pending_tool
  -> returns "User feedback:\n{feedback}" as MCP tool result

if feedback == "Accept":
  LLM calls koan_complete_step -> phase advances
else:
  LLM revises artifact, calls koan_review_artifact again
  (loop repeats with fresh PendingInteraction)
```

See [artifact-review.md](./artifact-review.md) for the full protocol.

---

## Sequence Diagrams

### Scout flow (blocking interaction)

```
Driver                         Scout CLI              Web UI
  |                                |                     |
  |<--koan_request_scouts---------|                     |
  |  create Future                |                     |
  |  spawn scout processes------->|                     |
  |                               |--koan_complete_step->|
  |                               |<-step 1 guidance----|
  |                               |  (does work)        |
  |                               |--koan_complete_step->|
  |                               |<-"Phase complete."--|
  |  scout exits                  |                     |
  |  resolve Future               |                     |
  |--tool result (findings)------>|                     |
```

### User interaction flow (blocking)

```
Subagent                      Driver                    Web UI
  |                              |                        |
  |--koan_ask_question---------->|                        |
  |                              |  create Future         |
  |                              |--SSE "ask" event------>|
  |                              |                        | user sees form
  |                              |                        | user submits
  |                              |<-POST /api/answer------|
  |                              |  resolve Future        |
  |<-tool result (answer)--------|                        |
```
