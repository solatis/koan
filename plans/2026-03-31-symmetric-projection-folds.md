# Symmetric Projection Folds

**Date:** 2026-03-31
**Status:** Draft
**Goal:** Make backend and frontend projection folds produce identical materialized state, eliminating the need for ad-hoc re-interpretation during snapshot recovery.

---

## Motivation / Bug Report

Two user-visible bugs triggered this plan, both manifesting on page refresh:

**Bug 1: Fragmented thinking cards.** After refreshing the page, the primary agent's thinking was displayed as dozens of tiny individual cards — "The", "user wants", "me to call", "k", "oan_complete_step to receive", "instructions.", etc. — instead of a single merged block. During a live session, thinking tokens arrive as `thinking` SSE events and are accumulated in the frontend's `thinkingBuffer` before being flushed into a single card. On refresh, `applySnapshot` received the raw event log and created one card per event.

**Bug 2: Scout events in the primary agent's feed.** After refresh, step headers (e.g., "step 3/3 Report") and thinking blocks from scout agents appeared in the primary agent's activity feed. The MCP server was processing a batch of scouts while the primary agent was blocked; those scouts' events were in the event log but clearly attributed to different `agent_id`s. The live `applyEvent` path correctly filters to the primary agent; `applySnapshot` did not.

**Root cause (shared):** `activity_log` in the backend `Projection` is not a materialized view — it is a raw event append. The frontend's `applySnapshot` was forced to re-fold this raw log, duplicating fold logic that was inconsistent with the live path.

**User statement:** "shouldn't the backend fold produce the same state that the frontend renders?" — confirmed as the correct design intent.

---

## Problem Statement

The backend `fold()` in `koan/projections.py` and the frontend `applyEvent()` in `frontend/src/store/index.ts` are supposed to be symmetric — they process the same events and produce the same materialized state. The client connects, receives a **snapshot** (materialized state at version N), then applies live events via its own fold.

**The current reality:**

The `activity_log` field in the backend `Projection` is **not** materialized. The backend fold just appends raw event dicts:

```python
case "tool_called":
    entry = {"event_type": event_type, "agent_id": agent_id, **payload}
    return projection.model_copy(update={
        "activity_log": [*projection.activity_log, entry],
    })
```

This makes `activity_log` a **second copy of the raw event log** — not a materialized view. The frontend's `applySnapshot()` then has to re-fold this raw log into rich `ActivityEntry[]` structures (merge consecutive thinking deltas, filter to primary agent, map typed tools, compute in-flight status). This re-folding logic is separate from and inconsistent with the live `applyEvent()` fold, causing the bugs above.

Meanwhile, the frontend's live `applyEvent()` does produce the correct rich view — but this logic is duplicated nowhere, and the snapshot path implements a buggy approximation of it.

**The design invariant stated in `docs/projections.md` — "Events are facts about things that happened — not state snapshots. The fold function derives state from facts" — was being violated for `activity_log`, which stored raw facts instead of derived state.**

---

## Event Types (33 total)

### Lifecycle (7)

| Event | Payload | Description |
|-------|---------|-------------|
| `phase_started` | `{phase: str}` | New workflow phase begins |
| `agent_spawned` | `{agent_id, role, label, model, is_primary, started_at_ms}` | Agent process launched |
| `agent_spawn_failed` | `{role, error_code, message, details?}` | Agent failed to spawn |
| `agent_step_advanced` | `{step, step_name, usage?, total_steps?}` | Agent progressed to next step |
| `agent_exited` | `{exit_code, error?, usage?}` | Agent process terminated |
| `workflow_completed` | `{success, summary?, error?}` | Entire workflow finished |
| `scout_queued` | `{scout_id, label, model?}` | Scout waiting for concurrency slot |

### Activity (13)

