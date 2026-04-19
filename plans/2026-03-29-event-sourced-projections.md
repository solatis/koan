# Event-Sourced Projections

## Summary

Replace the ad-hoc `last_sse_values` dict + per-type SSE caching with a proper
event-sourced projection system. The backend maintains a versioned, append-only
event log in memory. A pure fold function reduces events into a materialized
projection — the complete frontend-visible state. Clients subscribe via SSE
with version-negotiated catch-up: snapshot on first connect, event replay on
reconnect.

Also renames "pipeline" → "workflow" throughout the codebase for consistency
with existing `workflow-orchestrator` terminology.

## Problem

The current system stores `last_sse_values[event_type] = payload` — one value
per event type. On browser reconnect, these are replayed. This has two
fundamental issues:

1. **Accumulating state is lost.** `logs` (activity feed entries), `token-delta`
   (streaming text), and `notification` events are not cached. A page refresh
   mid-run loses the entire activity history and streaming buffer.

2. **Events are state snapshots, not facts.** The current SSE events (e.g.
   `subagent`, `agents`, `artifacts`) push full state replacements rather than
   describing what happened. `subagent-idle` is a "nothing happened" sentinel
   rather than the fact "agent X exited." This conflates the event log with
   the projection and makes the system impossible to reason about from an
   event-sourcing perspective.

## Decisions

### Naming: "projections"

The subsystem is called **projections**, consistent with the existing audit fold
terminology in `koan/audit/fold.py`. The backend module is `koan/projections.py`.
The materialized state type is `Projection`. The event log + fold + subscription
machinery lives in a `ProjectionStore` class.

### Naming: "pipeline" → "workflow"

The word "pipeline" is used for the overall run lifecycle (`pipeline-end` SSE
event, docs references). The word "workflow" is already used for the phase
routing subsystem (`workflow-orchestrator`, `workflow-decision`,
`koan_propose_workflow`). These refer to the same thing — the sequence of phases
from intake to completion. Standardize on **workflow** everywhere:

- `pipeline-end` event → `workflow_completed` event
- `pipeline_completed` references → `workflow_completed`
- `CompletionInfo` type keeps its name (describes the payload, not the concept)
- Docs references: "the pipeline" → "the workflow"
- The `workflow-orchestrator` name becomes _more_ natural: it orchestrates the workflow

No conflict: `workflow-orchestrator` already uses this term for exactly this
concept. The orchestrator orchestrates the workflow. The rename makes the naming
internally consistent rather than introducing a new term.

Note: the word "workflow" also appears informally in phase module comments
(e.g. `# Intake phase -- 5-step workflow`) where it means "step sequence within
a phase." This lowercase usage is distinct from "the Workflow" (the overall run)
and is clear from context. No rename needed for these comments.

### Events are facts, not snapshots

Every event in the versioned log represents **something that actually happened**
— not a state snapshot or derived metadata. The fold function derives state
from facts. This is the core design principle.

Example: when a primary agent's subprocess exits, the event is `agent_exited`
(fact: the process terminated). The fold _derives_ `projection.primary_agent =
None` from this fact. There is no `subagent-idle` event — "nothing is running"
is derived state, not a fact.

### All events are versioned

Every `push_event()` call produces a `VersionedEvent` with a monotonically
increasing version number (1-based). This includes high-frequency events like
`stream_delta` (token deltas). The fold accumulates these into
`projection.stream_buffer`. On snapshot, the client gets the accumulated buffer
string — not thousands of individual deltas.

Rationale: keeping the model uniform (every event gets a version) eliminates
special-case code paths. The event log may grow to thousands of entries per run,
but runs are short-lived and everything is in-memory. No persistence concern.

### Version-negotiated catch-up

The `/events` SSE endpoint accepts `?since=N`:

- `since=0` (or omitted): send a `snapshot` SSE event with the complete
  materialized projection + current version, then stream live events
- `since=N` where N > 0: replay events from version N+1 onward, then stream
  live events

The server always has the full event log in memory, so replay is always
possible. No threshold-based snapshot fallback needed.

### Snapshot shape is backend-native (snake_case)

The snapshot uses the same snake_case format as individual events. The frontend
transforms snake_case → camelCase at the bridge boundary, same as it does for
individual events today. This keeps the backend free of frontend formatting
concerns.

### Frontend does atomic state replacement on snapshot

When the frontend receives a `snapshot` event (on first connect), it atomically
replaces the entire Zustand store state via `useStore.setState(transform(data))`.
No merge logic, no version comparison. Simple and predictable. Any visual
flash from the re-render is acceptable.

On subsequent events (during a live connection or replayed from `?since=N`),
the frontend applies events incrementally through its own fold function.

### Pydantic models for type safety

All event types, the event envelope, and the projection shape are defined as
Pydantic `BaseModel` subclasses. Event types use `Literal` unions for static
checking and `match` dispatch. This replaces bare `dict` payloads with typed,
validated structures.

`EventType` is a `Literal` of all known event type strings. Unknown event types
are handled by the fold (return state unchanged, log warning) but cannot be
created through the typed API.

