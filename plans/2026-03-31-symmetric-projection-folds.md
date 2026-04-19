# Server-Authoritative State with JSON Patch

**Date:** 2026-03-31
**Status:** Draft
**Goal:** Single fold in Python, server-computed diffs via JSON Patch, frontend as a dumb renderer with zero business logic.

---

## Motivation

Two user-visible bugs on page refresh exposed a deeper architectural problem:

**Bug 1 — Fragmented thinking cards:** After refresh, thinking was displayed as dozens of tiny cards ("The", "user wants", "me to call"…) instead of one merged block. The live path accumulated deltas in a buffer; the snapshot path created one card per raw event.

**Bug 2 — Scout events in the primary feed:** After refresh, scout step headers and thinking blocks appeared in the primary agent's activity feed. The live path filtered by agent; the snapshot path did not.

**Root cause:** The backend's `activity_log` stored raw events, not materialized state. The frontend re-folded this raw log on snapshot recovery — duplicating fold logic inconsistently. But the deeper question is: **why does the frontend run fold logic at all?**

The answer: it shouldn't. The fold exists in one place (Python). The frontend applies server-computed state changes mechanically. This is how Google Docs, Figma, Linear, and Phoenix LiveView work — server computes, client renders.

---

## Architecture

### Core principle: server computes, client applies

The fold runs **only in Python**. The frontend has **zero business logic** — no event interpretation, no buffer management, no agent filtering, no in-flight tracking. It receives state and renders it.

### Protocol: snapshot + JSON Patch

The server sends two types of SSE messages:

| SSE event | When | Payload | Client action |
|-----------|------|---------|---------------|
| `snapshot` | First connect, reconnect | `{version, state}` — full materialized projection (camelCase) | Replace entire store |
| `patch` | After each event | `{version, patch}` — RFC 6902 JSON Patch operations (camelCase paths) | `applyPatch(store, patch)` |

**Everything goes through JSON Patch — including thinking and text deltas.** A thinking delta produces a `replace` on the agent's `pendingThinking` field carrying the full accumulated string. At 10KB of accumulated thinking with 20 deltas/second, this is ~200KB/s of patches. On a remote server this would warrant a special-cased delta bypass. But koan is a localhost tool — loopback traffic doesn't hit a NIC, and 200KB/s is noise compared to the LLM API traffic that dwarfs it. **The simplicity of a uniform protocol (two event types, two handlers, zero special cases) is worth more than the bandwidth savings of a third event type that only matters at scale we'll never hit.**

### Connection lifecycle

```
First connect:     GET /events?since=0
                   ← snapshot {version: N, state: {...}}         (camelCase keys)
                   ← patch {version: N+1, patch: [...]}          (camelCase paths)
                   ← patch {version: N+2, patch: [...]}
                   ...

Reconnect:         GET /events?since=N+2
                   ← snapshot {version: M, state: {...}}
                   (always a fresh snapshot — no patch replay)

Server restart:    GET /events?since=N+2
                   ← snapshot {version: 0, state: {settings: {...}, run: null}}
                   (client detects version < lastVersion, resets UI)
```

**Catch-up always uses snapshots.** The `since` parameter is a version check: if it matches the server's current version, skip the snapshot and stream live events. Otherwise, send a fresh snapshot. This eliminates the `events_since()` replay path (500K events × variable patch sizes = unbounded memory) and the `fatal_error` case (server restart caused `since > store.version`, requiring manual reload). One code path handles all reconnects; the client detects version regression and resets automatically.

### What the server stores

| Store | Purpose | Lifetime |
|-------|---------|----------|
| `self.events: list[VersionedEvent]` | Audit log, debugging | Session (in-memory) |
| `self.projection: Projection` | Materialized state for snapshots + diff computation | Session |
| `self.prev_state: dict` | Previous `to_wire()` for computing patches | Overwritten each event |

No stored patches. No catch-up replay buffer.

### Server-side push_event flow

```python
def push_event(self, event_type, payload, agent_id=None):
    self.version += 1
    event = VersionedEvent(version=self.version, ...)
    self.events.append(event)          # append-only audit log — never modified

    old_state = self.prev_state        # camelCase dict from previous to_wire()
    self.projection = fold(self.projection, event)
    new_state = self.projection.to_wire()   # camelCase — patch paths will be camelCase
    self.prev_state = new_state

    patch = jsonpatch.make_patch(old_state, new_state)
    if not patch:
        return  # fold produced no state change (e.g. koan MCP tool filtered by fold)
                # no message broadcast — subscribers stay at the same version

    msg = {"type": "patch", "version": self.version, "patch": patch.to_string()}
    # Snapshot self.subscribers before iterating — a subscriber may be added
    # or removed concurrently (asyncio, not threading, but still defensive)
    for q in list(self.subscribers):
        q.put_nowait(msg)
```

Every event takes the same path: fold, diff, broadcast. No branching on event type. Subscriber queues carry **plain dicts** — the dict shape matches the SSE JSON payload directly.

### Server-side sse_stream flow