| Event | Payload | Description |
|-------|---------|-------------|
| `tool_called` | `{call_id, tool, args, summary}` | Generic/unrecognized tool invocation |
| `tool_read` | `{call_id, tool:"read", file, lines}` | File read |
| `tool_write` | `{call_id, tool:"write", file}` | File write |
| `tool_edit` | `{call_id, tool:"edit", file}` | File edit |
| `tool_bash` | `{call_id, tool:"bash", command}` | Shell command |
| `tool_grep` | `{call_id, tool:"grep", pattern}` | Pattern search |
| `tool_ls` | `{call_id, tool:"ls", path}` | Directory listing |
| `tool_completed` | `{call_id, tool, result?}` | Tool invocation finished |
| `thinking` | `{delta: str}` | Incremental thinking token chunk |
| `stream_delta` | `{delta: str}` | Incremental text output chunk |
| `stream_cleared` | `{}` | Agent's stream ended (process EOF) |

All activity events carry `agent_id` identifying which agent produced them.

**Note:** `tool_read` through `tool_ls` are typed specialisations of `tool_called`, introduced to carry structured metadata (file paths, commands, patterns) that the generic `tool_called` payload cannot express uniformly across runners. The existing `docs/projections.md` "Why tool events are generic" rationale is superseded — that rationale was written before the typed events existed.

### Interactions (6)

| Event | Payload | Description |
|-------|---------|-------------|
| `questions_asked` | `{token, questions: [...]}` | User prompted with questions |
| `questions_answered` | `{token, cancelled, answers?}` | User responded |
| `artifact_review_requested` | `{token, path, description, content}` | Artifact review needed |
| `artifact_reviewed` | `{token, cancelled, accepted?, response?}` | Review completed |
| `workflow_decision_requested` | `{token, chat_turns}` | Phase selection needed |
| `workflow_decided` | `{token, cancelled, decision?}` | Decision made |

### Resources (3)

| Event | Payload | Description |
|-------|---------|-------------|
| `artifact_created` | `{path, size, modified_at}` | New file produced |
| `artifact_modified` | `{path, size, modified_at}` | File updated |
| `artifact_removed` | `{path}` | File deleted |

### Configuration (7)

| Event | Payload | Description |
|-------|---------|-------------|
| `probe_completed` | `{runners: [...]}` | Binary detection finished |
| `installation_created` | `{alias, runner_type, binary, extra_args}` | New agent installation |
| `installation_modified` | `{alias, runner_type, binary, extra_args}` | Installation updated |
| `installation_removed` | `{alias}` | Installation deleted |
| `profile_created` | `{name, read_only, tiers}` | New profile |
| `profile_modified` | `{name, read_only, tiers}` | Profile updated |
| `profile_removed` | `{name}` | Profile deleted |
| `active_profile_changed` | `{name}` | Active profile switched |
| `scout_concurrency_changed` | `{value}` | Concurrency limit changed |

---

## SSE Protocol

```
Client connects: GET /events?since=0
Server sends:    event: snapshot\ndata: {"version": N, "state": <Projection>}\n\n
Server sends:    event: <type>\ndata: {"version": N+1, ...payload}\n\n  (live)
                 event: <type>\ndata: {"version": N+2, ...payload}\n\n  (live)
                 ...

Client reconnects: GET /events?since=N+2
Server sends:      event: <type>\ndata: {"version": N+3, ...}\n\n  (catch-up)
                   event: <type>\ndata: {"version": N+4, ...}\n\n  (live)
                   ...
```

- `since=0`: snapshot + live events
- `since=N` (N > 0): catch-up replay of events with version > N, then live
- `since=N` where N > server version: `fatal_error` event, client reloads

**The snapshot is the materialized projection state.** The client reads it directly into its store, then applies subsequent events via its local fold. No re-interpretation. The `since` value is the version embedded in the snapshot — the client stores it and uses it on reconnect.

---

## Target Projection Shape

The projection is the single source of truth. Backend `fold()` produces it, `get_snapshot()` serializes it, frontend `applySnapshot()` reads it directly, frontend `applyEvent()` updates it identically. No field in the snapshot should require the frontend to re-fold, filter, or merge.

### `ConversationEntry` — why this model

The primary agent's activity is a timeline of events: reasoning blocks, text output, tool calls, step transitions. These form a sequential conversation that the UI renders as-is. The model name `ConversationEntry` reflects this — it is one entry in that conversation.