### `agent_id` in the event envelope

The event envelope carries an optional `agent_id: str | None` field. Most
events originate from a specific agent — tool calls, step advances, thinking,
streaming, interactions. A few do not (`phase_started`, `workflow_completed`,
artifact scan events when no agent is active). The envelope `agent_id`
eliminates the need to repeat it in every payload and enables generic
agent-scoped filtering.

The envelope does **not** carry a UUID, causation ID, or correlation ID:

- **No UUID**: `version` is a unique identifier within a run. UUIDs solve
  cross-system deduplication across persistent stores; koan events are ephemeral
  and in-memory.
- **No causation/correlation IDs**: These matter in multi-writer distributed
  systems where independent producers interleave events and causal chains are
  ambiguous. Koan has a single writer (the driver process). The causal chain is
  implicit in temporal ordering plus `agent_id`. There is no cross-system
  correlation to track.

### push_event is pure; callers build complete payloads

`push_event(event_type, payload, agent_id)` is a pure append + fold + broadcast.
It does not inspect or enrich the payload. Callers are responsible for building
fully-formed event payloads via typed helper functions in `koan/events.py`.

This decouples the projection system from `AppState` internals.

### `koan/projections.py` has zero koan domain imports

`koan/projections.py` contains pure event-sourcing machinery: `VersionedEvent`,
`Projection`, `AgentProjection`, `ProjectionStore`, and `fold()`. It imports
nothing from the koan domain (`AgentState`, `list_artifacts`, `RunnerDiagnostic`,
etc.). Domain-to-event bridging lives exclusively in `koan/events.py`.

This separation makes the projection engine testable in isolation and prevents
the event schema from leaking domain implementation details.

### Activity log stores raw events

`tool_called`, `tool_completed`, and `thinking` events are appended to
`activity_log` as-is, without a normalization layer. The frontend renders what
it needs from the raw payload. A normalization step would need to anticipate
every display use case in advance; raw events let the frontend decide. The
`call_id` on tool events enables the frontend to pair calls with completions
for in-flight state display.

### `workflow_completed` does not carry the artifact list

`workflow_completed` carries `success`, `summary`, and optional `error`. It
does not include the final artifact list. Consumers that need the current
artifact set at completion time read `projection.artifacts` — which is kept
current by `artifact_created`/`artifact_modified`/`artifact_removed` events
emitted throughout the run.

### Accumulating state is unbounded

The projection holds the complete activity log and stream buffer in memory with
no cap. Runs are short-lived; a typical run produces ~500–2000 activity entries.
This is well within memory bounds.

### Graceful shutdown after completion

koan is one-shot: one server instance serves one workflow run. After the
`workflow_completed` event, the server shuts down gracefully. No need to design
for state reset between runs.

### Token/usage metadata is additive, not a dedicated event

Token counts and usage metadata are not a standalone event type. They are
optional fields carried by events where they naturally occur:

- `tool_called` / `tool_completed` may carry per-call usage if available
- `agent_step_advanced` carries cumulative token counts at step boundaries
- `agent_exited` carries final cumulative token counts

The fold accumulates these into per-agent totals in the projection.

Currently, token tracking is approximate: `subagent.py` counts `len(delta)`
from stdout `token_delta` events as `tokens_received`. `tokens_sent` is always
0 — no runner reports input token counts. The audit system defines a
`UsageEvent` type but nothing emits it. Proper per-request usage from LLM
providers can be wired later by adding usage fields to existing events.

### Thinking events are incremental fire-and-forget

`thinking` events carry `delta: str` — incremental blocks of thinking tokens,
like `stream_delta` but for internal reasoning. No `thinking_started` or
`thinking_ended` lifecycle. The client derives "thinking stopped" from the
next non-thinking event.

Thinking content availability varies by runner. Some emit actual thinking text,
others emit markers with no content. The event is emitted with whatever the
runner provides.

### Interaction events split into typed pairs

The generic `interaction_created` / `interaction_resolved` events are replaced
by specific typed pairs:

- `questions_asked` / `questions_answered`
- `artifact_review_requested` / `artifact_reviewed`
- `workflow_decision_requested` / `workflow_decided`

Each pair has its own payload schema matching the interaction type's data.
Cancellation (e.g. agent exited while interaction pending) is indicated by
`cancelled: true` on the resolution event, not a separate event type.

The fold sets `active_interaction` on the request event and clears it on the
resolution event.

### `stream_cleared` is a tombstone event

`stream_cleared` is a proper control event (tombstone) marking the end of a
stream. It is emitted explicitly — not derived from `agent_exited`. This keeps
the stream lifecycle decoupled from the agent lifecycle (a stream could
theoretically be cleared mid-agent, or an agent could exit without having
streamed).

Emission points: emitted in `subagent.py` when the primary agent's streaming
loop ends (before `agent_exited`), and at the start of a new primary agent's
stdout streaming loop (to reset for the new agent).

### `notification_fired` is eliminated

There is no generic notification event. Every condition that was previously a
"notification" becomes a specific fact event:

- **Runner can't resolve/build** → `agent_spawn_failed` event. The agent was
  never spawned, so no `agent_spawned` event exists. `agent_id` in envelope is
  `None`; the payload carries `role` to identify what was attempted.
- **Process exited without handshake** → `agent_exited` with `error` field
  (e.g. `error: "bootstrap_failure"`). The agent WAS spawned.
- **Interaction cancelled due to agent exit** → the resolution pair event
  (e.g. `questions_answered`) carries `cancelled: true`.

The frontend derives which events are notification-worthy and maps event types
to severity in its own `SEVERITY_MAP`. The projection maintains a `notifications`
list populated by the fold when it encounters notification-worthy events
(`agent_spawn_failed`, `agent_exited` with error). This preserves notifications
across page refresh via snapshot.

### Artifacts decomposed into diffs

The old `artifacts_changed` event (full list replacement from filesystem scan)
is replaced by granular diff events: `artifact_created`, `artifact_modified`,
`artifact_removed`. Each carries a single artifact's metadata (`path`, `size`,
`modified_at`).

The scan function (`list_artifacts`) compares the current filesystem state
against the projection's known artifact set and emits individual events for
each difference. The fold maintains `artifacts` as a `dict[str, dict]` keyed
by path, enabling O(1) updates per event.

`agent_id` in the envelope is the primary agent at scan time. Scanning happens
at phase boundaries (bulk scan), so "which agent modified this file" is
approximate — it's "which agent was primary during this scan."

### Tool events: generic with `call_id`

`tool_called` and `tool_completed` are generic events — the `tool` field is a
canonical string (`"read"`, `"bash"`, `"koan_complete_step"`, etc.), not a
per-tool event type. The event schema is the same regardless of which tool.

Each tool call gets a `call_id: str` (UUID) to pair `tool_called` with
`tool_completed`. Both events are always emitted — no fire-and-forget.
`args` and `result` are unstructured (`dict | str`) because tool argument
schemas vary across runners and tool types.

The fold appends both to the activity log as raw events.

### MCP tool calls are authoritative; stdout duplicates filtered

When a subagent calls a koan MCP tool (e.g. `koan_complete_step`), two things
happen: the MCP endpoint handles the call, and the runner's stdout stream
contains the LLM's tool_use output. These are the same call seen from two
vantage points.

The MCP endpoint is the authoritative source — it emits both `tool_called` and
`tool_completed` with structured data. Stdout-parsed tool events are filtered:
if the tool name matches a koan MCP tool, the stdout event is suppressed.

For agent-native tools (file read, bash, etc.) that don't go through koan's
MCP, stdout parsing is the only source. These get a synthetic `call_id` (UUID)
generated at parse time.

### Tool name normalization is per-runner responsibility

Each runner normalizes its own tool names to canonical forms in
`parse_stream_event()`. Claude's `"Read"` → `"read"`. Codex's `"read_file"` →
`"read"`. Gemini's equivalent → `"read"`. By the time a `StreamEvent` leaves
the runner, tool names are already canonical.

Known canonical names: `read`, `write`, `edit`, `bash`, `grep`. Unknown tools
pass through as-is. This is a runner concern — no central alias table.

### `done_phases` is a frontend-only derivation

`done_phases` (the list of phases before the current one, used for pill strip
styling) is not part of the backend projection. The frontend derives it from
`phase` using its own `ALL_PHASES` ordering constant. The backend does not need
`done_phases` for any decision — it is purely a presentation concern.

The backend projection includes only `phase` (the current phase string). If the
backend ever needs the phase list for routing, that belongs in `AppState`, not
in the projection (derived values are not synchronized — the whole point is that
they can be derived).

### `intake_progress_updated` is removed

`intake_progress_updated` is not part of the event model. While there is
handling code for an `intake-progress` SSE event in the current `push_sse()`
and the frontend has a `setIntakeProgress` action, nothing in the codebase
actually emits this event. It is dead code end-to-end. Removed rather than
carried forward. If intake progress UI is needed, add it as a new event at that
time.

### `story` events are deferred

`push_sse(app_state, "story", {...})` is called 8 times in
`run_story_execution` and `run_story_reexecution`. The execution phase story
loop is partially stubbed — the story UI is a known gap (documented in
`docs/frontend.md`). These call sites are removed when `push_sse` is deleted.
Story projection events will be designed when the execution UI is built.

### `?since=N` with stale version sends `fatal_error` SSE event

If a client sends `?since=142` but the server's event log only goes up to
version 50 (or starts at 0 after restart), the server does NOT return an HTTP
error (browsers' `EventSource` cannot read error response bodies — any non-200
fires `onerror` and would cause infinite reconnect with the same stale version).

Instead, the server sends a `fatal_error` SSE event and closes the connection:

```
event: fatal_error
data: {"reason": "version_not_available"}
```

The frontend handles `fatal_error` by closing the `EventSource` WITHOUT
scheduling a reconnect, and sets a `fatalError` flag in the store. The UI
renders a "reload required" banner. This breaks the reconnect loop cleanly.

