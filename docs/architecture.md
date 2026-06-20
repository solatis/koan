# Koan Architecture

Koan coordinates coding task planning and execution through an in-process
orchestrator LLM agent that runs the entire workflow in one continuous session.
This document captures the design invariants, principles, and pitfalls that
govern the codebase.

**Spoke documents** cover subsystems in depth:

- [Subagents](./subagents.md) -- spawn lifecycle, boot protocol, step-first
  workflow, phase dispatch, permissions, model tiers
- [IPC](./ipc.md) -- in-process tool calls, blocking interactions, scout
  spawning, terminal-text hand-back, chat message delivery
- [Initiative](./initiative.md) -- initiative workflow contract, band hierarchy,
  architectural acceptance pattern
- [Token Streaming](./token-streaming.md) -- in-process StreamEvent delta path, SSE bridge
- [State & Driver](./state.md) -- the driver/LLM boundary, JSON vs markdown
  ownership, run state, orchestrator state
- [Projections](./projections.md) -- versioned event log, pure fold, JSON Patch
  protocol, projection model, camelCase wire format
- [Intake Loop](./intake-loop.md) -- two-step intake design, prompt engineering principles
- [Memory System](./memory-system.md) -- project memory, curation, and the RAG injection wired into phase transitions
- [Milestones](./milestones.md) -- milestone soundness criteria, sizing heuristics, grounding requirements, cross-milestone learning
- [Workflow Phases](./workflow-phases.md) -- phase taxonomy across all workflows,
  producer-validator pairing, re-entry shapes

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
Orchestrator calls koan_set_phase("execute")
  -> tool code writes run-state.json (JSON, for driver)
  -> driver reads run-state.json to validate and record the transition
  -> LLM receives the tool result (markdown text) as confirmation
```

**Why:** If an LLM writes JSON, schema drift and parse errors become runtime
failures in the deterministic driver. Markdown is forgiving; JSON is not.

### 2. Step-first workflow

Every subagent is an asyncio task inside the single backend process. Tools are
in-process `FunctionToolset`s composed per (role, phase) by
`koan/tools/tool_policy.py:compose_toolset`. There is no subprocess, no CLI
binary, and no HTTP transport.

**Step 1 guidance is injected as the first turn prompt.** `run_agent_loop`
(in `koan/agents/loop.py`) bootstraps each agent by calling
`_step_phase_handshake_core` (prepending the phase `SYSTEM_PROMPT`) and passing
the result as the first user-turn prompt. A **turn-outcome resolver**
(`resolve_turn_outcome`) runs at each end-of-turn (after any turn that ends in
terminal text with no outstanding tool calls):

```
Loop injects step 1 guidance as first turn prompt
     | Agent does work, calls tools as needed
     | Agent ends turn in terminal text (no outstanding tool call)
Resolver fires:
  validate_step_completion(step)   [pre-condition check -- no-op in all phases today]
  next_step = get_next_step(step)  [pure: decides where to go]
  - gate fails        -> re-inject the same step
  - more steps remain -> inject next step guidance, resume
  - steps exhausted, primary agent -> hand back to user
  - steps exhausted, non-primary   -> terminate
```

Bootstrap success is `AgentState.first_turn_completed`, set when the first
turn reaches the `End` node. A failure raised before that point is classified
as `bootstrap_failure`.

#### Phase boundaries

Each phase module's final step instructs the orchestrator (via `step_guidance`)
to either auto-advance or hand back to the user:

- **Auto-advance**: call `koan_set_phase("next-phase")` directly when
  `PhaseBinding.next_phase` is bound (no user input needed).
- **Hand back**: call `koan_suggest_next(suggestions=[...])` to record the
  suggested options, then end the turn in terminal text. The loop surfaces the
  text and suggestions and parks awaiting the user.

See `docs/guided-transitions.md` for per-workflow transition tables and
override discipline.

The hand-back is a terminal-text turn -- the orchestrator ends its turn with
assistant text. The loop parks and awaits the next user message. The user's
reply resumes the loop as the next turn's prompt. The orchestrator then either
continues the conversation or calls `koan_set_phase` to commit the transition.

#### Ending the workflow

Passing `"done"` to `koan_set_phase` acts as a tombstone:

```
koan_set_phase("done")
  -> emits workflow_completed
  -> sets AppState.workflow_done = True
  -> the loop terminates on the next turn boundary
