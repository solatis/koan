# Koan Architecture

Koan is a deterministic workflow that spawns isolated LLM subagents to plan and
execute complex coding tasks. This document captures the design invariants,
principles, and pitfalls that govern the codebase.

**Spoke documents** cover subsystems in depth:

- [Subagents](./subagents.md) -- spawn lifecycle, boot protocol, step-first
  workflow, phase dispatch, permissions, model tiers
- [IPC](./ipc.md) -- HTTP MCP inter-process communication, blocking tool calls,
  scout spawning
- [Token Streaming](./token-streaming.md) -- runner stdout parsing, SSE delta path
- [State & Driver](./state.md) -- the driver/LLM boundary, JSON vs markdown
  ownership, epic and story state, routing rules
- [Projections](./projections.md) -- versioned event log, fold function,
  projection shape, SSE protocol, version-negotiated catch-up
- [Intake Loop](./intake-loop.md) -- confidence-gated investigation loop,
  non-linear step progression, prompt engineering principles
- [Epic Brief](./epic-brief.md) -- brief artifact, brief-writer subagent, downstream references
- [Artifact Review](./artifact-review.md) -- artifact review protocol, review loop, reusability

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
Tool returns:  Step 2 instructions (or "Phase complete.")
```

Three reinforcement mechanisms make this robust across model capability levels:

| Mechanism         | Where                                                                | Why                                                          |
| ----------------- | -------------------------------------------------------------------- | ------------------------------------------------------------ |
| **Primacy**       | Boot prompt is the LLM's very first message                          | First action = tool call, at the top of conversation history |
| **Recency**       | `format_step()` appends "WHEN DONE: Call koan_complete_step..." last | LLMs weight end-of-context instructions heavily              |
| **Muscle memory** | By step 2+ the LLM has called the tool N times                       | Pattern is locked in through repetition                      |

### 3. Driver determinism

The driver (`koan/driver.py`) is a deterministic state machine. It reads JSON
state files and exit codes, applies routing rules, and spawns the next subagent.
It never makes judgment calls, parses free-text output, or adapts to LLM
behavior.

**Routing priority** in the story loop:

1. `retry` status -> re-execute (retry takes precedence over new work)
2. `selected` status -> plan + execute
3. All stories `done` or `skipped` -> epic complete
4. None of the above -> error ("orchestrator may have exited without a routing decision")

### 4. Default-deny permissions

Every tool call passes through a permission fence (`check_permission()` in
`koan/lib/permissions.py`). Unknown roles are blocked. Unknown tools are
blocked. Planning roles can only write inside the epic directory.

The one accepted limitation: `READ_TOOLS` (bash, read, grep, glob, find, ls)
are always allowed because distinguishing "read bash" from "write bash" is
intractable at the permission layer. **Prompt engineering constrains intended
bash use; enforcement does not.**

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
[ProjectionStore: append to log, fold projection, broadcast to SSE subscribers]
     |
[Browser receives versioned SSE event, applies frontend fold]
```

### Concrete example: `koan_complete_step`

```
LLM calls koan_complete_step({ thoughts: "..." }) via MCP
  -> MCP endpoint checks permissions
  -> emits step_advance audit event (audit fold)
  -> audit fold: projection.step = 2, projection.step_name = "Decompose"
  -> write_state(audit projection) -> state.json
  -> push_event("agent_step_advanced", {step: 2, step_name: "Decompose"}, agent_id="abc")
  -> ProjectionStore appends event v=47, folds projection, broadcasts to SSE subscribers
  -> browser receives: event: agent_step_advanced / data: {"version": 47, "agent_id": "abc", ...}
  -> frontend fold: primaryAgent.step = 2, primaryAgent.stepName = "Decompose"
  -> returns step 2 instructions as MCP tool result
```

### Version-negotiated catch-up

The `/events` endpoint accepts `?since=N`. On first connect (`since=0`), the
server sends a `snapshot` SSE event containing the full materialized projection
at the current version. On reconnect (`since=N`), the server replays events
with version > N, then streams live events.

```
event: snapshot
data: {"version": 42, "state": { ...full projection... }}

event: agent_spawned
data: {"version": 43, "agent_id": "...", "role": "intake", ...}
```

This ensures the browser always has complete state after a page reload or
network drop, without requiring a full page reload or losing accumulated state
(activity log, notifications, streaming buffer).

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

### Don't add `scouting` as an epic phase

Scouts run inside the `koan_request_scouts` tool handler during
intake/decomposer/planner phases, not as a top-level driver phase. Adding
`scouting` to `EpicPhase` would imply a driver state that never exists,
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

Note: `stream_delta` events (the projection system's name for token deltas) DO
go through the projection fold, but the fold only appends to an in-memory
string — no disk I/O. The distinction is between the audit pipeline (disk
writes per event) and the projection fold (in-memory only).