This is not a recoverable scenario — the client must reload the page. This is
acceptable because server restarts during a run are not a normal operation.

### No external library

There is no canonical Python library for in-memory event sourcing with
subscriptions. The closest candidates (`python-eventsourcing`, `reactivex`)
are either enterprise-heavy (designed for database persistence) or awkward with
asyncio. The pattern — append-only list + pure fold + asyncio.Queue subscribers
— is simple enough to implement directly. The existing `koan/audit/fold.py`
already demonstrates this pattern for a different domain.

## Event Model

### Event envelope

All events share this envelope. `agent_id` is included when the event
originates from or pertains to a specific agent.

```python
EventType = Literal[
    # Lifecycle
    "phase_started", "agent_spawned", "agent_spawn_failed",
    "agent_step_advanced", "agent_exited", "workflow_completed",
    # Activity
    "tool_called", "tool_completed", "thinking", "stream_delta", "stream_cleared",
    # Interactions
    "questions_asked", "questions_answered",
    "artifact_review_requested", "artifact_reviewed",
    "workflow_decision_requested", "workflow_decided",
    # Resources
    "artifact_created", "artifact_modified", "artifact_removed",
]

class VersionedEvent(BaseModel):
    version: int                    # 1-based, monotonic
    event_type: EventType
    timestamp: str                  # ISO8601 UTC
    agent_id: str | None = None     # originating agent, when known
    payload: dict                   # typed per event_type (see below)
```

### Lifecycle events

| Event                 | What happened                             | Payload fields                        | `agent_id` |
| --------------------- | ----------------------------------------- | ------------------------------------- | ---------- |
| `phase_started`       | Driver began a workflow phase             | `phase`                               | `None`     |
| `agent_spawned`       | A subagent process was launched           | `role, model, is_primary`             | set        |
| `agent_spawn_failed`  | Spawn attempted but failed (runner error) | `role, error_code, message, ?details` | `None`     |
| `agent_step_advanced` | Subagent called `koan_complete_step`      | `step, step_name, ?usage`             | set        |
| `agent_exited`        | Subagent process terminated               | `exit_code, ?error, ?usage`           | set        |
| `workflow_completed`  | Entire workflow finished                  | `success, summary, ?error`            | `None`     |

`agent_spawned` does not carry `step` — step 0 is implied. The first
`agent_step_advanced` is for step 1. `agent_exited` does not carry `is_primary`
— the fold looks up the agent in projection state.

### Activity events

| Event            | What happened                | Payload fields                     | `agent_id` |
| ---------------- | ---------------------------- | ---------------------------------- | ---------- |
| `tool_called`    | A tool was invoked           | `call_id, tool, args, summary`     | set        |
| `tool_completed` | A tool call finished         | `call_id, tool, ?result, ?summary` | set        |
| `thinking`       | LLM produced thinking tokens | `delta`                            | set        |
| `stream_delta`   | LLM produced output tokens   | `delta`                            | set        |
| `stream_cleared` | End-of-stream tombstone      | (none)                             | set        |

`tool_called` and `tool_completed` are paired by `call_id` (UUID). `tool` is a
canonical normalized name (`read`, `bash`, `edit`, `grep`,
`koan_complete_step`, etc.). `args` and `result` are unstructured (`dict | str`)
because tool schemas vary across runners.

MCP tool calls are authoritative — both `tool_called` and `tool_completed` are
emitted from the MCP endpoint. Stdout-parsed tool events are filtered to exclude
koan MCP tools (which would otherwise duplicate). Agent-native tools (not going
through koan MCP) get a synthetic `call_id` generated at parse time.

`thinking` events are fire-and-forget incremental deltas. No started/ended
lifecycle — the client derives "thinking stopped" from the next non-thinking
event.

### Interaction events

| Event                         | What happened                            | Payload fields                           | `agent_id` |
| ----------------------------- | ---------------------------------------- | ---------------------------------------- | ---------- |
| `questions_asked`             | Agent asked the user questions           | `token, questions`                       | set        |
| `questions_answered`          | User answered (or interaction cancelled) | `token, ?answers, cancelled`             | set        |
| `artifact_review_requested`   | Agent requested artifact review          | `token, path, description, content`      | set        |
| `artifact_reviewed`           | User reviewed artifact (or cancelled)    | `token, ?accepted, ?response, cancelled` | set        |
| `workflow_decision_requested` | Orchestrator proposed next phases        | `token, chat_turns`                      | set        |
| `workflow_decided`            | User chose next phase (or cancelled)     | `token, ?decision, cancelled`            | set        |

`agent_id` on resolution events is the agent whose interaction was resolved
(same as the requesting agent). Cancellation (`cancelled: true`) occurs when
the agent exits while the interaction is pending.

### Resource events

| Event               | What happened                        | Payload fields            | `agent_id` |
| ------------------- | ------------------------------------ | ------------------------- | ---------- |
| `artifact_created`  | New file appeared in epic directory  | `path, size, modified_at` | if known   |
| `artifact_modified` | Existing file was modified           | `path, size, modified_at` | if known   |
| `artifact_removed`  | File was removed from epic directory | `path`                    | if known   |

