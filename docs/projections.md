# Projections

How koan maintains frontend-visible state as a versioned event log with a
materialized projection, served to the browser as JSON Patch diffs over SSE.

> Parent doc: [architecture.md](./architecture.md)

---

## Overview

The projection system maintains:

1. An **append-only versioned event log** — every fact that occurs during a
   workflow run, in order, with a monotonically increasing version number.
2. A **materialized projection** — the complete frontend-visible state derived
   by folding the event log with a pure function.
3. A **diff engine** — `jsonpatch.make_patch` computes RFC 6902 JSON Patch
   operations between projection states, broadcast to SSE subscribers.
4. A **subscriber mechanism** — one `asyncio.Queue` per connected SSE client,
   fed from `push_event()`.

The `/events` SSE endpoint sends a full snapshot on connect or reconnect, then
streams JSON Patch operations for every subsequent state change.

**Design invariant:** The fold runs only in Python. The frontend applies
server-computed patches mechanically — it has no fold logic, no event
interpretation, and no business rules.

---

## The Event Log

All events share a common envelope. `agent_id` is set when the event originates
from a specific agent; `None` otherwise.

```python
class VersionedEvent(BaseModel):
    version: int                    # 1-based, monotonic
    event_type: str                 # one of the event types (stored as str for forward compat)
    timestamp: str                  # ISO8601 UTC
    agent_id: str | None = None     # originating agent, when known
    payload: dict                   # typed per event_type (see below)
```

The log is append-only. Events are never modified or removed. The entire log is
held in memory for the duration of a workflow run.

---

## Event Types (38 total)

### Lifecycle (10)

| Event                 | Payload                                                     | `agent_id`    |
| --------------------- | ----------------------------------------------------------- | ------------- |
| `run_started`         | `{profile, scout_concurrency}`                              | `None`        |
| `workflow_selected`   | `{workflow}`                                                | `None`        |
| `phase_started`       | `{phase}`                                                   | `None`        |
| `agent_spawned`       | `{agent_id, role, label, model, is_primary, started_at_ms}` | set           |
| `agent_spawn_failed`  | `{role, error_code, message, details?}`                     | `None`        |
| `agent_step_advanced` | `{step, step_name, usage?, total_steps?}`                   | set           |
| `agent_exited`        | `{exit_code, error?, usage?}`                               | set           |
| `workflow_completed`  | `{success, summary?, error?}`                               | `None`        |
| `scout_queued`        | `{scout_id, label, model?}`                                 | `None`        |
| `yield_started`       | `{suggestions: [{id, label, command}, ...]}`                | set (primary) |
| `yield_cleared`       | `{}`                                                        | `None`        |

`yield_started` is emitted by `run_agent_loop` when the turn-outcome resolver
parks a primary agent at a phase-boundary hand-back. The fold appends a
`YieldEntry` to the agent's conversation and sets `run.active_yield`.
`yield_cleared` removes `run.active_yield`; it is emitted by `koan_set_phase`
(any transition, including `"done"`) and implicitly by `phase_started` and
`workflow_completed`.

`run_started` is emitted by `api_start_run` before the driver begins. It
creates the `Run` object in the projection with the frozen `RunConfig`.

`workflow_selected` is emitted immediately after `run_started`, recording the
workflow type chosen by the user. The fold sets `run.workflow` from this event.

`agent_spawned` does not carry `step` — step 0 is implied. `agent_exited` does
not carry `is_primary` — the fold looks up the agent in `run.agents`.

### Activity (11)

| Event            | Payload                          | `agent_id` |
| ---------------- | -------------------------------- | ---------- |
| `tool_called`    | `{call_id, tool, args, summary}` | set        |
| `tool_read`      | `{call_id, file, lines}`         | set        |
| `tool_write`     | `{call_id, file}`                | set        |
| `tool_edit`      | `{call_id, file}`                | set        |
| `tool_bash`      | `{call_id, command}`             | set        |
| `tool_grep`      | `{call_id, pattern}`             | set        |
| `tool_ls`        | `{call_id, path}`                | set        |
| `tool_completed` | `{call_id, tool, result?}`       | set        |
| `tool_failed`    | `{call_id, tool, error, ts_ms}`  | set        |
| `thinking`       | `{delta}`                        | set        |
| `stream_delta`   | `{delta}`                        | set        |
| `stream_cleared` | `{}`                             | set        |

`tool_called` and the typed tool events (`tool_read`, `tool_bash`, etc.) are
mutually exclusive for any given tool invocation. The in-process event fan-out
emits a typed event when it can extract structured metadata (file path, command,
pattern). It falls back to `tool_called` for unknown or custom koan tools. The
fold never receives both for the same `call_id`.

`tool_called` and `tool_completed` are paired by `call_id` (UUID). `in_flight`
on the conversation entry is `True` until `tool_completed` arrives.

`thinking` events are incremental deltas. The fold accumulates them into
`agent.conversation.pending_thinking`; the completed `ThinkingEntry` is created
on the next transition (tool call, step advance, or stream delta).

### Focus (2)

| Event                | Payload                        | `agent_id` |
| -------------------- | ------------------------------ | ---------- |
| `questions_asked`    | `{token, questions}`           | set        |
| `questions_answered` | `{token, cancelled, answers?}` | set        |