The key properties of this model:

- **Discriminated union on `type`** (`thinking`, `text`, `tool`, `step`): the frontend branch on this field to pick the right rendering component. All other fields are optional and type-specific.
- **Merged, not incremental**: a `thinking` entry holds the full accumulated thinking text, not a delta. The fold merges consecutive deltas before flushing to an entry. This is what the live path already does via `thinkingBuffer`.
- **Agent-filtered**: only primary agent entries appear in `conversation`. Scout activity is tracked on the scout's own `AgentProjection.last_tool`.
- **In-flight tracking in the model**: `in_flight: bool` on tool entries lets the frontend show spinner vs checkmark without needing a separate `completedCallIds` set.

```python
class ConversationEntry(BaseModel):
    """A single entry in the primary agent's conversation timeline."""
    type: Literal["thinking", "text", "tool", "step"]

    # -- thinking --
    content: str | None = None            # accumulated thinking text (all deltas merged)

    # -- text --
    text: str | None = None               # accumulated stream text (all deltas merged)

    # -- tool --
    tool_type: str | None = None          # "read", "bash", "write", "edit", "grep", "ls", "other"
    tool_name: str | None = None          # display name (= tool_type, or original name for "other")
    call_id: str | None = None            # matched against tool_completed to clear in_flight
    in_flight: bool = False               # True until matching tool_completed received
    # typed tool metadata — set for the relevant tool_type, None otherwise:
    file: str | None = None               # read, write, edit
    lines: str | None = None              # read line range (e.g. "10-20")
    command: str | None = None            # bash
    pattern: str | None = None            # grep
    path: str | None = None               # ls
    summary: str | None = None            # tool_called (generic) fallback

    # -- step --
    step: int | None = None
    step_name: str | None = None
    total_steps: int | None = None
```

**Edge cases covered:**
- Multiple tool calls in one turn: each produces its own entry, accumulated in order.
- Thinking before tool call: thinking buffer flushed to entry when first tool arrives.
- Text before thinking (or thinking before text): transition triggers flush of the outgoing buffer.
- Koan MCP tools (`koan_complete_step`, etc.): filtered in the fold — they produce no `ConversationEntry`. The MCP endpoint's `tool_called`/`tool_completed` events are still in the raw log but the fold ignores them for the conversation. They are authoritative sources of `agent_step_advanced`, not tool display.
- Bootstrap step (step 0→1): `agent_step_advanced` with `step < 1` produces no step entry. The step header appears only when the agent reaches a named step.
- Incomplete thinking at snapshot time: `thinking_buffer` is non-empty. The entry is NOT yet created — the buffer is in the snapshot as-is, and the `isThinking` flag is derived from `thinking_buffer.length > 0`. This is correct: the live stream will continue producing deltas into the buffer.

### Fold rules for conversation entries

The backend fold maintains `conversation: list[ConversationEntry]` plus two transient accumulator fields (`thinking_buffer: str`, `stream_buffer: str`). The buffers accumulate incremental deltas and are flushed to completed entries when the output type changes or when a structural event (tool call, step advance, stream end) occurs.

**Why buffers in the projection (not the frontend only):**
The frontend's live fold already uses buffers for this purpose. Moving them to the projection means: (a) the snapshot captures mid-thought state accurately, and (b) the backend and frontend folds share the same algorithm. A client reconnecting mid-thought gets the partial thinking buffer in the snapshot and can display the live thinking card immediately.

| Event | Action |
|-------|--------|
| `thinking` (primary agent only) | If `stream_buffer` non-empty → flush to `text` entry, clear. Append delta to `thinking_buffer`. |
| `stream_delta` (primary agent only) | If `thinking_buffer` non-empty → flush to `thinking` entry, clear. Append delta to `stream_buffer`. |
| `tool_*` / `tool_called` (primary, non-koan) | Flush both buffers. Append typed tool entry with `in_flight=True`. |
| `tool_called` (koan MCP — `koan_*` prefix) | Ignore for conversation. Do not flush buffers. |
| `tool_completed` (primary agent only) | Set `in_flight=False` on entry matching `call_id`. |
| `agent_step_advanced` (primary agent only) | Flush both buffers. If `step >= 1`: append step entry. Update step/tokens on `primary_agent`. |
| `agent_step_advanced` (scout) | Update step/tokens on scout's `AgentProjection`. No conversation entry. |
| `stream_cleared` (primary agent only) | Flush both buffers. |
| Any activity event for non-primary agent | Update scout's `last_tool`. Do NOT touch `conversation` or buffers. |

