# Koan Architecture

Koan is a deterministic pipeline that spawns isolated LLM subagents to plan and
execute complex coding tasks. This document captures the design invariants,
principles, and pitfalls that govern the codebase.

**Spoke documents** cover subsystems in depth:

- [Subagents](./subagents.md) — spawn lifecycle, boot protocol, step-first
  workflow, phase dispatch, permissions, model tiers
- [IPC](./ipc.md) — file-based inter-process communication between parent and
  subagent, scout spawning, question routing
- [State & Driver](./state.md) — the driver/LLM boundary, JSON vs markdown
  ownership, epic and story state, routing rules
- [Intake Loop](./intake-loop.md) — confidence-gated investigation loop,
  non-linear step progression, prompt engineering principles

---

## Core Invariants

These are load-bearing rules. Violating any one of them breaks the system in
ways that are difficult to diagnose.

### 1. File boundary

LLMs write **markdown files only**. The driver maintains **JSON state files**
internally — no LLM ever reads or writes a `.json` file.

Tool code bridges both worlds: orchestrator tools write JSON state (for the
driver) and templated `status.md` (for LLMs). The driver reads JSON and exit
codes; it never parses markdown.

```
Orchestrator calls koan_complete_story(story_id)
  → tool code writes state.json + status.md
  → driver reads state.json to route next action
  → LLM reads status.md if it needs to reference the decision
```

**Why:** If an LLM writes JSON, schema drift and parse errors become runtime
failures in the deterministic driver. Markdown is forgiving; JSON is not.

### 2. Step-first workflow

Every subagent is a `pi -p` process. Once the LLM produces text without a tool
call, the process exits — there is no stdin to recover. The entire workflow
depends on the LLM calling `koan_complete_step` reliably.

**The first thing any subagent does is call `koan_complete_step`.** The spawn
prompt contains _only_ this directive. The tool returns step 1 instructions.
This establishes the calling pattern before the LLM sees complex instructions.

```
Boot prompt:  "You are a koan {role} agent. Call koan_complete_step to receive your instructions."
     ↓ LLM calls koan_complete_step (step 0 → 1 transition)
Tool returns:  Step 1 instructions (rich context, task details, guidance)
     ↓ LLM does work...
     ↓ LLM calls koan_complete_step
Tool returns:  Step 2 instructions (or "Phase complete.")
```

Three reinforcement mechanisms make this robust across model capability levels:

| Mechanism         | Where                                                               | Why                                                          |
| ----------------- | ------------------------------------------------------------------- | ------------------------------------------------------------ |
| **Primacy**       | Boot prompt is the LLM's very first message                         | First action = tool call, at the top of conversation history |
| **Recency**       | `formatStep()` appends "WHEN DONE: Call koan_complete_step..." last | LLMs weight end-of-context instructions heavily              |
| **Muscle memory** | By step 2+ the LLM has called the tool N times                      | Pattern is locked in through repetition                      |

### 3. Driver determinism

The driver (`driver.ts`) is a deterministic state machine. It reads JSON state
files and exit codes, applies routing rules, and spawns the next subagent. It
never makes judgment calls, parses free-text output, or adapts to LLM behavior.

**Routing priority** in the story loop:

1. `retry` status → re-execute (retry takes precedence over new work)
2. `selected` status → plan + execute
3. All stories `done` or `skipped` → epic complete
4. None of the above → error ("orchestrator may have exited without a routing decision")

### 4. Default-deny permissions

Every tool call in a subagent passes through a permission fence (`tool_call`
event handler in `BasePhase`). Unknown roles are blocked. Unknown tools are
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

This is not just tidiness — it is load-bearing. A previous design injected
step 1 guidance into the first user message (via a `context` event handler),
but that front-loaded complex instructions before the LLM had established the
`koan_complete_step` calling pattern. Weaker models (haiku) produced text
output and exited without entering the workflow. The `context` event handler
was deliberately removed; step guidance is now delivered exclusively through
`koan_complete_step` return values.

### 6. Directory-as-contract

The subagent directory is the **sole interface** between parent and child.
Everything a subagent needs — its task, its communication channel, its
observable state — lives in well-known files inside that directory.

Three JSON files, three lifecycles:

| File             | Writer                  | Reader                   | Lifecycle                                               |
| ---------------- | ----------------------- | ------------------------ | ------------------------------------------------------- |
| **`task.json`**  | Parent (before spawn)   | Child (once, at startup) | Write-once, never modified                              |
| **`state.json`** | Child (continuously)    | Parent (polling)         | Eagerly materialized audit projection                   |
| **`ipc.json`**   | Both (request/response) | Both (polling)           | Temporary — created per request, deleted after response |

