# Projection event-sourcing machinery: server-authoritative state with JSON Patch.
#
# Architecture: the fold runs only in Python. The frontend receives a full snapshot on
# connect, then RFC 6902 JSON Patch operations after each event. It has no fold logic.
#
# ProjectionStore holds three things:
#   events      -- append-only audit log, never modified
#   projection  -- materialized state, recomputed on every push_event
#   prev_state  -- to_wire() output from before the last fold, used to compute patches
#
# push_event flow: append to log → fold → to_wire → make_patch → broadcast plain dicts.
# All paths are uniform; no branching by event type. CamelCase wire format via KoanBaseModel.

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated, Literal

import jsonpatch
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .lib.workflows import WORKFLOWS
from .logger import get_logger
from .agents.events import KOAN_MCP_TOOLS

log = get_logger("projections")

# ---------------------------------------------------------------------------
# Event type registry
# ---------------------------------------------------------------------------

EventType = Literal[
    # Lifecycle
    "run_started",
    "phase_started",
    "agent_spawned",
    "agent_spawn_failed",
    "agent_step_advanced",
    "agent_exited",
    "workflow_completed",
    "run_cleared",
    "workflow_selected",
    "scout_queued",
    "agents_cleared",
    # Activity
    "tool_started",
    "tool_stopped",
    "tool_called",
    "tool_completed",
    "tool_read",
    "tool_write",
    "tool_edit",
    "tool_bash",
    "tool_grep",
    "tool_ls",
    "tool_request",
    "tool_input_delta",
    "tool_result",
    "tool_result_captured",
    # Domain events correlated by agent_id (not call_id): target the in-flight
    # tool entry for the agent. reflect_delta streams internal-LLM text output;
    # tool_attachments carries koan-side upload manifests from MCP handlers.
    "reflect_delta",
    "tool_attachments",
    "thinking",
    "stream_delta",
    "stream_cleared",
    "debug_step_guidance",
    # User chat
    "user_message",
    "phase_boundary_reached",
    # Yield — orchestrator hands control back to the user
    "yield_started",
    "yield_cleared",
    # Steering
    "steering_queued",
    "steering_delivered",
    # Focus (interactions)
    "questions_asked",
    "questions_answered",
    # Resources
    "artifact_created",
    "artifact_modified",
    "artifact_removed",
    # Settings
    # probe_completed / installation_* removed in M4: installation concept and
    # CLI binary probe deleted; provider credentials are the availability model.
    # profile_created/modified/removed/default_profile_changed removed in M5:
    # profile types deleted; replaced by connections/presets config events.
    "default_scout_concurrency_changed",
    "workflows_listed",
    # M2: model catalog initial event (kept; provider_status_listed reshaped M5)
    "model_registry_listed",
    # Dynamic per-provider model overlay (LM Studio + cloud providers)
    "provider_models_listed",
    # M5: new config entity events (replace profile events)
    "connections_listed",
    "configured_models_listed",
    "presets_listed",
    "active_changed",
    "memory_bindings_listed",
    # M5: provider_status_listed retained but reshaped to per-connection
    "provider_status_listed",
    # Memory curation — orchestrator blocked in koan_memory_propose
    "memory_curation_started",
    "memory_curation_cleared",
    # Memory mutation — emitted by koan_memorize / koan_forget / koan_memory_status
    "memory_entry_created",
    "memory_entry_updated",
    "memory_entry_deleted",
    "memory_summary_updated",
    # Reflect — background task lifecycle
    "reflect_started",
    "reflect_trace",
    "reflect_done",
    "reflect_cancelled",
    "reflect_failed",
    "reflect_cleared",
    # Static Voyage embedding model catalog; pushed once at startup.
    "embedding_models_listed",
]


# ---------------------------------------------------------------------------
# Wire serialization base
# ---------------------------------------------------------------------------

class KoanBaseModel(BaseModel):
    """Base model for all projection classes.

    alias_generator converts snake_case field names to camelCase at serialization.
    populate_by_name=True lets Python code use snake_case attributes normally;
    only to_wire() output is camelCase.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    def to_wire(self) -> dict:
        """Serialize to camelCase dict for snapshots and JSON Patch computation.

        Always call this at serialization boundaries, never model_dump() directly.
        snake_case keys from model_dump() break patch paths on the frontend.
        """
        return self.model_dump(by_alias=True)


# ---------------------------------------------------------------------------
# Versioned event envelope (audit log; NOT KoanBaseModel — never sent to wire)
# ---------------------------------------------------------------------------

class VersionedEvent(BaseModel):
    version: int
    event_type: str  # stored as str so unknown types deserialise without error
    timestamp: str
    agent_id: str | None = None
    payload: dict


# ---------------------------------------------------------------------------
# ConversationEntry discriminated union
# ---------------------------------------------------------------------------

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

class UserMessageEntry(KoanBaseModel):
    type: Literal["user_message"] = "user_message"
    content: str
    timestamp_ms: int

class AttachmentEntry(KoanBaseModel):
    """Wire shape for a committed upload attached to a tool call.

    Pydantic's to_camel alias yields uploadId/contentType on the wire,
    matching what the frontend AttachmentEntry interface declares.

    upload_id and path are required again post-M3: the tool_attachments domain
    event from MCP handlers carries full manifests with both fields. Runner-
    extracted partial manifests in tool_result content blocks (which lack
    koan-side fields) are silently dropped via the AttachmentEntry(**a)
    try/except guard in the tool_result and tool_completed fold cases (M1).
    """
    upload_id: str
    filename: str = Field(default="")
    size: int = Field(default=0)
    content_type: str = Field(default="")
    path: str


class BaseToolEntry(KoanBaseModel):
    """Shared fields for all tool entries and aggregate children."""
    call_id: str                           # unique per tool invocation
    in_flight: bool                        # True until tool_result
    # Populated by tool_completed when the backend committed uploads were
    # attached to this tool call (via build_tool_completed attachments arg).
    attachments: list[AttachmentEntry] | None = None
    # Streaming input accumulation: tool_input is the server-side aggregate of
    # all received deltas (most-complete known input); tool_input_delta is the
    # last raw chunk received (a partial JSON string from the Anthropic API).
    # The type is str | None rather than dict | None because the Anthropic
    # streaming API delivers input_json_delta as a string fragment, not a
    # parsed dict. tool_input (the aggregate) is always a dict when present.
    tool_input: dict | None = None
    tool_input_delta: str | None = None

class ToolWriteEntry(BaseToolEntry):
    type: Literal["tool_write"] = "tool_write"
    file: str                              # path that was created or overwritten

class ToolEditEntry(BaseToolEntry):
    type: Literal["tool_edit"] = "tool_edit"
    file: str                              # path that was edited in-place

class ToolBashEntry(BaseToolEntry):
    type: Literal["tool_bash"] = "tool_bash"
    command: str                           # shell command executed

class ToolGenericEntry(BaseToolEntry):
    """Catch-all for tools without a typed variant (e.g. custom MCP tools)."""
    type: Literal["tool_generic"] = "tool_generic"
    tool_name: str                         # original tool name from the LLM
    summary: str = ""                      # human-readable one-liner from the runner parser

class ToolKoanEntry(BaseToolEntry):
    """Koan MCP tool with structured args and result for rich frontend rendering."""
    type: Literal["tool_koan"] = "tool_koan"
    tool_name: str
    args: dict = {}
    result: dict | None = None

# ---------------------------------------------------------------------------
# Aggregate children — exploration tools (read, grep, ls) never appear as
# top-level ConversationEntry values. They live only inside a ToolAggregateEntry.
# ---------------------------------------------------------------------------

class AggregateReadChild(BaseToolEntry):
    tool: Literal["read"] = "read"
    file: str                              # path that was read
    lines: str = ""                        # line range, e.g. "1-50"
    started_at_ms: int = 0                 # creation timestamp
    completed_at_ms: int | None = None     # set by tool_completed
    lines_read: int | None = None          # attached by tool_result_captured
    bytes_read: int | None = None          # attached by tool_result_captured

class AggregateGrepChild(BaseToolEntry):
    tool: Literal["grep"] = "grep"
    pattern: str                           # search pattern
    started_at_ms: int = 0
    completed_at_ms: int | None = None
    matches: int | None = None             # attached by tool_result_captured
    files_matched: int | None = None       # attached by tool_result_captured

class AggregateLsChild(BaseToolEntry):
    tool: Literal["ls"] = "ls"
    path: str                              # directory listed
    started_at_ms: int = 0
    completed_at_ms: int | None = None
    entries: int | None = None             # attached by tool_result_captured
    directories: int | None = None         # attached by tool_result_captured

# M4: glob is a built-in file-search tool analogous to grep; it uses the
# same metrics shape (matches / files_matched) since each matched path is
# one match and one file. Separate discriminator value keeps the fold's
# dispatch clean and lets the frontend render glob entries distinctly later.
class AggregateGlobChild(BaseToolEntry):
    tool: Literal["glob"] = "glob"
    pattern: str                           # glob pattern searched
    started_at_ms: int = 0
    completed_at_ms: int | None = None
    matches: int | None = None             # attached by tool_result_captured
    files_matched: int | None = None       # attached by tool_result_captured

AggregateChild = Annotated[
    AggregateReadChild | AggregateGrepChild | AggregateLsChild | AggregateGlobChild,
    Field(discriminator="tool"),
]

class ToolAggregateEntry(KoanBaseModel):
    """A run of consecutive exploration tool calls (read, grep, ls).

    Created when the first exploration tool in a run arrives; grown as
    subsequent consecutive exploration tools arrive; left alone once any
    other entry type intervenes. Single-child aggregates are normal — the
    frontend renders one child as a ToolCallRow and 2+ children as a
    ToolAggregateCard. Active/elapsed state is derived from children at
    render time, not stored here.
    """
    type: Literal["tool_aggregate"] = "tool_aggregate"
    children: list[AggregateChild] = []
    started_at_ms: int = 0                 # timestamp of the first child's creation

class DebugStepGuidanceEntry(KoanBaseModel):
    """Step guidance prompt shown in --debug mode."""
    type: Literal["debug_step_guidance"] = "debug_step_guidance"
    content: str                           # full formatted step guidance text

class PhaseBoundaryEntry(KoanBaseModel):
    type: Literal["phase_boundary"] = "phase_boundary"
    phase: str
    message: str

class Suggestion(KoanBaseModel):
    """A structured option presented to the user at a yield point."""
    id: str                                # machine key (e.g. "plan-spec", "done")
    label: str                             # display text (e.g. "Write implementation plan")
    command: str = ""                      # pre-fills the chat input when the pill is clicked

class YieldEntry(KoanBaseModel):
    """Conversation entry emitted when the orchestrator yields to the user."""
    type: Literal["yield"] = "yield"
    suggestions: list[Suggestion] = []     # clickable options shown in the UI

class ActiveYield(KoanBaseModel):
    """Run-level state tracking the current yield's suggestions.

    Non-None while the orchestrator is blocked in koan_yield. Cleared when
    a phase starts, the workflow completes, or a new yield supersedes it.
    """
    suggestions: list[Suggestion] = []

ConversationEntry = Annotated[
    ThinkingEntry | TextEntry | StepEntry | UserMessageEntry |
    ToolWriteEntry | ToolEditEntry | ToolBashEntry | ToolGenericEntry |
    ToolKoanEntry | ToolAggregateEntry |
    DebugStepGuidanceEntry | PhaseBoundaryEntry | YieldEntry,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Conversation — per agent
# ---------------------------------------------------------------------------

class Conversation(KoanBaseModel):
    entries: list[ConversationEntry] = []
    pending_thinking: str = ""             # in-progress reasoning, not yet flushed to ThinkingEntry
    pending_text: str = ""                 # in-progress text output, not yet flushed to TextEntry
    is_thinking: bool = False              # True while thinking deltas are arriving
    input_tokens: int = 0                  # accumulated from agent_step_advanced usage
    output_tokens: int = 0
    # M5: cache token facts (folded from turn_complete RequestUsage, cumulative sums).
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # M5: derived fields -- computed in the fold, not recorded as event facts.
    # total_cost_usd: genai-prices bundled snapshot via price_for_usage (cumulative tokens).
    # context_window_percent: latest request's input / context_window, clamped 0-100.
    total_cost_usd: float = 0.0
    context_window_percent: float = 0.0


# ---------------------------------------------------------------------------
# Focus discriminated union
# ---------------------------------------------------------------------------

class ConversationFocus(KoanBaseModel):
    """Default state: rendering an agent's conversation."""
    type: Literal["conversation"] = "conversation"
    agent_id: str

