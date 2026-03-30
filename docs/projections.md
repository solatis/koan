# Projections

How koan maintains frontend-visible state as a versioned event log with a
materialized projection, enabling full state recovery on page reload or
reconnect.

> Parent doc: [architecture.md](./architecture.md)

---

## Overview

The projection system maintains:

1. An **append-only versioned event log** — every fact that occurs during a
   workflow run, in order, with a monotonically increasing version number.
2. A **materialized projection** — the complete frontend-visible state derived
   by folding the event log with a pure function.
3. A **subscriber mechanism** — one `asyncio.Queue` per connected SSE client,
   fed from `push_event()`.

The `/events` SSE endpoint serves either a full snapshot (for new clients) or
a replay of missed events (for reconnecting clients), then streams live events.

**Design invariant:** Events are facts about things that happened — not state
snapshots. The fold function derives state from facts. Derived state is never
stored as an event.

---

## The Event Log

All events share a common envelope. `agent_id` is set when the event originates
from a specific agent; `None` otherwise.

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
    event_type: str                 # EventType string; stored as str so unknown types deserialise safely
    timestamp: str                  # ISO8601 UTC
    agent_id: str | None = None     # originating agent, when known
    payload: dict                   # typed per event_type (see below)
```

The log is append-only. Events are never modified or removed. The entire log
is held in memory for the duration of a workflow run. koan is one-shot (one
server instance per run), so there is no cross-run accumulation concern.

---

## Event Types

### Lifecycle events

| Event | What happened | Payload fields | `agent_id` |
|---|---|---|---|
| `phase_started` | Driver began a workflow phase | `phase` | `None` |
| `agent_spawned` | A subagent process was launched | `role, model, is_primary` | set |
| `agent_spawn_failed` | Spawn attempted but failed (runner error) | `role, error_code, message, ?details` | `None` |
| `agent_step_advanced` | Subagent called `koan_complete_step` | `step, step_name, ?usage` | set |
| `agent_exited` | Subagent process terminated | `exit_code, ?error, ?usage` | set |
| `workflow_completed` | Entire workflow finished | `success, summary, ?error` | `None` |

`agent_spawned` does not carry `step` — step 0 is implied. The first
`agent_step_advanced` is for step 1. `agent_exited` does not carry `is_primary`
— the fold looks up the agent in projection state. `workflow_completed` does
not carry the artifact list — consumers read `projection.artifacts`.

### Activity events

| Event | What happened | Payload fields | `agent_id` |
|---|---|---|---|
| `tool_called` | A tool was invoked | `call_id, tool, args, summary` | set |
| `tool_completed` | A tool call finished | `call_id, tool, ?result, ?summary` | set |
| `thinking` | LLM produced thinking tokens | `delta` | set |
| `stream_delta` | LLM produced output tokens | `delta` | set |
| `stream_cleared` | End-of-stream tombstone | (none) | set |

`tool_called` and `tool_completed` are paired by `call_id` (UUID). `tool` is a
canonical normalized name (`read`, `bash`, `edit`, `grep`,
`koan_complete_step`, etc.). `args` and `result` are unstructured (`dict | str`)
because tool schemas vary across runners.

MCP tool calls are authoritative — both `tool_called` and `tool_completed` are
emitted from the MCP endpoint. Stdout-parsed events are filtered to exclude
koan MCP tool names (which would otherwise duplicate). Agent-native tools (file
read, bash, etc.) are sourced from stdout with a synthetic `call_id`.

`thinking` events are fire-and-forget incremental deltas. No started/ended
lifecycle — the client derives "thinking stopped" from the next non-thinking
event.

`stream_cleared` is emitted at the end of a primary agent's stdout streaming
loop (before `agent_exited`) and at the start of a new primary agent's
streaming loop (to reset for the new agent).

### Interaction events

| Event | What happened | Payload fields | `agent_id` |
|---|---|---|---|
| `questions_asked` | Agent asked the user questions | `token, questions` | set |
| `questions_answered` | User answered (or interaction cancelled) | `token, ?answers, cancelled` | set |
| `artifact_review_requested` | Agent requested artifact review | `token, path, description, content` | set |
| `artifact_reviewed` | User reviewed artifact (or cancelled) | `token, ?accepted, ?response, cancelled` | set |
| `workflow_decision_requested` | Orchestrator proposed next phases | `token, chat_turns` | set |
| `workflow_decided` | User chose next phase (or cancelled) | `token, ?decision, cancelled` | set |

`agent_id` on resolution events is the agent whose interaction was resolved
(same as the requesting agent). Cancellation (`cancelled: true`) occurs when
the agent exits while the interaction is pending — there is no separate
cancellation event type.

### Resource events

| Event | What happened | Payload fields | `agent_id` |
|---|---|---|---|
| `artifact_created` | New file appeared in epic directory | `path, size, modified_at` | if known |
| `artifact_modified` | Existing file was modified | `path, size, modified_at` | if known |
| `artifact_removed` | File was removed from epic directory | `path` | if known |

`agent_id` is the primary agent at scan time (approximate — scanning happens
at phase boundaries, not on individual file writes). `build_artifact_diff()` in
`koan/events.py` compares old and new artifact sets and emits individual events
for each difference.

### Optional usage metadata

Token/usage fields are optional on events that naturally carry them:

```python
class Usage(BaseModel):
    input_tokens: int = 0     # tokens sent to LLM
    output_tokens: int = 0    # tokens received from LLM