```

`"done"` is detected before the normal `is_valid_transition()` check and is
not a member of any workflow's `available_phases`. The driver treats the
asyncio task's completion as the actual workflow end signal.

### 3. Driver determinism (partially relaxed)

The driver (`koan/driver.py`) spawns the orchestrator asyncio task and awaits
its completion. Phase routing is driven by the orchestrator via `koan_set_phase`
rather than the driver's routing loop. The driver still validates every
transition (`is_valid_transition()` in the tool handler), updates `run-state.json`
atomically, and emits projection events. It never parses free text or makes
judgment calls. All routing decisions flow through typed tool parameters.

`is_valid_transition(workflow, from_phase, to_phase)` validates that `to_phase`
is a member of the active workflow's `available_phases` and is not equal to
`from_phase`. The special value `"done"` bypasses this check entirely. Any
real phase in the workflow is reachable from any other — suggested transitions
guide the orchestrator's default recommendations at phase boundaries, but the
user can request any available phase. Invalid phase strings raise `ToolError`.

### 4. Default-deny permissions

Capability restriction is **construction-time**, not call-time.
`compose_toolset(policy, role, phase)` in `koan/tools/tool_policy.py` builds
the allowed tool vocabulary once per (role, phase) before the agent's loop
starts. Disallowed tools never enter the model's context; the model cannot
call what it cannot see. The allowlist tables (`ROLE_PERMISSIONS` and the
universal read/memory sets) live in `tool_policy.py` as the single source of
truth.

Agents should not have access to tools they are never intended to need.
Restricting the tool vocabulary prevents the model from drifting toward
irrelevant capabilities (autonomous scheduling, subagent spawning, plan mode)
that compete with koan's step-first workflow.

The one accepted limitation: `READ_TOOLS` (bash, read, grep, glob, find, ls)
are always composed into every role because distinguishing "read bash" from
"write bash" is intractable at the vocabulary layer. **Prompt engineering
constrains intended bash use; vocabulary restriction does not.**

See [subagents.md -- Permissions](./subagents.md#permissions) for per-role
vocabulary tables.

### 5. Need-to-know prompts

Each subagent receives only the minimum context for its task:

- There is no boot prompt. The loop injects step 1 guidance as the first turn.
- The **system prompt** establishes role identity and rules, but no task details.
  It is prepended to the step 1 guidance at the top of the first turn prompt.
- **Task details** arrive via step 1 guidance, injected by `run_agent_loop`
  via `_step_phase_handshake_core` before the first model request.

This is not just tidiness -- it is load-bearing. Injecting all of step 1
guidance into the first turn front-loads complex instructions before the agent
has established any tool-calling pattern, which is why step 1 must have a
single clear cognitive goal: orient and do one thing, then end the turn.
Step guidance is delivered exclusively through the loop's turn-prompt injection.

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

**Memory injection.** At step 1 of every orchestrator phase, the
`_step_phase_handshake` response may include a `## Relevant memory`
block of top-5 memory entries retrieved by a per-phase static directive.
The mechanism is described in [memory-system.md](./memory-system.md);
the directive for each phase lives on its `PhaseBinding.retrieval_directive`
in `koan/lib/workflows.py`.

### 6. Directory-as-contract

The subagent directory is the **sole interface** between parent and child.
Everything a subagent needs -- its task, its observable state -- lives in
well-known files inside that directory.

Two JSON files:

| File               | Writer                    | Reader                   | Lifecycle                                   |
| ------------------ | ------------------------- | ------------------------ | ------------------------------------------- |
| **`task.json`**    | Parent (before spawn)     | Parent (at registration) | Write-once, never modified                  |
| **`state.json`**   | Parent (audit projection) | Available for debugging  | Eagerly materialized after each audit event |
| **`events.jsonl`** | Parent (audit log)        | Available for replay     | Append-only event log                       |

`task.json` carries `run_dir` (so the subagent knows the run directory) and
role-specific fields (`artifacts`, `instructions` for executors; `question` for
scouts). No structured configuration flows through CLI flags, environment
variables, or other process-level channels. In-process subagents are registered
in the `AppState` agent registry by `agent_id`; no URL is needed.

**Why:** Files are structured, inspectable (`cat task.json`), typed, and
consistent with how we handle observation (audit). The directory is
self-describing and inspectable after the fact.

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

**plan** -- intake -> plan -> execute -> curation