class QuestionFocus(KoanBaseModel):
    """Agent is blocked, needs user input."""
    type: Literal["question"] = "question"
    agent_id: str
    token: str
    questions: list[dict] = []

Focus = Annotated[
    ConversationFocus | QuestionFocus,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent(KoanBaseModel):
    # Identity — set at queue/spawn time, never changes
    agent_id: str
    role: str
    label: str = ""
    model: str | None = None
    is_primary: bool = False
    # M5: provider + context_window carried from agent_spawned so the fold can
    # derive cost and context-window percent without live config lookups.
    provider: str | None = None
    context_window: int = 0

    # Lifecycle — state machine: queued → running → done | failed
    status: Literal["queued", "running", "done", "failed"] = "queued"
    error: str | None = None
    started_at_ms: int = 0
    completed_at_ms: int | None = None

    # Progress — updated during execution, shown in agent monitor
    step: int = 0
    step_name: str = ""
    last_tool: str = ""

    # Content
    conversation: Conversation = Field(default_factory=Conversation)


# ---------------------------------------------------------------------------
# Settings and run configuration
# ---------------------------------------------------------------------------

# Installation model removed in M4: the agent installation concept is deleted.
# CLI binary configurations are replaced by provider credential availability.
# ProfileTierWire, Profile (wire), ProviderStatusWire removed in M5: profile
# types deleted; replaced by ConnectionWire, ConnectionStatusWire, etc. (plan-milestone-5.md).


class ConnectionStatusWire(KoanBaseModel):
    """Wire representation of per-connection availability (M5).

    Replaces ProviderStatusWire (which was per-type).  Payload shape:
    {connections: [{connection_id, connection_type, available}, ...]}.
    Fold sets Settings.provider_status from the connections list.
    """

    connection_id: str
    connection_type: str
    available: bool


class ConnectionWire(KoanBaseModel):
    """Wire representation of a Connection from config (M5).

    Carries non-secret endpoint settings only; the credential lives in the
    credential store keyed by connection_id (brief D3).
    """

    id: str
    connection_type: str
    base_url: str | None = None
    region: str | None = None


class ConfiguredModelWire(KoanBaseModel):
    """Wire representation of a ConfiguredModel from config (M5).

    A (connection, model-id) pair; global, referenced by slot assignments.
    context_window is the optional explicit override (tokens); None means
    "derive from capabilities".  embedding_dim is the selected Voyage output
    dimension; None means use the model's catalog default.  Both are emitted
    as camelCase by to_camel (contextWindow, embeddingDim).
    """

    id: str
    connection_id: str
    model_id: str
    resolved_from: str | None = None
    context_window: int | None = None
    # Selected Voyage output dimension; None = use catalog default.
    embedding_dim: int | None = None


class ResolvedCapabilitiesWire(KoanBaseModel):
    """Read-only resolved capability snapshot for one configured model (M6).

    Populated by resolve_capabilities(conn.type, cm.model_id) and surfaced via
    Settings.model_capabilities.  Never persisted and never asked -- computed
    from the PydanticAI profile + koan bundled knowledge + recognition parse
    (brief D4/D5).  Keyed by configured_model_id so the UI can join against the
    configured_models list without an extra lookup.
    """

    configured_model_id: str
    thinking_supported: bool = False
    thinking_modes: list[str] = []
    thinking_shape: str = "none"
    supports_web_search: bool = False
    supports_tools: bool = True
    context_window: int = 0
    context_window_variants: list[int] = []
    supports_prompt_caching: bool = False
    tier_hint: str | None = None
    recognized: bool = True


class SlotAssignmentWire(KoanBaseModel):
    """Wire representation of a SlotAssignment inside a preset (M5)."""

    configured_model_id: str
    thinking: str = "disabled"


class PresetWire(KoanBaseModel):
    """Wire representation of a Preset (M5).

    slots maps role-slot names (strong/standard/cheap) to SlotAssignmentWire.
    """

    slots: dict[str, SlotAssignmentWire] = {}


class ModelRegistryEntryWire(KoanBaseModel):
    """Wire representation of ModelRegistryEntry pushed by the model_registry_listed event.

    Payload shape: {models: [{provider, model, display_name, context_window,
    thinking_modes, tier_hint}, ...]}.
    Fold sets Settings.model_registry from the models list.
    """

    provider: str
    model: str
    display_name: str
    context_window: int
    thinking_modes: list[str] = []
    tier_hint: str | None = None


class EmbeddingModelWire(KoanBaseModel):
    """Wire representation of one recognized Voyage embedding model (camelCase via to_camel).

    Payload shape: {models: [{model_id, context_window, dimensions, default_dimension}, ...]}.
    Fold sets Settings.embedding_models from the models list on the
    embedding_models_listed event; replace-all semantics.
    """

    model_id: str
    context_window: int
    # Selectable output dimensions (ascending).
    dimensions: list[int] = []
    default_dimension: int = 0


class ProviderModelWire(KoanBaseModel):
    """Wire representation of ProviderModel pushed by the provider_models_listed event.

    Payload shape: {models: [{provider, model, display_name, context_window,
    connection_id}, ...]}.  The alias_generator=to_camel emits displayName,
    contextWindow, and connectionId on the wire.  Fold sets
    Settings.provider_models from the flat cross-provider models list;
    replace-all semantics (same as model_registry_listed).  The frontend
    overlay join is per-connection (by connectionId), not per provider type,
    so two connections of the same type keep independent model lists.
    """

    provider: str
    model: str
    display_name: str
    context_window: int = 0
    connection_id: str = ""


class ProviderFamilyWire(KoanBaseModel):
    """Wire representation of a per-provider newest-in-family pin.

    Payload shape: {families: [{provider, family, resolved, resolved_from,
    connection_id}, ...]}.  Delivered alongside provider_models in the
    provider_models_listed event.  Replace-all semantics: each event replaces
    the full families list.  connection_id scopes the pin to its originating
    connection so same-type connections carry independent family sets.
    resolved_from is optional on the wire (defaults to ""); callers may omit it.
    """

    provider: str
    family: str
    resolved: str
    resolved_from: str = ""
    connection_id: str = ""


class Settings(KoanBaseModel):
    """Top-level projection settings populated at server startup.

    workflows is static for the process lifetime: it is populated once by the
    workflows_listed initial event and never updated after that. It is placed
    here (rather than on Run) so the frontend can read it before any run starts.

    M5: profiles/default_profile removed; replaced by connections, configured_models,
    presets, active, memory_bindings (the new config entity surfaces).
    provider_status reshaped to per-connection ConnectionStatusWire (brief D3).
    model_registry and provider_models kept; they are capability/listing surfaces
    owned by M6.
    """
    # M5: new config entity surfaces (replace profiles/default_profile)
    connections: list[ConnectionWire] = []
    configured_models: list[ConfiguredModelWire] = []
    presets: dict[str, PresetWire] = {}
    active: str = "$last"
    # memory_bindings stored as opaque dict; M6 will add a typed wire shape.
    memory_bindings: dict | None = None
    # M5: per-connection availability (replaces per-type provider_status from M2)
    provider_status: list[ConnectionStatusWire] = []
    default_scout_concurrency: int = 8
    workflows: list[WorkflowInfo] = []            # populated once by workflows_listed at startup
    # M2: all-providers model registry (capability/listing surface; M6 owns reshape)
    model_registry: list[ModelRegistryEntryWire] = []
    # Dynamic per-provider model overlay; populated by provider_models_listed events.
    provider_models: list[ProviderModelWire] = []
    # Newest-in-family pins; populated alongside provider_models by provider_models_listed.
    provider_families: list[ProviderFamilyWire] = []
    # M6: read-only per-configured-model capability snapshot; populated by
    # model_capabilities_listed.  Recomputed on startup and on any mutation
    # that touches connections or configured_models (a connection's type
    # determines its models' resolved capabilities).
    model_capabilities: list[ResolvedCapabilitiesWire] = []
    # Static catalog of recognized Voyage embedding models; populated once at
    # startup by embedding_models_listed and never updated after that.
    embedding_models: list[EmbeddingModelWire] = []


class RunConfig(KoanBaseModel):
    """Resolved configuration frozen at run start.

    M5: 'profile' renamed to 'active_preset'; installations dropped (removed M4).
    """
    active_preset: str  # name of the preset active when the run started
    # installations removed in M4: agent installation concept deleted.
    scout_concurrency: int = 8


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

# -- Memory types -------------------------------------------------------------
# Flat optional strings rather than a discriminated union so the wire shape
# maps directly to MemoryCurationPage.tsx proposal types without a discriminator.

def _coerce_str(v: object) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return json.dumps(v)
    return str(v)

class Proposal(KoanBaseModel):
    id: str
    op: Literal["add", "update", "deprecate"]
    type: Literal["decision", "context", "lesson", "procedure"]
    seq: Annotated[str, BeforeValidator(_coerce_str)] = ""
    title: str
    meta: Annotated[str, BeforeValidator(_coerce_str)] = ""
    rationale: str
    body: str = ""       # used by add and deprecate
    before: str = ""     # used by update
    after: str = ""      # used by update

class ActiveCurationBatch(KoanBaseModel):
    proposals: list[Proposal]
    batch_id: str
    context_note: str = ""

class MemoryEntrySummary(KoanBaseModel):
    seq: str
    type: Literal["decision", "context", "lesson", "procedure"]
    title: str
    created_ms: int
    modified_ms: int

class MemoryState(KoanBaseModel):
    # Keyed by seq string (e.g. "0042"). Projection is project-scoped, not
    # run-scoped, so it persists across workflow boundaries.
    entries: dict[str, MemoryEntrySummary] = {}
    summary: str = ""

# -- Reflect types ------------------------------------------------------------

class ReflectCitation(KoanBaseModel):
    id: int
    title: str
    type: Literal["decision", "context", "lesson", "procedure"]
    modified_ms: int

class ReflectTrace(KoanBaseModel):
    iteration: int
    # Discriminator: "search"/"done" are tool calls; "thinking"/"text" are
    # streaming model output deltas. All ride in the same "reflect_trace" event
    # so the frontend receives one ordered list without separate event types.
    kind: Literal["search", "done", "thinking", "text"]
    # search-only fields
    query: str = ""
    type_filter: str = ""
    result_count: int | None = None
    # thinking / text delta
    delta: str = ""

class ReflectRun(KoanBaseModel):
    session_id: str
    question: str
    status: Literal["in_progress", "done", "cancelled", "failed"]
    started_at_ms: int
    completed_at_ms: int | None = None
    iteration: int = 0
    max_iterations: int = 10
    model: str = ""
    traces: list[ReflectTrace] = []
    answer: str = ""
    citations: list[ReflectCitation] = []
    error: str = ""

# -- Basic projection types ---------------------------------------------------

class ArtifactInfo(KoanBaseModel):
    path: str
    size: int = 0
    modified_at: int = 0                   # milliseconds since epoch

class CompletionInfo(KoanBaseModel):
    success: bool
    summary: str = ""
    error: str | None = None

class Notification(KoanBaseModel):
    message: str
    level: Literal["info", "warning", "error"] = "info"
    timestamp_ms: int = 0


# ---------------------------------------------------------------------------
# Run and top-level Projection
# ---------------------------------------------------------------------------

class SteeringMessage(KoanBaseModel):
    """A pending steering message shown above the chat input.

    timestamp_ms is the enqueue wall-clock time (milliseconds since epoch),
    carried from the steering_queued event payload. None for events recorded
    before this field was introduced -- callers must treat None as "not
    available" rather than zero to avoid spurious zero-latency readings.
    """
    content: str
    timestamp_ms: int | None = None

class PhaseInfo(KoanBaseModel):
    """A phase the user can transition to, as shown in the command palette."""
    id: str                                # phase key (e.g. "plan-spec")
    description: str                       # one-line description from the workflow

class WorkflowInfo(KoanBaseModel):
    """A workflow entry used in two contexts:
    - Settings.workflows: static list populated once at server startup via
      the workflows_listed initial event; read by NewRunForm for selection
      and by App.tsx for the /workflow:<name> command palette.
    - Previously also populated per-run in Run.available_workflows; that
      field was removed -- the registry now lives exclusively at Settings.workflows.

    phases and initial_phase are present in both contexts.
    """
    id: str                       # workflow name (e.g. "plan", "milestones", "curation")
    description: str              # one-line description from Workflow.description
    phases: list[PhaseInfo] = []  # ordered list of phases in this workflow
    initial_phase: str = ""       # first phase the orchestrator enters

class Run(KoanBaseModel):
    config: RunConfig
    phase: str = ""
    workflow: str = ""    # active workflow name
    available_phases: list[PhaseInfo] = []      # populated on workflow_selected; drives the / command palette
    # available_workflows removed: the workflows registry now lives at Settings.workflows,
    # populated once by the workflows_listed initial event.
    agents: dict[str, Agent] = {}          # all agents by ID — queued, running, done, failed
    focus: Focus | None = None             # None before first agent spawns
    artifacts: dict[str, ArtifactInfo] = {}
    completion: CompletionInfo | None = None
    steering: list[SteeringMessage] = []   # pending steering messages shown above chat
    active_yield: ActiveYield | None = None  # non-None while orchestrator is in koan_yield
    active_curation_batch: ActiveCurationBatch | None = None  # non-None while orchestrator is in koan_memory_propose

class Projection(KoanBaseModel):
    settings: Settings = Field(default_factory=Settings)
    run: Run | None = None                 # None → show landing page
    notifications: list[Notification] = []
    # Memory is project-scoped, not run-scoped: persists across workflow
    # boundaries and is reachable even when run is None.
    memory: MemoryState = Field(default_factory=MemoryState)
    # Reflect is project-scoped: not tied to a workflow run.
    reflect: ReflectRun | None = None


# ---------------------------------------------------------------------------
# Fold helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flush_conversation(conv: Conversation) -> Conversation:
    """Flush both pending fields into completed entries.

    Creates a ThinkingEntry from pending_thinking and/or TextEntry from pending_text,
    appends them to entries, and resets both pending fields and is_thinking.
    """
    new_entries = list(conv.entries)
    if conv.pending_thinking:
        new_entries.append(ThinkingEntry(content=conv.pending_thinking))
    if conv.pending_text:
        new_entries.append(TextEntry(text=conv.pending_text))
    return conv.model_copy(update={
        "entries": new_entries,
        "pending_thinking": "",
        "pending_text": "",
        "is_thinking": False,
    })


def _flush_pending_text(conv: Conversation) -> Conversation:
    """Flush only pending_text into a TextEntry (used when thinking starts)."""
    if not conv.pending_text:
        return conv.model_copy(update={"is_thinking": True})
    return conv.model_copy(update={
        "entries": [*conv.entries, TextEntry(text=conv.pending_text)],
        "pending_text": "",
        "is_thinking": True,
    })


def _flush_pending_thinking(conv: Conversation) -> Conversation:
    """Flush only pending_thinking into a ThinkingEntry (used when text starts)."""
    if not conv.pending_thinking:
        return conv.model_copy(update={"is_thinking": False})
    return conv.model_copy(update={
        "entries": [*conv.entries, ThinkingEntry(content=conv.pending_thinking)],
        "pending_thinking": "",
        "is_thinking": False,
    })


def _append_exploration_child(
    conv: Conversation,
    child: AggregateChild,
    ts_ms: int,
) -> Conversation:
    """Append an exploration-tool child to the trailing aggregate, or start a new one.

    Always flushes pending text/thinking first — exploration tools appear in the
    same stream as prose, so any in-progress prose must close out before a tool
    entry lands. After the flush, if the last entry is a ToolAggregateEntry the
    child is appended to it; otherwise a new ToolAggregateEntry is created. The
    existing aggregate's started_at_ms is preserved; only the children list grows.
    """
    flushed = _flush_conversation(conv)
    entries = list(flushed.entries)
    if entries and isinstance(entries[-1], ToolAggregateEntry):
        aggregate = entries[-1]
        grown = aggregate.model_copy(update={
            "children": [*aggregate.children, child],
        })
        entries[-1] = grown
    else:
        entries.append(ToolAggregateEntry(
            children=[child],
            started_at_ms=ts_ms,
        ))
    return flushed.model_copy(update={"entries": entries})


def _get_agent(run: Run, agent_id: str | None) -> Agent | None:
    if not agent_id or run is None:
        return None
    return run.agents.get(agent_id)


def _primary_agent_id(run: Run) -> str | None:
    """Return the agent_id of the primary agent, or None."""
    if run is None:
        return None
    for agent in run.agents.values():
        if agent.is_primary and agent.status == "running":
            return agent.agent_id
    # Fall back to any primary agent (e.g. if it just exited)
    for agent in run.agents.values():
        if agent.is_primary:
            return agent.agent_id
    return None




def _update_agent_conversation(run: Run, agent_id: str, new_conv: Conversation, **extra) -> Run:
    """Return a new Run with the agent's conversation replaced and optional extra updates."""
    agent = run.agents.get(agent_id)
    if agent is None:
        return run
    new_agent = agent.model_copy(update={"conversation": new_conv, **extra})
    new_agents = dict(run.agents)
    new_agents[agent_id] = new_agent
    return run.model_copy(update={"agents": new_agents})


# RENDERABLE_KOAN_TOOLS removed in M1: every koan MCP tool now follows the
# same lifecycle (tool_request -> tool_input_delta -> tool_result) and
# produces ToolKoanEntry. Selection happens in the fold's tool_request case
# by membership in KOAN_MCP_TOOLS (imported from koan.agents.events).


def _derive_usage(conv: "Conversation", agent: "Agent", usage: dict) -> "Conversation":
    """Accumulate cache token facts and derive cost + context-window percent.

    Called from both agent_exited and agent_step_advanced usage blocks so the
    derivation logic is in one place (mirrors the existing input/output dual-fold
    pattern). cache_read/write_tokens are folded facts (cumulative sums from the
    usage dict). total_cost_usd and context_window_percent are derived values:
    they are never recorded as event facts and belong entirely to the fold.

    Fold-safety contract:
    - price_for_usage is imported lazily (bundled snapshot only; no network).
    - try/except around price_for_usage: keeps the prior cost on any failure
      (e.g. unresolvable model, missing provider) rather than raising.
    - context_window_percent is only computed when agent.context_window > 0
      to avoid zero-division.
    """
    # Accumulate cache token facts (cumulative sums).
    new_cache_read = conv.cache_read_tokens + usage.get("cache_read_tokens", 0)
    new_cache_write = conv.cache_write_tokens + usage.get("cache_write_tokens", 0)

    conv = conv.model_copy(update={
        "input_tokens": conv.input_tokens + usage.get("input_tokens", 0),
        "output_tokens": conv.output_tokens + usage.get("output_tokens", 0),
        "cache_read_tokens": new_cache_read,
        "cache_write_tokens": new_cache_write,
    })

    # Derive total_cost_usd from the updated cumulative totals.
    # Wrapped in try/except so an unresolvable model never raises in the fold.
    if agent.provider and agent.model:
        try:
            from .agents.model_catalog import price_for_usage
            total_cost = float(price_for_usage(
                agent.provider,
                agent.model,
                conv.input_tokens,
                conv.output_tokens,
                conv.cache_read_tokens,
                conv.cache_write_tokens,
            ))
            conv = conv.model_copy(update={"total_cost_usd": total_cost})
        except Exception:
            # Keep the prior total_cost_usd on failure (e.g. unknown model).
            pass

    # Derive context_window_percent from the most recent turn's input tokens.
    # last_input_tokens is overwritten each turn (not summed) so it reflects
    # current context fullness rather than a double-counted cumulative sum.
    if agent.context_window > 0:
        last_input = usage.get("last_input_tokens", 0)
        percent = round(min(100.0, last_input / agent.context_window * 100), 1)
        conv = conv.model_copy(update={"context_window_percent": percent})

    return conv


# ---------------------------------------------------------------------------
# Fold
# ---------------------------------------------------------------------------

def fold(projection: Projection, event: VersionedEvent) -> Projection:
    """Pure fold: (Projection, VersionedEvent) → Projection.

    Unknown event types return projection unchanged with a logged warning.
    Any exception returns projection unchanged with the exception logged.
    """
    event_type = event.event_type
    payload = event.payload
    agent_id = event.agent_id

    try:
        match event_type:

            # ── Run lifecycle ──────────────────────────────────────────────

            case "run_started":
                # M5: 'profile' renamed to 'active_preset' in payload and RunConfig.
                config = RunConfig(
                    active_preset=payload.get("active_preset", ""),
                    scout_concurrency=payload.get("scout_concurrency", 8),
                )
                return projection.model_copy(update={"run": Run(config=config)})


            case "workflow_selected":
                if projection.run is None:
                    log.warning("fold workflow_selected: run is None, skipping")
                    return projection
                workflow_name = payload.get("workflow", "")
                workflow = WORKFLOWS.get(workflow_name)
                available_phases: list[PhaseInfo] = []
                if workflow is not None:
                    available_phases = [
                        PhaseInfo(id=p, description=workflow.phase_descriptions.get(p, ""))
                        for p in workflow.available_phases
                    ]
                # Workflows registry now lives at Settings.workflows, populated once
                # by the workflows_listed initial event -- no longer rebuilt here.
                new_run = projection.run.model_copy(update={
                    "workflow": workflow_name,
                    "available_phases": available_phases,
                })
                return projection.model_copy(update={"run": new_run})

            case "phase_started":
                if projection.run is None:
                    log.warning("fold phase_started: run is None, skipping")
                    return projection
                new_run = projection.run.model_copy(update={
                    "phase": payload.get("phase", ""),
                    "active_yield": None,          # clear yield when a new phase starts
                    "active_curation_batch": None,  # clear any pending curation on phase transition
                })
                return projection.model_copy(update={"run": new_run})

            case "workflow_completed":
                if projection.run is None:
                    log.warning("fold workflow_completed: run is None, skipping")
                    return projection
                completion = CompletionInfo(
                    success=payload.get("success", False),
                    summary=payload.get("summary", ""),
                    error=payload.get("error"),
                )
                new_run = projection.run.model_copy(update={
                    "completion": completion,
                    "active_yield": None,          # clear yield on completion
                    "active_curation_batch": None,  # clear any pending curation on completion
                })
                return projection.model_copy(update={"run": new_run})

            case "run_cleared":
                # Idempotent: no-op when the run is already gone. This is an
                # expected call path (e.g. double-clear), not a bug, so no warning.
                if projection.run is None:
                    return projection
                return projection.model_copy(update={"run": None})

            # ── Agent lifecycle ────────────────────────────────────────────

            case "agents_cleared":
                if projection.run is None:
                    return projection
                new_agents = {k: v for k, v in projection.run.agents.items() if v.is_primary}
                new_run = projection.run.model_copy(update={"agents": new_agents})
                return projection.model_copy(update={"run": new_run})

            case "scout_queued":
                if projection.run is None:
                    log.warning("fold scout_queued: run is None, skipping")
                    return projection
                scout_id = payload.get("scout_id", "")
                new_agent = Agent(
                    agent_id=scout_id,
                    role="scout",
                    label=payload.get("label", ""),
                    model=payload.get("model"),
                    status="queued",
                )
                new_agents = dict(projection.run.agents)
                new_agents[scout_id] = new_agent
                new_run = projection.run.model_copy(update={"agents": new_agents})
                return projection.model_copy(update={"run": new_run})

            case "agent_spawned":
                if projection.run is None:
                    log.warning("fold agent_spawned: run is None, skipping")
                    return projection
                eid = agent_id or payload.get("agent_id", "")
                is_primary = payload.get("is_primary", False)
                new_agents = dict(projection.run.agents)

                # Look up by agent_id first (exact match), then fall back
                # to label match.  scout_queued keys agents by label
                # (e.g. "database-and-testing") while agent_spawned keys
                # by UUID, so the secondary lookup bridges the two.
                queued_key: str | None = None
                if eid in new_agents:
                    queued_key = eid
                else:
                    spawn_label = payload.get("label", "")
                    if spawn_label:
                        for k, a in new_agents.items():
                            if a.label == spawn_label and a.status == "queued":
                                queued_key = k
                                break

                if queued_key is not None:
                    # Transition queued -> running. Re-key under the real
                    # agent_id so all subsequent events (which use the UUID)
                    # find the right entry.
                    existing = new_agents.pop(queued_key)
                    new_agents[eid] = existing.model_copy(update={
                        "agent_id": eid,
                        "status": "running",
                        "started_at_ms": payload.get("started_at_ms", 0),
                        "role": payload.get("role", existing.role),
                        "label": payload.get("label", existing.label),
                        "model": payload.get("model", existing.model),
                        "provider": payload.get("provider"),
                        "context_window": payload.get("context_window", 0),
                    })
                else:
                    # New agent (primary agents are always new)
                    new_agents[eid] = Agent(
                        agent_id=eid,
                        role=payload.get("role", ""),
                        label=payload.get("label", ""),
                        model=payload.get("model"),
                        is_primary=is_primary,
                        status="running",
                        started_at_ms=payload.get("started_at_ms", 0),
                        provider=payload.get("provider"),
                        context_window=payload.get("context_window", 0),
                    )

                new_run = projection.run.model_copy(update={"agents": new_agents})

                # Set ConversationFocus when primary agent spawns
                if is_primary:
                    new_run = new_run.model_copy(update={
                        "focus": ConversationFocus(agent_id=eid),
                    })

                return projection.model_copy(update={"run": new_run})

            case "agent_exited":
                error = payload.get("error")
                # Append error notification regardless of run/agent state — the fact
                # of a failed exit is worth preserving even if the agent wasn't tracked.
                if error and (projection.run is None or not agent_id or
                              agent_id not in (projection.run.agents if projection.run else {})):
                    notif = Notification(
                        message=f"Agent exited with error: {error}",
                        level="error",
                        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                    )
                    return projection.model_copy(update={
                        "notifications": [*projection.notifications, notif],
                    })
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    log.warning("fold agent_exited: unknown agent_id=%s", agent_id)
                    return projection

                exit_code = payload.get("exit_code", 0)
                usage = payload.get("usage")
                status: Literal["done", "failed"] = "failed" if error or exit_code != 0 else "done"

                # Accumulate final usage into conversation and derive cost/context%.
                # _derive_usage handles input/output/cache accumulation and
                # derives total_cost_usd + context_window_percent in one call.
                new_conv = agent.conversation
                if usage:
                    new_conv = _derive_usage(new_conv, agent, usage)

                new_agent = agent.model_copy(update={
                    "status": status,
                    "error": error,
                    "conversation": new_conv,
                    "completed_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
                })
                new_agents = dict(projection.run.agents)
                new_agents[agent_id] = new_agent
                new_run = projection.run.model_copy(update={"agents": new_agents})
                # Executor failures surface in the orchestrator's koan_request_executor
                # tool result (see ExecutorCard); failed agent status persists on
                # agent.status/agent.error. No transient notification toast.
                return projection.model_copy(update={"run": new_run})

            case "agent_spawn_failed":
                notif = Notification(
                    message=payload.get("message", "Agent spawn failed"),
                    level="error",
                    timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                )
                return projection.model_copy(update={
                    "notifications": [*projection.notifications, notif],
                })

            # ── Agent conversation ─────────────────────────────────────────

            case "thinking":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                delta = payload.get("delta", "")
                # Flush pending_text → TextEntry, then accumulate thinking delta
                new_conv = _flush_pending_text(agent.conversation)
                new_conv = new_conv.model_copy(update={
                    "pending_thinking": new_conv.pending_thinking + delta,
                    "is_thinking": True,
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "stream_delta":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                delta = payload.get("delta", "")
                # Flush pending_thinking → ThinkingEntry, then accumulate text delta
                new_conv = _flush_pending_thinking(agent.conversation)
                new_conv = new_conv.model_copy(update={
                    "pending_text": new_conv.pending_text + delta,
                    "is_thinking": False,
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "stream_cleared":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                new_conv = _flush_conversation(agent.conversation)
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "tool_started":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                tool_name = payload.get("tool", "")
                call_id = payload.get("call_id", "")
                last_tool = tool_name
                new_conv = _flush_conversation(agent.conversation)
                new_entry = ToolGenericEntry(
                    call_id=call_id,
                    in_flight=True,
                    tool_name=tool_name,
                    summary="",
                )
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, new_entry],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=last_tool),
                })

            case "tool_stopped":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                call_id = payload.get("call_id", "")
                summary = payload.get("summary", "")
                tool_name = payload.get("tool", "")
                last_tool = f"{tool_name} {summary}".strip() if summary else tool_name
                new_entries = []
                for entry in agent.conversation.entries:
                    if isinstance(entry, BaseToolEntry) and entry.call_id == call_id:
                        update: dict = {"in_flight": False}
                        if summary and isinstance(entry, ToolGenericEntry):
                            update["summary"] = summary
                        new_entries.append(entry.model_copy(update=update))
                    else:
                        new_entries.append(entry)
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=last_tool),
                })

            case "tool_called":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                tool_name = payload.get("tool", "")
                # Legacy tool_called fold case retains the historical gate so
                # existing test fixtures and replay logs are not broken. New
                # code emits tool_request (handled below) not tool_called.
                if tool_name == "koan_reflect":
                    call_id = payload.get("call_id", "")
                    raw_args = payload.get("args", {})
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except (json.JSONDecodeError, TypeError):
                            raw_args = {"raw": raw_args}
                    summary = payload.get("summary", "")
                    last_tool = f"{tool_name} {summary}".strip() if summary else tool_name
                    new_conv = _flush_conversation(agent.conversation)
                    new_entry = ToolKoanEntry(
                        call_id=call_id,
                        in_flight=True,
                        tool_name=tool_name,
                        args=raw_args,
                    )
                    new_conv = new_conv.model_copy(update={
                        "entries": [*new_conv.entries, new_entry],
                    })
                    return projection.model_copy(update={
                        "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                          last_tool=last_tool),
                    })
                if tool_name.startswith("koan_") or tool_name.startswith("mcp__koan"):
                    return projection
                call_id = payload.get("call_id", "")
                summary = payload.get("summary", "")
                last_tool = f"{tool_name} {summary}".strip() if summary else tool_name
                new_conv = _flush_conversation(agent.conversation)
                new_entry = ToolGenericEntry(
                    call_id=call_id,
                    in_flight=True,
                    tool_name=tool_name,
                    summary=summary,
                )
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, new_entry],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=last_tool),
                })

            case "tool_read":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                file = payload.get("file", "")
                lines = payload.get("lines", "")
                last_tool = f"read {file}:{lines}" if lines else f"read {file}"
                ts_ms = payload.get("ts_ms", 0)
                child = AggregateReadChild(
                    call_id=payload.get("call_id", ""),
                    in_flight=True,
                    file=file,
                    lines=lines,
                    started_at_ms=ts_ms,
                )
                new_conv = _append_exploration_child(agent.conversation, child, ts_ms)
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=last_tool),
                })

            case "tool_write":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                file = payload.get("file", "")
                new_conv = _flush_conversation(agent.conversation)
                new_entry = ToolWriteEntry(
                    call_id=payload.get("call_id", ""),
                    in_flight=True,
                    file=file,
                )
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, new_entry],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=f"write {file}"),
                })

            case "tool_edit":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                file = payload.get("file", "")
                new_conv = _flush_conversation(agent.conversation)
                new_entry = ToolEditEntry(
                    call_id=payload.get("call_id", ""),
                    in_flight=True,
                    file=file,
                )
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, new_entry],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=f"edit {file}"),
                })

            case "tool_bash":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                command = payload.get("command", "")
                new_conv = _flush_conversation(agent.conversation)
                new_entry = ToolBashEntry(
                    call_id=payload.get("call_id", ""),
                    in_flight=True,
                    command=command,
                )
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, new_entry],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=f"bash {command}"),
                })

            case "tool_grep":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                pattern = payload.get("pattern", "")
                ts_ms = payload.get("ts_ms", 0)
                child = AggregateGrepChild(
                    call_id=payload.get("call_id", ""),
                    in_flight=True,
                    pattern=pattern,
                    started_at_ms=ts_ms,
                )
                new_conv = _append_exploration_child(agent.conversation, child, ts_ms)
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=f"grep {pattern}"),
                })

            case "tool_ls":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                path = payload.get("path", "")
                ts_ms = payload.get("ts_ms", 0)
                child = AggregateLsChild(
                    call_id=payload.get("call_id", ""),
                    in_flight=True,
                    path=path,
                    started_at_ms=ts_ms,
                )
                new_conv = _append_exploration_child(agent.conversation, child, ts_ms)
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      last_tool=f"ls {path}"),
                })

            case "tool_completed":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                call_id = payload.get("call_id", "")
                ts_ms = payload.get("ts_ms", 0)
                # Scan two levels: top-level tool entries (bash/write/edit/generic)
                # and aggregate children (read/grep/ls). A single tool_completed
                # event may target either — the runner does not know which.
                new_entries = []
                found = False
                # Parse attachment manifest from the event once; applied to the
                # matched entry regardless of type (koan, bash, write, etc.).
                raw_attachments = payload.get("attachments")
                parsed_attachments: list[AttachmentEntry] | None = None
                if raw_attachments and isinstance(raw_attachments, list):
                    try:
                        parsed_attachments = [AttachmentEntry(**a) for a in raw_attachments]
                    except Exception:
                        pass  # malformed manifest; degrade silently
                for entry in agent.conversation.entries:
                    if (
                        isinstance(entry, BaseToolEntry)
                        and entry.call_id == call_id
                        and not isinstance(entry, ToolAggregateEntry)
                    ):
                        update: dict = {"in_flight": False}
                        if isinstance(entry, ToolKoanEntry):
                            raw_result = payload.get("result")
                            if raw_result and isinstance(raw_result, str):
                                try:
                                    update["result"] = json.loads(raw_result)
                                except (json.JSONDecodeError, TypeError):
                                    update["result"] = {"raw": raw_result}
                            elif isinstance(raw_result, dict):
                                update["result"] = raw_result
                        if parsed_attachments:
                            update["attachments"] = parsed_attachments
                        new_entries.append(entry.model_copy(update=update))
                        found = True
                    elif isinstance(entry, ToolAggregateEntry):
                        new_children = []
                        child_found = False
                        for child in entry.children:
                            if child.call_id == call_id:
                                new_children.append(child.model_copy(update={
                                    "in_flight": False,
                                    "completed_at_ms": ts_ms or None,
                                }))
                                child_found = True
                            else:
                                new_children.append(child)
                        if child_found:
                            found = True
                            new_entries.append(entry.model_copy(update={"children": new_children}))
                        else:
                            new_entries.append(entry)
                    else:
                        new_entries.append(entry)
                if not found:
                    log.warning(
                        "fold: tool_completed for unknown call_id=%r agent=%r",
                        call_id, agent_id,
                    )
                    return projection
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "tool_result_captured":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                call_id = payload.get("call_id", "")
                metrics = payload.get("metrics")
                if not metrics or not isinstance(metrics, dict):
                    # No parsed metrics to attach; fold is a no-op. Runner emits
                    # these even when parsing failed so the event trail stays
                    # symmetric, but there is nothing for the projection to do.
                    return projection
                new_entries = []
                found = False
                for entry in agent.conversation.entries:
                    if not isinstance(entry, ToolAggregateEntry):
                        new_entries.append(entry)
                        continue
                    new_children = []
                    child_found = False
                    for child in entry.children:
                        if child.call_id != call_id:
                            new_children.append(child)
                            continue
                        update: dict = {}
                        if isinstance(child, AggregateReadChild):
                            if "lines_read" in metrics:
                                update["lines_read"] = metrics["lines_read"]
                            if "bytes_read" in metrics:
                                update["bytes_read"] = metrics["bytes_read"]
                        elif isinstance(child, AggregateGrepChild):
                            if "matches" in metrics:
                                update["matches"] = metrics["matches"]
                            if "files_matched" in metrics:
                                update["files_matched"] = metrics["files_matched"]
                        elif isinstance(child, AggregateLsChild):
                            if "entries" in metrics:
                                update["entries"] = metrics["entries"]
                            if "directories" in metrics:
                                update["directories"] = metrics["directories"]
                        elif isinstance(child, AggregateGlobChild):
                            # M4: glob uses same metrics shape as grep.
                            if "matches" in metrics:
                                update["matches"] = metrics["matches"]
                            if "files_matched" in metrics:
                                update["files_matched"] = metrics["files_matched"]
                        if update:
                            new_children.append(child.model_copy(update=update))
                        else:
                            new_children.append(child)
                        child_found = True
                    if child_found:
                        found = True
                        new_entries.append(entry.model_copy(update={"children": new_children}))
                    else:
                        new_entries.append(entry)
                if not found:
                    log.warning(
                        "fold: tool_result_captured for unknown call_id=%r agent=%r",
                        call_id, agent_id,
                    )
                    return projection
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "tool_request":
                # Single entry-creation event for all tool types. Replaces
                # tool_started / tool_called / tool_read / tool_bash / etc.
                # Branch on tool_name once here; all subsequent events use
                # call_id for correlation without tool-name branching.
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                tool_name = payload.get("tool", "")
                call_id = payload.get("call_id", "")
                if tool_name in KOAN_MCP_TOOLS:
                    new_conv = _flush_conversation(agent.conversation)
                    new_entry = ToolKoanEntry(
                        call_id=call_id, in_flight=True,
                        tool_name=tool_name, args={}, result=None,
                    )
                    new_conv = new_conv.model_copy(update={
                        "entries": [*new_conv.entries, new_entry],
                    })
                    return projection.model_copy(update={
                        "run": _update_agent_conversation(
                            projection.run, agent_id, new_conv,
                            last_tool=tool_name,
                        ),
                    })
                if tool_name == "write":
                    new_conv = _flush_conversation(agent.conversation)
                    new_entry = ToolWriteEntry(call_id=call_id, in_flight=True, file="")
                    new_conv = new_conv.model_copy(update={
                        "entries": [*new_conv.entries, new_entry],
                    })
                    return projection.model_copy(update={
                        "run": _update_agent_conversation(
                            projection.run, agent_id, new_conv, last_tool="write",
                        ),
                    })
                if tool_name == "edit":
                    new_conv = _flush_conversation(agent.conversation)
                    new_entry = ToolEditEntry(call_id=call_id, in_flight=True, file="")
                    new_conv = new_conv.model_copy(update={
                        "entries": [*new_conv.entries, new_entry],
                    })
                    return projection.model_copy(update={
                        "run": _update_agent_conversation(
                            projection.run, agent_id, new_conv, last_tool="edit",
                        ),
                    })
                if tool_name == "bash":
                    new_conv = _flush_conversation(agent.conversation)
                    new_entry = ToolBashEntry(call_id=call_id, in_flight=True, command="")
                    new_conv = new_conv.model_copy(update={
                        "entries": [*new_conv.entries, new_entry],
                    })
                    return projection.model_copy(update={
                        "run": _update_agent_conversation(
                            projection.run, agent_id, new_conv, last_tool="bash",
                        ),
                    })
                if tool_name in ("read", "grep", "ls", "glob"):
                    # Exploration tools aggregate into ToolAggregateEntry.
                    # Typed fields start empty; tool_input_delta fills them in.
                    # glob is treated like grep (file-search returning matches +
                    # files_matched); added in M4 when the built-in glob tool landed.
                    ts_ms = 0
                    if tool_name == "read":
                        child: AggregateChild = AggregateReadChild(
                            call_id=call_id, in_flight=True,
                            file="", lines="", started_at_ms=ts_ms,
                        )
                    elif tool_name == "grep":
                        child = AggregateGrepChild(
                            call_id=call_id, in_flight=True,
                            pattern="", started_at_ms=ts_ms,
                        )
                    elif tool_name == "glob":
                        child = AggregateGlobChild(
                            call_id=call_id, in_flight=True,
                            pattern="", started_at_ms=ts_ms,
                        )
                    else:  # ls
                        child = AggregateLsChild(
                            call_id=call_id, in_flight=True,
                            path="", started_at_ms=ts_ms,
                        )
                    new_conv = _append_exploration_child(agent.conversation, child, ts_ms)
                    return projection.model_copy(update={
                        "run": _update_agent_conversation(
                            projection.run, agent_id, new_conv, last_tool=tool_name,
                        ),
                    })
                # Unrecognised tool: generic fallback.
                new_conv = _flush_conversation(agent.conversation)
                new_entry_g = ToolGenericEntry(
                    call_id=call_id, in_flight=True, tool_name=tool_name, summary="",
                )
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, new_entry_g],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(
                        projection.run, agent_id, new_conv, last_tool=tool_name,
                    ),
                })

            case "tool_input_delta":
                # Update the in-flight entry with the latest aggregate input dict
                # and the just-arrived raw chunk. Also derive typed convenience
                # fields (file, command, pattern, path, args) so the frontend
                # renders live partial data without waiting for tool_result.
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                call_id = payload.get("call_id", "")
                new_tool_input: dict | None = payload.get("tool_input")
                new_delta = payload.get("delta")
                new_entries = []
                found = False
                for entry in agent.conversation.entries:
                    if isinstance(entry, ToolAggregateEntry):
                        new_children = []
                        child_found = False
                        for child in entry.children:
                            if child.call_id == call_id:
                                ti = new_tool_input if new_tool_input is not None else (child.tool_input or {})
                                upd: dict = {
                                    "tool_input": ti,
                                    "tool_input_delta": new_delta,
                                }
                                if isinstance(child, AggregateReadChild):
                                    upd["file"] = ti.get("file_path", "") or ti.get("path", "")
                                elif isinstance(child, AggregateGrepChild):
                                    upd["pattern"] = ti.get("pattern", "") or ti.get("query", "")
                                elif isinstance(child, AggregateLsChild):
                                    upd["path"] = ti.get("path", "") or ti.get("directory", "")
                                new_children.append(child.model_copy(update=upd))
                                child_found = True
                            else:
                                new_children.append(child)
                        if child_found:
                            found = True
                            new_entries.append(entry.model_copy(update={"children": new_children}))
                        else:
                            new_entries.append(entry)
                    elif isinstance(entry, BaseToolEntry) and entry.call_id == call_id:
                        ti = new_tool_input if new_tool_input is not None else (entry.tool_input or {})
                        upd = {"tool_input": ti, "tool_input_delta": new_delta}
                        if isinstance(entry, (ToolWriteEntry, ToolEditEntry)):
                            upd["file"] = ti.get("file_path", "") or ti.get("path", "")
                        elif isinstance(entry, ToolBashEntry):
                            upd["command"] = ti.get("command", "")
                        elif isinstance(entry, ToolKoanEntry):
                            # args is the canonical "latest known input" for koan tools
                            upd["args"] = ti
                        new_entries.append(entry.model_copy(update=upd))
                        found = True
                    else:
                        new_entries.append(entry)
                if not found:
                    log.warning(
                        "fold: tool_input_delta for unknown call_id=%r agent=%r",
                        call_id, agent_id,
                    )
                    return projection
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "tool_result":
                # Mirrors tool_completed semantics: set in_flight=False, attach
                # result/attachments. For exploration aggregate children also sets
                # completed_at_ms and applies metrics when present (same metrics
                # that tool_result_captured carries; whichever arrives first wins).
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                call_id = payload.get("call_id", "")
                ts_ms = payload.get("ts_ms", 0)
                metrics = payload.get("metrics")
                raw_attachments = payload.get("attachments")
                parsed_attachments: list[AttachmentEntry] | None = None
                if raw_attachments and isinstance(raw_attachments, list):
                    try:
                        parsed_attachments = [AttachmentEntry(**a) for a in raw_attachments]
                    except Exception:
                        pass  # malformed manifest; degrade silently
                new_entries = []
                found = False
                for entry in agent.conversation.entries:
                    if (
                        isinstance(entry, BaseToolEntry)
                        and entry.call_id == call_id
                        and not isinstance(entry, ToolAggregateEntry)
                    ):
                        upd = {"in_flight": False}
                        if isinstance(entry, ToolKoanEntry):
                            raw_result = payload.get("result")
                            if raw_result and isinstance(raw_result, str):
                                try:
                                    upd["result"] = json.loads(raw_result)
                                except (json.JSONDecodeError, TypeError):
                                    upd["result"] = {"raw": raw_result}
                            elif isinstance(raw_result, dict):
                                upd["result"] = raw_result
                        if parsed_attachments:
                            upd["attachments"] = parsed_attachments
                        new_entries.append(entry.model_copy(update=upd))
                        found = True
                    elif isinstance(entry, ToolAggregateEntry):
                        new_children = []
                        child_found = False
                        for child in entry.children:
                            if child.call_id == call_id:
                                child_upd: dict = {
                                    "in_flight": False,
                                    "completed_at_ms": ts_ms or None,
                                }
                                # Apply metrics when present so exploration children
                                # are complete after a single tool_result event;
                                # tool_result_captured may still arrive and is no-op.
                                if metrics and isinstance(metrics, dict):
                                    if isinstance(child, AggregateReadChild):
                                        if "lines_read" in metrics:
                                            child_upd["lines_read"] = metrics["lines_read"]
                                        if "bytes_read" in metrics:
                                            child_upd["bytes_read"] = metrics["bytes_read"]
                                    elif isinstance(child, AggregateGrepChild):
                                        if "matches" in metrics:
                                            child_upd["matches"] = metrics["matches"]
                                        if "files_matched" in metrics:
                                            child_upd["files_matched"] = metrics["files_matched"]
                                    elif isinstance(child, AggregateLsChild):
                                        if "entries" in metrics:
                                            child_upd["entries"] = metrics["entries"]
                                        if "directories" in metrics:
                                            child_upd["directories"] = metrics["directories"]
                                    elif isinstance(child, AggregateGlobChild):
                                        # M4: glob reuses grep's metrics shape.
                                        if "matches" in metrics:
                                            child_upd["matches"] = metrics["matches"]
                                        if "files_matched" in metrics:
                                            child_upd["files_matched"] = metrics["files_matched"]
                                new_children.append(child.model_copy(update=child_upd))
                                child_found = True
                            else:
                                new_children.append(child)
                        if child_found:
                            found = True
                            new_entries.append(entry.model_copy(update={"children": new_children}))
                        else:
                            new_entries.append(entry)
                    else:
                        new_entries.append(entry)
                if not found:
                    log.warning(
                        "fold: tool_result for unknown call_id=%r agent=%r",
                        call_id, agent_id,
                    )
                    return projection
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "reflect_delta":
                # Domain event: forward internal-LLM text fragments to the in-flight
                # ToolKoanEntry for this agent. Correlated by agent_id only per
                # intake decision 4 -- koan MCP tools block, so at most one in-flight
                # koan entry per agent. Other ReflectTraceEvent kinds (search, done,
                # thinking) stay on the project-scoped reflect projection; they do not
                # flow into the agent's conversation (M3 decision 3).
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                delta = payload.get("delta", "")
                if not delta:
                    return projection
                new_entries = list(agent.conversation.entries)
                target_idx: int | None = None
                for i, entry in enumerate(new_entries):
                    if isinstance(entry, ToolKoanEntry) and entry.in_flight:
                        target_idx = i
                        break
                if target_idx is None:
                    log.warning(
                        "fold reflect_delta: no in-flight ToolKoanEntry for agent=%r",
                        agent_id,
                    )
                    return projection
                target = new_entries[target_idx]
                existing_result = target.result or {}
                existing_answer = existing_result.get("answer", "") or ""
                new_result = {**existing_result, "answer": existing_answer + delta}
                new_entries[target_idx] = target.model_copy(update={"result": new_result})
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "tool_attachments":
                # Domain event: overwrite the in-flight tool entry's attachments with
                # a koan-side manifest carrying full upload_id and path fields. Emitted
                # by MCP handlers that have committed uploads. Correlated by agent_id
                # only -- same uniqueness invariant as reflect_delta.
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                raw_attachments = payload.get("attachments")
                if not raw_attachments or not isinstance(raw_attachments, list):
                    return projection
                try:
                    parsed = [AttachmentEntry(**a) for a in raw_attachments]
                except Exception:
                    log.warning(
                        "fold tool_attachments: malformed manifest for agent=%r",
                        agent_id,
                    )
                    return projection
                # Find the unique in-flight non-aggregate tool entry.
                # ToolAggregateEntry has no in_flight field; only its children do.
                new_entries = list(agent.conversation.entries)
                target_idx = None
                for i, entry in enumerate(new_entries):
                    if (
                        isinstance(entry, BaseToolEntry)
                        and not isinstance(entry, ToolAggregateEntry)
                        and entry.in_flight
                    ):
                        target_idx = i
                        break
                if target_idx is None:
                    log.warning(
                        "fold tool_attachments: no in-flight tool entry for agent=%r",
                        agent_id,
                    )
                    return projection
                new_entries[target_idx] = new_entries[target_idx].model_copy(
                    update={"attachments": parsed}
                )
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "debug_step_guidance":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                content = payload.get("content", "")
                new_conv = agent.conversation.model_copy(update={
                    "entries": [*agent.conversation.entries, DebugStepGuidanceEntry(content=content)],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "user_message":
                if projection.run is None:
                    return projection
                pid = _primary_agent_id(projection.run)
                if pid is None:
                    return projection
                agent = projection.run.agents.get(pid)
                if agent is None:
                    return projection
                entry = UserMessageEntry(
                    content=payload.get("content", ""),
                    timestamp_ms=payload.get("timestamp_ms", 0),
                )
                new_conv = _flush_conversation(agent.conversation)
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, entry],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, pid, new_conv),
                })

            case "phase_boundary_reached":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                entry = PhaseBoundaryEntry(
                    phase=payload.get("phase", ""),
                    message=payload.get("message", ""),
                )
                new_conv = _flush_conversation(agent.conversation)
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, entry],
                })
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "steering_queued":
                if projection.run is None:
                    return projection
                # timestamp_ms is optional: absent on legacy events.jsonl entries.
                # Treat None as "not available" (not 0) to avoid false zero-latency.
                entry = SteeringMessage(
                    content=payload.get("content", ""),
                    timestamp_ms=payload.get("timestamp_ms"),
                )
                return projection.model_copy(update={
                    "run": projection.run.model_copy(update={
                        "steering": [*projection.run.steering, entry],
                    }),
                })

            case "steering_delivered":
                if projection.run is None:
                    return projection
                # enqueue_ts_ms_list and delivery_ts_ms exist on the wire event
                # for replay/latency analysis only; they are not stored in the
                # live projection -- no in-memory consumer reads them here.
                return projection.model_copy(update={
                    "run": projection.run.model_copy(update={"steering": []}),
                })

            case "agent_step_advanced":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    log.warning("fold agent_step_advanced: unknown agent_id=%s", agent_id)
                    return projection

                step = payload.get("step", 0)
                step_name = payload.get("step_name", "")
                total_steps = payload.get("total_steps")
                usage = payload.get("usage")

                # Flush both pending fields, optionally append StepEntry.
                # step >= 0 so phase-transition markers (step=0 from koan_set_phase) also appear.
                new_conv = _flush_conversation(agent.conversation)
                if step >= 0 and step_name:
                    new_conv = new_conv.model_copy(update={
                        "entries": [*new_conv.entries, StepEntry(
                            step=step,
                            step_name=step_name,
                            total_steps=total_steps,
                        )],
                    })

                # Accumulate token usage from step (including cache facts and
                # derived cost/context%). agent_step_advanced carries no usage today
                # so this is a defensive no-op consistent with agent_exited's pattern.
                if usage:
                    new_conv = _derive_usage(new_conv, agent, usage)

                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv,
                                                      step=step, step_name=step_name),
                })

            # ── Focus transitions ──────────────────────────────────────────

            case "questions_asked":
                if projection.run is None or not agent_id:
                    return projection
                new_focus = QuestionFocus(
                    agent_id=agent_id,
                    token=payload.get("token", ""),
                    questions=payload.get("questions", []),
                )
                new_run = projection.run.model_copy(update={"focus": new_focus})
                return projection.model_copy(update={"run": new_run})

            case "questions_answered":
                if projection.run is None:
                    return projection
                pid = _primary_agent_id(projection.run)
                if pid is None:
                    return projection
                new_run = projection.run.model_copy(update={
                    "focus": ConversationFocus(agent_id=pid),
                })
                return projection.model_copy(update={"run": new_run})



            # ── Resources ─────────────────────────────────────────────────

            case "artifact_created":
                if projection.run is None:
                    return projection
                path = payload.get("path", "")
                info = ArtifactInfo(
                    path=path,
                    size=payload.get("size", 0),
                    modified_at=payload.get("modified_at", 0),
                )
                new_artifacts = dict(projection.run.artifacts)
                new_artifacts[path] = info
                new_run = projection.run.model_copy(update={"artifacts": new_artifacts})
                return projection.model_copy(update={"run": new_run})

            case "artifact_modified":
                if projection.run is None:
                    return projection
                path = payload.get("path", "")
                info = ArtifactInfo(
                    path=path,
                    size=payload.get("size", 0),
                    modified_at=payload.get("modified_at", 0),
                )
                new_artifacts = dict(projection.run.artifacts)
                new_artifacts[path] = info
                new_run = projection.run.model_copy(update={"artifacts": new_artifacts})
                return projection.model_copy(update={"run": new_run})

            case "artifact_removed":
                if projection.run is None:
                    return projection
                path = payload.get("path", "")
                new_artifacts = {k: v for k, v in projection.run.artifacts.items() if k != path}
                new_run = projection.run.model_copy(update={"artifacts": new_artifacts})
                return projection.model_copy(update={"run": new_run})

            # ── Settings ──────────────────────────────────────────────────

            # probe_completed / installation_* fold cases removed in M4:
            # installation concept and CLI binary probe deleted.
            # profile_created/modified/removed/default_profile_changed removed in M5:
            # profile types deleted; replaced by connections/presets fold cases below.

            case "connections_listed":
                # Replace-all: {connections: [{id, connection_type, base_url, region}, ...]}.
                raw_conns = payload.get("connections", [])
                new_conns = [
                    ConnectionWire(
                        id=c.get("id", ""),
                        connection_type=c.get("connection_type", ""),
                        base_url=c.get("base_url"),
                        region=c.get("region"),
                    )
                    for c in raw_conns
                ]
                new_settings = projection.settings.model_copy(update={"connections": new_conns})
                return projection.model_copy(update={"settings": new_settings})

            case "configured_models_listed":
                # Replace-all: {configured_models: [{id, connection_id, model_id,
                # resolved_from, context_window, embedding_dim}, ...]}.
                raw_cms = payload.get("configured_models", [])
                new_cms = [
                    ConfiguredModelWire(
                        id=m.get("id", ""),
                        connection_id=m.get("connection_id", ""),
                        model_id=m.get("model_id", ""),
                        resolved_from=m.get("resolved_from"),
                        context_window=m.get("context_window"),
                        embedding_dim=m.get("embedding_dim"),
                    )
                    for m in raw_cms
                ]
                new_settings = projection.settings.model_copy(update={"configured_models": new_cms})
                return projection.model_copy(update={"settings": new_settings})

            case "presets_listed":
                # Replace-all: {presets: {name: {slots: {slot_name: {configured_model_id, thinking}}}}}.
                raw_presets = payload.get("presets", {})
                new_presets: dict[str, PresetWire] = {}
                for preset_name, preset_raw in raw_presets.items():
                    if not isinstance(preset_raw, dict):
                        continue
                    slots_raw = preset_raw.get("slots", {})
                    slots: dict[str, SlotAssignmentWire] = {}
                    for slot_name, slot_raw in (slots_raw.items() if isinstance(slots_raw, dict) else []):
                        if isinstance(slot_raw, dict):
                            slots[slot_name] = SlotAssignmentWire(
                                configured_model_id=slot_raw.get("configured_model_id", ""),
                                thinking=slot_raw.get("thinking", "disabled"),
                            )
                    new_presets[preset_name] = PresetWire(slots=slots)
                new_settings = projection.settings.model_copy(update={"presets": new_presets})
                return projection.model_copy(update={"settings": new_settings})

            case "active_changed":
                # Payload {active: str}: update the active preset pointer.
                new_settings = projection.settings.model_copy(update={
                    "active": payload.get("active", "$last"),
                })
                return projection.model_copy(update={"settings": new_settings})

            case "memory_bindings_listed":
                # Payload {memory_bindings: dict | None}: stored opaque for now;
                # M6 may add a proper wire subtype when the mutation surface lands.
                new_settings = projection.settings.model_copy(update={
                    "memory_bindings": payload.get("memory_bindings"),
                })
                return projection.model_copy(update={"settings": new_settings})

            case "default_scout_concurrency_changed":
                new_settings = projection.settings.model_copy(update={
                    "default_scout_concurrency": payload.get("value", 8),
                })
                return projection.model_copy(update={"settings": new_settings})

            case "workflows_listed":
                # Build the WorkflowInfo list from the payload. The payload uses
                # snake_case keys (id, description, phases, initial_phase) so that
                # WorkflowInfo(**entry) constructs cleanly without alias resolution.
                raw_workflows = payload.get("workflows", [])
                new_workflows: list[WorkflowInfo] = []
                for entry in raw_workflows:
                    try:
                        new_workflows.append(WorkflowInfo(**entry))
                    except Exception:
                        log.warning("fold workflows_listed: skipping malformed entry %r", entry)
                new_settings = projection.settings.model_copy(update={"workflows": new_workflows})
                return projection.model_copy(update={"settings": new_settings})

            case "provider_status_listed":
                # M5: payload reshaped from {providers: [{provider, available, ...}]} to
                # {connections: [{connection_id, connection_type, available}]}.
                raw_conns = payload.get("connections", [])
                new_ps = [
                    ConnectionStatusWire(
                        connection_id=c.get("connection_id", ""),
                        connection_type=c.get("connection_type", ""),
                        available=c.get("available", False),
                    )
                    for c in raw_conns
                ]
                new_settings = projection.settings.model_copy(update={"provider_status": new_ps})
                return projection.model_copy(update={"settings": new_settings})

            case "model_registry_listed":
                # Payload: {models: [{provider, model, display_name, context_window,
                # thinking_modes, tier_hint}, ...]}.
                # Populates the all-providers model catalog in the Settings projection.
                raw_models = payload.get("models", [])
                new_mr = [
                    ModelRegistryEntryWire(
                        provider=m.get("provider", ""),
                        model=m.get("model", ""),
                        display_name=m.get("display_name", ""),
                        context_window=m.get("context_window", 0),
                        thinking_modes=m.get("thinking_modes", []),
                        tier_hint=m.get("tier_hint"),
                    )
                    for m in raw_models
                ]
                new_settings = projection.settings.model_copy(update={"model_registry": new_mr})
                return projection.model_copy(update={"settings": new_settings})

            case "provider_models_listed":
                # Payload: {models: [{provider, model, display_name, context_window,
                #                     connection_id}, ...],
                #           families: [{provider, family, resolved, resolved_from,
                #                       connection_id}, ...]}.
                # Flat cross-provider list; replace-all semantics (same as model_registry_listed).
                # Populated by the eager startup task and refreshed on Test/save.
                # connection_id scopes each model/family to its originating connection
                # so same-type connections keep independent lists on the frontend.
                raw_pm = payload.get("models", [])
                new_pm = [
                    ProviderModelWire(
                        provider=m.get("provider", ""),
                        model=m.get("model", ""),
                        display_name=m.get("display_name", ""),
                        context_window=m.get("context_window", 0),
                        connection_id=m.get("connection_id", ""),
                    )
                    for m in raw_pm
                ]
                # Families are a pass-through: the fold stays a dumb dict->wire mapping;
                # family/version recognition logic lives in the app layer (app.py).
                raw_pf = payload.get("families", [])
                new_pf = [
                    ProviderFamilyWire(
                        provider=f.get("provider", ""),
                        family=f.get("family", ""),
                        resolved=f.get("resolved", ""),
                        resolved_from=f.get("resolved_from", ""),
                        connection_id=f.get("connection_id", ""),
                    )
                    for f in raw_pf
                ]
                new_settings = projection.settings.model_copy(
                    update={"provider_models": new_pm, "provider_families": new_pf}
                )
                return projection.model_copy(update={"settings": new_settings})

            case "model_capabilities_listed":
                # Replace-all: {capabilities: [{configured_model_id, thinking_supported,
                # thinking_modes, thinking_shape, supports_web_search, supports_tools,
                # context_window, context_window_variants, supports_prompt_caching,
                # tier_hint, recognized}, ...]}.
                # Recomputed on startup and on any connection/configured-model mutation.
                raw_caps = payload.get("capabilities", [])
                new_caps = [
                    ResolvedCapabilitiesWire(
                        configured_model_id=c.get("configured_model_id", ""),
                        thinking_supported=c.get("thinking_supported", False),
                        thinking_modes=c.get("thinking_modes", []),
                        thinking_shape=c.get("thinking_shape", "none"),
                        supports_web_search=c.get("supports_web_search", False),
                        supports_tools=c.get("supports_tools", True),
                        context_window=c.get("context_window", 0),
                        context_window_variants=c.get("context_window_variants", []),
                        supports_prompt_caching=c.get("supports_prompt_caching", False),
                        tier_hint=c.get("tier_hint"),
                        recognized=c.get("recognized", True),
                    )
                    for c in raw_caps
                ]
                new_settings = projection.settings.model_copy(update={"model_capabilities": new_caps})
                return projection.model_copy(update={"settings": new_settings})

            case "yield_started":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                raw_suggestions = payload.get("suggestions", [])
                suggestions = [
                    Suggestion(
                        id=s.get("id", ""),
                        label=s.get("label", ""),
                        command=s.get("command", ""),
                    )
                    for s in raw_suggestions
                ]
                # Append YieldEntry to the agent's conversation stream
                new_conv = _flush_conversation(agent.conversation)
                new_conv = new_conv.model_copy(update={
                    "entries": [*new_conv.entries, YieldEntry(suggestions=suggestions)],
                })
                # Set run-level active_yield so the UI can pin pills above the input
                new_run = _update_agent_conversation(projection.run, agent_id, new_conv)
                new_run = new_run.model_copy(update={
                    "active_yield": ActiveYield(suggestions=suggestions),
                })
                return projection.model_copy(update={"run": new_run})

            case "yield_cleared":
                if projection.run is None:
                    return projection
                new_run = projection.run.model_copy(update={"active_yield": None})
                return projection.model_copy(update={"run": new_run})

            # ── Memory curation ────────────────────────────────────────────

            case "memory_curation_started":
                if projection.run is None:
                    return projection
                batch = ActiveCurationBatch.model_validate(payload["batch"])
                new_run = projection.run.model_copy(update={
                    "active_curation_batch": batch,
                })
                return projection.model_copy(update={"run": new_run})

            case "memory_curation_cleared":
                if projection.run is None:
                    return projection
                new_run = projection.run.model_copy(update={
                    "active_curation_batch": None,
                })
                return projection.model_copy(update={"run": new_run})

            # ── Memory mutations ───────────────────────────────────────────

            case "memory_entry_created" | "memory_entry_updated":
                # No run guard: memory is project-scoped.
                summary = MemoryEntrySummary.model_validate(payload)
                new_entries = dict(projection.memory.entries)
                new_entries[summary.seq] = summary
                new_memory = projection.memory.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={"memory": new_memory})

            case "memory_entry_deleted":
                seq = payload.get("seq", "")
                new_entries = dict(projection.memory.entries)
                new_entries.pop(seq, None)
                new_memory = projection.memory.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={"memory": new_memory})

            case "memory_summary_updated":
                new_memory = projection.memory.model_copy(update={
                    "summary": payload.get("summary", ""),
                })
                return projection.model_copy(update={"memory": new_memory})

            # ── Reflect ───────────────────────────────────────────────────

            case "reflect_started":
                new_reflect = ReflectRun(
                    session_id=payload["session_id"],
                    question=payload.get("question", ""),
                    status="in_progress",
                    started_at_ms=payload.get("started_at_ms", 0),
                    max_iterations=payload.get("max_iterations", 10),
                    model=payload.get("model", ""),
                )
                return projection.model_copy(update={"reflect": new_reflect})

            case "reflect_trace":
                r = projection.reflect
                if r is None or r.session_id != payload.get("session_id"):
                    return projection
                trace = ReflectTrace.model_validate(payload.get("trace", {}))
                new_traces = list(r.traces) + [trace]
                new_reflect = r.model_copy(update={
                    "traces": new_traces,
                    "iteration": trace.iteration,
                })
                return projection.model_copy(update={"reflect": new_reflect})

            case "reflect_done":
                r = projection.reflect
                if r is None or r.session_id != payload.get("session_id"):
                    return projection
                citations = [
                    ReflectCitation.model_validate(c)
                    for c in payload.get("citations", [])
                ]
                new_reflect = r.model_copy(update={
                    "status": "done",
                    "answer": payload.get("answer", ""),
                    "citations": citations,
                    "completed_at_ms": payload.get("completed_at_ms"),
                    "iteration": payload.get("iterations", r.iteration),
                })
                return projection.model_copy(update={"reflect": new_reflect})

            case "reflect_cancelled":
                r = projection.reflect
                if r is None or r.session_id != payload.get("session_id"):
                    return projection
                new_reflect = r.model_copy(update={
                    "status": "cancelled",
                    "completed_at_ms": payload.get("completed_at_ms"),
                })
                return projection.model_copy(update={"reflect": new_reflect})

            case "reflect_failed":
                r = projection.reflect
                if r is None or r.session_id != payload.get("session_id"):
                    return projection
                new_reflect = r.model_copy(update={
                    "status": "failed",
                    "error": payload.get("error", ""),
                    "completed_at_ms": payload.get("completed_at_ms"),
                })
                return projection.model_copy(update={"reflect": new_reflect})

            case "reflect_cleared":
                return projection.model_copy(update={"reflect": None})

            case "embedding_models_listed":
                # Replace-all: {models: [{model_id, context_window, dimensions,
                # default_dimension}, ...]}.  Pushed once at startup; static for
                # the process lifetime.  The frontend uses this to populate the
                # dimension selector and the context window display.
                raw_models = payload.get("models", [])
                new_ems = [
                    EmbeddingModelWire(
                        model_id=m.get("model_id", ""),
                        context_window=m.get("context_window", 0),
                        dimensions=m.get("dimensions", []),
                        default_dimension=m.get("default_dimension", 0),
                    )
                    for m in raw_models
                ]
                new_settings = projection.settings.model_copy(update={"embedding_models": new_ems})
                return projection.model_copy(update={"settings": new_settings})

            case _:
                log.warning("fold: unknown event_type=%r", event_type)
                return projection

    except Exception:
        log.exception(
            "fold: exception handling event_type=%r version=%d",
            event_type, event.version,
        )
        return projection