These events transition `run.focus` between variants of the `Focus` union.
Cancellation (`cancelled: true`) occurs when the agent exits while the
interaction is pending — there is no separate cancellation event type.

### User messages (1)

| Event          | Payload                   | `agent_id`          |
| -------------- | ------------------------- | ------------------- |
| `user_message` | `{content, timestamp_ms}` | set (primary agent) |

Emitted by `POST /api/chat` when the user sends a message during a run. The
fold appends a `UserMessageEntry` to the primary agent's conversation entries,
making user messages appear inline in the activity feed alongside agent output.

### Resources (3)

| Event               | Payload                     | `agent_id` |
| ------------------- | --------------------------- | ---------- |
| `artifact_created`  | `{path, size, modified_at}` | if known   |
| `artifact_modified` | `{path, size, modified_at}` | if known   |
| `artifact_removed`  | `{path}`                    | if known   |

`agent_id` is the primary agent at scan time (approximate -- scanning happens at
phase boundaries, not on individual file writes). `build_artifact_diff()` in
`koan/events.py` compares old and new artifact sets and emits individual events
for each difference.

**`ArtifactInfo` and `producedPhaseId`.** Each artifact in `run.artifacts` is
modeled as `ArtifactInfo(path, size, modified_at, produced_phase_id)`. The
`produced_phase_id` field is stamped once in the `artifact_created` fold arm
from `projection.run.phase` at the moment the event arrives, and is preserved
unchanged across all subsequent `artifact_modified` events -- an artifact's
producing phase never changes. On the wire the field is camelCase
(`producedPhaseId`) via the `KoanBaseModel` alias generator.

`derivePhaseNodes` in `frontend/src/store/selectors.ts` reads `producedPhaseId`
from each `ArtifactInfo` to build a `phase-id -> artifact-name[]` map, which it
attaches as `producedArtifacts` on each `PhaseNodeData`. The `TimelineHandoff`
component renders these badge lists -- it reads `producedArtifacts` directly from
the server-stamped field; the browser does not re-derive which phase produced
which artifact (single-fold invariant).

`TimelineSubArtifact` (per-milestone plan badges within a milestone group) is
**not yet wired** -- there is no milestone-group derivation in `derivePhaseNodes`,
and no milestone-group field exists in the projection. Wiring it is an explicit
follow-up that would also consume `producedPhaseId`.

### Settings (9)

| Event                               | Payload                                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------------------------- |
| `provider_status_listed`            | `{providers: [{provider, available, env_keys}]}`                                         |
| `model_registry_listed`             | `{models: [{provider, model, display_name, context_window, thinking_modes, tier_hint}]}` |
| `profile_created`                   | `{name, read_only, tiers}`                                                               |
| `profile_modified`                  | `{name, read_only, tiers}`                                                               |
| `profile_removed`                   | `{name}`                                                                                 |
| `default_profile_changed`           | `{name}`                                                                                 |
| `default_scout_concurrency_changed` | `{value}`                                                                                |

`provider_status_listed` is emitted at server start via `_push_initial_config_events`.
The fold sets `settings.provider_status` from this event. `model_registry_listed`
sets `settings.model_registry`; the frontend `ProfileForm` sources its
tier/model/thinking options from this list. There is no binary probe; provider
availability is determined by env-key presence only.

---

## The Projection

The fold is: `fold(Projection, VersionedEvent) → Projection`. It is a pure
function — same event sequence produces the same projection. No I/O, no side
effects. Unknown event types return the projection unchanged (logged warning).

### KoanBaseModel — wire format base class

All projection models inherit from `KoanBaseModel`:

```python
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

class KoanBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,   # snake_case → camelCase at serialization
        populate_by_name=True,       # Python code uses snake_case; only JSON output is camelCase
    )

    def to_wire(self) -> dict:
        """Serialize for snapshots and JSON Patch computation.

        Always produces camelCase keys. Call only at serialization boundaries:
          - push_event(): to_wire() before and after fold to compute the diff
          - get_snapshot(): to_wire() once for the snapshot payload
        Never call model_dump() directly on projection objects.
        """
        return self.model_dump(by_alias=True)
```

Python fold code uses snake_case attributes (`agent.conversation.pending_thinking`).
The JSON output and all patch paths are camelCase (`pendingThinking`,
`isThinking`, `defaultScoutConcurrency`).

### Projection model hierarchy

```
Projection
├── settings: Settings
│   ├── provider_status: list[ProviderStatus]    # per-provider env-key presence
│   ├── model_registry: list[ModelRegistryEntry] # all-providers model catalog
│   ├── profiles: dict[str, Profile]             # name → Profile
│   ├── default_profile: str
│   └── default_scout_concurrency: int
├── run: Run | None
│   ├── config: RunConfig                        # frozen at run_started
│   ├── workflow: str                            # workflow name, set by workflow_selected
│   ├── phase: str
│   ├── agents: dict[str, Agent]                 # agent_id → Agent (all statuses)
│   │   └── conversation: Conversation
│   │       ├── entries: list[ConversationEntry] # discriminated union of 11 types
│   │       ├── pending_thinking: str
│   │       ├── pending_text: str
│   │       ├── is_thinking: bool
│   │       ├── input_tokens: int                # fact: accumulated per agent_exited
│   │       ├── output_tokens: int               # fact: accumulated per agent_exited
│   │       ├── cache_read_tokens: int           # fact: accumulated per agent_exited
│   │       ├── cache_write_tokens: int          # fact: accumulated per agent_exited
│   │       ├── total_cost_usd: float            # derived in fold (genai-prices mapping)
│   │       └── context_window_percent: float    # derived in fold (tokens / context_window)
│   ├── focus: Focus | None                      # discriminated union of 2 variants
│   ├── artifacts: dict[str, ArtifactInfo]       # path → ArtifactInfo
│   ├── completion: CompletionInfo | None
│   ├── steering: list[SteeringMessage]          # pending user feedback shown above chat
│   └── active_yield: ActiveYield | None         # non-None while loop is parked at hand-back
└── notifications: list[Notification]
```