```

Present on: `agent_step_advanced`, `agent_exited`, `tool_called`,
`tool_completed`. The fold accumulates these into per-agent token totals.

---

## The Projection

The fold reduces `(Projection, VersionedEvent) → Projection`. It is a pure
function: same event sequence → same projection. No I/O, no side effects.
Unknown event types return the projection unchanged (logged warning).

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
    completed_agents: list[AgentProjection] = [] # agents that exited (preserves final token totals)

    # Activity (raw events appended as-is)
    activity_log: list[dict] = []
    stream_buffer: str = ""                     # accumulated stream_delta text

    # Interactions
    active_interaction: dict | None = None

    # Resources
    artifacts: dict[str, dict] = {}             # keyed by path
    notifications: list[dict] = []              # derived from error events

    # Completion
    completion: dict | None = None
```

`done_phases` is NOT in the projection — it is a frontend-only derivation from
`phase` using the frontend's `ALL_PHASES` ordering constant.

`notifications` is derived by the fold from `agent_spawn_failed` and
`agent_exited` with error. It is not a dedicated event type — these are
projections of facts, preserved in the snapshot so they survive page refresh.

### Fold cases

**Lifecycle:**

| Event | Projection update |
|---|---|
| `phase_started` | `phase = event.phase`, `run_started = True` |
| `agent_spawned` | if `is_primary`: set `primary_agent`; else: add to `scouts[agent_id]` |
| `agent_spawn_failed` | append to `notifications` |
| `agent_step_advanced` | update `step`, `step_name` on agent; if `usage`: accumulate tokens |
| `agent_exited` | accumulate final `usage` tokens, move agent to `completed_agents`; if primary: `primary_agent = None`; if scout: remove from `scouts`; if `error`: append to `notifications` |
| `workflow_completed` | `completion = event.payload` |

**Activity:**

| Event | Projection update |
|---|---|
| `tool_called` | append raw event to `activity_log`; if `usage`: accumulate tokens on agent |
| `tool_completed` | append raw event to `activity_log`; if `usage`: accumulate tokens on agent |
| `thinking` | append raw event to `activity_log` |
| `stream_delta` | `stream_buffer += event.delta` |
| `stream_cleared` | `stream_buffer = ""` |

**Interactions:**