`agent_id` is the primary agent at scan time (approximate — scanning happens
at phase boundaries, not on individual file writes).

`modified_at` is Unix epoch milliseconds (`int`). `build_artifact_diff()`
converts the `float` seconds from `list_artifacts()` to `int(seconds * 1000)`,
consistent with `started_at_ms` elsewhere in the codebase.

### Optional `usage` metadata

Token/usage fields are optional on events that naturally carry them. When
present, the fold accumulates into per-agent totals in the projection.

```python
# Optional field on agent_step_advanced, agent_exited, tool_called, tool_completed:
class Usage(BaseModel):
    input_tokens: int = 0     # tokens sent to LLM
    output_tokens: int = 0    # tokens received from LLM
```

Currently only `output_tokens` is approximated (byte length of stdout deltas).
Per-request usage from LLM providers can be added by populating these fields
when runners report usage data.

### Events that are removed

| Old event                   | Replacement                                                   | Why                                       |
| --------------------------- | ------------------------------------------------------------- | ----------------------------------------- |
| `subagent` (state snapshot) | `agent_spawned` + `agent_step_advanced`                       | Facts, not snapshots                      |
| `subagent-idle`             | `agent_exited`                                                | "No agent" is derived from "agent exited" |
| `agents` (full scout list)  | `agent_spawned` + `agent_exited` per scout                    | Facts, not snapshots                      |
| `pipeline-end`              | `workflow_completed`                                          | Renamed                                   |
| `token-delta`               | `stream_delta`                                                | Consistent naming                         |
| `token-clear`               | `stream_cleared`                                              | Consistent naming                         |
| `logs`                      | `tool_called` / `tool_completed` / `thinking`                 | Specific facts, not generic "log"         |
| `notification`              | `agent_spawn_failed` / `agent_exited` with error              | Specific facts, not generic bucket        |
| `artifacts` (full list)     | `artifact_created` / `artifact_modified` / `artifact_removed` | Diffs, not snapshots                      |
| `interaction` (generic)     | Typed pairs: `questions_asked`/`answered`, etc.               | Specific facts per interaction type       |

## Fold Function

The fold reduces `(Projection, VersionedEvent) → Projection`. It runs on both
backend (Python) and frontend (TypeScript). Both implementations must produce
the same derived state from the same event sequence.

Unknown event types return the projection unchanged (with a logged warning).

### Projection shape

```python
class AgentProjection(BaseModel):
    agent_id: str
    role: str
    model: str | None = None
    step: int = 0
    step_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

class Projection(BaseModel):
    # Run state
    run_started: bool = False
    phase: str = ""

    # Agents
    primary_agent: AgentProjection | None = None
    scouts: dict[str, AgentProjection] = {}     # keyed by agent_id
    completed_agents: list[AgentProjection] = [] # agents that have exited (preserves final token totals)

    # Activity (raw events: tool_called, tool_completed, thinking)
    activity_log: list[dict] = []
    stream_buffer: str = ""                     # accumulated stream deltas

    # Interactions
    active_interaction: dict | None = None

    # Resources
    artifacts: dict[str, dict] = {}             # keyed by path
    notifications: list[dict] = []              # derived from error events

    # Completion
    completion: dict | None = None
```

`done_phases` is NOT in the projection — it is a frontend-only derivation
from `phase` using the frontend's `ALL_PHASES` ordering constant.

`notifications` is derived by the fold from specific events (`agent_spawn_failed`,
`agent_exited` with error). It is not a separate event type — these are
projections of facts, preserved in the snapshot so they survive page refresh.

### Fold cases

**Lifecycle:**

- `phase_started` → set `phase`, set `run_started = True`
- `agent_spawned` → create `AgentProjection` from payload; if `is_primary`: set `primary_agent`; else: add to `scouts[agent_id]`
- `agent_spawn_failed` → append to `notifications` (derived: spawn failure notification)
- `agent_step_advanced` → find agent in `primary_agent` or `scouts[agent_id]`; update `step`, `step_name`; if `usage`: accumulate tokens
- `agent_exited` → find agent by `agent_id`: if primary, accumulate final `usage` tokens, move to `completed_agents`, set `primary_agent = None`; if scout, accumulate then remove from `scouts`; if `error`: append to `notifications`
- `workflow_completed` → set `completion`

**Activity:**

- `tool_called` → append raw event to `activity_log`; if `usage`: accumulate tokens on agent
- `tool_completed` → append raw event to `activity_log`; if `usage`: accumulate tokens on agent
- `thinking` → append raw event to `activity_log`
- `stream_delta` → append `delta` to `stream_buffer`
- `stream_cleared` → set `stream_buffer = ""`

**Interactions:**

- `questions_asked` → set `active_interaction = {interaction_type: "questions_asked", **payload}`
- `questions_answered` → clear `active_interaction`
- `artifact_review_requested` → set `active_interaction = {interaction_type: "artifact_review_requested", **payload}`
- `artifact_reviewed` → clear `active_interaction`
- `workflow_decision_requested` → set `active_interaction = {interaction_type: "workflow_decision_requested", **payload}`
- `workflow_decided` → clear `active_interaction`