```python
async def sse_stream(request: Request, since: int = 0):
    queue = asyncio.Queue()
    store = request.app.state.projection_store

    # Version check: decide whether to send a snapshot first.
    # The only branching is "same version or not" — no event replay, no fatal_error.
    if since != store.version:
        # Client is behind (reconnect) or ahead (server restarted).
        # Either way, a fresh snapshot is the correct recovery.
        yield sse_event("snapshot", {
            "version": store.version,
            "state": store.projection.to_wire(),
        })

    # Subscribe to live patches. From here, every message is a dict
    # with {"type": "patch", "version": N, "patch": "..."} — we just
    # forward it as an SSE event with the dict's "type" as the event name.
    store.subscribers.add(queue)
    try:
        while True:
            msg = await queue.get()           # plain dict from push_event
            yield sse_event(msg["type"], msg) # "patch" event with JSON payload
    finally:
        store.subscribers.discard(queue)
```

The consumer is trivial — it reads dicts from the queue and serializes them. No interpretation, no filtering, no transformation.

### Wire format: camelCase via Pydantic aliases

The server emits camelCase JSON. The frontend applies it directly — no field renaming, no shadow state, no mapping function.

Pydantic's `alias_generator` handles the conversion at serialization boundaries. Python fold code uses snake_case attributes (`agent.conversation.pending_thinking`). Only `to_wire()` output is camelCase:

```python
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

class KoanBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,   # snake_case → camelCase at serialization
        populate_by_name=True,       # Python code still uses snake_case attributes;
                                     # only the JSON output uses camelCase aliases
    )

    def to_wire(self) -> dict:
        """Serialize for snapshots and JSON Patch computation.

        Always produces camelCase keys via the alias_generator.
        Call this at the two serialization boundaries:
          - ProjectionStore.push_event(): to_wire() twice (before and after fold)
            to compute the JSON Patch diff
          - get_snapshot(): to_wire() once to build the snapshot payload
        Never call model_dump() directly on projection objects — that produces
        snake_case keys and breaks patch paths on the frontend.
        """
        return self.model_dump(by_alias=True)
```

All projection models inherit from `KoanBaseModel`. Snapshot JSON and patch paths are all camelCase. The frontend receives `pendingThinking`, `scoutConcurrency`, `isThinking` — matching JavaScript conventions natively.

**Why not keep snake_case on the wire and rename in the frontend?** Because that requires a `mapProjectionToStore()` function that renames every field, a `projectionState` shadow variable for patch application, and maintenance of both in sync with the Projection model. Every new field needs a rename entry. That mapping layer *is* business logic — it contradicts the "frontend has zero business logic" principle. Emitting camelCase from the server eliminates the layer entirely: patches apply directly to the store, snapshots spread directly into the store, adding a field to the Projection requires zero frontend changes.

### Frontend — complete implementation

```typescript
// Module-level projection dict. fast-json-patch operates on plain JS objects,
// not on Zustand state. Patches mutate this, then we spread it into the store.
let storeState: Record<string, unknown> = {}

es.addEventListener('snapshot', (e) => {
  const { version, state } = JSON.parse(e.data)
  storeState = state                         // replace wholesale on every snapshot
  set({ lastVersion: version, ...state })    // spread all camelCase fields into store
})

es.addEventListener('patch', (e) => {
  const { version, patch } = JSON.parse(e.data)
  // applyPatch with mutate:false returns { newDocument } — a new object
  // rather than modifying storeState in-place. This matters because Zustand
  // may still hold a reference to the previous storeState for the current render.
  storeState = applyPatch(storeState, patch, /*validate*/false, /*mutate*/false).newDocument
  set({ lastVersion: version, ...storeState })
})
```

That is the **entire** frontend sync implementation. Two handlers. No `applyEvent`. No 33-case switch. No fold logic. No buffer management. No agent filtering. No field renaming. No special cases.

**`storeState`** is a module-level variable in `connect.ts` — the raw projection dict for patch application. It must be a plain JS object because `fast-json-patch`'s `applyPatch` operates on plain objects. On snapshot, it is replaced wholesale. On patch, `applyPatch` returns a `newDocument` (immutable variant — avoids mutating state Zustand may still reference).

**Error handling:** If `applyPatch` throws, the client's local state may be inconsistent. The recovery path is the same as any connection failure — reconnect for a fresh snapshot:

```typescript
es.addEventListener('patch', (e) => {
  try {
    const { version, patch } = JSON.parse(e.data)
    storeState = applyPatch(storeState, patch, false, false).newDocument
    set({ lastVersion: version, ...storeState })
  } catch (err) {
    console.error('Patch failed, reconnecting for fresh snapshot:', err)
    es.close()                               // tear down broken connection
    set({ lastVersion: 0 })                  // force snapshot on reconnect
    setTimeout(() => connect(set), 1000)     // reconnect after brief backoff
  }
})
```

**Ordering guarantee:** SSE is connection-ordered. Patches cannot arrive out of order. If the connection drops, the client reconnects and gets a fresh snapshot. The `version` field is diagnostic only.

---

## Rejected alternatives

### Dual folds (symmetric fold in Python + TypeScript)

| Concern | Dual folds | JSON Patch |
|---------|-----------|------------|
| Fold implementations | 2 — must stay in sync forever | **1 (Python only)** |
| New event type cost | Python fold + TS fold + TS snapshot | **Python fold only** |
| Bug surface | event_type_count × 2 | event_type_count × 1 |
| Frontend complexity | 33-case switch, buffer management, agent filtering | **2 event listeners, zero logic** |
| Correctness | Requires discipline ("symmetric fold invariant") | **Correct by construction** |

The dual-fold approach is *complected*: fold logic interleaved with two language runtimes. JSON Patch eliminates the invariant because the logic exists in one place.

### WASM shared fold

Compile fold to WASM, run in both Python and browser. Eliminates duplication but adds WASM toolchain, FFI boundaries, and build complexity. Over-engineered for a single-user local tool.