Review of `plan.md` is performed inline by the mechanical PLAN_REVIEWER
sub-agent spawned by `koan_artifact_write`. The reviewer runs in a fresh
read-only context, returns freeform findings to the producer, and koan persists
them to `plan.review.md`. The producer reconciles findings in place
(INCORPORATED / OVERRULED / ESCALATED) before advancing. There is no separate
`plan-review` phase.

Execution is triggered by `koan_set_phase("execute", plan_file="plan.md")`,
which freezes the plan, spawns the executor (blocking), and returns the deviation
report. The `execute` phase runs inline conformance review of the executor's
work, appends notes to `plan.review.md`, and branches: clean -> advance to
`curation`; non-conforming -> one-shot remediation via a new
`plan-remediation-K.md` successor (re-triggers PLAN_REVIEWER), then re-execute;
second failure -> escalate to the user.

| Phase      | Role                        | Steps                         | Artifact                  |
| ---------- | --------------------------- | ----------------------------- | ------------------------- |
| `intake`   | Requirement gathering       | 3 (Gather/Deepen/Summarize)   | `brief.md`                |
| `plan`     | Technical planning + review | 2 (Analyze/Write+Reconcile)   | `plan.md`, `plan.review.md` |
| `execute`  | Execution + inline review   | 2 (Verify/Assess+Bookkeeping) | Code changes via executor |
| `curation` | Postmortem                  | 2 (Inventory/Memorize)        | `.koan/memory/` entries   |

**milestones** -- intake -> milestone -> plan -> execute -> milestone (loop) -> curation

Review of `milestones.md` and each `plan-milestone-N.md` is performed inline by
the mechanical MILESTONE_REVIEWER and PLAN_REVIEWER sub-agents respectively,
both spawned by `koan_artifact_write`. Each reviewer runs in a fresh read-only
context and koan persists findings to the corresponding `.review.md` sidecar.
The producer reconciles findings before advancing. There are no separate
`milestone-review` or `plan-review` phases.

After execution, the `execute` phase runs inline conformance review and -- on
a clean result -- updates `milestones.md` (marks `[done]`, adds `### Outcome`)
via `koan_artifact_edit`. The loop then returns to `plan` for the next milestone
or advances to `curation` when all milestones are complete.

| Phase       | Role                              | Steps                         | Artifact                        |
| ----------- | --------------------------------- | ----------------------------- | ------------------------------- |
| `intake`    | Requirement gathering             | 3 (Gather/Deepen/Summarize)   | `brief.md`                      |
| `milestone` | Milestone decomposition + review  | 2 (Analyze/Write+Reconcile)   | `milestones.md`, `.review.md`   |
| `plan`      | Milestone planning + review       | 2 (Analyze/Write+Reconcile)   | `plan-milestone-N.md`, `.review.md` |
| `execute`   | Execution + inline review + UPDATE| 2 (Verify/Assess+Bookkeeping) | Code changes; `milestones.md` UPDATE |
| `curation`  | Postmortem                        | 2 (Inventory/Memorize)        | `.koan/memory/` entries         |

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
default hand-back suggestions (built by `build_phase_suggestions`, or authored
via `koan_suggest_next`). These are recommendations, not constraints —
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

## Provider Credential Model

Provider availability is determined by `ProviderStatus` (env-key presence), not
by probing a CLI binary. `koan/agents/model_catalog.py` builds the all-providers
model registry (`ModelRegistryEntry` list) sourced from the genai-prices bundled
snapshot joined with a koan-owned capability table. Credentials are never stored
by koan; the Settings UI shows per-provider env-key presence and a Validate
action that constructs the model object locally (never a live provider call).
`model_catalog.price_for_usage` is the single cost-derivation entry point,
reading the bundled snapshot only (for fold determinism).

## Tool Registration

Tools are registered as in-process `FunctionToolset`s built by:

- `koan/tools/koan_tools.py:build_koan_toolset(deps)` -- koan tools
  (`koan_suggest_next`, `koan_set_phase`, `koan_ask_question`, etc.); the
  toolset receives a `ToolDeps(app_state, agent)` object that carries the
  in-process state needed by each tool core.
- `koan/tools/builtin_tools.py:build_builtin_toolset(deps)` -- built-in
  file/bash tools (`Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`).

