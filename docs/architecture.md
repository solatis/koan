# Koan Architecture

Koan coordinates coding task planning and execution through a single long-lived
orchestrator LLM process that runs the entire workflow in one continuous session. This document captures the design invariants,
principles, and pitfalls that govern the codebase.

**Spoke documents** cover subsystems in depth:

- [Subagents](./subagents.md) -- spawn lifecycle, boot protocol, step-first
  workflow, phase dispatch, permissions, model tiers
- [IPC](./ipc.md) -- HTTP MCP inter-process communication, blocking tool calls,
  scout spawning, koan_yield blocking, chat message delivery
- [Token Streaming](./token-streaming.md) -- runner stdout parsing, SSE delta path
- [State & Driver](./state.md) -- the driver/LLM boundary, JSON vs markdown
  ownership, run state, orchestrator state
- [Projections](./projections.md) -- versioned event log, pure fold, JSON Patch
  protocol, projection model, camelCase wire format
- [Intake Loop](./intake-loop.md) -- two-step intake design, prompt engineering principles

---

## Core Invariants

These are load-bearing rules. Violating any one of them breaks the system in
ways that are difficult to diagnose.

### 1. File boundary

LLMs write **markdown files only**. The driver maintains **JSON state files**
internally -- no LLM ever reads or writes a `.json` file.

Tool code bridges both worlds: orchestrator tools write JSON state (for the
driver) and templated `status.md` (for LLMs). The driver reads JSON and exit
codes; it never parses markdown.

```
Orchestrator calls koan_complete_story(story_id)
  -> tool code writes state.json + status.md
  -> driver reads state.json to route next action
  -> LLM reads status.md if it needs to reference the decision
```

**Why:** If an LLM writes JSON, schema drift and parse errors become runtime
failures in the deterministic driver. Markdown is forgiving; JSON is not.

### 2. Step-first workflow

Every subagent is a CLI process (`claude`, `codex`, or `gemini`) that connects
to the driver's HTTP MCP endpoint at `http://localhost:{port}/mcp?agent_id={id}`.
The subagent receives tools via MCP and calls them over HTTP. Once the LLM
produces text without a tool call, the process may exit -- there is no stdin to
recover. The entire workflow depends on the LLM calling `koan_complete_step`
reliably.

**The first thing any subagent does is call `koan_complete_step`.** The spawn
prompt contains _only_ this directive. The tool returns step 1 instructions.
This establishes the calling pattern before the LLM sees complex instructions.

```
Boot prompt:  "You are a koan {role} agent. Call koan_complete_step to receive your instructions."
     | LLM calls koan_complete_step (step 0 -> 1 transition)
Tool returns:  Step 1 instructions (rich context, task details, guidance)
     | LLM does work...
     | LLM calls koan_complete_step
Tool returns:  Step 2 instructions (or "Phase complete. Call koan_yield.")
```

Three reinforcement mechanisms make this robust across model capability levels:

| Mechanism         | Where                                                                | Why                                                          |
| ----------------- | -------------------------------------------------------------------- | ------------------------------------------------------------ |
| **Primacy**       | Boot prompt is the LLM's very first message                          | First action = tool call, at the top of conversation history |
| **Recency**       | `format_step()` appends "WHEN DONE: Call koan_complete_step..." last | LLMs weight end-of-context instructions heavily              |
| **Muscle memory** | By step 2+ the LLM has called the tool N times                       | Pattern is locked in through repetition                      |

#### Phase boundaries and koan_yield

When a phase's final step completes, `koan_complete_step` returns a **non-blocking**
response (`format_phase_complete`) that tells the orchestrator to summarize its
work and call `koan_yield`. The orchestrator then generates a summary and calls
`koan_yield` with structured suggestions.

`koan_yield` is the **generic conversation primitive** — it blocks the
orchestrator process until the user sends a message, then returns that message
as the tool result. The orchestrator can call `koan_yield` repeatedly for
multi-turn conversation before committing a phase transition.