### Server-rendered HTML (LiveView)

Server renders the full UI, sends DOM diffs. Zero client logic. But koan's UI has rich interactivity — question wizards, settings overlays, artifact browsing, drag interactions. LiveView fights against client-side interactivity.

### Delta bypass for streaming

Special-case `thinking`/`stream_delta` events: send raw string deltas instead of JSON Patch `replace` operations. Saves bandwidth (600B/s vs 200KB/s for thinking). Rejected because koan is localhost — loopback bandwidth is free, and the complexity of a third event type (third handler, branching in `push_event`, special-case in frontend) is not worth the savings. Two event types, two handlers, zero special cases.

---

## Projection Model

The projection is the single materialized view of all state. It has a layered structure:

- **Projection** — top level: `settings`, `run`, `notifications`
  - **Settings** — persistent config: installations, profiles, defaults
    - **Installation** — a configured LLM CLI binary
    - **Profile** — maps roles to installations
  - **Run** — ephemeral workflow state (or `None`)
    - **RunConfig** — frozen configuration for this run
    - **Agent** — identity + lifecycle + progress + conversation
      - **Conversation** — timeline entries + pending fields + token stats
        - **ConversationEntry** — discriminated union of 10 entry types
    - **Focus** — discriminated union: what the main content area renders
    - **ArtifactInfo**, **CompletionInfo** — existing types, unchanged
  - **Notification** — transient UI toasts

Each class is defined below in dependency order.

### Top-level structure

The projection has three concerns with different lifetimes:

```python
class Projection(KoanBaseModel):
    settings: Settings = Settings()        # persistent config + probe results
    run: Run | None = None                 # None when no run is active
    notifications: list[Notification] = [] # transient UI toasts
```

`run is None` → show landing page. `run.completion is not None` → run finished (show results + summary). The `run` object is **not** set to `None` on completion — it persists so the user can review the final conversation, artifacts, and token usage. It resets to `None` only when the user starts a new run (the `run_started` event creates a fresh `Run`).

`notifications` are transient UI toasts (e.g. "agent spawn failed", "probe completed"). They span both settings and run events, which is why they live at the top level rather than inside `run`. They are currently append-only; a future `notification_dismissed` event could remove them. No boolean flags anywhere.

### Settings

Settings are what's *available* — they exist before any run, persist across runs to `~/.koan/config.json`, and describe the user's configured environment.

```python
class Installation(KoanBaseModel):
    """A configured LLM CLI installation."""
    alias: str                             # unique key: "claude-default", "claude-fast"
    runner_type: str                       # "claude" | "codex" | "gemini"
    binary: str                            # resolved path: "/usr/local/bin/claude"
    extra_args: list[str] = []             # e.g. ["--effort", "low"]
    available: bool = False                # probe result: binary exists and responds
    # Everything except `available` persists to config.json.
    # `available` is ephemeral — re-probed each server start.
    # Replaces the separate `config_runners` concept: the list of available
    # runner types is derivable from installations where available == True.

class Profile(KoanBaseModel):
    """Maps roles to installations for a workflow run."""
    name: str                              # "balanced", "thorough", "fast"
    read_only: bool = False                # built-in profiles can't be edited
    tiers: dict[str, str] = {}             # role → installation alias
                                           # {"primary": "claude-default", "scout": "haiku-default"}

class Settings(KoanBaseModel):
    installations: dict[str, Installation] = {}   # alias → Installation
    profiles: dict[str, Profile] = {}             # name → Profile
    default_profile: str = "balanced"             # pre-selected for next run
    default_scout_concurrency: int = 8            # default for next run
    # installations and profiles are dicts (not lists) because JSON Patch
    # paths for named entities must be stable — /settings/installations/claude-fast
    # not /settings/installations/2 which shifts on insert/delete.
```

### Run configuration

Run configuration describes *how a specific run uses settings*. Resolved from settings at run start, frozen for the run's lifetime.

```python
class RunConfig(KoanBaseModel):
    """Resolved configuration for a single workflow run."""
    profile: str                           # which profile was selected
    installations: dict[str, str]          # role → installation alias
                                           # resolved from profile tiers + user overrides on landing page
                                           # e.g. {"primary": "claude-default", "scout": "haiku-default"}
    scout_concurrency: int                 # may differ from settings.default_scout_concurrency
```

The distinction between settings and run config:

| | Settings | Run config |
|--|---------|-----------|
| Lifetime | Persists across runs | Single run |
| Mutation | Settings overlay, any time | Frozen at run start |
| `default_profile` | Pre-selected for next run | — |
| `profile` | — | Which profile this run uses |
| `scout_concurrency` | Default for next run | What this run uses |
| `installations` (map) | All configured installations | Role → alias mapping for this run |

### Agent

All agents — primary, scouts, queued — live in one dict keyed by `agent_id`. The lifecycle is a state machine on `status`. No separate collections, no `QueuedScout` type.

**Why `dict[str, Agent]` not `list[Agent]`?** JSON Patch paths for list elements use positional indices (`/run/agents/2`). If an agent is removed or the list is reordered, subsequent indices shift and pending patches become invalid. Dict keys are stable: `/run/agents/abc123` refers to the same agent regardless of insertions or removals.