### Settings

```python
class ProviderStatus(KoanBaseModel):
    provider: str          # "google" | "anthropic" | "openai" | "bedrock"
    available: bool        # all required env keys present
    env_keys: list[str]    # env var NAMES checked -- never values

class ModelRegistryEntry(KoanBaseModel):
    provider: str
    model: str
    display_name: str
    context_window: int
    thinking_modes: list[str]
    tier_hint: str | None  # "strong" | "standard" | "cheap"

class ProfileTierWire(KoanBaseModel):
    provider: str
    model: str
    thinking: str | None

class Profile(KoanBaseModel):
    name: str
    read_only: bool = False
    tiers: dict[str, ProfileTierWire] = {}   # tier name -> {provider, model, thinking}

class Settings(KoanBaseModel):
    provider_status: list[ProviderStatus] = []
    model_registry: list[ModelRegistryEntry] = []
    profiles: dict[str, Profile] = {}
    default_profile: str = "balanced"
    default_scout_concurrency: int = 8
```

`Settings` represents what is _available_ -- it persists across runs to
`~/.koan/config.yaml` and describes the user's configured environment.
Provider availability is env-key presence only; no binary probe is performed.

### Run configuration

```python
class RunConfig(KoanBaseModel):
    profile: str           # which profile was selected
    scout_concurrency: int
```

`RunConfig` is frozen at `run_started` and never modified during the run.

|                     | Settings                   | RunConfig                   |
| ------------------- | -------------------------- | --------------------------- |
| Lifetime            | Persists across runs       | Single run                  |
| Mutation            | Settings overlay, any time | Frozen at run start         |
| `default_profile`   | Pre-selected for next run  | —                           |
| `profile`           | —                          | Which profile this run uses |
| `scout_concurrency` | Default for next run       | What this run uses          |

### Agent

All agents — primary, scouts, queued — live in `run.agents`, keyed by
`agent_id`. Status is a state machine: `queued → running → done | failed`.

```python
class Agent(KoanBaseModel):
    # Identity
    agent_id: str
    role: str
    label: str = ""
    model: str | None = None
    is_primary: bool = False

    # Lifecycle
    status: Literal["queued", "running", "done", "failed"] = "queued"
    error: str | None = None
    started_at_ms: int = 0

    # Progress
    step: int = 0
    step_name: str = ""
    last_tool: str = ""    # summary of last tool call, for monitor display

    # Content
    conversation: Conversation = Conversation()
```

Agents are never removed from `run.agents` — status transitions to `done` or
`failed` on exit. Dict keys are stable, which keeps JSON Patch paths valid
across insertions.

### Conversation

Per-agent. The primary agent's conversation is rendered in the activity feed.

```python
class Conversation(KoanBaseModel):
    entries: list[ConversationEntry] = []
    pending_thinking: str = ""    # accumulating thinking, not yet flushed to ThinkingEntry
    pending_text: str = ""        # accumulating output text, not yet flushed to TextEntry
    is_thinking: bool = False     # True while thinking deltas are arriving
    input_tokens: int = 0
    output_tokens: int = 0
    next_entry_id: int = Field(default=0, exclude=True)  # in-memory only; see entry_id below
```

`pending_thinking` and `pending_text` hold incomplete LLM output that will
become conversation entries on the next state transition. "Flush" means: if the
field is non-empty, create a completed entry (ThinkingEntry or TextEntry),
append it to `entries`, reset the field to `""`.

`next_entry_id` is a monotonic counter used by `_assign_entry_ids` to stamp
each top-level entry with a stable `entry_id`. `exclude=True` keeps it off the
wire (no `nextEntryId` in JSON Patch or snapshots); the counter is rebuilt
deterministically by re-folding the event log on restart.

### ConversationEntry — discriminated union

Every top-level entry carries a stable `entry_id` (wire: `entryId`) assigned by
`_assign_entry_ids` at the `_update_agent_conversation` seam from the
per-`Conversation` `next_entry_id` counter. The counter is excluded from the
wire. Aggregate children (`AggregateReadChild`, `AggregateGrepChild`,
`AggregateLsChild`, `AggregateGlobChild`) inherit `entry_id` via `BaseToolEntry`
but leave it `""` -- they are keyed by `call_id` instead.

