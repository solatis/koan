# Symmetric Projection Folds

**Date:** 2026-03-31
**Status:** Draft
**Goal:** Make backend and frontend projection folds produce identical materialized state, eliminating the need for ad-hoc re-interpretation during snapshot recovery.

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

This makes `activity_log` a **second copy of the raw event log** — not a materialized view. The frontend's `applySnapshot()` then has to re-fold this raw log into rich `ActivityEntry[]` structures (merge consecutive thinking deltas, filter to primary agent, map typed tools, compute in-flight status). This re-folding logic is separate from and inconsistent with the live `applyEvent()` fold, causing bugs:

- Fragmented thinking cards (each delta becomes its own card instead of being merged)
- Scout events leaking into the primary agent's activity feed (no agent filtering)
- Different entry shapes between live and recovered state

Meanwhile, the frontend's live `applyEvent()` does produce the correct rich view — but this logic is duplicated nowhere.

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

The snapshot is the **materialized projection state** — the client reads it directly into its store, then applies subsequent events via its local fold.

---

## Target Projection Shape

The projection is the single source of truth. Backend `fold()` produces it, `get_snapshot()` serializes it, frontend `applySnapshot()` reads it, frontend `applyEvent()` updates it identically.

### Primary agent conversation

The key insight: `activity_log` should be a **materialized conversation** — not a raw event log. The backend fold must produce the same structure the frontend renders.

```python
class ConversationEntry(BaseModel):
    """A single entry in an agent's conversation timeline."""
    type: Literal["thinking", "text", "tool", "step"]
    
    # -- thinking --
    content: str | None = None            # accumulated thinking text
    
    # -- text --
    text: str | None = None               # accumulated stream text
    
    # -- tool --
    tool_type: str | None = None          # "read", "bash", "write", "edit", "grep", "ls", "other"
    tool_name: str | None = None          # display name (tool_type or original name for "other")
    call_id: str | None = None
    in_flight: bool = False
    # tool metadata (typed)
    file: str | None = None               # read, write, edit
    lines: str | None = None              # read (e.g. "10-20")
    command: str | None = None            # bash
    pattern: str | None = None            # grep
    path: str | None = None               # ls
    summary: str | None = None            # generic tool_called fallback
    
    # -- step --
    step: int | None = None
    step_name: str | None = None
    total_steps: int | None = None
```

### Fold rules for conversation entries

The backend fold maintains a `conversation: list[ConversationEntry]` plus two transient buffers (`thinking_buffer: str`, `stream_buffer: str`). The buffers accumulate incremental deltas; they get flushed to conversation entries on transitions:

| Event | Action |
|-------|--------|
| `thinking` (primary agent only) | If `stream_buffer` non-empty → flush to `text` entry, clear. Append delta to `thinking_buffer`. |
| `stream_delta` (primary agent only) | If `thinking_buffer` non-empty → flush to `thinking` entry, clear. Append delta to `stream_buffer`. |
| `tool_*` / `tool_called` (primary agent only) | Flush both buffers. Append typed tool entry with `in_flight=True`. Skip koan MCP tools (`koan_*`, `mcp__koan*`). |
| `tool_completed` (primary agent only) | Set `in_flight=False` on entry matching `call_id`. |
| `agent_step_advanced` (primary agent only) | Flush both buffers. Append `step` entry (skip step < 1). |
| `stream_cleared` (primary agent only) | Flush both buffers. |
| Any activity event for non-primary agent | Update scout's `last_tool` (see agents section). Do NOT touch conversation. |

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
    
    # -- Primary agent conversation (materialized) --
    conversation: list[ConversationEntry] = []
    thinking_buffer: str = ""                     # transient accumulator
    stream_buffer: str = ""                       # transient accumulator
    
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
    last_tool: str = ""                           # most recent tool summary for scouts