```python
class Agent(KoanBaseModel):
    # Identity — set at queue/spawn time, never changes
    agent_id: str
    role: str                              # "intake", "brief-writer", "implementer", ...
    label: str = ""                        # human-readable: "engine-methods" for scouts
    model: str | None = None               # "sonnet", "haiku", "opus"
    is_primary: bool = False

    # Lifecycle — state machine: queued → running → done | failed
    status: Literal["queued", "running", "done", "failed"] = "queued"
    error: str | None = None               # set when status → failed
    started_at_ms: int = 0                 # 0 while queued

    # Progress — shown in agent monitor, updated during execution
    step: int = 0
    step_name: str = ""
    last_tool: str = ""                    # last tool summary for monitor display

    # Content
    conversation: Conversation = Conversation()
```

The frontend derives views by filtering on `status` and `is_primary`. These are Zustand selectors — React components subscribe to them and re-render when the result changes:

```typescript
// Agent monitor: grouped sections
const agents = useStore(s => s.run?.agents ?? {})
const primary = Object.values(agents).find(a => a.isPrimary)       // at most one
const running = Object.values(agents).filter(a => !a.isPrimary && a.status === 'running')
const queued  = Object.values(agents).filter(a => a.status === 'queued')
const done    = Object.values(agents).filter(a => a.status === 'done' || a.status === 'failed')

// Activity feed: conversation of the focused agent
const focusId = useStore(s => s.run?.focus?.agentId)
const conversation = useStore(s =>
  focusId ? s.run?.agents?.[focusId]?.conversation : undefined
)
```

### Conversation

Per-agent. Groups everything about what an agent has said, done, and cost. The primary agent's conversation is rendered in the activity feed. Scout conversations are available for the agent monitor.

```python
class Conversation(KoanBaseModel):
    entries: list[ConversationEntry] = []   # materialized timeline
    pending_thinking: str = ""              # in-progress LLM reasoning, not yet flushed to ThinkingEntry
    pending_text: str = ""                  # in-progress LLM text output, not yet flushed to TextEntry
    is_thinking: bool = False               # True while thinking deltas are arriving
    input_tokens: int = 0                   # accumulated from usage reports in agent_step_advanced
    output_tokens: int = 0
```

**Why `Conversation` is a sub-object, not fields directly on `Agent`?** `Agent` describes who the agent is and where it is in the workflow (identity + lifecycle + progress). `Conversation` describes what the agent has said and what it cost. These change at different rates and serve different UI concerns — `step`/`status` update for every agent in the monitor, while `entries`/`pending_thinking` update only for the visible conversation. Separating them also makes `agent.conversation` a natural unit to pass to `ActivityFeed` as a single prop.

**Why `pending_thinking` / `pending_text`, not `thinkingBuffer` / `streamBuffer`?** "Buffer" describes the mechanism (accumulate, flush, reset). "Pending" describes the content: incomplete LLM output that will become a conversation entry on the next transition. The names should describe *what it is*, not *how it works*.

**Why tokens are in Conversation, not Agent:** They're accumulated from conversation turns (each `agent_step_advanced` carries usage). They describe the cost of what the agent said, not the agent's identity or lifecycle.

**Why `is_thinking` is a projection field, not derived:** The fold sets `is_thinking = True` when a thinking delta arrives and `False` on any transition. It arrives via patch like everything else. The frontend reads a boolean — no derivation logic.

### Focus

What the main content area renders. A discriminated union managed by the fold. Replaces the implicit "if interaction exists, show it, else show primary" logic.

```python
class ConversationFocus(KoanBaseModel):
    """Default state: showing an agent's conversation."""
    type: Literal["conversation"] = "conversation"
    agent_id: str                          # whose conversation to render

class QuestionFocus(KoanBaseModel):
    """Agent is blocked, needs user input."""
    type: Literal["question"] = "question"
    agent_id: str                          # who asked (conversation is backdrop)
    token: str                             # correlation ID for response
    questions: list[AskQuestion]           # existing koan type (koan/web/interactions.py)

class ReviewFocus(KoanBaseModel):
    """Agent is blocked, artifact needs review."""
    type: Literal["review"] = "review"
    agent_id: str
    token: str
    path: str                              # artifact under review
    description: str
    content: str

class DecisionFocus(KoanBaseModel):
    """Workflow decision needed from user."""
    type: Literal["decision"] = "decision"
    agent_id: str
    token: str
    chat_turns: list[ChatTurn]             # existing koan type

Focus = Annotated[
    ConversationFocus | QuestionFocus | ReviewFocus | DecisionFocus,
    Field(discriminator="type"),
]
```

The fold manages transitions. `run.focus` starts as `None` (no agents yet). The first `agent_spawned` event for the primary agent sets it to `ConversationFocus` — from that point, the main content area always has an explicit state.

| Event | Focus transition |
|-------|-----------------|
| `agent_spawned` (primary) | `ConversationFocus(agent_id=...)` |
| `questions_asked` | `QuestionFocus(agent_id=..., token=..., questions=...)` |
| `questions_answered` | `ConversationFocus(agent_id=primary_id)` |
| `artifact_review_requested` | `ReviewFocus(...)` |
| `artifact_reviewed` | `ConversationFocus(agent_id=primary_id)` |
| `workflow_decision_requested` | `DecisionFocus(...)` |
| `workflow_decided` | `ConversationFocus(agent_id=primary_id)` |

The frontend rendering is a switch on `focus.type`:

```tsx
function MainContent({ focus, agents }: Props) {
  if (!focus) return null                    // no agents yet — nothing to show

  // Every focus variant has agentId — the conversation is always the backdrop
  const conversation = agents[focus.agentId]?.conversation

  switch (focus.type) {
    case 'conversation':                     // default: just the conversation
      return <ActivityFeed conversation={conversation} />
    case 'question':                         // agent blocked, needs user answer
      return <>
        <ActivityFeed conversation={conversation} dimmed />
        <QuestionWizard questions={focus.questions} token={focus.token} />
      </>
    case 'review':                           // agent blocked, artifact needs review
      return <ArtifactReview path={focus.path} content={focus.content} token={focus.token} />
    case 'decision':                         // workflow decision needed
      return <DecisionChat turns={focus.chatTurns} token={focus.token} />
  }
}
```

No conditional logic about "is there an active interaction." No implicit fallback to the primary agent. Every state of the main content area is explicitly modeled and rendered.

### ConversationEntry — discriminated union

Each entry type has exactly the fields it needs. No optional fields that only apply to other variants.

```python
class ThinkingEntry(KoanBaseModel):
    type: Literal["thinking"] = "thinking"
    content: str                           # full accumulated thinking text

class TextEntry(KoanBaseModel):
    type: Literal["text"] = "text"
    text: str                              # full accumulated output text

class StepEntry(KoanBaseModel):
    type: Literal["step"] = "step"
    step: int
    step_name: str
    total_steps: int | None = None

class BaseToolEntry(KoanBaseModel):
    """Shared fields for all tool entries."""
    call_id: str                           # unique per tool invocation
    in_flight: bool                        # True until tool_completed

class ToolReadEntry(BaseToolEntry):
    type: Literal["tool_read"] = "tool_read"
    file: str                              # path that was read
    lines: str = ""                        # line range, e.g. "1-50"

class ToolWriteEntry(BaseToolEntry):
    type: Literal["tool_write"] = "tool_write"
    file: str                              # path that was created or overwritten

class ToolEditEntry(BaseToolEntry):
    type: Literal["tool_edit"] = "tool_edit"
    file: str                              # path that was edited in-place

class ToolBashEntry(BaseToolEntry):
    type: Literal["tool_bash"] = "tool_bash"
    command: str                           # shell command executed

class ToolGrepEntry(BaseToolEntry):
    type: Literal["tool_grep"] = "tool_grep"
    pattern: str                           # search pattern

class ToolLsEntry(BaseToolEntry):
    type: Literal["tool_ls"] = "tool_ls"
    path: str                              # directory listed

class ToolGenericEntry(BaseToolEntry):
    """Catch-all for tools without a typed variant (e.g. custom MCP tools)."""
    type: Literal["tool_generic"] = "tool_generic"
    tool_name: str                         # original tool name from the LLM
    summary: str = ""                      # human-readable one-liner from the runner parser

ConversationEntry = Annotated[
    ThinkingEntry | TextEntry | StepEntry |
    ToolReadEntry | ToolWriteEntry | ToolEditEntry |
    ToolBashEntry | ToolGrepEntry | ToolLsEntry | ToolGenericEntry,
    Field(discriminator="type"),
]
```

**`tool_completed` handling:** The fold scans `agent.conversation.entries` for `isinstance(entry, BaseToolEntry) and entry.call_id == target`, sets `in_flight = False`.

**Extensibility:** Adding `ToolWebFetchEntry` means: define the model, add to the union, add a fold case. The frontend is unchanged — JSON Patch carries the new structure automatically.

### Supporting types

These existing types are referenced by `Run` and `Projection`. Key fields listed for completeness — full definitions remain in their current modules.

```python
class ArtifactInfo(KoanBaseModel):
    """A markdown document managed by the workflow."""
    path: str                              # relative to epic directory
    size: int                              # bytes
    modified_at: str                       # ISO 8601 timestamp

class CompletionInfo(KoanBaseModel):
    """Set when the workflow finishes."""
    success: bool
    summary: str = ""                      # human-readable result summary
    error: str | None = None               # set on failure

class Notification(KoanBaseModel):
    """Transient UI toast. Shown briefly, then fades."""
    message: str
    level: Literal["info", "warning", "error"] = "info"
    timestamp_ms: int
```

### Run

Ephemeral workflow state. Created by `run_started`, persists through completion for result viewing.

```python
class Run(KoanBaseModel):
    config: RunConfig                      # frozen at run start — never modified
    phase: str = ""                        # current workflow phase (e.g. "intake", "execution")
    agents: dict[str, Agent] = {}          # all agents by ID — primary, scouts, queued, completed
    focus: Focus | None = None             # what the main content area renders; None before first agent
    artifacts: dict[str, ArtifactInfo] = {}  # keyed by relative path (e.g. "docs/architecture.md")
    completion: CompletionInfo | None = None  # None during run; set by workflow_completed
```

### End-to-end: starting a run

```
1. User opens koan web UI
   ← Frontend connects to /events?since=0
   ← snapshot {settings: {installations: {...}, profiles: {...}, ...}, run: null}
   → Landing page renders: profile selector (from settings.defaultProfile),
     installation selector (from settings.installations where available == true)

2. User selects profile + installations, clicks "Start Run"
   → POST /api/start-run {profile: "balanced", installations: {"primary": "claude-default", ...}, scout_concurrency: 8}

3. Backend validates binaries, emits run_started event
   → fold creates Run(config=RunConfig(...))
   ← patch [{op: "add", path: "/run", value: {config: {...}, phase: "", agents: {}, ...}}]
   → Frontend: run is no longer null → switch from landing page to run view

4. Driver starts first phase, spawns primary agent
   → phase_started {phase: "intake"}
   → agent_spawned {agent_id: "intake-0", role: "intake", is_primary: true, ...}
   → fold: adds agent, sets focus = ConversationFocus(agent_id="intake-0")
   ← patches flow to frontend → activity feed appears
```