The fold stores `interaction_type` (the event type string) alongside the payload
so the frontend can discriminate which component to render (`AskWizard`,
`ArtifactReview`, or `WorkflowDecision`) without duck-typing payload fields.

**Resources:**

- `artifact_created` → add `{path, size, modified_at}` to `artifacts[path]`
- `artifact_modified` → update `artifacts[path]` with new `size`, `modified_at`
- `artifact_removed` → delete `artifacts[path]`

**Unknown event type** → return projection unchanged, log warning.

**Unknown `agent_id`** (event references an agent not in `primary_agent` or
`scouts`) → return projection unchanged, log warning. Same guarantee as unknown
event types.

**Fold exception safety:** `fold()` wraps each event type handler in
`try/except`. Any exception returns projection unchanged and logs the exception
with full event details. The event is still appended to the log (append-only is
inviolable) but its fold effect is skipped. This ensures a single malformed
payload cannot permanently break event replay.

## Backend Architecture

### New module: `koan/projections.py`

Pure event-sourcing machinery. No koan domain imports.

```python
class VersionedEvent(BaseModel):
    version: int                    # 1-based, monotonic
    event_type: EventType           # Literal union
    timestamp: str                  # ISO8601 UTC
    agent_id: str | None = None     # originating agent, when known
    payload: dict                   # event-specific (typed per event_type)

class ProjectionStore:
    """In-memory versioned event log + materialized projection."""

    events: list[VersionedEvent]
    projection: Projection
    version: int  # current version (0 = empty)
    subscribers: list[asyncio.Queue]

    def push_event(self, event_type: EventType, payload: dict,
                   agent_id: str | None = None) -> VersionedEvent:
        """Append event, increment version, fold, broadcast to subscribers."""

    def get_snapshot(self) -> dict:
        """Return {version, state: <projection as dict>}."""

    def events_since(self, version: int) -> list[VersionedEvent]:
        """Return events with version > given version."""

    def subscribe(self) -> asyncio.Queue:
        """Create and register a subscriber queue."""

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
```

### Event payload builders: `koan/events.py`

Bridges koan domain types into typed event payloads. Separate from
`projections.py` to keep the projection engine pure.

```python
# koan/events.py -- bridges koan domain types into projection event payloads.
# Imports AgentState, list_artifacts, etc. projections.py does not.

def build_agent_spawned(agent: AgentState) -> dict
def build_agent_exited(agent_id: str, exit_code: int, error: str | None = None) -> dict
def build_agent_spawn_failed(role: str, diagnostic: RunnerDiagnostic) -> dict
def build_tool_called(call_id: str, tool: str, args: dict | str, summary: str) -> dict
def build_tool_completed(call_id: str, tool: str, result: str | None = None) -> dict
def build_artifact_diff(old: dict[str, dict], new: dict[str, dict]) -> list[tuple[EventType, dict]]
# etc.
```

`build_artifact_diff` compares old and new artifact sets, returns a list of
`(event_type, payload)` tuples — one per created/modified/removed file.

Callers import from both modules:

```python
from .projections import ProjectionStore
from .events import build_agent_spawned

store.push_event("agent_spawned", build_agent_spawned(agent), agent_id=agent.agent_id)
```

Centralizing helpers in one module ensures payload shapes stay consistent
across call sites (`driver.py`, `subagent.py`, `web/mcp_endpoint.py`).

### Changes to existing modules

**`koan/state.py`:** Remove `last_sse_values` and `sse_clients` from `AppState`.
Add `projection_store: ProjectionStore` field.

**`koan/driver.py`:** Delete `push_sse()` function. All callers switch to
`app_state.projection_store.push_event(...)` with helper-built payloads.
Delete `_build_subagent_json`, `_build_agents_json`, `_build_artifacts_json`.
Delete `STATEFUL_EVENTS` set. The `app_state.phase = phase` mutation currently
inside `push_sse()` moves to `driver_main()` — set `app_state.phase` before
calling `push_event("phase_started", ...)`. This keeps the mutation in the
driver's sequential flow, not inside projection machinery.

**`koan/runners/*.py`:** Each runner's `parse_stream_event()` normalizes tool
names to canonical forms (`Read` → `read`, `Bash` → `bash`, etc.). Unknown
tools pass through as-is. This is a per-runner responsibility — no central
alias table. Runners also filter out koan MCP tool names from stdout events
to prevent duplicates.

**`koan/subagent.py`:** All `_push_sse()` calls become `push_event()` calls
with specific event types and complete payloads. The lazy import pattern stays
to avoid circular deps. Stdout tool processing changes: generate synthetic
`call_id` per tool call, emit paired `tool_called`/`tool_completed` events.
Add `stream_cleared` emission at end of stdout streaming loop (before
`agent_exited`). Notification `_push_sse` calls become `agent_spawn_failed`
or enriched `agent_exited` events.