**Why primary-agent filtering is in the fold, not the frontend:**
The fold owns the semantics of what belongs in the primary agent's conversation. Scattering this logic across the frontend's snapshot reconstruction and live event paths creates inconsistency — as seen in the bugs. A single authoritative filter in the fold means both paths are correct by construction.

**Why koan MCP tools are filtered in the fold:**
`koan_complete_step`, `koan_ask_question`, `koan_request_scouts` etc. are infrastructure calls — they drive the workflow state machine, not the primary agent's work. They have no meaningful display in the conversation timeline. Their effect is already captured by `agent_step_advanced`, `questions_asked`, and `scout_queued` events. Showing them as tool lines would be noise. The MCP endpoint still emits `tool_called`/`tool_completed` for these — that is intentional, as the raw event log preserves them for audit — but the fold does not materialize them into conversation entries.

### Full projection model

```python
class Projection(BaseModel):
    # -- Run state --
    run_started: bool = False
    phase: str = ""

    # -- Agents --
    primary_agent: AgentProjection | None = None
    scouts: dict[str, AgentProjection] = {}      # keyed by agent_id
    queued_scouts: list[QueuedScout] = []
    completed_agents: list[AgentProjection] = []

    # -- Primary agent conversation (materialized, ready to render) --
    conversation: list[ConversationEntry] = []
    thinking_buffer: str = ""                     # partial thinking block in progress
    stream_buffer: str = ""                       # partial text block in progress

    # -- Interactions --
    active_interaction: InteractionState | None = None

    # -- Artifacts --
    artifacts: dict[str, ArtifactInfo] = {}       # keyed by path

    # -- Notifications --
    notifications: list[NotificationEntry] = []

    # -- Workflow completion --
    completion: CompletionInfo | None = None

    # -- Configuration --
    config_runners: list[RunnerInfo] = []
    config_profiles: list[ProfileInfo] = []
    config_installations: list[InstallationInfo] = []
    config_active_profile: str = "balanced"
    config_scout_concurrency: int = 8
```

### Agent model

```python
class AgentProjection(BaseModel):
    agent_id: str
    role: str
    label: str = ""                               # scout identifier (e.g. "engine-methods")
    model: str | None = None
    step: int = 0
    step_name: str = ""
    started_at_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    status: Literal["running", "done", "failed"] = "running"
    error: str | None = None
    last_tool: str = ""                           # most recent tool summary (scouts only)
```

**Why `status`, `error`, `last_tool` move to the backend model:**
Currently these only exist on the frontend's `AgentInfo`. The snapshot would need to carry them for the agent monitor to display correct state after refresh. They are derived facts about agent state — they belong in the projection.

**Why `label` is already in the backend `agent_spawned` payload:**
`label` carries the scout's human-readable identifier (e.g., `engine-methods`, `spec-etag`) which comes from `q["id"]` in `koan_request_scouts`. This was added to `build_agent_spawned` as part of the scout naming work. It belongs on `AgentProjection` as a display field.

### What changes

| Field | Current | Target |
|-------|---------|--------|
| `activity_log: list[dict]` | Raw event dicts, no merging, no filtering | **Removed.** Replaced by `conversation: list[ConversationEntry]` |
| `stream_buffer: str` | Exists, cleared on `stream_cleared` | Stays — fold logic remains here |
| (new) `thinking_buffer: str` | Frontend-only | Moves to projection — backend fold accumulates |
| (new) `conversation` | Frontend-only (`activityLog`) | Backend fold produces the identical structure |
| `AgentProjection.status` | Frontend-only | Backend fold sets on `agent_exited` |
| `AgentProjection.error` | Frontend-only | Backend fold sets on `agent_exited` |
| `AgentProjection.last_tool` | Frontend-only | Backend fold updates on tool events for scouts |
| `AgentProjection.label` | Already in backend | Already in backend ✓ |