`compose_toolset(policy, role, phase)` in `koan/tools/tool_policy.py` selects
which tools from each set are included for a given (role, phase) pair. The
composed toolset is passed to `PydanticAIAgent.run()` and registered with the
PydanticAI `Agent` before the first turn. Disallowed tools are absent from the
model's vocabulary; no call-time gate exists.

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
[Agent calls in-process tool (e.g. koan_suggest_next)]
     |
[Tool core runs, emits audit event]
     |
[fold() updates audit projection, state.json written atomically]
     |
[push_event() called with workflow-level event]
     |
[ProjectionStore: fold projection, compute JSON Patch, broadcast to subscribers]
     |
[Browser receives patch, applies applyPatch(store, patch) -- no interpretation]
```

### Concrete example: phase-boundary hand-back

```
Agent calls koan_suggest_next({ suggestions: [{id:"plan", label:"Write plan", command:"..."}] })
  -> suggest_next_core stores suggestions on InteractionState.next_suggestions
  -> (no projection event; suggestions are consumed at the hand-back)

Agent ends its turn in terminal text (no outstanding tool call)
  -> resolve_turn_outcome: steps exhausted, primary agent -> hand back
  -> push_event("yield_started", {suggestions: [...]}, agent_id="abc")
  -> fold: appends YieldEntry to agent conversation, sets run.active_yield
  -> patch: [{op:"add", path:"/run/agents/abc/conversation/entries/-", value:{type:"yield",...}},
             {op:"replace", path:"/run/activeYield", value:{suggestions:[...]}}]
  -> broadcast patch to SSE subscribers
  -> browser renders suggestion pills in activity feed and above chat input
  -> loop parks: yield_future created, awaits user message

user clicks suggestion pill "Write plan" in the browser
  -> YieldCard.onClick -> setChatDraft("write dashboard redesign implementation plan")
  -> FeedbackInput useEffect fires -> textarea pre-filled
  -> user reviews, presses Enter
  -> POST /api/chat { message: "write dashboard redesign implementation plan" }
  -> api_chat: yield_future is set -> append to user_message_buffer -> set_result(True)
  -> yield_future resolves
  -> loop resumes; user message becomes the next turn's prompt
  -> agent responds conversationally, then calls koan_set_phase("plan")
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

### Don't overload the first turn prompt

Step 1 guidance is injected as the first turn prompt by `run_agent_loop`. It
must have a single clear cognitive goal. Putting multiple goals or a large
context dump into step 1 risks the model treating it as a broad planning pass
and producing a vague turn rather than doing the specific first-step work.

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
- **Gate alone** -- the LLM receives a cryptic error with no context.

Two enforcement mechanisms are available -- use the appropriate one for the
constraint:

| Mechanism                        | What it enforces                              | How                                                                   |
| -------------------------------- | --------------------------------------------- | --------------------------------------------------------------------- |
| **`compose_toolset`**            | Which tools a role (or phase) can call        | Absent from vocabulary; model cannot call what it cannot see          |
| **`validate_step_completion()`** | Required pre-conditions before step advancement | Re-inject the same step at the turn boundary; LLM sees an error and must comply |
| **Tool description**             | Soft guidance on when to call                 | Cannot be enforced; LLM can ignore it                                 |

Any behavioral constraint that matters for correctness needs **both** a prompt
instruction (so the LLM knows what to do) and a mechanical gate (so
non-compliance is caught and corrected, not silently propagated).
`validate_step_completion` is evaluated by `resolve_turn_outcome` at the
turn boundary -- currently a no-op in every phase, but the gate is preserved
for future use.

### Don't give a step multiple cognitive goals

Each step should have exactly one cognitive goal. Grouping multiple goals into
a single step ("do A, then B, then C") enables **simulated refinement**: the
LLM artificially downgrades its output for A to manufacture visible improvement
in C. The turn-outcome resolver advances the step only at the end-of-turn
boundary, so each step gets exactly one turn to accomplish its goal.

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
value. The in-process `StreamEvent` path emitted by `PydanticAIAgent.run()`
exists for exactly this case -- token deltas flow directly to the projection
fold without touching the audit log. See [token-streaming.md](./token-streaming.md).

Note: `stream_delta` events (token deltas) DO go through the projection fold,
but the fold only updates an in-memory string (`pending_text` on the agent's
conversation) — no disk I/O. The distinction is between the audit pipeline
(disk writes per event) and the projection fold (in-memory only).