### Complete Projection

```python
class Projection(KoanBaseModel):
    settings: Settings = Settings()        # persists across runs, loaded from config.json + probe
    run: Run | None = None                 # None → landing page; set by run_started; persists after completion
    notifications: list[Notification] = [] # append-only toasts from both settings and run events
```

Three top-level fields. Everything else is nested where it belongs.

**JSON Patch paths:**

```
Settings:    /settings/installations/claude-default/available
             /settings/profiles/balanced/tiers/primary
             /settings/defaultProfile
             /settings/defaultScoutConcurrency

Run config:  /run/config/profile
             /run/config/scoutConcurrency

Agent:       /run/agents/abc123/status
             /run/agents/abc123/step
             /run/agents/abc123/lastTool

Conversation:/run/agents/abc123/conversation/pendingThinking
             /run/agents/abc123/conversation/entries/-
             /run/agents/abc123/conversation/isThinking
             /run/agents/abc123/conversation/inputTokens

Focus:       /run/focus
Artifacts:   /run/artifacts/docs~1architecture.md/size
Phase:       /run/phase
```

Named entities (installations, profiles, agents, artifacts) are dicts for stable patch paths. Ordered collections (conversation entries, notifications) are lists — append-only, so positional indices are stable.

---

## Fold rules

The fold is a pure function: `fold(projection, event) → projection`. It is the **only** place where business logic runs. Rules are grouped by the part of the projection they modify. An event may trigger rules in multiple groups (e.g. `agent_step_advanced` updates the agent's conversation AND its progress fields).

### Agent conversation

These rules apply to the agent identified by `event.agent_id`. Since every agent has its own conversation, there is no primary-agent filtering — the fold appends to the relevant agent's conversation unconditionally. The frontend chooses which conversation to render via `focus`.

"Flush" means: if the pending field is non-empty, create a completed entry (ThinkingEntry or TextEntry) with its content, append to `entries`, reset the field to `""`.

| Event | Action on agent's conversation |
|-------|-------------------------------|
| `thinking` | Flush `pending_text` → TextEntry. Append delta to `pending_thinking`. Set `is_thinking = True`. |
| `stream_delta` | Flush `pending_thinking` → ThinkingEntry. Append delta to `pending_text`. Set `is_thinking = False`. |
| typed tool (`tool_read`, `tool_write`, etc.) | Flush both pending fields. Append typed entry with `in_flight=True`. Set `is_thinking = False`. Update `agent.last_tool` with tool summary (e.g. `"read src/main.py:1-50"`). |
| `tool_called` (non-koan, no typed variant) | Flush both pending fields. Append `ToolGenericEntry` with `in_flight=True`. Set `is_thinking = False`. Update `agent.last_tool`. |
| `tool_called` where tool name starts with `koan_` | Skip — koan MCP tools are infrastructure. Effects already captured by `agent_step_advanced`, `questions_asked`, etc. |

**`tool_called` vs typed tool events:** The runner's stream parser decides which to emit. When it can extract structured metadata (file path, command, pattern), it emits a typed event (`tool_read`, `tool_bash`, etc.) *instead of* `tool_called`. When it cannot (custom MCP tools, unknown tool names), it emits `tool_called` as a fallback. The fold never receives both for the same invocation — it's one or the other.
| `tool_completed` | Set `in_flight=False` on the entry whose `call_id` matches. |
| `agent_step_advanced` | Flush both pending fields. Append StepEntry if `step >= 1`. Set `is_thinking = False`. **Cross-cutting:** updates `agent.step`, `agent.step_name` (progress) and accumulates `usage.input_tokens`, `usage.output_tokens` into `agent.conversation` (stats). |
| `stream_cleared` | Flush both pending fields. Set `is_thinking = False`. |

### Agent lifecycle

| Event | Action |
|-------|--------|
| `scout_queued` | Add `Agent(agent_id=scout_id, status="queued", ...)` to `run.agents`. |
| `agent_spawned` | Look up `agent_id` in `run.agents`. If found (scout was previously queued via `scout_queued`), transition: set `status="running"`, `started_at_ms`. If not found (first time seeing this agent — always the primary), create a new `Agent` with `status="running"`, `is_primary=True`, and add to `run.agents`. |
| `agent_exited` | Set `status="done"` or `"failed"`, set `error` if present. Accumulate final usage into conversation tokens. |
| `agent_spawn_failed` | Append to `notifications`. |

### Focus transitions

| Event | Action |
|-------|--------|
| `agent_spawned` (primary) | `run.focus = ConversationFocus(agent_id=...)` |
| `questions_asked` | `run.focus = QuestionFocus(agent_id=..., token=..., questions=...)` |
| `questions_answered` | `run.focus = ConversationFocus(agent_id=primary_agent_id)` |
| `artifact_review_requested` | `run.focus = ReviewFocus(...)` |
| `artifact_reviewed` | `run.focus = ConversationFocus(agent_id=primary_agent_id)` |
| `workflow_decision_requested` | `run.focus = DecisionFocus(...)` |
| `workflow_decided` | `run.focus = ConversationFocus(agent_id=primary_agent_id)` |

### Run lifecycle

| Event | Action |
|-------|--------|
| `run_started` | `projection.run = Run(config=RunConfig(...))` |
| `phase_started` | `run.phase = phase` |
| `workflow_completed` | `run.completion = CompletionInfo(...)` |

### Settings

| Event | Action |
|-------|--------|
| `probe_completed` | Set `available` flag on each installation in `settings.installations`. |
| `installation_created` | Add to `settings.installations`. |
| `installation_modified` | Update in `settings.installations`. |
| `installation_removed` | Remove from `settings.installations`. |
| `profile_created` | Add to `settings.profiles`. |
| `profile_modified` | Update in `settings.profiles`. |
| `profile_removed` | Remove from `settings.profiles`. |
| `default_profile_changed` | Set `settings.default_profile`. |
| `default_scout_concurrency_changed` | Set `settings.default_scout_concurrency`. |

### Artifacts

| Event | Action |
|-------|--------|
| `artifact_created` | Add to `run.artifacts`. |
| `artifact_modified` | Update in `run.artifacts`. |
| `artifact_removed` | Remove from `run.artifacts`. |

---

## Event Types (37 total)

### Lifecycle (8)

| Event | Payload |
|-------|---------|
| `run_started` | `{profile, installations, scout_concurrency}` |
| `phase_started` | `{phase}` |
| `agent_spawned` | `{agent_id, role, label, model, is_primary, started_at_ms}` |
| `agent_spawn_failed` | `{role, error_code, message, details?}` |
| `agent_step_advanced` | `{step, step_name, usage?, total_steps?}` |
| `agent_exited` | `{exit_code, error?, usage?}` |
| `workflow_completed` | `{success, summary?, error?}` |
| `scout_queued` | `{scout_id, label, model?}` |

### Activity (11)

| Event | Payload |
|-------|---------|
| `tool_called` | `{call_id, tool, args, summary}` |
| `tool_read` | `{call_id, tool:"read", file, lines}` |
| `tool_write` | `{call_id, tool:"write", file}` |
| `tool_edit` | `{call_id, tool:"edit", file}` |
| `tool_bash` | `{call_id, tool:"bash", command}` |
| `tool_grep` | `{call_id, tool:"grep", pattern}` |
| `tool_ls` | `{call_id, tool:"ls", path}` |
| `tool_completed` | `{call_id, tool, result?}` |
| `thinking` | `{delta}` |
| `stream_delta` | `{delta}` |
| `stream_cleared` | `{}` |

### Focus (6)

| Event | Payload |
|-------|---------|
| `questions_asked` | `{token, questions}` |
| `questions_answered` | `{token, cancelled, answers?}` |
| `artifact_review_requested` | `{token, path, description, content}` |
| `artifact_reviewed` | `{token, cancelled, accepted?, response?}` |
| `workflow_decision_requested` | `{token, chat_turns}` |
| `workflow_decided` | `{token, cancelled, decision?}` |

### Resources (3)

| Event | Payload |
|-------|---------|
| `artifact_created` | `{path, size, modified_at}` |
| `artifact_modified` | `{path, size, modified_at}` |
| `artifact_removed` | `{path}` |

### Settings (9)

| Event | Payload |
|-------|---------|
| `probe_completed` | `{results: {alias: available, ...}}` |
| `installation_created` | `{alias, runner_type, binary, extra_args}` |
| `installation_modified` | `{alias, runner_type, binary, extra_args}` |
| `installation_removed` | `{alias}` |
| `profile_created` | `{name, read_only, tiers}` |
| `profile_modified` | `{name, read_only, tiers}` |
| `profile_removed` | `{name}` |
| `default_profile_changed` | `{name}` |
| `default_scout_concurrency_changed` | `{value}` |

---

## Scale considerations

A full koan epic spans 10 tickets, each with multiple agent sessions and scout batches. The numbers below project the upper bound of state that the projection must handle.

**Event volume:** 20 markdown documents × 10 tickets = 200 artifacts. 5 primary agent sessions per ticket = 50 primary runs. 5 scout batches × 10 concurrent scouts = 250 scout sessions. Each scout produces ~50 tool calls and ~20 thinking blocks. Each primary agent produces ~200 tool calls and ~100 thinking blocks. Total: **200K–500K events over the epic.**

**Patch sizes by event type:**

| Event type | Patch size | Notes |
|-----------|-----------|-------|
| Tool call | ~100 bytes | `add` to `/run/agents/{id}/conversation/entries/-` |
| Step advance | ~200 bytes | Flush pending → `add` entry + `replace` step/step_name |
| `tool_completed` | ~80 bytes | `replace` on `/...entries/{N}/inFlight` |
| Thinking delta | ~10KB peak | `replace` on `pendingThinking` — O(accumulated_size). At 20 deltas/sec with 10KB accumulated = ~200KB/s. Acceptable on localhost. |
| Focus transition | ~500 bytes | `replace` on `/run/focus` with full focus object |
| Snapshot | ~50MB peak | Dominated by artifact content references. Sent only on connect/reconnect. |

**Why patch replay was rejected for catch-up:** Storing 500K patches for replay requires unbounded memory (patches vary from 80 bytes to 10KB+). A fresh 50MB snapshot sent once on reconnect is both cheaper and simpler — no replay buffer, no ordering logic, no partial-replay edge cases.

---

## Implementation Plan

### Phase 1: Backend — projection model + JSON Patch

1. `pip install jsonpatch` — add to dependencies
2. Define `KoanBaseModel` with `alias_generator=to_camel`, `populate_by_name=True`, and `to_wire()` method
3. Define all model classes: `Settings`, `Installation`, `Profile`, `RunConfig`, `Run`, `Agent`, `Conversation`, `Focus` variants, `ConversationEntry` union — all inheriting `KoanBaseModel`
4. Replace current `Projection` (15 top-level fields) with new `Projection` (3 fields: `settings`, `run`, `notifications`)
5. Add `run_started` event — creates `Run` with `RunConfig`
6. Rewrite fold: settings events → `projection.settings.*`, run events → `projection.run.*`, agent events → `projection.run.agents[id].*`, conversation events → `...agents[id].conversation.*`, focus events → `projection.run.focus`
7. Update `ProjectionStore.push_event()`: `to_wire()` for camelCase dicts, `make_patch` for diffs, uniform broadcast
8. Update `sse_stream()`: always-snapshot on reconnect, remove `events_since()`, remove `fatal_error`
9. Update `get_snapshot()` to use `to_wire()`

### Phase 2: Frontend — dumb renderer

1. `npm install fast-json-patch`
2. Define TypeScript types matching wire format (camelCase): `Projection`, `Settings`, `Run`, `Agent`, `Conversation`, `Focus`, `ConversationEntry`
3. Replace `connect.ts`: 2 event listeners (`snapshot`, `patch`), module-level `storeState`
4. Delete `applySnapshot`, `applyEvent`, `mapProjectionToStore`, `transformAgent`, `transformArtifact`, KNOWN_EVENTS
5. Update components: `ActivityFeed` reads `run.agents[focusId].conversation`, `AgentMonitor` filters `run.agents` by status, `SettingsOverlay` reads `settings.*`, `LandingPage` reads `settings.*` for defaults

### Phase 3: Tests

1. Fold tests: assert `conversation.entries`, `pending_thinking`, `is_thinking`, `in_flight` state per agent
2. Patch tests: fold event → verify JSON Patch operations target correct camelCase paths
3. Focus transition tests: interaction events produce correct focus variants
4. Settings/run separation tests: settings events don't touch `run`, run events don't touch `settings`
5. Snapshot round-trip: fold events → `to_wire()` → verify frontend-readable structure
6. Delete `events_since()` tests — replace with snapshot-based assertions

### Phase 4: Cleanup & docs

1. Remove dead frontend code
2. Remove `events_since()` from `ProjectionStore`
3. Update `docs/projections.md`: new model, two-message protocol, fold rules, localhost assumption for uniform patches
4. Update `docs/architecture.md`: "The fold runs only in Python. The frontend applies server-computed patches. It has no business logic."
5. Docstrings on `ProjectionStore` and `KoanBaseModel`

---

## Risks

**JSON Patch array diffing:** `make_patch` uses positional indices. Conversation entries are append-only (never reordered or removed), so patches are clean `add` operations. The one mutation is `tool_completed` setting `in_flight=False`, which produces a targeted `replace` at `/run/agents/{id}/conversation/entries/{N}/inFlight`.

**Nesting depth:** Paths like `/run/agents/abc123/conversation/entries/-` are 5 levels deep. Frontend access is `state.run?.agents?.[id]?.conversation?.entries`. Verbose, but selectors encapsulate the patterns. The nesting is meaningful — each level represents a real domain concept.

**Patch computation cost:** `make_patch` diffs two dicts. Proportional to what changed, not total state. Thinking deltas replace one string field — O(1) to detect, O(accumulated_size) payload. Acceptable on localhost.

**Library trust:** `jsonpatch` (Python) and `fast-json-patch` (JavaScript) — both mature, RFC 6902 compliant, widely used.

**Snapshot size:** ~50MB at peak. ~1 second on localhost. Gzip-compressible if needed.

---

## Documentation updates

### `docs/projections.md`

1. Replace `activity_log` with per-agent `Conversation` model. Document `ConversationEntry` union.
2. Replace "snapshot + raw events" SSE description with two-message protocol (`snapshot`, `patch`).
3. Rewrite fold rules: per-agent conversation, focus transitions, settings vs run separation.
4. Document localhost assumption for uniform JSON Patch (no delta bypass).
5. Document settings vs run config distinction.
6. Add all event types including `run_started`, `scout_queued`, typed tool events.
7. Remove "Why activity_log stores raw events" section.

### `docs/architecture.md`

Add invariant:

> **The fold runs only in Python.** The frontend applies server-computed JSON Patches mechanically. It has no fold logic, no event interpretation, and no business rules. When the frontend's view of state differs from the backend's, the bug is in the fold or the patch computation — not in the frontend.

### `koan/projections.py`

Module-level docstring documenting `ProjectionStore`: events (audit log), projection (materialized state), prev_state (for patch computation). Push flow: fold → to_wire → make_patch → broadcast. Uniform path, no branching. CamelCase via `KoanBaseModel`.

### `frontend/src/sse/connect.ts`

Comment documenting: snapshot → replace, patch → apply. Server emits camelCase. No field renaming. All events go through JSON Patch. Frontend has no fold logic.

---

## Migration

**Breaking change.** The SSE protocol changes from per-event-type messages to `snapshot`/`patch`. The projection structure changes completely (3 top-level fields, nested model). Old clients cannot connect to new servers.

**No on-disk migration.** All state is in-memory. Server restart forces a full reload. `~/.koan/config.json` schema is unchanged — the projection model restructuring is in-memory only.

**Deployment:** Single-user local tool. `pip install --upgrade koan` and restart.