---

## Frontend `applySnapshot` (after)

With a properly materialized projection, `applySnapshot` becomes a direct mapping — no re-folding:

```typescript
applySnapshot: (data) => {
  const state = data.state
  set({
    lastVersion: data.version,
    phase: state.phase,
    runStarted: state.run_started,
    primaryAgent: state.primary_agent ? transformAgent(state.primary_agent) : null,
    scouts: transformScouts(state.scouts),
    queuedScouts: state.queued_scouts,
    completedAgents: state.completed_agents.map(transformAgent),

    // Direct read — no re-folding, no merging, no filtering
    activityLog: state.conversation,
    thinkingBuffer: state.thinking_buffer,
    streamBuffer: state.stream_buffer,
    isThinking: state.thinking_buffer.length > 0,

    activeInteraction: state.active_interaction,
    artifacts: state.artifacts,
    notifications: state.notifications,
    completion: state.completion,
    configProfiles: state.config_profiles,
    configInstallations: state.config_installations,
    configActiveProfile: state.config_active_profile,
    configScoutConcurrency: state.config_scout_concurrency,
    configRunners: state.config_runners,
  })
}
```

No `completedCallIds` set, no `flatMap`, no thinking merging, no agent filtering, no raw-event re-interpretation. The snapshot IS the view.

---

## Frontend `applyEvent` (after)

The live fold stays the same conceptually — it's already correct. The `flushThinkingBuffer()` / `flushStreamBuffer()` / `flushBuffers()` helpers stay. The entries they produce must match `ConversationEntry` field names exactly:

```typescript
// Flush thinking buffer → ConversationEntry type "thinking"
{ type: "thinking", content: thinkingBuffer }

// Flush stream buffer → ConversationEntry type "text"
{ type: "text", text: streamBuffer }

// Tool event → ConversationEntry type "tool"
{ type: "tool", tool_type: "read", call_id: "...", in_flight: true, file: "/path" }

// Step advance → ConversationEntry type "step"
{ type: "step", step: 3, step_name: "Ask", total_steps: 5 }
```

**Why snake_case field names throughout:**
Pydantic's `model_dump()` produces snake_case by default. Aligning the TypeScript interface to snake_case eliminates a camelCase conversion layer at the boundary. The existing frontend convention is to accept snake_case from the API and leave conversion to individual `transformAgent()` helpers where needed; `ConversationEntry` fields are read directly from the snapshot, so they should arrive in the shape they're used.

---

## Implementation Plan

### Phase 1: Backend fold produces materialized conversation

1. Define `ConversationEntry` Pydantic model in `koan/projections.py`
2. Add `conversation: list[ConversationEntry]` and `thinking_buffer: str` to `Projection`; remove `activity_log`
3. Add `status`, `error`, `last_tool` to `AgentProjection`
4. Rewrite fold cases for all activity events:
   - `thinking`: accumulate into `thinking_buffer` (primary only)
   - `stream_delta`: accumulate into `stream_buffer` (primary only)
   - `tool_read/write/edit/bash/grep/ls`: flush buffers, append typed tool entry (primary); update `last_tool` (scout)
   - `tool_called` (non-koan): flush buffers, append generic tool entry (primary); update `last_tool` (scout)
   - `tool_called` (koan MCP): ignore for conversation
   - `tool_completed`: set `in_flight=False` by `call_id` in `conversation`
   - `agent_step_advanced`: flush buffers, append step entry if `step >= 1` (primary); update step/tokens (any agent)
   - `stream_cleared`: flush both buffers
   - `agent_exited`: set `status`, `error` on the agent before moving to `completed_agents`
5. Update `get_snapshot()` — no changes needed; `model_dump()` will include `conversation` automatically

**Dependency:** Phase 1 must complete before Phase 2 — the frontend cannot read a materialized snapshot until the backend produces one.