**`koan/web/mcp_endpoint.py`:** `_log_tool_call()` becomes the authoritative
tool event emitter. Emits `tool_called` on entry with a generated `call_id`,
and `tool_completed` on return. Each MCP tool handler wraps its logic with
paired tool events.

**`koan/web/interactions.py`:** `_push_sse("interaction", ...)` calls become
typed pair events: `questions_asked` / `questions_answered`,
`artifact_review_requested` / `artifact_reviewed`,
`workflow_decision_requested` / `workflow_decided`. Cancellation sets
`cancelled: true` on the resolution event.

**`koan/web/app.py`:** `sse_stream()` rewritten to read `?since=N`, send
snapshot or replay events, then live-tail from a subscriber queue. If
`since > current_version` (stale client after server restart), send a
`fatal_error` SSE event (see decision). Note: `since == current_version` is
valid — it means the client has all events and should live-tail. The `_sse_event()` helper remains for
SSE wire formatting.

**`koan/driver.py` story events (8 call sites):** The `push_sse(app_state,
"story", {...})` calls in `run_story_execution` and `run_story_reexecution`
are removed. The execution phase story loop is partially stubbed and the
story UI is a known gap. Story projection events will be designed when the
execution UI is built.

### SSE wire protocol

**Snapshot event** (sent when `since=0`):

```
event: snapshot
data: {"version": 42, "state": { ...projection as dict... }}
```

**Versioned event** (sent during replay or live stream):

```
event: <event_type>
data: {"version": 43, "agent_id": "abc-123", ...payload fields...}
```

The SSE event name IS the event type (`agent_spawned`, `stream_delta`, etc.).
The version and agent_id are included in every data payload.

## Frontend Architecture

### Store changes

Add to Zustand store:

```typescript
lastVersion: number; // tracks the latest applied event version
```

Add actions:

```typescript
applySnapshot: (data: SnapshotPayload) => void  // atomic state replacement
applyEvent: (event: VersionedEvent) => void      // incremental fold
```

### SSE bridge changes (`sse/connect.ts`)

The `connectSSE` function changes from per-event-type listeners to a unified
protocol:

1. Connect with `new EventSource('/events?since=${store.lastVersion}')`
2. Listen for `snapshot` event → call `store.applySnapshot(data)` (atomic replace)
3. Listen for all other events → call `store.applyEvent(event)` (incremental fold)
4. On disconnect: `lastVersion` is already tracked in store; reconnect uses it

The frontend fold function mirrors the backend fold. Both produce the same
projection shape from the same event sequence.

### Reconnect flow

```
Browser loads → connect ?since=0 → receive snapshot → render full state
Browser refreshes → connect ?since=0 → receive snapshot → render full state
Connection drops → reconnect ?since=142 → receive events 143..150 → fold each → up to date
```

## Documentation Updates

### `docs/architecture.md`

Update these sections:

- **SSE Event Lifecycle**: replace the current push_sse / last_sse_values /
  replay description with the event-sourced projection model
- **Event-Sourced Audit**: add a section distinguishing the two fold systems
  (audit fold for per-subagent state, projection fold for frontend state)
- **Replay on reconnect**: replace "buffers the last value of every stateful
  SSE event type" with version-negotiated catch-up description
- References to "pipeline" → "workflow"

### `docs/frontend.md`

Update these sections:

- **State Model**: document `lastVersion`, `applySnapshot`, `applyEvent`
- **SSE Bridge**: document the `?since=N` protocol, snapshot vs event replay
- **Backend Contract**: document the event types table (replacing current
  `push_sse` / builder function documentation)
- Replace all `pipeline-end` references with `workflow_completed`
- Remove references to `subagent-idle`, `last_sse_values`, `STATEFUL_EVENTS`

### `docs/token-streaming.md`

Update:

- **SSE Path**: rename `token-delta` → `stream_delta`, document that it goes
  through the versioned event log (not bypassing it as the current doc states)
- **Replay on reconnect**: document that the snapshot includes
  `stream_buffer` (the accumulated text), so reconnecting clients get the full
  streaming state without replaying individual deltas

### New doc: `docs/projections.md`

Spoke document covering:

- The event model (full event type table with fields)
- The fold function (all cases)
- The projection shape
- The `ProjectionStore` class API
- The SSE protocol (`?since=N`, snapshot, event replay)
- The relationship to the audit fold (two separate fold systems, different purposes)
- Decision record: why no external library, why events are facts not snapshots,
  why all events are versioned

### `docs/artifact-review.md`

- Rewrite "Web UI Component" section: remove Jinja2/HTMX references (frontend
  is React). Component is `ArtifactReview.tsx`.
- SSE Events table: `artifact-review` → `artifact_review_requested`;
  `artifact-review-cancelled` removed (cancellation is now `artifact_reviewed`
  with `cancelled: true`).
- "pipeline advancement" → "workflow advancement".

### `docs/ipc.md`

- Ask Flow: "pushes SSE 'ask' event" → `questions_asked`
- Artifact Review Flow: "pushes SSE 'artifact-review' event" → `artifact_review_requested`
- PendingInteraction type values (`"ask"`, `"artifact-review"`) are internal
  identifiers, not SSE event names — leave as-is.