```
koan_complete_step (last step)
  -> returns: "Phase complete. Summarize and call koan_yield."
     | LLM writes summary, constructs suggestions
     | LLM calls koan_yield(suggestions=[{id, label, command}, ...])
Tool blocks until user sends message
     | user types in chat or clicks a suggestion pill
Tool returns:  user message text
     | LLM responds conversationally
     | LLM calls koan_yield again (or calls koan_set_phase if direction confirmed)
...
     | LLM calls koan_set_phase("plan-spec")   -- or "done" to end the workflow
```

`koan_yield` is phase-agnostic — it knows nothing about workflow structure.
Suggestions are constructed by the orchestrator at each yield point; the UI
renders them as clickable pills that pre-fill the chat input.

#### Ending the workflow

Passing `"done"` to `koan_set_phase` acts as a tombstone:

```
koan_set_phase("done")
  -> emits workflow_completed
  -> sets AppState.workflow_done = True
  -> returns "Workflow complete. Call koan_complete_step to finish."
     | LLM calls koan_complete_step
Tool returns:  "All phases complete. You may now exit."
     | LLM exits (no more tool calls)
```

`"done"` is detected before the normal `is_valid_transition()` check and is
not a member of any workflow's `available_phases`. The driver treats the
orchestrator's process exit as the actual workflow end signal.

### 3. Driver determinism (partially relaxed)

The driver (`koan/driver.py`) spawns the orchestrator and awaits its exit.
Phase routing is driven by the orchestrator via `koan_set_phase` rather than
the driver's routing loop. The driver still validates every transition
(`is_valid_transition()` in the tool handler), updates `run-state.json`
atomically, emits projection events, and enforces the permission fence. It
never parses free text or makes judgment calls. All routing decisions flow
through typed tool parameters.

`is_valid_transition(workflow, from_phase, to_phase)` validates that `to_phase`
is a member of the active workflow's `available_phases` and is not equal to
`from_phase`. The special value `"done"` bypasses this check entirely. Any
real phase in the workflow is reachable from any other — suggested transitions
guide the orchestrator's default recommendations at phase boundaries, but the
user can request any available phase. Invalid phase strings raise `ToolError`.

### 4. Default-deny permissions

Two enforcement layers restrict what tools each agent can use:

1. **CLI tool whitelist** (`CLAUDE_TOOL_WHITELISTS` in `subagent.py`) --
   controls which Claude Code built-in tools exist in the model's context.
   Unlisted tools are not presented to the model; it cannot call them.
2. **MCP permission fence** (`check_permission()` in `permissions.py`) --
   gates koan MCP tool calls per role and phase. Unknown roles and tools are
   blocked. Planning roles can only write inside the run directory.

Agents should not have access to tools they are never intended to need.
Restricting the tool vocabulary prevents the model from drifting toward
irrelevant capabilities (autonomous scheduling, subagent spawning, plan mode)
that compete with koan's step-first workflow.

The one accepted limitation: `READ_TOOLS` (bash, read, grep, glob, find, ls)
are always allowed because distinguishing "read bash" from "write bash" is
intractable at the permission layer. **Prompt engineering constrains intended
bash use; enforcement does not.**