```python
class ThinkingEntry(KoanBaseModel):
    type: Literal["thinking"] = "thinking"
    content: str                        # full accumulated thinking text
    entry_id: str = ""                  # stable id assigned by _assign_entry_ids

class TextEntry(KoanBaseModel):
    type: Literal["text"] = "text"
    text: str                           # full accumulated output text
    entry_id: str = ""

class StepEntry(KoanBaseModel):
    type: Literal["step"] = "step"
    step: int
    step_name: str
    total_steps: int | None = None
    entry_id: str = ""

class UserMessageEntry(KoanBaseModel):
    type: Literal["user_message"] = "user_message"
    content: str
    timestamp_ms: int
    entry_id: str = ""

class BaseToolEntry(KoanBaseModel):
    call_id: str        # unique per tool invocation
    in_flight: bool     # True until tool_completed
    entry_id: str = ""  # top-level entries: assigned; aggregate children: leave as ""

class ToolWriteEntry(BaseToolEntry):
    type: Literal["tool_write"] = "tool_write"
    file: str

class ToolEditEntry(BaseToolEntry):
    type: Literal["tool_edit"] = "tool_edit"
    file: str

class ToolBashEntry(BaseToolEntry):
    type: Literal["tool_bash"] = "tool_bash"
    command: str

class ToolGenericEntry(BaseToolEntry):
    type: Literal["tool_generic"] = "tool_generic"
    tool_name: str      # original tool name from the LLM
    summary: str = ""

class ToolKoanEntry(BaseToolEntry):
    type: Literal["tool_koan"] = "tool_koan"
    tool_name: str
    args: dict = {}
    result: dict | None = None

class ToolFailedEntry(BaseToolEntry):
    # Terminal entry for a call whose arguments failed validation (the tool
    # body never ran). The tool_failed fold case REPLACES the in-flight entry
    # with this one, retaining entry_id/phase_id for stable list keys.
    # raw_input is the JSON-dumped last-known tool_input -- an opaque string;
    # the malformed model-authored payload never survives as structured data.
    type: Literal["tool_failed"] = "tool_failed"
    tool_name: str
    error: str = ""
    raw_input: str = ""

class ToolAggregateEntry(KoanBaseModel):
    type: Literal["tool_aggregate"] = "tool_aggregate"
    children: list[AggregateChild] = []
    started_at_ms: int = 0
    entry_id: str = ""  # assigned to the aggregate; children remain "" and key by call_id

class DebugStepGuidanceEntry(KoanBaseModel):
    type: Literal["debug_step_guidance"] = "debug_step_guidance"
    content: str
    entry_id: str = ""

class PhaseBoundaryEntry(KoanBaseModel):
    type: Literal["phase_boundary"] = "phase_boundary"
    phase: str
    message: str
    entry_id: str = ""

class YieldEntry(KoanBaseModel):
    type: Literal["yield"] = "yield"
    suggestions: list[Suggestion] = []   # structured options presented at this yield point
    entry_id: str = ""


ConversationEntry = Annotated[
    ThinkingEntry | TextEntry | StepEntry | UserMessageEntry |
    ToolWriteEntry | ToolEditEntry | ToolBashEntry | ToolGenericEntry |
    ToolKoanEntry | ToolFailedEntry | ToolAggregateEntry |
    DebugStepGuidanceEntry | PhaseBoundaryEntry | YieldEntry,
    Field(discriminator="type"),
]
```

`YieldEntry` is appended to the conversation when the orchestrator hands back
at a phase boundary (the terminal-text turn). It records the suggestions offered
at that hand-back point, providing a historical record of what options were presented.

### Focus — discriminated union

`run.focus` determines what the main content area renders. Every variant
carries `agent_id` — the conversation is always the backdrop.

```python
class ConversationFocus(KoanBaseModel):
    type: Literal["conversation"] = "conversation"
    agent_id: str

class QuestionFocus(KoanBaseModel):
    type: Literal["question"] = "question"
    agent_id: str
    token: str
    questions: list[dict]           # raw LLM output, not validated by fold

Focus = Annotated[
    ConversationFocus | QuestionFocus,
    Field(discriminator="type"),
]
```

`run.focus` is `None` before the first agent spawns. Once the primary agent
spawns, `focus` is always set — every state of the main content area is
explicit.

### Supporting types

```python
class Suggestion(KoanBaseModel):
    id: str         # machine key -- phase name (e.g. "plan") or "done"
    label: str      # display text shown in UI pill (e.g. "Write implementation plan")
    command: str = ""   # pre-filled into chat input when pill is clicked

class ActiveYield(KoanBaseModel):
    # Live view of the last hand-back — non-None while the loop is parked at the hand-back.
    # Cleared by yield_cleared, phase_started, and workflow_completed.
    suggestions: list[Suggestion] = []

class SteeringMessage(KoanBaseModel):
    content: str    # user feedback message queued during active agent work

class ArtifactInfo(KoanBaseModel):
    path: str           # relative to run directory
    size: int           # bytes
    modified_at: int = 0            # milliseconds since epoch

class CompletionInfo(KoanBaseModel):
    success: bool
    summary: str = ""
    error: str | None = None

class Notification(KoanBaseModel):
    message: str
    level: Literal["info", "warning", "error"] = "info"
    timestamp_ms: int
```

### Complete Projection

```python
class Projection(KoanBaseModel):
    settings: Settings = Settings()
    run: Run | None = None
    notifications: list[Notification] = []
```

`run is None` → show landing page. `run.completion is not None` → run finished
(results remain visible). `run` is replaced wholesale on the next `run_started`
event.

### JSON Patch paths