The spawn command carries only the directory path. The child reads `task.json`
to discover its role, epic context, and task-specific parameters. No
structured configuration flows through CLI flags, environment variables, or
other process-level channels.

```
# Spawn interface: one koan flag, the rest is pi-level
pi -p -e {extensionPath} --koan-dir {subagentDir} [--model {model}] "{bootPrompt}"
```

**Why:** CLI flags are a flat namespace — they cause naming collisions (e.g.,
`--koan-role` for pipeline role vs `--koan-scout-role` for investigator
persona), cannot represent nested structure, are visible in process listings,
and are subject to `ARG_MAX` limits for large values like retry context.
Files are structured, inspectable (`cat task.json`), typed, and consistent
with how we already handle runtime communication (IPC) and observation (audit).

See [subagents.md § Task Manifest](./subagents.md#task-manifest) for the
`task.json` schema and spawn flow.

---

## Atomic Writes

All persistent writes (JSON state, IPC files, status.md, audit state.json)
use the same pattern: write to a `.tmp` file, then `fs.rename()` to the target.
This prevents partial reads during concurrent access.

```typescript
const tmp = path.join(dir, "file.tmp");
await fs.writeFile(tmp, content, "utf8");
await fs.rename(tmp, target);
```

This is not optional — the IPC responder, web server, and audit system all
poll files concurrently. A partial read of `ipc.json` or `state.json` would
cause silent data corruption or spurious errors.

---

## Tool Registration Constraint

All tools **must** be registered unconditionally at extension init, before
pi's `_buildRuntime()` snapshot. Tools registered after `_buildRuntime()` are
invisible to the LLM.

CLI flags are unavailable during init (`getFlag()` returns undefined before
`_buildRuntime()` sets flagValues), so conditional registration based on role
is impossible. Instead:

1. All tools register at init, reading from the mutable `RuntimeContext` at call time
2. `BasePhase.registerHandlers()` adds a `tool_call` event listener that checks permissions per-role at runtime
3. The `RuntimeContext` is populated later, during `before_agent_start`

This is the **mutable-ref pattern**: static registration, dynamic dispatch.

---

## Event-Sourced Audit

Each subagent maintains an append-only event log (`events.jsonl`) and an
eagerly-materialized projection (`state.json`). This is the observability
layer that drives the web dashboard.

```
audit event appended → fold(events) → state.json written atomically
web server polls state.json (50ms) → detects change → pushes SSE event
sse.js handler → Zustand store update → component re-render
```

### Rules

- **`fold()` is pure** — given the same event sequence, it must produce the same
  projection. No I/O, no randomness, no side effects inside `fold()`.
- **New event types require a fold handler.** Unknown events are silently ignored
  (forward compatibility), but a new event that is not folded contributes nothing
  to the projection and will not be visible to the web server or UI.
- **Projection is eagerly materialized.** It is written atomically after every
  `append()` call. The web server reads `state.json`, not `events.jsonl`. This
  keeps polling cheap (one file read) without needing to replay the log.
- **`append()` calls are serialized.** `EventLog` serializes appends via an
  internal promise chain. Concurrent callers (e.g., heartbeat timer and
  `tool_result` handler) enqueue without racing on the `.tmp.json` file.

### Adding new observable state

When adding a new piece of state that the UI should see, wire all five layers:

1. **Emit an audit event** — add a typed event and an `emit*()` helper in `lib/audit.ts`
2. **Update `fold()`** — handle the new event type to update the projection field
3. **Update the Projection type** — add the field to the `Projection` interface
4. **Web server polling** — read the new field from the cached projection in the 50ms polling callback and include it in the SSE payload
5. **Frontend** — add a handler in `sse.js` and a slice in `store.js`

All five layers must be present. Missing any one of them produces silent data
loss — the event is appended but never reaches the browser.

---

## SSE Event Lifecycle

State flows from LLM tool calls to the browser through a five-layer pipeline.
All layers must be wired for a new event type to be visible end-to-end.

```
[LLM calls tool]
     |
[tool mutates ctx + calls ctx.eventLog.emit*()] <- lib/audit.ts
     |
[fold() updates Projection -> state.json written atomically]
     |
[web server polls state.json every 50ms, detects change] <- web/server.ts
     |
[pushEvent(type, payload) -> SSE stream -> browser]
     |
[sse.js dispatches to named handler from store.js] <- web/js/sse.js
     |
[named handler calls useStore.setState()] <- web/js/store.js
     |
[Zustand component selector -> React re-render]
```

### Concrete example: `koan_set_confidence`

```
LLM calls koan_set_confidence({ level: "high" })
  → ctx.intakeConfidence = "high"
  → ctx.eventLog.emitConfidenceChange("high", 2)
      → append({ kind: "confidence_change", level: "high", iteration: 2 })
      → fold: projection.intakeConfidence = "high", projection.intakeIteration = 2
      → writeState(projection) → state.json
  → returns "Confidence set to high."

web server polling timer fires (50ms)
  → pollAgent(intake) → readProjection(dir) → intakeConfidence: "high"
  → agent.lastProjection = projection
  → intake sub-phase → builds IntakeProgressEvent { confidence: "high", iteration: 2, ... }
  → pushEvent("intake-progress", event) → SSE stream

browser receives "intake-progress" event
  → sse.js handler → useStore.setState({ intakeProgress: event })
  → confidence visualization component re-renders
```

### `sse.js` / `store.js` boundary

`sse.js` connects to the SSE stream and routes each event type to a named
handler. It does not import `useStore` or know the store's internal shape.

`store.js` owns the Zustand store shape and exports named handler functions
(one per SSE event type). Each handler maps a raw SSE payload to a store
state update.

Changing the store shape only requires updating `store.js`; `sse.js` is
stable across store shape changes.

### Replay on reconnect

The web server buffers the last value of every stateful SSE event type. On
reconnect, `replayState()` writes all buffered events to the new client. This
ensures the browser always has current state after a network drop, without
requiring a full page reload.

---

## Pitfalls

Lessons learned from previous failures. Check new changes against these.

### Don't put task content in spawn prompts

The boot prompt must be exactly one sentence: role identity + "call
koan_complete_step". Putting task content (file paths, instructions, context)
risks the LLM producing text output on the first turn and exiting. This has
happened with haiku-class models and is not recoverable.

### Don't inject step guidance via the `context` event

A `context` event handler that injects step 1 guidance into the first user
message was tried and removed. It creates the same problem as putting content
in the spawn prompt — the LLM sees complex instructions before establishing
the tool-calling pattern.

### Don't add `escalated` as a story status

Escalation is handled via `koan_ask_question` (IPC → web server → user
answers → IPC response). A separate `escalated` status was tried and created
a dead routing path — the driver had nowhere clean to send it without
duplicating the ask UI flow that IPC already handles.

### Don't add `scouting` as an epic phase

Scouts run inside the IPC responder during intake/decomposer/planner phases,
not as a top-level driver phase. Adding `scouting` to `EpicPhase` would imply
a driver state that never exists, creating dead code paths.

### Don't rely on file existence for scout success

Scout success is derived from the JSON projection (`readProjection()` →
`status === "completed"`), not from checking whether `findings.md` exists.
A scout can write a partial findings file and then crash — file existence is
not proof of completion.

### Don't crash on recoverable model-output parse errors

Fail-fast is scoped to **unrecoverable conditions**:

- invariant/contract violations (e.g., broken `task.json` bootstrap contract)
- unexpected states where there is no safe deterministic next action
- failures with no simple local recovery path

If a model emits malformed tool-call payloads (invalid JSON/args) or other
per-turn formatting errors, treat them as recoverable execution errors:
return a structured tool error (`tool_result` with `isError=true`) so the model
can self-correct and retry in the same subagent process.

Contrastive examples:

| Condition | Classification | Expected handling |
| --------- | -------------- | ----------------- |
| Malformed tool-call JSON/args from LLM | Recoverable | Return `tool_result` error (`isError=true`), keep process alive |
| Tool argument schema validation failure | Recoverable | Return validation error as `tool_result`, let model retry |
| Disallowed/unknown tool call | Recoverable | Return blocked tool error, continue turn |
| Missing/malformed `task.json` at subagent startup | Unrecoverable | Fail fast (bootstrap contract broken) |
| Impossible phase routing / internal invariant breach | Unrecoverable | Fail fast |
| Unexpected runtime state with no clear deterministic recovery | Unrecoverable | Fail fast |

Crashing the process for recoverable model-output errors converts a local retry
loop into a pipeline-level failure and should be avoided.

### Don't write state.json from outside state.ts / tool code

The state module (`epic/state.ts`) and orchestrator tools are the only
writers of JSON state. `status.md` writes belong exclusively in
`tools/orchestrator.ts`. Mixing these responsibilities violates the file
boundary invariant.

### Don't call koan_complete_step in the tool description eagerly

The tool description says "DO NOT call this tool until the step instructions
explicitly tell you to." Without this guard, aggressive models call
`koan_complete_step` immediately after receiving step guidance, skipping
the actual work.

### Don't assume bash is restricted per role

`bash` is in `READ_TOOLS` and always allowed. The permission layer cannot
distinguish a read-bash from a write-bash. Prompt engineering is the only
constraint. Do not assume bash calls are blocked for planning roles.

### Don't rely on prompt instructions alone to restrict step behavior

**The pattern: prompt expresses intent; mechanical gate catches non-compliance.
Neither alone is sufficient.**

- **Prompt alone** — the LLM can ignore it. The original 3-step intake design
  told the LLM not to scout in step 1; it frontloaded all work into step 1
  anyway, producing duplicate scout requests in later steps.
- **Gate alone** — the LLM receives a cryptic "blocked" error with no context.
  It cannot fix the problem if it does not know what it did wrong.

Three enforcement mechanisms are available — use the appropriate one for the
constraint:

| Mechanism                                | What it enforces                           | How                                                           |
| ---------------------------------------- | ------------------------------------------ | ------------------------------------------------------------- |
| **Permission fence** (`checkPermission`) | Which tools a role (or step) can use       | Block at `tool_call` event; LLM sees a rejection message      |
| **`validateStepCompletion()`**           | Required pre-calls before step advancement | Block `koan_complete_step`; LLM sees an error and must comply |
| **Tool description**                     | Soft guidance on when to call              | Cannot be enforced; LLM can ignore it                         |

Any behavioral constraint that matters for correctness needs **both** a prompt
instruction (so the LLM knows what to do) and a mechanical gate (so
non-compliance is caught and corrected, not silently propagated).

See [intake-loop.md § Step-Aware Permission Gating](./intake-loop.md#step-aware-permission-gating).

### Don't give a step multiple cognitive goals

Each step should have exactly one cognitive goal. Grouping multiple goals into
a single step ("do A, then B, then C") enables **simulated refinement**: the
LLM artificially downgrades its output for A to manufacture visible improvement
in C. When all three goals are in one step, the model can pre-plan the
"improvement" because it already knows C is coming.

Separate `koan_complete_step` calls enforce genuinely isolated reasoning: the
LLM must complete each goal before it sees the next goal's instructions. There
is no opportunity to sandbag — the next step's prompt has not arrived yet.

This is why the intake phase has three loop steps (Scout / Deliberate / Reflect)
rather than a single monolithic "investigate" step. The scout phase follows the
same principle (orient → investigate → verify → report — four distinct goals,
four distinct steps).

When designing a new phase, each step should answer: "What is the single thing
this step accomplishes?" If the answer requires "and then", split the step.

See [intake-loop.md § Prompt Chaining over Stepwise](./intake-loop.md#prompt-engineering-principles)
for the detailed rationale.

### Don't parse free-text for loop control decisions

Confidence (the gate that controls the intake loop) is a structured enum
value set via a dedicated tool call, not a sentiment extracted from the LLM's
`thoughts` text. The driver determinism invariant prohibits parsing free-text
for routing decisions. Any loop gate must flow through a typed tool parameter
and a structured context field.

### Don't put side effects in getNextStep()

`getNextStep()` must be a pure query — it returns the next step number and
nothing else. Putting state mutations, counter increments, or event emission
inside `getNextStep()` violates this contract and makes the method unsafe to
reason about (e.g., a test that calls `getNextStep()` to inspect the decision
should not trigger side effects).

Side effects that accompany a loop-back belong in `onLoopBack()`, which
`BasePhase` calls after detecting a backward transition:

```
BAD:  getNextStep(4) { this.iteration++; this.ctx.confidence = null; return 2; }
GOOD: getNextStep(4) { return 2; }
      onLoopBack(4, 2) { this.iteration++; this.ctx.confidence = null; }
```

The `onLoopBack()` hook is async and properly awaited, ensuring event
emission (`emitIterationStart`) is correctly sequenced in `events.jsonl`.

### Don't pass structured data through CLI flags

If information is needed by a subagent, write it to `task.json` in the
subagent directory before spawning. CLI flags are for bootstrap only (locating
the directory). Structured data in flags creates flat-namespace collisions,
size limits, and an uninspectable interface. The directory-as-contract
invariant exists specifically to prevent this.