# ---------------------------------------------------------------------------
# ProjectionStore
# ---------------------------------------------------------------------------

class ProjectionStore:
    """In-memory versioned event log + materialized projection + JSON Patch broadcaster.

    push_event flow:
      1. Increment version and append VersionedEvent to audit log.
      2. Fold event into projection.
      3. Compute RFC 6902 JSON Patch between prev_state and new_state (both camelCase).
      4. If patch is non-empty, broadcast {type, version, patch} dict to all subscriber queues.

    Subscriber queues receive plain dicts (not VersionedEvent objects) — the dict shape
    matches the SSE JSON payload so sse_stream() can forward it directly.
    """

    def __init__(self) -> None:
        self.events: list[VersionedEvent] = []
        self.projection: Projection = Projection()
        self.version: int = 0
        self.subscribers: set[asyncio.Queue] = set()
        self.prev_state: dict = self.projection.to_wire()

    def push_event(
        self,
        event_type: str,
        payload: dict,
        agent_id: str | None = None,
    ) -> VersionedEvent:
        """Append event, fold into projection, compute patch, broadcast to subscribers."""
        log.debug(
            "push_event: type=%s agent_id=%s",
            event_type, (agent_id or "")[:8],
        )
        self.version += 1
        event = VersionedEvent(
            version=self.version,
            event_type=event_type,
            timestamp=_utcnow(),
            agent_id=agent_id,
            payload=payload,
        )
        self.events.append(event)

        old_state = self.prev_state
        try:
            self.projection = fold(self.projection, event)
        except Exception:
            log.exception(
                "ProjectionStore: fold raised for event version=%d type=%r",
                self.version, event_type,
            )

        new_state = self.projection.to_wire()
        self.prev_state = new_state

        patch = jsonpatch.make_patch(old_state, new_state)
        if not patch:
            # No state change — koan MCP tools and other filtered events land here.
            # Subscribers stay at the same version; no broadcast needed.
            return event

        msg: dict = {
            "type": "patch",
            "version": self.version,
            "patch": patch.patch,  # list of RFC 6902 operation dicts
        }
        # Snapshot subscribers before iterating — defensive against concurrent
        # add/remove (asyncio, not threading, but still good practice).
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                log.warning(
                    "ProjectionStore: subscriber queue full, dropping event version=%d",
                    self.version,
                )
            except Exception:
                pass

        return event

    def get_snapshot(self) -> dict:
        """Return {version, state} for SSE snapshot. State is camelCase via to_wire()."""
        return {
            "version": self.version,
            "state": self.projection.to_wire(),
        }

    def subscribe(self) -> asyncio.Queue:
        """Create and register a subscriber queue. Returns the queue."""
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        self.subscribers.discard(queue)