### Phase 2: Frontend reads materialized snapshot

1. Define `ConversationEntry` TypeScript type in `frontend/src/store/index.ts` matching the Python model exactly (snake_case field names, same `type` discriminator values)
2. Rewrite `applySnapshot` to directly read `conversation`, `thinking_buffer`, `stream_buffer` — remove all re-folding code (the `flatMap`, `completedCallIds` set, thinking merge loop, agent filtering)
3. Update `applyEvent` to produce `ConversationEntry`-shaped objects: rename `ActivityEntry` fields to match (`thinkingContent` → `content`, `textContent` → `text`, `inFlight` → `in_flight`, etc.)
4. Update `ActivityFeed` component — it renders `ConversationEntry[]`; field names may need updating in render components

### Phase 3: Tests

1. Update backend projection fold tests — assert `conversation` entries and `thinking_buffer`, not raw `activity_log` dicts
2. Add tests for:
   - Thinking buffer merging (consecutive deltas → single entry content)
   - Scout filtering (scout tool events update `last_tool`, not `conversation`)
   - In-flight tracking (`tool_completed` sets `in_flight=False` by `call_id`)
   - Koan MCP tool filtering (no conversation entry produced)
   - Bootstrap step filtering (`step < 1` produces no step entry)
   - Buffer flushing on transitions (thinking → text, text → thinking, either → tool)
3. Snapshot round-trip test: fold N events → `get_snapshot()` → `applySnapshot()` on fresh frontend state → compare `activityLog` with live `applyEvent()` on same events

### Phase 4: Cleanup

1. Remove `ActivityEntry` TypeScript type — replaced by `ConversationEntry`
2. Remove dead `applySnapshot` re-folding code (now unreachable after Phase 2)
3. Update `docs/projections.md` (see Documentation Updates section)
4. Update `docs/architecture.md` (see Documentation Updates section)
5. Verify all views render correctly from snapshot recovery

---

## Risks & Decisions

**Thinking buffer in projection:**
The `thinking_buffer` is transient state that only matters for the "live tail". Including it in the snapshot means a reconnecting client picks up mid-thought state correctly — the active thinking card continues rather than disappearing on reconnect. The buffer is empty after any turn completes; it only holds content while the LLM is actively reasoning.

**Koan MCP tool filtering in fold:**
Currently filtered in the frontend's `applyEvent`. Must move to the backend fold — `tool_called` events with `koan_*` tool names should not produce conversation entries. The MCP endpoint's `begin_tool_call`/`end_tool_call` still emit these events and they remain in the raw event log (append-only invariant), but the fold skips them when building `conversation`.

**Primary agent identification:**
The fold needs to know which `agent_id` is the primary agent to decide whether to add to `conversation` or update scout `last_tool`. The projection already has `primary_agent.agent_id`. The fold checks `agent_id == projection.primary_agent.agent_id`.

**`ConversationEntry` field naming (snake_case):**
Must be identical between Python `model_dump()` and TypeScript. Using snake_case throughout eliminates a transformation layer and makes the snapshot-to-store path direct. The frontend's existing `ActivityEntry` uses camelCase (`inFlight`, `thinkingContent`) — these will be renamed during Phase 2.

**Scout `last_tool` as a formatted string:**
The fold formats a human-readable string like `"read /path/to/file"` or `"bash ls -la"`. This is a display concern embedded in the fold. It avoids the frontend needing to re-derive display text from structured fields, and the monitor only needs one field to render. If more structured scout data becomes needed (e.g., separate tool type and argument for richer UI), `last_tool` can be split into `last_tool_type: str` and `last_tool_detail: str`.

**`tool_completed` applied to completed conversation entries:**
`tool_completed` sets `in_flight=False` on the matching entry. The fold must scan `conversation` in reverse to find the matching `call_id`. This is O(n) in the number of conversation entries, but conversation length is bounded by run duration and tool calls per turn rarely exceed dozens.

---

## Migration / Backwards Compatibility