| Event | Projection update |
|---|---|
| `questions_asked` | `active_interaction = {interaction_type: "questions_asked", **payload}` |
| `questions_answered` | `active_interaction = None` |
| `artifact_review_requested` | `active_interaction = {interaction_type: "artifact_review_requested", **payload}` |
| `artifact_reviewed` | `active_interaction = None` |
| `workflow_decision_requested` | `active_interaction = {interaction_type: "workflow_decision_requested", **payload}` |
| `workflow_decided` | `active_interaction = None` |

The fold stores `interaction_type` (the event type string) alongside the payload
so the frontend can discriminate which component to render without duck-typing
payload fields.

**Resources:**

| Event | Projection update |
|---|---|
| `artifact_created` | add `{path, size, modified_at}` to `artifacts[path]` |
| `artifact_modified` | update `artifacts[path]` with new `size`, `modified_at` |
| `artifact_removed` | delete `artifacts[path]` |

**Unknown event type** → return projection unchanged, log warning.

**Unknown `agent_id`** (event references an agent not in `primary_agent` or
`scouts`) → return projection unchanged, log warning.

**Fold exception safety:** `fold()` wraps each event type handler in
`try/except`. Any exception returns projection unchanged and logs the exception
with full event details. The event is still appended to the log (append-only is
inviolable) but its fold effect is skipped.

**Accumulating fields** (`activity_log`, `notifications`, `stream_buffer`) are
unbounded — entries are never evicted. Runs are short-lived; the in-memory cost
is bounded by run duration.

---

## ProjectionStore

`koan/projections.py` contains the store class. This module has **zero koan
domain imports** — it is pure event-sourcing machinery. Domain-to-event
bridging lives in `koan/events.py`.

```python
class ProjectionStore:
    """In-memory versioned event log + materialized projection."""

    events: list[VersionedEvent]    # append-only
    projection: Projection           # eagerly materialized after each push_event
    version: int                     # current version (0 = empty)
    subscribers: list[asyncio.Queue]

    def push_event(self, event_type: str, payload: dict,
                   agent_id: str | None = None) -> VersionedEvent:
        """Append event, increment version, fold projection, broadcast to subscribers."""

    def get_snapshot(self) -> dict:
        """Return {version: int, state: dict} — the full projection as a dict."""

    def events_since(self, version: int) -> list[VersionedEvent]:
        """Return events with version > given version, in order."""

    def subscribe(self) -> asyncio.Queue:
        """Create and register a subscriber queue. Queue receives VersionedEvent objects."""

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
```

`push_event()` snapshots `self.subscribers` before iterating
(`for q in list(self.subscribers)`) to avoid `RuntimeError` if a subscriber
is added or removed during broadcast.

### Event payload builders: koan/events.py

`koan/events.py` bridges koan domain types (`AgentState`, `list_artifacts`,
`RunnerDiagnostic`, etc.) into typed event payloads. It imports domain types;
`projections.py` does not.