```
Settings:     /settings/installations/claude-default/available
              /settings/profiles/balanced/tiers/primary
              /settings/defaultProfile
              /settings/defaultScoutConcurrency

Run config:   /run/config/profile
              /run/config/scoutConcurrency

Run:          /run/workflow
              /run/phase

Agent:        /run/agents/abc123/status
              /run/agents/abc123/step
              /run/agents/abc123/lastTool

Conversation: /run/agents/abc123/conversation/pendingThinking
              /run/agents/abc123/conversation/entries/-
              /run/agents/abc123/conversation/isThinking
              /run/agents/abc123/conversation/inputTokens

Focus:        /run/focus
Artifacts:    /run/artifacts/docs~1architecture.md/size
Yield:        /run/activeYield
              /run/activeYield/suggestions
```

Named entities (installations, profiles, agents, artifacts) are dicts for
stable patch paths. Ordered collections (conversation entries, notifications)
are append-only lists — positional indices are stable.

---

## Fold Rules

The fold is grouped by the part of the projection it modifies. An event may
trigger rules in multiple groups (`agent_step_advanced` updates both the
agent's progress fields and its conversation).

### Agent conversation

These rules apply to the agent identified by `event.agent_id`. There is no
primary-agent filtering in the fold — every agent has its own conversation and
the fold appends unconditionally. The frontend chooses which conversation to
render via `focus`.

| Event                                                                       | Action                                                                                                                                                                                                                                                                                                                                    |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `thinking`                                                                  | Flush `pending_text` → TextEntry. Append delta to `pending_thinking`. Set `is_thinking = True`.                                                                                                                                                                                                                                           |
| `stream_delta`                                                              | Flush `pending_thinking` → ThinkingEntry. Append delta to `pending_text`. Set `is_thinking = False`.                                                                                                                                                                                                                                      |
| `tool_read`, `tool_write`, `tool_edit`, `tool_bash`, `tool_grep`, `tool_ls` | Flush both pending fields. Append typed entry with `in_flight=True`. Set `is_thinking = False`. Update `agent.last_tool`.                                                                                                                                                                                                                 |
| `tool_called` (non-koan)                                                    | Flush both pending fields. Append `ToolGenericEntry` with `in_flight=True`. Set `is_thinking = False`. Update `agent.last_tool`.                                                                                                                                                                                                          |
| `tool_called` (tool name starts with `koan_`)                               | Skip. koan MCP tools are infrastructure; their effects arrive via `agent_step_advanced`, `questions_asked`, etc.                                                                                                                                                                                                                          |
| `tool_completed`                                                            | Find entry by `call_id`, set `in_flight = False`.                                                                                                                                                                                                                                                                                         |
| `tool_failed`                                                               | Argument validation rejected the call (tool body never ran). Top-level entry: REPLACE with `ToolFailedEntry` (retains `entry_id`/`phase_id`; malformed input kept only as the opaque `raw_input` JSON string). Aggregate child: mark `failed=True, in_flight=False` in place (extraction would break the `len(children) >= 2` invariant). |
| `agent_step_advanced`                                                       | Flush both pending fields. Append `StepEntry` if `step >= 1`. Set `is_thinking = False`. **Also** update `agent.step`, `agent.step_name`; accumulate `usage` into `conversation.input_tokens`, `conversation.output_tokens`.                                                                                                              |
| `stream_cleared`                                                            | Flush both pending fields. Set `is_thinking = False`.                                                                                                                                                                                                                                                                                     |

**Koan tool input sanitization:** the `tool_input_delta` fold sanitizes the
streaming input aggregate for koan tools before storing it (`_sanitize_koan_input`
with the explicit `_KOAN_INPUT_SHAPES` table in `koan/projections.py`). Fields
whose container shape does not match what the frontend cards index into (e.g.
`koan_ask_question.questions` must be a list of dicts) are dropped from both
`tool_input` and `args`; mid-stream partials self-heal on the next delta. This
is the trust boundary: model-authored payloads never reach the frontend
unvalidated, even while a call is still streaming.

### Agent lifecycle

| Event                | Action                                                                                                                                                                                                           |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scout_queued`       | Add `Agent(agent_id=scout_id, status="queued", ...)` to `run.agents`.                                                                                                                                            |
| `agent_spawned`      | Look up `agent_id` in `run.agents`. If found (queued scout): set `status="running"`, `started_at_ms`. If not found (primary agent): create `Agent(is_primary=True, status="running", ...)`, add to `run.agents`. |
| `agent_exited`       | Set `status="done"` or `"failed"`. Set `error` if present. Accumulate final `usage` into conversation tokens.                                                                                                    |
| `agent_spawn_failed` | Append `Notification` to `projection.notifications`.                                                                                                                                                             |

Agents are never removed from `run.agents`. Status distinguishes active from
completed agents.

### Focus transitions

| Event                     | Action                                                              |
| ------------------------- | ------------------------------------------------------------------- |
| `agent_spawned` (primary) | `run.focus = ConversationFocus(agent_id=...)`                       |
| `questions_asked`         | `run.focus = QuestionFocus(agent_id=..., token=..., questions=...)` |
| `questions_answered`      | `run.focus = ConversationFocus(agent_id=primary_id)`                |
| `user_message`            | `primary_agent.conversation.entries += UserMessageEntry(...)`       |

### Run lifecycle

| Event                | Action                                                                                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `run_started`        | `projection.run = Run(config=RunConfig(...))`                                                                                                                                                                      |
| `workflow_selected`  | `run.workflow = payload["workflow"]`                                                                                                                                                                               |
| `phase_started`      | `run.phase = phase`. Clear `run.active_yield = None`.                                                                                                                                                              |
| `workflow_completed` | `run.completion = CompletionInfo(...)`. Clear `run.active_yield = None`.                                                                                                                                           |
| `yield_started`      | Parse `suggestions` from payload → `Suggestion` list. Append `YieldEntry(suggestions=...)` to primary agent's conversation (flushing pending fields first). Set `run.active_yield = ActiveYield(suggestions=...)`. |
| `yield_cleared`      | Set `run.active_yield = None`.                                                                                                                                                                                     |

### Settings

| Event                               | Action                                                                              |
| ----------------------------------- | ----------------------------------------------------------------------------------- |
| `probe_completed`                   | For each alias in `payload.results`, set `settings.installations[alias].available`. |
| `installation_created`              | Add `Installation(...)` to `settings.installations[alias]`.                         |
| `installation_modified`             | Update `settings.installations[alias]`.                                             |
| `installation_removed`              | Remove `settings.installations[alias]`.                                             |
| `profile_created`                   | Add `Profile(...)` to `settings.profiles[name]`.                                    |
| `profile_modified`                  | Update `settings.profiles[name]`.                                                   |
| `profile_removed`                   | Remove `settings.profiles[name]`.                                                   |
| `default_profile_changed`           | Set `settings.default_profile`.                                                     |
| `default_scout_concurrency_changed` | Set `settings.default_scout_concurrency`.                                           |

### Artifacts

| Event               | Action                        |
| ------------------- | ----------------------------- |
| `artifact_created`  | Add to `run.artifacts[path]`. |
| `artifact_modified` | Update `run.artifacts[path]`. |
| `artifact_removed`  | Remove `run.artifacts[path]`. |

### Fold safety

- **Unknown event type** → return projection unchanged, log warning.
- **Agent event with unknown `agent_id`** → return projection unchanged, log
  warning. (Exception: `agent_spawn_failed` — it appends a notification
  regardless because the error fact is worth preserving.)
- **Fold exception** → return projection unchanged, log full exception. The
  event is still in the audit log; only the fold effect is skipped.
- **`run is None` when a run event arrives** → return projection unchanged, log
  warning. (Prevents crashes from late-arriving events after restart.)

---

## ProjectionStore

`koan/projections.py` contains the store class. This module has **zero koan
domain imports** — it is pure event-sourcing machinery.

```python
class ProjectionStore:
    """In-memory versioned event log + materialized projection + JSON Patch broadcaster.

    Three stores, three purposes:
      events      — append-only audit log, never modified
      projection  — materialized state for snapshot serving and diff computation
      prev_state  — previous to_wire() output; overwritten each push_event()

    Push flow:
      1. Increment version, create VersionedEvent, append to events
      2. Fold: projection = fold(projection, event)
      3. Diff: patch = make_patch(prev_state, projection.to_wire())
      4. If patch is non-empty: broadcast {type, version, patch} dict to all subscribers
      5. Update prev_state

    Every event takes the same path. No branching on event type.
    Subscriber queues receive plain dicts — the dict is the SSE JSON payload.
    """

    events: list[VersionedEvent]     # append-only
    projection: Projection           # eagerly materialized
    version: int                     # current version (0 = empty)
    prev_state: dict                 # previous to_wire() for diff computation
    subscribers: set[asyncio.Queue]  # one per connected SSE client
```

### push_event

```python
def push_event(self, event_type, payload, agent_id=None):
    self.version += 1
    event = VersionedEvent(version=self.version, ...)
    self.events.append(event)

    old_state = self.prev_state
    self.projection = fold(self.projection, event)
    new_state = self.projection.to_wire()
    self.prev_state = new_state

    patch = jsonpatch.make_patch(old_state, new_state)
    if not patch:
        return event    # no state change — no broadcast

    msg = {"type": "patch", "version": self.version, "patch": patch.patch}
    for q in list(self.subscribers):    # snapshot to avoid concurrent-modification issues
        q.put_nowait(msg)
    return event
```

When the fold produces no state change (e.g., a `tool_called` event for a koan
MCP tool that the fold skips), no message is broadcast. Subscribers stay at the
same version.

### get_snapshot

```python
def get_snapshot(self) -> dict:
    return {"version": self.version, "state": self.projection.to_wire()}
```

Always produces camelCase via `to_wire()`. Called by `sse_stream()` for every
connect and reconnect.

### Event payload builders: koan/events.py

`koan/events.py` bridges koan domain types into event payloads. It imports
domain types; `projections.py` does not.

```python
def build_run_started(profile, installations, scout_concurrency) -> dict
def build_workflow_selected(workflow: str) -> dict
def build_agent_spawned(agent: AgentState) -> dict
def build_agent_exited(exit_code, error=None, usage=None) -> dict
def build_agent_spawn_failed(role, diagnostic: RunnerDiagnostic) -> dict
def build_step_advanced(step, step_name, usage=None, total_steps=None) -> dict
def build_tool_called(call_id, tool, args, summary="") -> dict
def build_tool_read(call_id, file, lines="") -> dict
def build_tool_bash(call_id, command) -> dict
# ... other typed tool builders ...
def build_tool_completed(call_id, tool, result=None) -> dict
def build_tool_failed(call_id, tool, error="", ts_ms=0) -> dict
def build_artifact_diff(old, new_artifacts) -> list[tuple[str, dict]]
# ... interaction and settings builders ...
```

`build_artifact_diff` compares old and new artifact sets, returns a list of
`(event_type, payload)` tuples — one per created/modified/removed file.

---

## SSE Protocol

### Endpoint

`GET /events?since=N`

| `since` value                                          | Server response                                        |
| ------------------------------------------------------ | ------------------------------------------------------ |
| matches `store.version`                                | Subscribe and stream live patches (no snapshot needed) |
| anything else (including 0, reconnect, server restart) | Send snapshot, then stream live patches                |

The `since` parameter is a version check, not a replay cursor. If the client's
`lastVersion` matches the server's current version, there is nothing to catch
up on. Otherwise, a fresh snapshot is always the correct recovery — it handles
reconnects, page reloads, and server restarts identically.

### Wire format

**Snapshot** (on every connect or reconnect where `since != store.version`):

```
event: snapshot
data: {"version": 42, "state": { ...full projection in camelCase... }}
```

**Patch** (after each state-changing event):

```
event: patch
data: {"type": "patch", "version": 43, "patch": [{"op": "replace", "path": "/run/agents/abc/conversation/pendingThinking", "value": "The user wants..."}]}
```

All keys and paths are camelCase. The frontend applies patches directly to its
store without any field renaming.

### sse_stream implementation

```python
async def sse_stream(request, since=0):
    store = request.app.state.projection_store
    queue = store.subscribe()
    try:
        if since != store.version:
            # Client is behind, ahead (server restart), or connecting fresh.
            # Fresh snapshot is the correct recovery in all cases.
            yield sse_event("snapshot", store.get_snapshot())
        while True:
            msg = await queue.get()       # plain dict: {type, version, patch}
            yield sse_event(msg["type"], msg)
    except asyncio.CancelledError:
        pass
    finally:
        store.unsubscribe(queue)
```

The queue is subscribed before the snapshot is yielded — no events can be
missed between the two operations.

### Reconnect flow

```
Browser loads         → GET /events?since=0  → snapshot → render full state
Browser refreshes     → GET /events?since=0  → snapshot → render full state
Connection drops      → GET /events?since=N  → snapshot → render full state
Server restarts       → GET /events?since=N  → snapshot (version=0) → render fresh state
```

All cases are handled by the same code path. The client does not need to
distinguish between them.

---

## Frontend Integration

`frontend/src/sse/connect.ts` — the complete sync implementation:

```typescript
// Module-level projection dict for fast-json-patch operations.
// fast-json-patch operates on plain JS objects, not Zustand state.
// On snapshot, replaced wholesale. On patch, applyPatch returns a new object.
let storeState: Record<string, unknown> = {};

es.addEventListener("snapshot", (e) => {
  const { version, state } = JSON.parse(e.data);
  storeState = state;
  set({ lastVersion: version, ...state }); // spread camelCase fields directly into Zustand store
});

es.addEventListener("patch", (e) => {
  try {
    const { version, patch } = JSON.parse(e.data);
    // mutate:false returns a new object rather than modifying storeState in-place.
    storeState = applyPatch(storeState, patch, false, false).newDocument;
    set({ lastVersion: version, ...storeState });
  } catch (err) {
    console.error("Patch failed, reconnecting:", err);
    es.close();
    set({ lastVersion: 0 }); // force snapshot on next connect
    setTimeout(() => connect(set), 1000);
  }
});
```

Two handlers. No `applyEvent`. No fold logic. No field renaming. No special
cases. The server emits camelCase; the frontend stores camelCase; patches apply
directly.

**Component access pattern:**

```typescript
// Agent monitor: filter run.agents by status
const agents = useStore((s) => s.run?.agents ?? {});
const running = Object.values(agents).filter(
  (a) => !a.isPrimary && a.status === "running",
);
const queued = Object.values(agents).filter((a) => a.status === "queued");

// Activity feed: conversation of the focused agent
const focusId = useStore((s) => s.run?.focus?.agentId);
const conversation = useStore((s) =>
  focusId ? s.run?.agents?.[focusId]?.conversation : undefined,
);

// Settings: read directly from store
const installations = useStore((s) => s.settings?.installations ?? {});
const defaultProfile = useStore(
  (s) => s.settings?.defaultProfile ?? "balanced",
);

// Run: workflow type
const workflow = useStore((s) => s.run?.workflow);
```

---

## Relationship to the Audit Fold

Koan has two independent fold systems sharing the same structural pattern (pure
fold function, append-only log) but serving different purposes:

| Aspect      | Audit fold (`koan/audit/fold.py`)                 | Projection fold (`koan/projections.py`)   |
| ----------- | ------------------------------------------------- | ----------------------------------------- |
| Input       | Per-subagent audit events (`events.jsonl`)        | Workflow-level projection events          |
| Output      | Per-subagent `Projection` written to `state.json` | Frontend-visible `Projection` (in-memory) |
| Scope       | One subagent's execution                          | Entire workflow run                       |
| Persistence | Written to disk on each event                     | In-memory only                            |
| Consumers   | Debugging, post-mortem analysis                   | Browser frontend via SSE                  |

---

## Design Decisions

### Why JSON Patch over a dual fold

The previous architecture maintained two fold implementations — one in Python,
one in TypeScript — that were required to produce the same projection from the
same event sequence ("symmetric fold invariant"). Every new event type required
adding a case to both, with no mechanical check that they stayed in sync. Two
bugs (fragmented thinking cards, scout events in the primary feed) traced
directly to the two folds diverging. JSON Patch eliminates the invariant: the
fold exists in one place, the server computes diffs, the frontend applies them
mechanically. Correctness is structural, not disciplinary.

### Why camelCase on the wire

Emitting snake_case from the server requires a `mapProjectionToStore()` function
in the frontend that renames every field, plus a `projectionState` shadow object
for patch application (patches must apply to the pre-renamed dict, not the
renamed store). Every new projection field needs a rename entry in that mapping.
The mapping layer _is_ business logic and it contradicts the "frontend has zero
business logic" principle. Emitting camelCase eliminates the layer: patches
apply directly to the Zustand store, snapshots spread directly into it, and
adding a field to `Projection` requires zero frontend changes.

### Why uniform JSON Patch (no delta bypass for thinking)

A thinking delta produces a `replace` operation on `pendingThinking` carrying
the full accumulated string. At 10KB accumulated with 20 deltas/second, this is
~200KB/s of patches. On a remote server, a dedicated delta event type would be
worth the complexity. On localhost, loopback traffic is free — 200KB/s is noise
next to the LLM API traffic. Two event types (`snapshot`, `patch`) mean two
handlers, zero special cases, and no branching in `push_event`. The complexity
of a third event type (third handler, branching, special-case in the frontend)
costs more than the bandwidth savings are worth.

### Why dict not list for named entities

JSON Patch paths for list elements use positional indices (`/run/agents/2`).
When an agent is removed or the list is reordered, subsequent indices shift and
in-flight patches referencing those indices become invalid. Dict keys are stable:
`/run/agents/abc123` refers to the same agent regardless of insertions or
removals elsewhere. This applies to installations, profiles, agents, and
artifacts — all named entities are dicts.

### Why `pending_thinking` / `pending_text` not `thinkingBuffer` / `streamBuffer`

"Buffer" describes the mechanism — accumulate, flush, reset. "Pending" describes
the content: incomplete LLM output that will become a conversation entry on the
next transition. Names should describe what a field _is_, not how it works.
"Pending" also communicates the temporal relationship correctly: this text is
not yet complete and will be committed to `entries` on the next event.

### Why Focus is a discriminated union

An explicit discriminated union models every possible main-content state.
The frontend switch on `focus.type` is exhaustive — TypeScript will flag
unhandled variants. The `agent_id` on every variant means the conversation is
always available as backdrop without a separate lookup.

### Why Settings vs RunConfig

Settings describe what's _available_ (persistent, mutable via the settings
overlay at any time). RunConfig describes what _this run uses_ (frozen at
`run_started`, never modified). This separation prevents a settings change
mid-run from affecting the in-flight run. It also makes the landing page
straightforward: it reads `settings.defaultProfile` and
`settings.defaultScoutConcurrency` as the pre-selected values, which the user
may override before starting.

### Why always-snapshot on reconnect

The previous architecture stored events and replayed them for reconnecting
clients (`?since=N` returned events `N+1..M`). At 500K events over a full run,
with patches ranging from 80 bytes to 10KB, storing patches for replay requires
unbounded memory and adds ordering logic and partial-replay edge cases. A fresh
snapshot is sent once on reconnect — cheaper, simpler, and handles server
restarts (which would have caused a `fatal_error` in the old protocol)
identically to a normal reconnect.

### Why `is_thinking` is a projection field, not derived

`is_thinking` could be derived as "is `pending_thinking` non-empty." But that
derivation would need to run in the frontend on every patch, which contradicts
the "frontend has zero business logic" principle. The fold sets it explicitly;
it arrives via patch like every other field.

### Why accumulating fields are unbounded

`conversation.entries` and `notifications` are never evicted. Capping them
would require eviction logic that creates edge cases for what a reconnecting
client receives in a snapshot. Koan is one-shot — the server shuts down after
the workflow completes — so accumulation is bounded by run duration.

### Why koan tool calls are authoritative over stream events

When an agent calls a koan tool, the call appears twice: as a structured
in-process call (complete, typed) and as a `StreamEvent` from the agent loop
(which carries summary text). The tool core has the full structured data.
`StreamEvent`s are filtered to exclude koan tool names (`koan_*`); only
built-in file/bash tools are sourced from stream events.

### Why `build_artifact_diff` uses diff events, not a full list

`artifact_created`/`artifact_modified`/`artifact_removed` carry exactly what
changed, not the full current set. The fold maintains `run.artifacts` as a dict
keyed by path, enabling O(1) per-event updates. `build_artifact_diff()` scans
the run directory at phase boundaries and produces the minimal set of events.

### Why projections.py has zero koan domain imports

`koan/projections.py` contains pure event-sourcing machinery. Domain-to-event
bridging lives in `koan/events.py`. This separation makes the projection engine
testable in isolation and prevents the event schema from leaking domain
implementation details.