**Snapshot format change:**
The snapshot's `state` dict will no longer contain `activity_log`; it will contain `conversation`, `thinking_buffer`. Any client holding a stale connection when the server is updated will receive a `fatal_error` on their next reconnect (server version > client version), forcing a page reload. This is the existing handling for server restarts — no special migration needed.

**Existing event logs (in-memory):**
The `ProjectionStore.events` list stores raw `VersionedEvent` objects. These are unchanged — events are facts, the fold interpretation of them changes. An in-progress run at deployment time would lose its in-memory state on restart (koan is one-shot; server restart during a run is already a failure case handled by `fatal_error`).

**No on-disk migration:**
`activity_log` only exists in-memory in `ProjectionStore.projection`. It is not persisted to disk. The audit fold (`koan/audit/fold.py`) is independent and unaffected.

**Client version detection:**
The snapshot includes `version: int` and the frontend's `lastVersion` drives reconnect. There is no separate schema version field. If a new client connects to an old server (unlikely in practice — koan is one-shot), the snapshot will have `activity_log` instead of `conversation`. The frontend will silently render an empty activity feed. This is acceptable: old servers don't run long.

---

## Documentation Updates

These docs must be updated as part of Phase 4:

### `docs/projections.md` — primary updates

1. **Projection model section:** Replace the `activity_log: list[dict]` field with `conversation: list[ConversationEntry]` and `thinking_buffer: str`. Add the full `ConversationEntry` model definition (with field docs).

2. **Fold cases — Activity section:** Rewrite the activity fold table. Replace "append raw event to activity_log" with the actual fold rules: buffer accumulation, flush triggers, `in_flight` tracking, agent filtering, koan MCP filtering.

3. **"Why activity_log stores raw events" design decision:** Remove this section. Replace with "Why conversation is materialized, not raw" explaining the symmetric fold invariant and the bugs it prevents.

4. **"Why tool events are generic" design decision:** Update to reflect the typed tool events (`tool_read`, `tool_write`, etc.) that now exist. The rationale for generic `tool_called` as a fallback still applies, but the typed events are the primary path for known tools.

5. **Event Types section:** Add the 6 typed tool events (`tool_read`, `tool_write`, `tool_edit`, `tool_bash`, `tool_grep`, `tool_ls`) and `scout_queued` which are currently missing from this doc.

6. **`AgentProjection` model:** Add `status`, `error`, `last_tool`, `label` fields.

### `docs/architecture.md` — add invariant

Add a 7th core invariant (or extend Invariant 5 on projections):

> **Symmetric fold invariant:** The backend `fold()` in `koan/projections.py` and the frontend `applyEvent()` in `frontend/src/store/index.ts` must produce the same materialized state from the same event sequence. The snapshot sent to the client is the backend's materialized projection — the client reads it directly without re-folding, filtering, or interpreting raw events. When adding a new event type, add a fold case to both implementations.

This invariant explains why `applySnapshot` must never contain ad-hoc event re-interpretation logic — that logic belongs in the fold.

### `koan/projections.py` — code comments

Add a module-level docstring clarifying:
- `Projection` fields are materialized views, not raw event stores
- `conversation` is the primary agent's timeline, filtered and merged by the fold
- `thinking_buffer` and `stream_buffer` are transient accumulators — they are part of projection state because reconnecting clients need mid-turn state

Add a comment on the `ConversationEntry` class explaining that field names are deliberately snake_case to allow direct JSON deserialization on the frontend without transformation.

### `AGENTS.md` — no changes required

The six core invariants in `AGENTS.md` do not need updating. The symmetric fold is a consequence of existing Invariant 5 (projections) and the general principle that the fold produces derived state from facts. The detail belongs in `docs/architecture.md`.

### `frontend/src/store/index.ts` — code comments

After the change, add a comment on `applySnapshot` explaining:
- The snapshot `state` is already the materialized view — no re-folding
- `conversation` maps directly to `activityLog`
- `thinking_buffer` and `stream_buffer` carry mid-turn state for reconnecting clients

Add a comment on `applyEvent` explaining that it must produce `ConversationEntry`-shaped objects and stay in sync with the backend fold in `koan/projections.py`.