```python
def build_agent_spawned(agent: AgentState) -> dict
def build_agent_exited(exit_code: int, error: str | None = None, usage: dict | None = None) -> dict
def build_agent_spawn_failed(role: str, diagnostic: RunnerDiagnostic) -> dict
def build_step_advanced(step: int, step_name: str, usage: dict | None = None) -> dict
def build_tool_called(call_id: str, tool: str, args: dict | str, summary: str = "") -> dict
def build_tool_completed(call_id: str, tool: str, result: str | None = None) -> dict
def build_artifact_diff(old: dict[str, dict], new_artifacts: list[dict]) -> list[tuple[str, dict]]
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

---

## SSE Protocol

### Endpoint

`GET /events?since=N`

| `since` value | Server response |
|---|---|
| `0` (or omitted) | Send one `snapshot` SSE event, then stream live events |
| `N > 0` | Replay events with `version > N`, then stream live events |
| `N > current_version` (server restart) | Send `fatal_error` SSE event, close connection |

The server retains the full event log in memory. Replay is always possible for
any valid version.

When `since > current_version` (stale client after server restart), the server
sends a `fatal_error` SSE event with `{"reason": "version_not_available"}` and
closes the connection. The frontend handles `fatal_error` by closing the
`EventSource` without scheduling a reconnect and rendering a "reload required"
banner. This avoids infinite reconnect loops (browsers' `EventSource` fires
`onerror` on non-200 responses and would retry with the same stale version).

### Wire format

**Snapshot event** (`since=0`):

```
event: snapshot
data: {"version": 42, "state": { ...projection as dict... }}
```

**Versioned event** (replay or live stream):

```
event: agent_spawned
data: {"version": 43, "agent_id": "abc", "role": "intake", ...}
```

The SSE event name is the event type. Version and `agent_id` are included in
every data payload. The snapshot payload uses backend-native snake_case — the
frontend transforms to camelCase at the bridge boundary.

### Reconnect flow

```
Browser loads         → connect ?since=0   → receive snapshot  → render full state
Browser refreshes     → connect ?since=0   → receive snapshot  → render full state
Connection drops      → reconnect ?since=N → receive events N+1..M → fold each → up to date
```

---

## Frontend Integration

The Zustand store gains:

```typescript
lastVersion: number   // version of last applied event or snapshot