See [subagents.md -- Permissions](./subagents.md#permissions) for per-role
whitelists and the full MCP permission matrix.

### 5. Need-to-know prompts

Each subagent receives only the minimum context for its task:

- The **boot prompt** is one sentence (role identity + "call koan_complete_step")
- The **system prompt** establishes role identity and rules, but no task details
- **Task details** arrive via step 1 guidance (returned by the first tool call)

This is not just tidiness -- it is load-bearing. Injecting step 1 guidance
into the first user message front-loads complex instructions before the LLM has
established the `koan_complete_step` calling pattern. Weaker models produce
text output and exit without entering the workflow. Step guidance is delivered
exclusively through `koan_complete_step` return values.

**Phase guidance injection.** Each workflow provides a `phase_guidance` dict
mapping phase names to scope-framing text. When the orchestrator calls
`koan_set_phase(phase)`, the workflow's guidance for that phase is stored in
`PhaseContext.phase_instructions`. The step 1 response renders this injection
at the top of the guidance, before procedural instructions, so scope framing
reaches the LLM before it reads task details.

The injection contract every `phase_guidance` entry must cover:

| Section                   | Purpose                                                 |
| ------------------------- | ------------------------------------------------------- |
| **Scope**                 | What kind of task this workflow targets                 |
| **Downstream consumer**   | What phase reads the output, what detail level it needs |
| **Investigation posture** | Direct reading vs. scouts, typical scout count          |
| **Question posture**      | How aggressively to ask, typical round count            |
| **User override**         | Always present, always last: "follow their lead"        |

### 6. Directory-as-contract

The subagent directory is the **sole interface** between parent and child.
Everything a subagent needs -- its task, its observable state -- lives in
well-known files inside that directory.

Two JSON files and an MCP URL:

| File               | Writer                    | Reader                   | Lifecycle                                   |
| ------------------ | ------------------------- | ------------------------ | ------------------------------------------- |
| **`task.json`**    | Parent (before spawn)     | Parent (at registration) | Write-once, never modified                  |
| **`state.json`**   | Parent (audit projection) | Available for debugging  | Eagerly materialized after each audit event |
| **`events.jsonl`** | Parent (audit log)        | Available for replay     | Append-only event log                       |

The `task.json` includes an `mcp_url` field pointing at
`http://localhost:{port}/mcp?agent_id={id}`. The child reads this to discover
its MCP endpoint. No structured configuration flows through CLI flags,
environment variables, or other process-level channels.

**Why:** CLI flags are a flat namespace -- they cause naming collisions, cannot
represent nested structure, are visible in process listings, and are subject to
`ARG_MAX` limits for large values like retry context. Files are structured,
inspectable (`cat task.json`), typed, and consistent with how we handle
observation (audit).

See [subagents.md -- Task Manifest](./subagents.md#task-manifest) for the
`task.json` schema and spawn flow.

### 7. Server-authoritative projection

The fold runs only in Python. The frontend applies server-computed JSON Patches
mechanically -- it has no fold logic, no event interpretation, and no business
rules. When the frontend's view of state differs from the backend's, the bug is
in the fold or the patch computation -- not in the frontend.

```
push_event() -> fold() -> to_wire() -> make_patch() -> broadcast to subscribers
                                                         |
                                              Browser receives patch,
                                              applies applyPatch(store, patch)
```

**Why:** Maintaining two fold implementations (Python + TypeScript) requires
disciplinary synchronization. Any divergence produces subtle display bugs that
are hard to trace. JSON Patch makes correctness structural: one fold, one
source of truth, mechanical application on the client.

---

## Workflow System

### Workflow definitions

A `Workflow` defines the set of phases available for a run, the initial phase,
and suggested transitions between phases. Two workflows are defined in
`koan/lib/workflows.py`:

**plan** — intake → plan-spec → plan-review → execute

| Phase         | Role                   | Steps                           | Artifact                  |
| ------------- | ---------------------- | ------------------------------- | ------------------------- |
| `intake`      | Requirement gathering  | 3 (Gather → Deepen → Summarize) | Chat summary only         |
| `plan-spec`   | Technical planning     | 2 (Analyze → Write)             | `plan.md`                 |
| `plan-review` | Quality review         | 2 (Read → Evaluate)             | Chat report only          |
| `execute`     | Implementation handoff | 2 (Compose → Request)           | Code changes via executor |

**milestones** — stub workflow; runs intake only, then yields with a single
"done" suggestion.

### Workflow selection

The user selects a workflow at run start. The selection is stored in
`AppState.workflow` and used throughout the run for:

- Phase transition validation (`is_valid_transition`)
- Phase boundary suggestions (`get_suggested_phases`)
- Phase guidance injection (`workflow.phase_guidance[phase]`)

### Phase transition validation

```python
def is_valid_transition(workflow: Workflow, from_phase: str, to_phase: str) -> bool:
    return (
        to_phase in workflow.available_phases
        and to_phase != from_phase
    )
```

The special value `"done"` bypasses this function — it is handled before the
validation call in `koan_set_phase`. For real phases, suggested transitions
from `workflow.suggested_transitions[current_phase]` guide the orchestrator's
default `koan_yield` suggestions. These are recommendations, not constraints —
the user can request any phase in `workflow.available_phases`.

---

## Atomic Writes

All persistent writes (JSON state, status.md, audit state.json) use the same
pattern: write to a `.tmp` file, then `os.rename()` to the target. This
prevents partial reads during concurrent access.

The `koan/audit/event_log.py` module uses this pattern for all state writes.
This is not optional -- the web server and audit system access files
concurrently. A partial read of `state.json` would cause silent data
corruption or spurious errors.

---

## Tool Registration

Tools are registered as `fastmcp` tool handlers in `koan/web/mcp_endpoint.py`.
When a tool call arrives via HTTP, the MCP endpoint:

1. Extracts `agent_id` from the URL query parameter
2. Looks up the agent's state (role, step counter, permissions) in the in-process registry
3. Calls `check_permission()` from `koan/lib/permissions.py`
4. If allowed, dispatches to the tool handler
5. Returns the result as the MCP tool response

Tools are HTTP handlers; permissions are checked per-call.

---

## Two Fold Systems

Koan uses two independent fold systems that share the same structural pattern
(pure fold function, append-only log) but serve different purposes:

### Audit fold (`koan/audit/fold.py`)

Tracks the internal execution of each individual subagent. Input: per-subagent
audit events written to `events.jsonl`. Output: per-subagent `Projection`
materialized to `state.json`. One fold instance per running subagent.
Consumed by debugging and post-mortem analysis.

### Projection fold (`koan/projections.py`)

Tracks the complete frontend-visible state of the entire workflow run. Input:
workflow-level projection events emitted by `ProjectionStore.push_event()`.
Output: a single in-memory `Projection` covering all agents, run state, and
UI interactions. Consumed by the browser frontend via SSE.

When adding new observable state, decide which system it belongs to:

- State visible only in logs/debugging → audit fold
- State visible in the browser UI → projection fold

See [projections.md](./projections.md) for the full event model, fold
specification, and SSE protocol.

### Rules for both folds

- **`fold()` is pure** -- given the same event sequence, it must produce the same
  projection. No I/O, no randomness, no side effects inside `fold()`.
- **New event types require a fold handler.** Unknown events are silently ignored
  (forward compatibility), but a new event that is not folded contributes nothing
  to the projection.
- **Projection is eagerly materialized.** Updated after every `push_event()`.
- **Events are facts, not snapshots.** Events record what happened; the fold
  derives current state from those facts. Do not store derived state as an event.

---

## SSE Event Lifecycle

State flows from LLM tool calls to the browser through the projection system.

```
[LLM calls tool via HTTP MCP]
     |
[MCP endpoint handles call, emits audit event]
     |
[fold() updates audit projection, state.json written atomically]
     |
[push_event() called with workflow-level event]
     |
[ProjectionStore: fold projection, compute JSON Patch, broadcast to subscribers]
     |
[Browser receives patch, applies applyPatch(store, patch) — no interpretation]
```

### Concrete example: `koan_yield`

```
LLM calls koan_yield({ suggestions: [{id:"plan-spec", label:"Write plan", command:"..."}] })
  -> MCP endpoint checks permissions
  -> push_event("yield_started", {suggestions: [...]}, agent_id="abc")
  -> fold: appends YieldEntry to agent conversation, sets run.active_yield
  -> patch: [{op:"add", path:"/run/agents/abc/conversation/entries/-", value:{type:"yield",...}},
             {op:"replace", path:"/run/activeYield", value:{suggestions:[...]}}]
  -> broadcast patch to SSE subscribers
  -> browser renders suggestion pills in activity feed and above chat input
  -> tool handler creates asyncio.Future, stores in app_state.yield_future, awaits it
  -> (HTTP connection held open)

user clicks suggestion pill "Write plan" in the browser
  -> YieldCard.onClick -> setChatDraft("write dashboard redesign implementation plan")
  -> FeedbackInput useEffect fires -> textarea pre-filled
  -> user reviews, presses Enter
  -> POST /api/chat { message: "write dashboard redesign implementation plan" }
  -> api_chat: yield_future is set -> append to user_message_buffer -> set_result(True)
  -> yield_future resolves
  -> drain_user_messages -> "write dashboard redesign implementation plan"
  -> returns message text as MCP tool result
LLM receives user's message, responds, calls koan_set_phase("plan-spec")
```

### Snapshot on reconnect

The `/events` endpoint accepts `?since=N`. If `since` matches the server's
current version, the client is up to date and only live patches are streamed.
Otherwise — on first connect, page reload, connection drop, or server restart
— a fresh snapshot is sent, then live patches follow.

```
event: snapshot
data: {"version": 42, "state": { ...full projection in camelCase... }}

event: patch
data: {"type": "patch", "version": 43, "patch": [{...}, ...]}
```

All reconnect scenarios are handled identically. The client does not distinguish
between a brief disconnect and a server restart — it receives a snapshot and
renders from it.

---

## Pitfalls

Known invariant violations and their consequences. Check new changes against these.

### Don't put task content in spawn prompts

The boot prompt must be exactly one sentence: role identity + "call
koan_complete_step". Putting task content (file paths, instructions, context)
risks the LLM producing text output on the first turn and exiting. This has
happened with haiku-class models and is not recoverable.

### Don't add `escalated` as a story status

Escalation flows through `koan_ask_question` (MCP tool call -> web UI -> user
answers -> MCP response). A separate `escalated` status creates a dead routing
path -- the driver has nowhere clean to send it without duplicating the ask UI
flow.

### Don't add `scouting` as a workflow phase

Scouts run inside the `koan_request_scouts` tool handler during
intake/planning phases, not as a top-level driver phase. Adding
`scouting` to `WorkflowPhase` would imply a driver state that never exists,
creating dead code paths.

### Don't rely on file existence for scout success

Scout success is derived from the JSON projection (`status === "completed"`),
not from checking whether `findings.md` exists. A scout can write a partial
findings file and then crash -- file existence is not proof of completion.

### Don't crash on recoverable model-output parse errors

Fail-fast is scoped to **unrecoverable conditions**:

- invariant/contract violations (e.g., broken `task.json` bootstrap contract)
- unexpected states where there is no safe deterministic next action
- failures with no simple local recovery path

If a model emits malformed tool-call payloads (invalid JSON/args) or other
per-turn formatting errors, treat them as recoverable execution errors:
return a structured tool error so the model can self-correct and retry in
the same subagent process.

| Condition                                                     | Classification | Expected handling                        |
| ------------------------------------------------------------- | -------------- | ---------------------------------------- |
| Malformed tool-call JSON/args from LLM                        | Recoverable    | Return tool error, keep process alive    |
| Tool argument schema validation failure                       | Recoverable    | Return validation error, let model retry |
| Disallowed/unknown tool call                                  | Recoverable    | Return blocked tool error, continue turn |
| Missing/malformed `task.json` at subagent startup             | Unrecoverable  | Fail fast (bootstrap contract broken)    |
| Impossible phase routing / internal invariant breach          | Unrecoverable  | Fail fast                                |
| Unexpected runtime state with no clear deterministic recovery | Unrecoverable  | Fail fast                                |

### Don't assume bash is restricted per role

`bash` is in `READ_TOOLS` and always allowed. The permission layer cannot
distinguish a read-bash from a write-bash. Prompt engineering is the only
constraint. Do not assume bash calls are blocked for planning roles.

### Don't rely on prompt instructions alone to restrict step behavior

**The pattern: prompt expresses intent; mechanical gate catches non-compliance.
Neither alone is sufficient.**

- **Prompt alone** -- the LLM can ignore it.
- **Gate alone** -- the LLM receives a cryptic "blocked" error with no context.

Three enforcement mechanisms are available -- use the appropriate one for the
constraint:

| Mechanism                                 | What it enforces                           | How                                                           |
| ----------------------------------------- | ------------------------------------------ | ------------------------------------------------------------- |
| **Permission fence** (`check_permission`) | Which tools a role (or step) can use       | Block at MCP endpoint; LLM sees a rejection message           |
| **`validate_step_completion()`**          | Required pre-calls before step advancement | Block `koan_complete_step`; LLM sees an error and must comply |
| **Tool description**                      | Soft guidance on when to call              | Cannot be enforced; LLM can ignore it                         |

Any behavioral constraint that matters for correctness needs **both** a prompt
instruction (so the LLM knows what to do) and a mechanical gate (so
non-compliance is caught and corrected, not silently propagated).

See [intake-loop.md -- Step-Aware Permission Gating](./intake-loop.md#step-aware-permission-gating).

### Don't give a step multiple cognitive goals

Each step should have exactly one cognitive goal. Grouping multiple goals into
a single step ("do A, then B, then C") enables **simulated refinement**: the
LLM artificially downgrades its output for A to manufacture visible improvement
in C. Separate `koan_complete_step` calls enforce genuinely isolated reasoning.

When designing a new phase, each step should answer: "What is the single thing
this step accomplishes?" If the answer requires "and then", split the step.

See [intake-loop.md -- Prompt Chaining over Stepwise](./intake-loop.md#prompt-engineering-principles)
for the detailed rationale.

### Don't parse free-text for loop control decisions

Confidence (the gate that controls the intake loop) is a structured enum
value set via a dedicated tool call, not a sentiment extracted from the LLM's
`thoughts` text. The driver determinism invariant prohibits parsing free-text
for routing decisions. Any loop gate must flow through a typed tool parameter
and a structured context field.

### Don't put side effects in get_next_step()

`get_next_step()` must be a pure query -- it returns the next step number and
nothing else. Putting state mutations, counter increments, or event emission
inside `get_next_step()` violates this contract.

Side effects that accompany a loop-back belong in `on_loop_back()`:

```
BAD:  get_next_step(4) { self.iteration += 1; self.confidence = None; return 2 }
GOOD: get_next_step(4) { return 2 }
      on_loop_back(4, 2) { self.iteration += 1; self.confidence = None }
```

### Don't pass structured data through CLI flags

If information is needed by a subagent, write it to `task.json` in the
subagent directory before spawning. CLI flags are for bootstrap only. The
directory-as-contract invariant exists specifically to prevent this.

### Don't store derived state as an event

Events record facts — things that happened. Derived state belongs in the fold
function, not in the event log.

**Bad:** Emitting a `subagent_idle` event to signal "no agent is running."
"No agent" is derived from `agent_exited`, not a fact in itself. Storing it as
an event conflates the log with the projection.

**Good:** Emitting `agent_exited`. The fold derives `primary_agent = None`.

### Don't put high-frequency ephemeral data through the audit pipeline

Token deltas and similar high-frequency signals arrive at hundreds of events
per second. Routing them through the audit pipeline would mean hundreds of
append + fold + atomic-write cycles per second for data that has no persistence
value. The runner stdout parsing path exists for exactly this case. See
[token-streaming.md](./token-streaming.md).

Note: `stream_delta` events (token deltas) DO go through the projection fold,
but the fold only updates an in-memory string (`pending_text` on the agent's
conversation) — no disk I/O. The distinction is between the audit pipeline
(disk writes per event) and the projection fold (in-memory only).