### `AGENTS.md`

Update the pipeline phases list to use "workflow" terminology.

## Implementation Order

### Phase 1: Backend projection infrastructure

1. Create `koan/projections.py` with `VersionedEvent`, `Projection`,
   `ProjectionStore`, and the `fold()` function. `push_event()` must snapshot
   `self.subscribers` before iterating (`for q in list(self.subscribers)`)
   to avoid `RuntimeError` if a subscriber is added/removed during broadcast.
2. Add `projection_store` to `AppState`. Remove `last_sse_values` and
   `sse_clients` AND rewrite `sse_stream()` in the same commit (steps 2+3
   are atomic — intermediate state where `sse_clients` is removed but
   `sse_stream` still references it will crash).

### Phase 2: Runner tool normalization

3. Add tool name normalization to each runner's `parse_stream_event()`:
   canonical names (`read`, `bash`, `edit`, `grep`, etc.). Add a
   `KOAN_MCP_TOOLS: frozenset[str]` constant in `koan/web/mcp_endpoint.py`
   (where the tools are registered). Runners import it for stdout filtering —
   any stdout tool event whose name is in `KOAN_MCP_TOOLS` is dropped.

### Phase 3: Event model migration

4. Create `koan/events.py` with Pydantic payload models and builder helpers,
   including `build_artifact_diff()` for diffing artifact scans
5. Move `app_state.phase = phase` from `push_sse()` into `driver_main()`
   before the `push_event("phase_started", ...)` call
6. Migrate all `push_sse()` call sites in `driver.py` to `push_event()` with
   proper event types (remove the 8 `story` call sites — deferred). Replace
   bulk `artifacts` pushes with `build_artifact_diff()` + individual events.
7. Migrate all `_push_sse()` call sites in `subagent.py`. Generate synthetic
   `call_id` for stdout tool events, emit paired `tool_called`/`tool_completed`.
   Handle `turn_complete` in the stdout `else` branch: drop it (emit nothing).
   `stream_cleared` at stdout EOF already signals end-of-stream.
   Add `stream_cleared` emission. Convert notification pushes to
   `agent_spawn_failed` or enriched `agent_exited`.
   Cancellation resolution events are only emitted for the ACTIVE interaction.
   Queued-but-not-active interactions are cancelled silently (future resolved
   with error result, no projection event emitted).
8. Migrate `web/interactions.py` to typed pair events (`questions_asked`/
   `questions_answered`, `artifact_review_requested`/`artifact_reviewed`,
   `workflow_decision_requested`/`workflow_decided`). Cancellation sets
   `cancelled: true` on resolution event.
9. Migrate `web/mcp_endpoint.py`: replace `_log_tool_call()` with two
   functions: `begin_tool_call(agent, tool, args, summary) -> str` (returns
   `call_id`, emits `tool_called`) and `end_tool_call(agent, call_id, result)`
   (emits `tool_completed`). Blocking tools (`koan_ask_question`,
   `koan_review_artifact`, `koan_propose_workflow`, `koan_request_scouts`)
   call `begin_tool_call` before the `await` and `end_tool_call` in a
   `try/finally` after. `call_id` is a local variable in each handler.
10. Delete `push_sse()`, `_build_subagent_json`, `_build_agents_json`,
    `_build_artifacts_json`, `STATEFUL_EVENTS` from `driver.py`

### Phase 4: Frontend adaptation

11. Add `lastVersion` and `applySnapshot`/`applyEvent` to the Zustand store.
    Remove `done_phases` from store — derive it in a selector from `phase`.
    Change `artifacts` from list to dict keyed by path.
12. Implement the frontend fold function (TypeScript mirror of backend fold),
    including all typed interaction pairs and artifact diff events
13. Rewrite `connectSSE()` to handle `snapshot` + typed events with version
    tracking. Derive notification severity via `SEVERITY_MAP` on event types.
14. Update `App.tsx` reconnect logic to pass `?since=N`

### Phase 5: Rename pipeline → workflow

15. Rename `pipeline-end` → `workflow_completed` in all backend code
16. Update frontend references
17. Update all docs

### Phase 6: Documentation ✓

18. Write `docs/projections.md` ✓
19. Update `docs/architecture.md`, `docs/frontend.md`, `docs/token-streaming.md`,
    `docs/ipc.md`, `docs/artifact-review.md`, `docs/state.md`,
    `docs/subagents.md`, `docs/intake-loop.md` ✓
20. Update `AGENTS.md` ✓

### Phase 7: Tests

21. Unit tests for `ProjectionStore` and `fold()`
22. Unit tests for `build_artifact_diff()` (correct diff detection)
23. Update existing SSE tests in `test_web_flows.py`
24. Update interaction tests that mock `_push_sse`
25. Test `?since=N` replay and snapshot paths
26. Test `?since=N` where N exceeds server version → error response
27. Test tool name normalization per runner

### Phase 8: Graceful shutdown

28. After `workflow_completed` event, schedule server shutdown