```

Note: `status` and `last_tool` are added to the backend model. Currently `status` only exists on the frontend (`AgentInfo`). The backend `AgentProjection` should carry these so the snapshot is complete.

### What changes

| Field | Current | Target |
|-------|---------|--------|
| `activity_log: list[dict]` | Raw event dicts, no merging, no filtering | **Removed.** Replaced by `conversation: list[ConversationEntry]` |
| `stream_buffer: str` | Exists | Stays, but fold logic moves here from frontend |
| (new) `thinking_buffer: str` | Frontend-only | Moves to projection — backend fold accumulates |
| (new) `conversation` | Frontend-only (`activityLog`) | Backend fold produces the identical structure |
| `AgentProjection.status` | Frontend-only | Backend fold sets on `agent_exited` |
| `AgentProjection.last_tool` | Frontend-only | Backend fold updates on tool events for scouts |
| `AgentProjection.label` | Already in backend | Already in backend ✓ |

---

## Frontend `applySnapshot` (after)

With a properly materialized projection, `applySnapshot` becomes a direct mapping:

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
    
    // Direct read — no re-folding needed
    activityLog: state.conversation,        // already the right shape
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

The live fold stays the same conceptually — it's already correct. But it must produce `ConversationEntry`-shaped objects that match what the backend fold produces. The `flushThinkingBuffer()` / `flushStreamBuffer()` / `flushBuffers()` helpers stay, but the entries they produce must match `ConversationEntry`:

```typescript
// Flush thinking buffer → ConversationEntry of type "thinking"
{ type: "thinking", content: thinkingBuffer }

// Flush stream buffer → ConversationEntry of type "text"  
{ type: "text", text: streamBuffer }

// Tool event → ConversationEntry of type "tool"
{ type: "tool", tool_type: "read", call_id: "...", in_flight: true, file: "/path" }
```

The field names and shapes must match exactly between Python's `ConversationEntry.model_dump()` and TypeScript's entry objects.

---

## Implementation Plan

### Phase 1: Backend fold produces materialized conversation

1. Define `ConversationEntry` as a Pydantic model in `koan/projections.py`
2. Add `conversation: list[ConversationEntry]`, `thinking_buffer: str`, rename/remove `activity_log`
3. Add `status`, `error`, `last_tool`, `label` to `AgentProjection`
4. Rewrite fold cases for all activity events to produce `ConversationEntry` items:
   - `thinking`: accumulate into `thinking_buffer` (primary only)
   - `stream_delta`: accumulate into `stream_buffer` (primary only)
   - `tool_*` / `tool_called`: flush buffers → entries, append tool entry (primary); update `last_tool` (scout)
   - `tool_completed`: set `in_flight=False` by `call_id`
   - `agent_step_advanced`: flush buffers → entries, append step entry (primary); update step/tokens (any agent)
   - `stream_cleared`: flush buffers
   - `agent_exited`: set `status`, `error` on the agent before moving to completed
5. Update `get_snapshot()` — `model_dump()` now includes `conversation` instead of `activity_log`

### Phase 2: Frontend reads materialized snapshot

1. Define `ConversationEntry` TypeScript type matching the Python model exactly
2. Rewrite `applySnapshot` to directly read `conversation`, `thinking_buffer`, `stream_buffer` — remove all re-folding logic
3. `applyEvent` produces `ConversationEntry`-shaped objects (rename fields to match)
4. `ActivityFeed` renders `ConversationEntry[]` — field names may need updating

### Phase 3: Tests

1. Update backend projection fold tests — assert `conversation` entries, not raw `activity_log` dicts
2. Add specific tests for thinking merging, scout filtering, in-flight tracking in the fold
3. Verify snapshot→frontend round-trip: fold N events, take snapshot, feed to `applySnapshot`, compare with live `applyEvent` applied to same events

### Phase 4: Cleanup

1. Remove `activity_log` from `Projection`
2. Remove dead `applySnapshot` re-folding code from frontend
3. Remove `ActivityEntry` type — replaced by `ConversationEntry`
4. Verify all views render correctly from snapshot recovery

---

## Risks & Decisions

- **Thinking buffer in projection**: The `thinking_buffer` is transient state that only matters for the "live tail". After snapshot recovery, it's either empty (agent isn't thinking) or has partial content (agent is mid-thought). This is correct — the snapshot captures the current state.

- **Koan MCP tool filtering in fold**: Currently filtered in the frontend's `applyEvent`. Must move to the backend fold — `tool_called` events with `koan_*` tool names should not produce conversation entries. The MCP endpoint's `begin_tool_call`/`end_tool_call` still emit these events for the raw event log, but the fold skips them.

- **Primary agent identification**: The fold needs to know which `agent_id` is the primary agent to decide whether to add to conversation or update scout lastTool. The projection already has `primary_agent.agent_id`.

- **ConversationEntry field naming**: Must be identical between Python `model_dump()` and TypeScript. Use snake_case everywhere (Pydantic default). Frontend accesses `entry.call_id`, `entry.in_flight`, `entry.tool_type`, etc.

- **Scout `last_tool` as a string**: The fold formats a human-readable string like `"read /path/to/file"` or `"bash ls -la"`. This is a display concern in the fold, but it's simple and avoids the frontend needing to re-derive it.