applySnapshot(data):  // atomic replace of entire store state
applyEvent(event):    // incremental fold — mirrors backend fold cases
```

On snapshot, `applySnapshot` atomically replaces all store state via
`useStore.setState(transform(data))`. No merge logic. Any visual flash from
the re-render is acceptable — simplicity over smoothness.

`connectSSE()` in `sse/connect.ts`:

1. Connects with `new EventSource('/events?since=${store.lastVersion}')`
2. `snapshot` event → `store.applySnapshot(data)`, sets `lastVersion`
3. All other events → `store.applyEvent(event)`, increments `lastVersion`
4. On disconnect: `lastVersion` is already in store; reconnect uses it automatically

The TypeScript fold mirrors the Python fold. Both must produce the same
projection shape from the same event sequence. When adding a new event type,
add a fold case to both implementations.

`done_phases` is NOT in the projection snapshot. The frontend derives it from
`phase` using its own `ALL_PHASES` ordering constant. Notification severity is
derived from event type in the frontend's `SEVERITY_MAP`.

---

## Relationship to the Audit Fold

Koan has two independent fold systems sharing the same structural pattern (pure
fold function, append-only log) but serving different purposes:

| Aspect | Audit fold (`koan/audit/fold.py`) | Projection fold (`koan/projections.py`) |
|---|---|---|
| Input | Per-subagent audit events (`events.jsonl`) | Workflow-level projection events |
| Output | Per-subagent `Projection` (phase, step, tokens, tool calls) | Frontend-visible `Projection` (all agents, run state, UI interactions) |
| Scope | One subagent's execution | Entire workflow run |
| Persistence | Written to `state.json` on disk | In-memory only |
| Consumers | Debugging, post-mortem analysis | Browser frontend via SSE |
| Parallelism | One fold per subagent | Single fold for the whole run |

The audit fold tracks the internal execution of each subagent. The projection
fold tracks the frontend-visible state of the whole workflow. They share the
same structural pattern but are not connected.

---

## Design Decisions

### No external library

There is no canonical Python library for in-memory event sourcing with
subscriptions that fits this use case:

- **`python-eventsourcing`** — designed for database persistence (PostgreSQL,
  etc.), not in-memory UI state
- **`reactivex`/`rxpy`** — reactive streams, awkward with asyncio, overkill
  for this volume

The pattern — append-only list + pure fold + `asyncio.Queue` subscribers — is
simple enough to implement directly. `koan/audit/fold.py` demonstrates the same
pattern for the audit domain.

### Why all events are versioned, including stream_delta

Token deltas fire at high frequency. Including each delta in the versioned log
means the log grows large, but the **snapshot** captures only
`stream_buffer: "accumulated text"` — a single small string. Reconnecting
clients receive the accumulated buffer from the snapshot, not thousands of
individual deltas.

The uniform model (every event gets a version) eliminates special-case code
paths. A system where some events are versioned and others are not creates
complexity in the reconnect path.

### Why tool events are generic, not per-tool-type

Tool schemas vary across runners and versions. A separate event type per tool
(`read_called`, `bash_called`, etc.) would require updating the event type
system whenever a runner adds or renames a tool. The `tool` field carries a
canonical normalized name; `args` and `result` are unstructured. The fold
appends raw events to the activity log without interpreting tool semantics.

### Why tool name normalization is per-runner

Each runner normalizes its own tool names in `parse_stream_event()`. This
keeps normalization knowledge co-located with runner-specific parsing logic.
By the time a `StreamEvent` leaves the runner, tool names are canonical
(`read`, `bash`, `edit`, `grep`, etc.). A central alias table would require
updating a shared file for each runner-specific change.

### Why MCP tool calls are authoritative over stdout

When a subagent calls a koan MCP tool, the call appears twice: as an MCP
request (structured, complete) and in the runner's stdout stream
(runner-specific format, possibly truncated). The MCP endpoint has full
structured data for both the call and the result. Stdout events are filtered
to exclude koan MCP tool names; only agent-native tools are sourced from stdout.

### Why notification_fired is eliminated

A generic notification bucket conflates facts with presentation concerns. Each
condition that warrants user notification is captured by a specific fact event
(`agent_spawn_failed`, `agent_exited` with error, `cancelled: true` on
interaction resolution). The fold derives `notifications` from these facts. The
frontend determines which events are notification-worthy and maps event types
to severity in its own `SEVERITY_MAP`.

### Why artifacts use diff events, not a full list

`artifact_created`/`artifact_modified`/`artifact_removed` carry exactly what
changed, not the full current set. The fold maintains `artifacts` as a
`dict[str, dict]` keyed by path, enabling O(1) per-event updates.

### Why the envelope has no UUID or causation fields

`version` is a unique identifier within a run — no UUID needed. Causation and
correlation IDs matter in multi-writer distributed systems where independent
producers interleave events and causal chains are ambiguous. Koan has a single
writer (the driver process). The causal chain is implicit in temporal ordering
plus `agent_id`. There is no cross-system correlation to track.

### Why projections.py has zero koan domain imports

`koan/projections.py` contains pure event-sourcing machinery. It imports
nothing from the koan domain. Domain-to-event bridging lives in `koan/events.py`.
This separation makes the projection engine testable in isolation and prevents
the event schema from leaking domain implementation details.

### Why activity_log stores raw events

`tool_called`, `tool_completed`, and `thinking` events are appended to
`activity_log` as-is without normalization. The frontend renders what it needs
from the raw payload. A normalization layer would need to anticipate every
display use case in advance; raw events let the frontend decide.

### Why accumulating fields are unbounded

`activity_log`, `notifications`, and `stream_buffer` are never evicted.
Capping them would require eviction logic that creates edge cases around what a
reconnecting client receives in a snapshot. koan is one-shot — the server shuts
down after the workflow completes — so accumulation is bounded by run duration.

### Why the server shuts down after workflow completion

koan runs one workflow per server instance. After `workflow_completed` is
emitted, the server shuts down gracefully. There is no idle state between runs,
no need to reset projection state, and no ambiguity about what a freshly
connecting browser should receive.

### Why version-negotiated catch-up instead of always-snapshot

A brief network hiccup should not force the frontend to rebuild all state from
scratch. `?since=N` lets a briefly-disconnected client receive only the events
it missed (typically a handful) and fold them incrementally.

### Why snapshot triggers atomic state replacement

When the frontend receives a snapshot, `useStore.setState(transform(data))`
atomically replaces the entire store. No merge logic, no version comparison.
A snapshot is authoritative. Any visual re-render is acceptable.
