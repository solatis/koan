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
from typing import Annotated, Callable, Literal

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
    "tool_write",
    "tool_edit",
    "tool_bash",
    "tool_request",
    "tool_input_delta",
    "tool_result",
    "tool_failed",
    "tool_result_captured",
    "tool_aggregate",
    # Domain events correlated by agent_id (not call_id): target the in-flight
    # tool entry for the agent. reflect_inline_trace carries thinking deltas,
    # text streaming, search lifecycle, and metadata; tool_attachments
    # carries koan-side upload manifests from MCP handlers.
    "reflect_inline_trace",
    "tool_attachments",
    "thinking",
    "stream_delta",
    "stream_cleared",
    # Telemetry
    "token_telemetry",
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
    # M4: artifact execution lifecycle (execute_entry / execute_completion).
    # M3: execute_entry is a no-op started-marker (frozen field removed).
    # M5: execute_completion is also a no-op fold; ArtifactInfo carries no
    # lifecycle fields. Both events are still emitted and logged as the audit
    # record; their fold cases are kept so they stay recognized.
    "execute_entry",
    "execute_completion",
    # Settings
    # probe_completed / installation_* removed in M4: installation concept and
    # CLI binary probe deleted; provider credentials are the availability model.
    # profile_created/modified/removed/default_profile_changed removed in M5:
    # profile types deleted; replaced by connections/presets config events.
    "default_scout_concurrency_changed",
    "retry_settings_changed",
    "workflows_listed",
    # M2: model catalog initial event (kept; provider_status_listed reshaped M5)
    "model_registry_listed",
    # Dynamic per-provider model overlay (live per-connection)
    "provider_models_listed",
    # M5: new config entity events (replace profile events)
    "connections_listed",
    "configured_models_listed",
    "presets_listed",
    "active_changed",
    "memory_bindings_listed",
    # M5: provider_status_listed retained but reshaped to per-connection
    "provider_status_listed",
    # memory_curation_started / memory_curation_cleared removed in M7:
    # koan_memory_propose gate retired; no blocking curation events.
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
    # Stable per-conversation id assigned in the fold (_assign_entry_ids); '' until assigned;
    # aggregate children leave this unset and key by call_id.
    entry_id: str = ""
    # Phase this entry belongs to, stamped by _stamp_entry_phases in the fold.
    phase_id: str = ""

class TextEntry(KoanBaseModel):
    type: Literal["text"] = "text"
    text: str                              # full accumulated output text
    entry_id: str = ""
    phase_id: str = ""

class StepEntry(KoanBaseModel):
    type: Literal["step"] = "step"
    step: int
    step_name: str
    total_steps: int | None = None
    entry_id: str = ""
    phase_id: str = ""

class UserMessageEntry(KoanBaseModel):
    type: Literal["user_message"] = "user_message"
    content: str
    timestamp_ms: int
    entry_id: str = ""
    phase_id: str = ""

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
    """Shared fields for all tool entries and aggregate children.

    entry_id is the stable per-conversation id for top-level entries, assigned
    by _assign_entry_ids in the fold.  phase_id is the phase the entry belongs
    to, stamped by _stamp_entry_phases.  Aggregate children inherit both
    fields but leave them '' -- they are keyed by call_id instead.
    """
    call_id: str                           # unique per tool invocation
    in_flight: bool                        # True until tool_result
    # Stable per-conversation id assigned in the fold (_assign_entry_ids); '' until assigned;
    # aggregate children leave this unset and key by call_id.
    entry_id: str = ""
    # Phase this entry belongs to, stamped by _stamp_entry_phases; aggregate
    # children inherit it but leave it '' -- they are keyed by call_id.
    phase_id: str = ""
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
    # Set by the tool_failed fold for aggregate children: the call's arguments
    # failed validation and the tool body never ran. Top-level entries are
    # instead replaced wholesale by ToolFailedEntry; the flag exists on the
    # base so children can be marked in place without breaking the
    # len(children) >= 2 aggregate invariant.
    failed: bool = False

class ToolWriteEntry(BaseToolEntry):
    type: Literal["tool_write"] = "tool_write"
    file: str                              # path that was created or overwritten

class ToolEditEntry(BaseToolEntry):
    type: Literal["tool_edit"] = "tool_edit"
    file: str                              # path that was edited in-place

class ToolBashEntry(BaseToolEntry):
    """A bash tool call — shell command execution.

    Valid as a top-level ConversationEntry (single bash) and as a
    ToolAggregateEntry child (bash in a run of 2+ exploration ops). The
    aggregate-child fields (started_at_ms, completed_at_ms, exit_code,
    output_lines) are populated when bash is part of an aggregate run.
    """
    type: Literal["tool_bash"] = "tool_bash"
    command: str                           # shell command executed
    started_at_ms: int = 0                 # creation timestamp (aggregate child)
    completed_at_ms: int | None = None     # set by tool_completed/tool_result
    exit_code: int | None = None           # attached by tool_result_captured
    output_lines: int | None = None        # attached by tool_result_captured

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

class ToolFailedEntry(BaseToolEntry):
    """Terminal entry for a tool call whose arguments failed validation.

    Replaces the in-flight entry (retaining entry_id/phase_id for stable
    list keys). raw_input is the JSON-dumped last-known tool_input -- an
    opaque string; the malformed structured payload never survives in the
    projection.
    """
    type: Literal["tool_failed"] = "tool_failed"
    tool_name: str
    error: str = ""
    raw_input: str = ""

# ---------------------------------------------------------------------------
# Exploration entry types — the six exploration tools (read, grep, glob, bash,
# web_search, web_fetch) are valid both as top-level ConversationEntry values
# (single call -> ToolCallRow family variant) and as children of
# ToolAggregateEntry (2+ calls -> ToolAggregateCard). The ExplorationChild union
# is used for aggregate children; the same types also appear in the
# ConversationEntry union for top-level rendering.
# ---------------------------------------------------------------------------

class ToolReadEntry(BaseToolEntry):
    """A read tool call — file content retrieval.

    Valid as a top-level ConversationEntry (single read) and as a
    ToolAggregateEntry child (read in a run of 2+ exploration ops). The
    range property derives the display string (e.g. "1-80") from offset/limit;
    whole-file reads (limit is None) carry no range.
    """
    type: Literal["tool_read"] = "tool_read"
    file: str                              # path that was read
    started_at_ms: int = 0                 # creation timestamp
    completed_at_ms: int | None = None     # set by tool_completed/tool_result
    lines_read: int | None = None          # attached by tool_result_captured
    bytes_read: int | None = None          # attached by tool_result_captured
    offset: int = 0                        # 0-based line offset from tool args
    limit: int | None = None              # max lines; None = whole-file read

    @property
    def range(self) -> str | None:
        """Derive display range string, e.g. "1-80". None for whole-file reads."""
        if self.limit is not None and self.limit > 0:
            return f"{self.offset + 1}–{self.offset + self.limit}"
        return None

class ToolGrepEntry(BaseToolEntry):
    """A grep tool call — regex search across files.

    Valid as a top-level ConversationEntry and as a ToolAggregateEntry child.
    """
    type: Literal["tool_grep"] = "tool_grep"
    pattern: str                           # search pattern
    started_at_ms: int = 0
    completed_at_ms: int | None = None
    matches: int | None = None             # attached by tool_result_captured
    files_matched: int | None = None       # attached by tool_result_captured
    matched_lines: int | None = None       # attached by tool_result_captured

class ToolGlobEntry(BaseToolEntry):
    """A glob tool call — file pattern search.

    Valid as a top-level ConversationEntry and as a ToolAggregateEntry child.
    """
    type: Literal["tool_glob"] = "tool_glob"
    pattern: str                           # glob pattern searched
    started_at_ms: int = 0
    completed_at_ms: int | None = None
    matches: int | None = None             # attached by tool_result_captured
    files_matched: int | None = None       # attached by tool_result_captured

class ToolWebSearchEntry(BaseToolEntry):
    """A web_search tool call — DuckDuckGo search.

    Valid as a top-level ConversationEntry and as a ToolAggregateEntry child.
    """
    type: Literal["tool_web_search"] = "tool_web_search"
    query: str = ""
    started_at_ms: int = 0
    completed_at_ms: int | None = None
    result_count: int | None = None

class ToolWebFetchEntry(BaseToolEntry):
    """A web_fetch tool call — URL content retrieval.

    Valid as a top-level ConversationEntry and as a ToolAggregateEntry child.
    """
    type: Literal["tool_web_fetch"] = "tool_web_fetch"
    url: str = ""
    started_at_ms: int = 0
    completed_at_ms: int | None = None
    content_size_bytes: int | None = None

ExplorationChild = Annotated[
    ToolReadEntry | ToolGrepEntry | ToolGlobEntry | ToolBashEntry
    | ToolWebSearchEntry | ToolWebFetchEntry,
    Field(discriminator="type"),
]

class ToolAggregateEntry(KoanBaseModel):
    """A run of 2+ consecutive exploration tool calls.

    Invariant: len(children) >= 2. A single exploration tool is a top-level
    entry (ToolReadEntry, ToolGrepEntry, etc.), never a single-child
    aggregate. The aggregate is created when a second consecutive exploration
    tool arrives and the previous entry is a top-level exploration entry;
    it grows as further consecutive exploration tools arrive. Active/elapsed
    state is derived from children at render time, not stored here.
    """
    type: Literal["tool_aggregate"] = "tool_aggregate"
    children: list[ExplorationChild] = []
    started_at_ms: int = 0                 # timestamp of the first child's creation
    entry_id: str = ""
    phase_id: str = ""

class DebugStepGuidanceEntry(KoanBaseModel):
    """Step guidance prompt shown in --debug mode."""
    type: Literal["debug_step_guidance"] = "debug_step_guidance"
    content: str                           # full formatted step guidance text
    entry_id: str = ""
    phase_id: str = ""

class PhaseBoundaryEntry(KoanBaseModel):
    type: Literal["phase_boundary"] = "phase_boundary"
    phase: str
    message: str
    entry_id: str = ""
    phase_id: str = ""

class Suggestion(KoanBaseModel):
    """A structured option presented to the user at a yield point."""
    id: str                                # machine key (e.g. "plan", "done")
    label: str                             # display text (e.g. "Write implementation plan")
    command: str = ""                      # pre-fills the chat input when the pill is clicked
    phase: str = ""                         # marks a mechanical phase-transition suggestion; empty for free-text

class YieldEntry(KoanBaseModel):
    """Conversation entry emitted when the orchestrator yields to the user."""
    type: Literal["yield"] = "yield"
    suggestions: list[Suggestion] = []     # clickable options shown in the UI
    entry_id: str = ""
    phase_id: str = ""

class ActiveYield(KoanBaseModel):
    """Run-level state tracking the current yield's suggestions.

    Non-None while the orchestrator is blocked in koan_yield. Cleared when
    a phase starts, the workflow completes, or a new yield supersedes it.
    """
    suggestions: list[Suggestion] = []

ConversationEntry = Annotated[
    ThinkingEntry | TextEntry | StepEntry | UserMessageEntry |
    ToolWriteEntry | ToolEditEntry | ToolBashEntry | ToolGenericEntry |
    ToolKoanEntry | ToolFailedEntry | ToolAggregateEntry |
    ToolReadEntry | ToolGrepEntry | ToolGlobEntry |
    ToolWebSearchEntry | ToolWebFetchEntry |
    DebugStepGuidanceEntry | PhaseBoundaryEntry | YieldEntry,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Conversation — per agent
# ---------------------------------------------------------------------------

class Telemetry(KoanBaseModel):
    """Per-agent token telemetry, updated by the token_telemetry fold case.

    context_size is the latest measured context size in tokens (from
    Model.count_tokens() on the full message history). Delta fields are
    per-turn deltas computed by the fold: new cumulative minus old cumulative
    from the parent Conversation's cumulative token fields.

    Cumulative totals live on Conversation (input_tokens etc.) and are NOT
    duplicated here -- the fold updates both in a single model_copy so they
    cannot diverge.
    """
    context_size: int = 0
    delta_input_tokens: int = 0
    delta_output_tokens: int = 0
    delta_cache_read_tokens: int = 0
    delta_cache_write_tokens: int = 0


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
    # M5: derived field -- computed in the fold, not recorded as event facts.
    # total_cost_usd: genai-prices bundled snapshot via price_for_usage (cumulative tokens).
    total_cost_usd: float = 0.0
    # Per-agent token telemetry (context size + per-turn deltas). Cumulative
    # totals stay on the Conversation fields above; Telemetry holds only the
    # latest context_size and the deltas from the most recent token_telemetry
    # fold. Grouped under a namespace to stay extensible for future metrics.
    telemetry: Telemetry = Field(default_factory=Telemetry)
    # Monotonic counter for entry_id assignment; in-memory only (exclude=True keeps it off
    # the wire), rebuilt deterministically on restart by re-folding the event log.
    next_entry_id: int = Field(default=0, exclude=True)


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
    # provider carried from agent_spawned so the fold can derive cost without live config lookups.
    provider: str | None = None

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
    embedding_dim is the selected Voyage output dimension; None means use the
    model's catalog default.
    """

    id: str
    connection_id: str
    model_id: str
    resolved_from: str | None = None
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
    supports_prompt_caching: bool = False
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

    Payload shape: {models: [{provider, model, display_name, thinking_modes}, ...]}.  Fold sets Settings.model_registry from the models list.
    """

    provider: str
    model: str
    display_name: str
    thinking_modes: list[str] = []


class EmbeddingModelWire(KoanBaseModel):
    """Wire representation of one recognized Voyage embedding model (camelCase via to_camel).

    Payload shape: {models: [{model_id, dimensions, default_dimension}, ...]}.
    Fold sets Settings.embedding_models from the models list on the
    embedding_models_listed event; replace-all semantics.
    """

    model_id: str
    # Selectable output dimensions (ascending).
    dimensions: list[int] = []
    default_dimension: int = 0


class ProviderModelWire(KoanBaseModel):
    """Wire representation of ProviderModel pushed by the provider_models_listed event.

    Payload shape: {models: [{provider, model, display_name, connection_id}, ...]}.
    The alias_generator=to_camel emits displayName and connectionId on the wire.
    Fold sets Settings.provider_models from the flat cross-provider models list;
    replace-all semantics (same as model_registry_listed). The frontend overlay
    join is per-connection (by connectionId), not per provider type.
    """

    provider: str
    model: str
    display_name: str
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
    max_retry_attempts: int = 10
    max_retry_wait_seconds: float = 60.0
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

# Proposal, ActiveCurationBatch, and _coerce_str removed in M7: the
# koan_memory_propose approval gate is retired; curation writes memory directly.

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
    """A single trace event for the standalone reflect page.

    The web app's on_trace callback filters out internal lifecycle events
    (search_start, thinking_delta) and only forwards final-form events
    (search, text) to this model.
    """
    iteration: int
    kind: Literal["search", "thinking", "text"]
    # search-only fields
    query: str = ""
    type_filter: str = ""
    result_count: int | None = None
    # thinking / text delta
    delta: str = ""
    # lifecycle status for search (running/done) and thinking (running/done)
    status: Literal["running", "done"] | None = None

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
    """Per-artifact metadata.

    path/size/modified_at are set by artifact_created/artifact_modified events.
    produced_phase_id is stamped at artifact_created from run.phase and
    preserved across artifact_modified -- an artifact's producing phase never
    changes. camelCase on the wire: producedPhaseId (via KoanBaseModel alias).
    M3: frozen field removed (execute_entry is a no-op started-marker).
    M5: executed/exec_outcome removed -- execution history lives in the event
    log and inline in the plan; no lifecycle state is folded here.
    """

    path: str
    size: int = 0
    modified_at: int = 0                   # milliseconds since epoch
    # Phase active when the artifact was first created; preserved across
    # artifact_modified so the timeline handoff badges can group by producer.
    produced_phase_id: str | None = None

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
    id: str                                # phase key (e.g. "plan")
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
    # active_curation_batch removed in M7: koan_memory_propose gate retired.

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
    child: ExplorationChild,
    ts_ms: int,
) -> Conversation:
    """Append an exploration-tool child to the trailing aggregate.

    Only appends when the last entry is already a ToolAggregateEntry; the
    invariant len(children) >= 2 is maintained because this function is never
    called to create a new aggregate (single exploration tools are top-level
    entries). When there is no trailing aggregate, this is a no-op — the
    caller (tool_request fold case) handles top-level entry creation and
    aggregate promotion separately.

    Always flushes pending text/thinking first — exploration tools appear in the
    same stream as prose, so any in-progress prose must close out before a tool
    entry lands.
    """
    flushed = _flush_conversation(conv)
    entries = list(flushed.entries)
    if entries and isinstance(entries[-1], ToolAggregateEntry):
        aggregate = entries[-1]
        assert len(aggregate.children) >= 1, "aggregate must have >= 1 child before append"
        grown = aggregate.model_copy(update={
            "children": [*aggregate.children, child],
        })
        entries[-1] = grown
        return flushed.model_copy(update={"entries": entries})
    # No trailing aggregate — no-op; the tool_request case handles promotion.
    return flushed


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




def _stamp_entry_phases(conv: Conversation, phase: str) -> Conversation:
    """Stamp every top-level entry lacking a phase_id with the current phase.

    Idempotent and append-only: entries that already have a non-empty
    phase_id are preserved unchanged.  Returns the same conversation object
    when no stamping is needed (no JSON Patch ops), matching the contract
    of _assign_entry_ids.  Aggregate children are intentionally left
    untouched -- they are keyed by call_id and do not appear as top-level
    entries.
    """
    if not phase:
        return conv
    new_entries = []
    changed = False
    for e in conv.entries:
        if e.phase_id == "":
            new_entries.append(e.model_copy(update={"phase_id": phase}))
            changed = True
        else:
            new_entries.append(e)
    if not changed:
        return conv
    return conv.model_copy(update={"entries": new_entries})


def _assign_entry_ids(conv: Conversation) -> Conversation:
    """Assign a stable entry_id to every top-level entry that does not yet have one.

    Advances conv.next_entry_id for each assignment.  Existing ids are preserved
    so re-folding a no-op event never changes ids already assigned (idempotent,
    append-only stability).  Aggregate children are intentionally left untouched --
    they remain keyed by call_id.  Returns the same conversation object unchanged
    when no assignment is needed, so unrelated re-folds produce no JSON Patch ops.
    """
    counter = conv.next_entry_id
    new_entries = []
    changed = False
    for e in conv.entries:
        if e.entry_id == "":
            new_entries.append(e.model_copy(update={"entry_id": f"e{counter}"}))
            counter += 1
            changed = True
        else:
            new_entries.append(e)
    if not changed:
        return conv
    return conv.model_copy(update={"entries": new_entries, "next_entry_id": counter})


def _update_agent_conversation(run: Run, agent_id: str, new_conv: Conversation, **extra) -> Run:
    """Return a new Run with the agent's conversation replaced and optional extra updates.

    Stamps phase ids via _stamp_entry_phases, then assigns stable entry ids
    via _assign_entry_ids before writing back, so every top-level entry
    carries a monotonic per-conversation id and its phase on the wire.
    """
    agent = run.agents.get(agent_id)
    if agent is None:
        return run
    new_conv = _stamp_entry_phases(new_conv, run.phase)
    new_conv = _assign_entry_ids(new_conv)
    new_agent = agent.model_copy(update={"conversation": new_conv, **extra})
    new_agents = dict(run.agents)
    new_agents[agent_id] = new_agent
    return run.model_copy(update={"agents": new_agents})


# RENDERABLE_KOAN_TOOLS removed in M1: every koan MCP tool now follows the
# same lifecycle (tool_request -> tool_input_delta -> tool_result) and
# produces ToolKoanEntry. Selection happens in the fold's tool_request case
# by membership in KOAN_MCP_TOOLS (imported from koan.agents.events).


def _derive_usage(conv: "Conversation", agent: "Agent", usage: dict) -> "Conversation":
    """Accumulate cache token facts and derive total_cost_usd.

    Called from both agent_exited and agent_step_advanced usage blocks so the
    derivation logic is in one place. cache_read/write_tokens are folded facts
    (cumulative sums from the usage dict). total_cost_usd is a derived value:
    never recorded as an event fact; belongs entirely to the fold.

    Fold-safety contract:
    - price_for_usage is imported lazily (bundled snapshot only; no network).
    - try/except around price_for_usage: keeps the prior cost on any failure
      (e.g. unresolvable model, missing provider) rather than raising.
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

    return conv


# Tuple of all six exploration entry types, for isinstance checks in the fold.
EXPLORATION_ENTRY_TYPES: tuple[type, ...] = (
    ToolReadEntry, ToolGrepEntry, ToolGlobEntry, ToolBashEntry,
    ToolWebSearchEntry, ToolWebFetchEntry,
)


def _make_exploration_entry(
    tool_name: str, call_id: str, ts_ms: int, tool_args: dict | None = None,
) -> ExplorationChild:
    """Create an exploration entry of the appropriate type from a tool_request.

    Command fields are populated from tool_args when available (providers that
    send complete args at tool_start, e.g. Anthropic). The tool_input_delta
    fold case fills them in for all providers at tool_stop time.
    """
    ti = tool_args or {}
    if tool_name == "read":
        e = ToolReadEntry(
            call_id=call_id, in_flight=True, file="",
            started_at_ms=ts_ms,
        )
        if ti:
            e = e.model_copy(update=_read_args_update(ti))
        return e
    elif tool_name == "grep":
        e = ToolGrepEntry(
            call_id=call_id, in_flight=True, pattern="",
            started_at_ms=ts_ms,
        )
        if ti:
            e = e.model_copy(update={"pattern": ti.get("pattern", "") or ti.get("query", "")})
        return e
    elif tool_name == "glob":
        e = ToolGlobEntry(
            call_id=call_id, in_flight=True, pattern="",
            started_at_ms=ts_ms,
        )
        if ti:
            e = e.model_copy(update={"pattern": ti.get("pattern", "")})
        return e
    elif tool_name == "bash":
        e = ToolBashEntry(
            call_id=call_id, in_flight=True, command="",
            started_at_ms=ts_ms,
        )
        if ti:
            e = e.model_copy(update={"command": ti.get("command", "")})
        return e
    elif tool_name == "web_search":
        e = ToolWebSearchEntry(
            call_id=call_id, in_flight=True, query="",
            started_at_ms=ts_ms,
        )
        if ti:
            e = e.model_copy(update={"query": ti.get("query", "")})
        return e
    elif tool_name == "web_fetch":
        e = ToolWebFetchEntry(
            call_id=call_id, in_flight=True, url="",
            started_at_ms=ts_ms,
        )
        if ti:
            e = e.model_copy(update={"url": ti.get("url", "")})
        return e
    # Should not reach here; caller filters by the exploration set.
    raise ValueError(f"not an exploration tool: {tool_name}")


def _as_str(v: object) -> object | None:
    return v if isinstance(v, str) else None


def _as_list(v: object) -> object | None:
    return v if isinstance(v, list) else None


def _as_item_list(
    v: object,
    str_fields: tuple[str, ...] = (),
    list_fields: tuple[str, ...] = (),
) -> list | None:
    """Accept only a list whose elements are all dicts.

    Per-item fields of the wrong shape are dropped (mid-stream partial values
    self-heal on the next delta). Returns None (drop the whole field) when the
    value is not a list of dicts.
    """
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        return None
    out = []
    for item in v:
        item = dict(item)
        for f in str_fields:
            if f in item and not isinstance(item[f], str):
                item.pop(f)
        for f in list_fields:
            if f in item and not isinstance(item[f], list):
                item.pop(f)
        out.append(item)
    return out


# Expected container shapes for koan tool input fields the frontend indexes
# into (.map/.length/item property access). Model-authored streaming input is
# untrusted; fields that do not conform are dropped from the stored aggregate
# so no card ever renders a non-conforming shape, even mid-call. The table is
# the koan-tool analogue of the typed scalar derivation the exploration tools
# get (file/command/pattern below).
_KOAN_INPUT_SHAPES: dict[str, dict[str, Callable[[object], object | None]]] = {
    "koan_reflect": {"question": _as_str},
    "koan_artifact_write": {"filename": _as_str, "content": _as_str},
    "koan_artifact_edit": {"filename": _as_str},
    "koan_ask_question": {"questions": lambda v: _as_item_list(
        v, str_fields=("question", "context"), list_fields=("options",))},
    "koan_yield": {"suggestions": lambda v: _as_item_list(
        v, str_fields=("label", "command"))},
    "koan_request_executor": {"artifacts": _as_list},
}


def _sanitize_koan_input(tool_name: str, ti: dict) -> dict:
    """Drop non-conforming fields from a koan tool's streaming input aggregate."""
    spec = _KOAN_INPUT_SHAPES.get(tool_name)
    if not spec or not ti:
        return ti
    out = dict(ti)
    for field, clean in spec.items():
        if field in out:
            cleaned = clean(out[field])
            if cleaned is None:
                out.pop(field)
            else:
                out[field] = cleaned
    return out


def _read_args_update(ti: dict) -> dict:
    """Derive ToolReadEntry update dict from tool_input args."""
    upd: dict = {"file": ti.get("file_path", "") or ti.get("path", "")}
    upd["offset"] = ti.get("offset", 0)
    if "limit" in ti:
        upd["limit"] = ti["limit"]
    return upd


def _apply_exploration_metrics(child: BaseToolEntry, metrics: dict) -> dict:
    """Derive a model_copy update dict from native metrics for an exploration entry.

    Handles all six families. Returns an empty dict when no metrics apply.
    Works for both aggregate children and top-level exploration entries.
    """
    update: dict = {}
    if isinstance(child, ToolReadEntry):
        if "lines_read" in metrics:
            update["lines_read"] = metrics["lines_read"]
        if "bytes_read" in metrics:
            update["bytes_read"] = metrics["bytes_read"]
    elif isinstance(child, ToolGrepEntry):
        if "matches" in metrics:
            update["matches"] = metrics["matches"]
        if "files_matched" in metrics:
            update["files_matched"] = metrics["files_matched"]
        if "matched_lines" in metrics:
            update["matched_lines"] = metrics["matched_lines"]
    elif isinstance(child, ToolGlobEntry):
        if "matches" in metrics:
            update["matches"] = metrics["matches"]
        if "files_matched" in metrics:
            update["files_matched"] = metrics["files_matched"]
    elif isinstance(child, ToolBashEntry):
        if "exit_code" in metrics:
            update["exit_code"] = metrics["exit_code"]
        if "output_lines" in metrics:
            update["output_lines"] = metrics["output_lines"]
    elif isinstance(child, ToolWebSearchEntry):
        if "result_count" in metrics:
            update["result_count"] = metrics["result_count"]
    elif isinstance(child, ToolWebFetchEntry):
        if "content_size_bytes" in metrics:
            update["content_size_bytes"] = metrics["content_size_bytes"]
    return update


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

                # Accumulate final usage into conversation and derive cost.
                # _derive_usage handles input/output/cache accumulation and
                # derives total_cost_usd in one call.
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
                        # Top-level exploration entries get completed_at_ms.
                        if isinstance(entry, EXPLORATION_ENTRY_TYPES):
                            update["completed_at_ms"] = ts_ms or None
                        if isinstance(entry, ToolKoanEntry):
                            raw_result = payload.get("result")
                            parsed = None
                            if raw_result and isinstance(raw_result, str):
                                try:
                                    parsed = json.loads(raw_result)
                                except (json.JSONDecodeError, TypeError):
                                    parsed = {"raw": raw_result}
                            elif isinstance(raw_result, dict):
                                parsed = raw_result
                            if parsed is not None:
                                existing = entry.result or {}
                                # Merge to preserve fields accumulated by domain events
                                # (reflect_inline_trace sets traces/model/maxIterations/
                                #  iteration; reflect_inline_trace with kind 'text' sets
                                #  answer). tool_completed adds citations and the final
                                #  iterations count.
                                update["result"] = {**existing, **parsed}
                                # If the last trace is a running thinking entry, close
                                # it. The reflect loop can terminate while the model is
                                # still in thinking state (no explicit thinking_end).
                                result = update["result"]
                                traces = result.get("traces", [])
                                if traces and isinstance(traces, list):
                                    last = traces[-1]
                                    if isinstance(last, dict) and last.get("kind") == "thinking" and last.get("status") == "running":
                                        result["traces"] = list(traces[:-1]) + [{**last, "status": "done"}]
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
                    if isinstance(entry, ToolAggregateEntry):
                        new_children = []
                        child_found = False
                        for child in entry.children:
                            if child.call_id != call_id:
                                new_children.append(child)
                                continue
                            update = _apply_exploration_metrics(child, metrics)
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
                    elif isinstance(entry, EXPLORATION_ENTRY_TYPES) and entry.call_id == call_id:
                        # Top-level exploration entry (single call).
                        update = _apply_exploration_metrics(entry, metrics)
                        if update:
                            new_entries.append(entry.model_copy(update=update))
                        else:
                            new_entries.append(entry)
                        found = True
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
                if tool_name in ("read", "grep", "glob", "bash", "web_search", "web_fetch"):
                    # Exploration tools: valid as top-level entries (single call) and
                    # as ToolAggregateEntry children (2+ consecutive calls). The
                    # invariant len(children) >= 2 is maintained: the first
                    # exploration tool in a run creates a top-level entry; a second
                    # consecutive one promotes the top-level entry to a 2-child
                    # aggregate; further ones append to the existing aggregate.
                    ts_ms = payload.get("ts_ms", 0)
                    tool_args = payload.get("args")  # complete args at start (Anthropic)
                    child = _make_exploration_entry(tool_name, call_id, ts_ms, tool_args)
                    flushed = _flush_conversation(agent.conversation)
                    entries = list(flushed.entries)
                    if entries and isinstance(entries[-1], ToolAggregateEntry):
                        # Append to existing aggregate (3rd+ consecutive tool).
                        agg = entries[-1]
                        assert len(agg.children) >= 1
                        grown = agg.model_copy(update={
                            "children": [*agg.children, child],
                        })
                        entries[-1] = grown
                    elif entries and isinstance(entries[-1], EXPLORATION_ENTRY_TYPES):
                        # Promote the previous top-level exploration entry to a
                        # 2-child aggregate (2nd consecutive tool). Clear the
                        # promoted entry's entry_id — children are keyed by
                        # call_id, not entry_id.
                        prev = entries[-1]
                        prev_child = prev.model_copy(update={"entry_id": ""}) if prev.entry_id else prev
                        entries[-1] = ToolAggregateEntry(
                            children=[prev_child, child],
                            started_at_ms=prev.started_at_ms if hasattr(prev, "started_at_ms") else ts_ms,
                        )
                    else:
                        # First exploration tool in a run: top-level entry.
                        entries.append(child)
                    new_conv = flushed.model_copy(update={"entries": entries})
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
                                if isinstance(child, ToolReadEntry):
                                    upd.update(_read_args_update(ti))
                                elif isinstance(child, ToolGrepEntry):
                                    upd["pattern"] = ti.get("pattern", "") or ti.get("query", "")
                                elif isinstance(child, ToolGlobEntry):
                                    upd["pattern"] = ti.get("pattern", "")
                                elif isinstance(child, ToolBashEntry):
                                    upd["command"] = ti.get("command", "")
                                elif isinstance(child, ToolWebSearchEntry):
                                    upd["query"] = ti.get("query", "")
                                elif isinstance(child, ToolWebFetchEntry):
                                    upd["url"] = ti.get("url", "")
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
                        elif isinstance(entry, ToolReadEntry):
                            upd.update(_read_args_update(ti))
                        elif isinstance(entry, ToolGrepEntry):
                            upd["pattern"] = ti.get("pattern", "") or ti.get("query", "")
                        elif isinstance(entry, ToolGlobEntry):
                            upd["pattern"] = ti.get("pattern", "")
                        elif isinstance(entry, ToolWebSearchEntry):
                            upd["query"] = ti.get("query", "")
                        elif isinstance(entry, ToolWebFetchEntry):
                            upd["url"] = ti.get("url", "")
                        elif isinstance(entry, ToolKoanEntry):
                            # Sanitize BOTH stored copies: cards bind toolInput
                            # (ContentStream passes entry.toolInput); args is
                            # the canonical "latest known input" for koan tools.
                            ti = _sanitize_koan_input(entry.tool_name, ti)
                            upd["tool_input"] = ti
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
                        upd: dict = {"in_flight": False}
                        # Exploration entries (top-level or bash) get completed_at_ms
                        # and metrics applied here, same as aggregate children.
                        if isinstance(entry, EXPLORATION_ENTRY_TYPES):
                            upd["completed_at_ms"] = ts_ms or None
                            if metrics and isinstance(metrics, dict):
                                upd.update(_apply_exploration_metrics(entry, metrics))
                        if isinstance(entry, ToolKoanEntry):
                            raw_result = payload.get("result")
                            parsed = None
                            if raw_result and isinstance(raw_result, str):
                                try:
                                    parsed = json.loads(raw_result)
                                except (json.JSONDecodeError, TypeError):
                                    parsed = {"raw": raw_result}
                            elif isinstance(raw_result, dict):
                                parsed = raw_result
                            if parsed is not None:
                                existing = entry.result or {}
                                # Merge to preserve fields accumulated by domain events
                                # (same rationale as tool_completed case above).
                                upd["result"] = {**existing, **parsed}
                                # Dangling thinking_end cleanup (same as tool_completed).
                                result = upd["result"]
                                traces = result.get("traces", [])
                                if traces and isinstance(traces, list):
                                    last = traces[-1]
                                    if isinstance(last, dict) and last.get("kind") == "thinking_start":
                                        has_end = any(
                                            isinstance(t, dict) and t.get("kind") == "thinking_end"
                                            for t in traces
                                        )
                                        if not has_end:
                                            result["traces"] = list(traces) + [{"kind": "thinking_end"}]
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
                                    child_upd.update(_apply_exploration_metrics(child, metrics))
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


            case "tool_failed":
                # Argument validation rejected the call; the tool body never
                # ran. Top-level entries are REPLACED by ToolFailedEntry (the
                # malformed model-authored input survives only as the opaque
                # raw_input JSON string). Aggregate children are marked failed
                # in place: extraction would break the len(children) >= 2
                # invariant and reorder list keys.
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                call_id = payload.get("call_id", "")
                new_entries = []
                found = False
                for entry in agent.conversation.entries:
                    if isinstance(entry, ToolAggregateEntry):
                        new_children = []
                        child_found = False
                        for child in entry.children:
                            if child.call_id == call_id:
                                new_children.append(child.model_copy(update={
                                    "in_flight": False,
                                    "failed": True,
                                    "completed_at_ms": payload.get("ts_ms", 0) or None,
                                }))
                                child_found = True
                            else:
                                new_children.append(child)
                        if child_found:
                            found = True
                            new_entries.append(entry.model_copy(update={"children": new_children}))
                        else:
                            new_entries.append(entry)
                    elif isinstance(entry, BaseToolEntry) and entry.call_id == call_id:
                        raw = ""
                        if entry.tool_input:
                            try:
                                raw = json.dumps(entry.tool_input, ensure_ascii=False, default=str)
                            except (TypeError, ValueError):
                                raw = str(entry.tool_input)
                        # Retain entry_id/phase_id so the frontend list key is
                        # stable across the replacement.
                        new_entries.append(ToolFailedEntry(
                            call_id=call_id,
                            in_flight=False,
                            failed=True,
                            entry_id=entry.entry_id,
                            phase_id=entry.phase_id,
                            tool_name=payload.get("tool", "")
                                or getattr(entry, "tool_name", "") or entry.type,
                            error=payload.get("error", ""),
                            raw_input=raw,
                        ))
                        found = True
                    else:
                        new_entries.append(entry)
                if not found:
                    log.warning(
                        "fold: tool_failed for unknown call_id=%r agent=%r",
                        call_id, agent_id,
                    )
                    return projection
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })


            case "reflect_inline_trace":
                # Domain event: forward reflect subagent trace events (thinking
                # deltas, text streaming, search lifecycle, metadata) to the
                # in-flight ToolKoanEntry's result.traces array. Correlated by
                # agent_id only -- same uniqueness invariant as reflect_inline_trace.
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    return projection
                trace = payload.get("trace")
                if not trace or not isinstance(trace, dict):
                    return projection
                new_entries = list(agent.conversation.entries)
                target_idx: int | None = None
                for i, entry in enumerate(new_entries):
                    if isinstance(entry, ToolKoanEntry) and entry.in_flight:
                        target_idx = i
                        break
                if target_idx is None:
                    log.warning(
                        "fold reflect_inline_trace: no in-flight ToolKoanEntry for agent=%r",
                        agent_id,
                    )
                    return projection
                target = new_entries[target_idx]
                existing_result = target.result or {}
                trace_kind = trace.get("kind", "")

                if trace_kind == "meta":
                    new_result = {
                        **existing_result,
                        "model": trace.get("model", ""),
                        "maxIterations": trace.get("maxIterations", 0),
                        "iteration": trace.get("iteration", 0),
                        "traces": existing_result.get("traces", []),
                    }
                elif trace_kind == "search_done":
                    # Match the last running search entry and update it in place.
                    # The reflect agent calls search sequentially, so at most one
                    # running search exists at any time.
                    traces: list = list(existing_result.get("traces", []))
                    for j in range(len(traces) - 1, -1, -1):
                        t = traces[j]
                        if isinstance(t, dict) and t.get("kind") == "search" and t.get("status") == "running":
                            traces[j] = {**t, "status": "done", "resultCount": trace.get("resultCount")}
                            break
                    new_result = {
                        **existing_result,
                        "traces": traces,
                        "iteration": trace.get("iteration", existing_result.get("iteration")),
                    }
                elif trace_kind == "thinking_start":
                    traces: list = list(existing_result.get("traces", []))
                    traces.append({"kind": "thinking", "status": "running", "delta": ""})
                    new_result = {
                        **existing_result,
                        "traces": traces,
                        "iteration": trace.get("iteration", existing_result.get("iteration")),
                    }
                elif trace_kind == "thinking_delta":
                    traces: list = list(existing_result.get("traces", []))
                    # Accumulate delta into the last running thinking entry.
                    for j in range(len(traces) - 1, -1, -1):
                        t = traces[j]
                        if isinstance(t, dict) and t.get("kind") == "thinking" and t.get("status") == "running":
                            traces[j] = {**t, "delta": t.get("delta", "") + trace.get("delta", "")}
                            break
                    else:
                        # No running thinking entry found -- create one.
                        log.warning("fold reflect_inline_trace: thinking_delta without running thinking entry")
                        traces.append({"kind": "thinking", "status": "running", "delta": trace.get("delta", "")})
                    new_result = {
                        **existing_result,
                        "traces": traces,
                        "iteration": trace.get("iteration", existing_result.get("iteration")),
                    }
                elif trace_kind == "thinking_end":
                    traces: list = list(existing_result.get("traces", []))
                    for j in range(len(traces) - 1, -1, -1):
                        t = traces[j]
                        if isinstance(t, dict) and t.get("kind") == "thinking" and t.get("status") == "running":
                            traces[j] = {**t, "status": "done"}
                            break
                    new_result = {
                        **existing_result,
                        "traces": traces,
                        "iteration": trace.get("iteration", existing_result.get("iteration")),
                    }
                elif trace_kind == "text":
                    # Append delta to answer AND append a trace entry.
                    existing_answer = existing_result.get("answer", "") or ""
                    traces: list = list(existing_result.get("traces", []))
                    traces.append({"kind": "text", "delta": trace.get("delta", "")})
                    new_result = {
                        **existing_result,
                        "answer": existing_answer + trace.get("delta", ""),
                        "traces": traces,
                        "iteration": trace.get("iteration", existing_result.get("iteration")),
                    }
                else:
                    # search (running) -- append.
                    traces: list = list(existing_result.get("traces", []))
                    traces.append(trace)
                    new_result = {
                        **existing_result,
                        "traces": traces,
                        "iteration": trace.get("iteration", existing_result.get("iteration")),
                    }

                new_entries[target_idx] = target.model_copy(update={"result": new_result})
                new_conv = agent.conversation.model_copy(update={"entries": new_entries})
                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            case "tool_attachments":
                # Domain event: overwrite the in-flight tool entry's attachments with
                # a koan-side manifest carrying full upload_id and path fields. Emitted
                # by MCP handlers that have committed uploads. Correlated by agent_id
                # only -- same uniqueness invariant as reflect_inline_trace.
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

            # ── Telemetry ─────────────────────────────────────────────────

            case "token_telemetry":
                if projection.run is None or not agent_id:
                    return projection
                agent = projection.run.agents.get(agent_id)
                if agent is None:
                    log.warning("fold token_telemetry: unknown agent_id=%s", agent_id)
                    return projection

                conv = agent.conversation
                tel = conv.telemetry

                # Per-turn facts from the event payload.
                turn_input = payload.get("input_tokens", 0)
                turn_output = payload.get("output_tokens", 0)
                turn_cache_read = payload.get("cache_read_tokens", 0)
                turn_cache_write = payload.get("cache_write_tokens", 0)
                context_size = payload.get("context_size", 0)

                # Compute per-turn deltas: new cumulative minus old cumulative.
                # The event carries per-turn (not cumulative) values, so the delta
                # equals the turn value -- but deriving it from the cumulative totals
                # keeps the result correct if the event format ever changes.
                new_cumulative_input = conv.input_tokens + turn_input
                new_cumulative_output = conv.output_tokens + turn_output
                new_cumulative_cache_read = conv.cache_read_tokens + turn_cache_read
                new_cumulative_cache_write = conv.cache_write_tokens + turn_cache_write

                delta_input = new_cumulative_input - conv.input_tokens
                delta_output = new_cumulative_output - conv.output_tokens
                delta_cache_read = new_cumulative_cache_read - conv.cache_read_tokens
                delta_cache_write = new_cumulative_cache_write - conv.cache_write_tokens

                # Update Telemetry with the measured context_size and computed deltas.
                new_telemetry = tel.model_copy(update={
                    "context_size": context_size,
                    "delta_input_tokens": delta_input,
                    "delta_output_tokens": delta_output,
                    "delta_cache_read_tokens": delta_cache_read,
                    "delta_cache_write_tokens": delta_cache_write,
                })

                # Update Conversation cumulative fields and telemetry in one copy so
                # they cannot diverge (cumulative totals stay on Conversation, derived
                # deltas/context_size stay on Telemetry).
                new_conv = conv.model_copy(update={
                    "input_tokens": new_cumulative_input,
                    "output_tokens": new_cumulative_output,
                    "cache_read_tokens": new_cumulative_cache_read,
                    "cache_write_tokens": new_cumulative_cache_write,
                    "telemetry": new_telemetry,
                })

                return projection.model_copy(update={
                    "run": _update_agent_conversation(projection.run, agent_id, new_conv),
                })

            # ── Focus transitions ──────────────────────────────────────────
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
                # Stamp with the phase active at creation; this is the single
                # server-authoritative source for the timeline handoff badges.
                info = ArtifactInfo(
                    path=path,
                    size=payload.get("size", 0),
                    modified_at=payload.get("modified_at", 0),
                    produced_phase_id=projection.run.phase or None,
                )
                new_artifacts = dict(projection.run.artifacts)
                new_artifacts[path] = info
                new_run = projection.run.model_copy(update={"artifacts": new_artifacts})
                return projection.model_copy(update={"run": new_run})

            case "artifact_modified":
                if projection.run is None:
                    return projection
                path = payload.get("path", "")
                # Carry the producing phase forward -- an artifact's producer
                # never changes, so we must not reset it on subsequent writes.
                prev = projection.run.artifacts.get(path)
                info = ArtifactInfo(
                    path=path,
                    size=payload.get("size", 0),
                    modified_at=payload.get("modified_at", 0),
                    produced_phase_id=prev.produced_phase_id if prev else None,
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

            case "execute_entry":
                # M3: freeze removed; execute_entry is now a pure no-op
                # started-marker.  The event is still emitted and appended to the
                # event log as the audit record of when execution began.
                return projection

            case "execute_completion":
                # M5: pure no-op. ArtifactInfo no longer carries executed/exec_outcome.
                # The case is kept (not deleted) so this event stays recognized and
                # appended to the event log as the audit record; deleting it would
                # produce "unknown event_type" noise for every koan_request_executor call.
                return projection

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
                # resolved_from, embedding_dim}, ...]}.
                raw_cms = payload.get("configured_models", [])
                new_cms = [
                    ConfiguredModelWire(
                        id=m.get("id", ""),
                        connection_id=m.get("connection_id", ""),
                        model_id=m.get("model_id", ""),
                        resolved_from=m.get("resolved_from"),
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

            case "retry_settings_changed":
                new_settings = projection.settings.model_copy(update={
                    "max_retry_attempts": payload.get("max_retry_attempts", 10),
                    "max_retry_wait_seconds": payload.get("max_retry_wait_seconds", 60.0),
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
                # Payload: {models: [{provider, model, display_name, thinking_modes}, ...]}.
                # Populates the all-providers model catalog in the Settings projection.
                raw_models = payload.get("models", [])
                new_mr = [
                    ModelRegistryEntryWire(
                        provider=m.get("provider", ""),
                        model=m.get("model", ""),
                        display_name=m.get("display_name", ""),
                        thinking_modes=m.get("thinking_modes", []),
                    )
                    for m in raw_models
                ]
                new_settings = projection.settings.model_copy(update={"model_registry": new_mr})
                return projection.model_copy(update={"settings": new_settings})

            case "provider_models_listed":
                # Payload: {models: [{provider, model, display_name, connection_id}, ...],
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
                # supports_prompt_caching, recognized}, ...]}.
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
                        supports_prompt_caching=c.get("supports_prompt_caching", False),
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
                        phase=s.get("phase", ""),
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
            # memory_curation_started / memory_curation_cleared fold cases
            # removed in M7: the koan_memory_propose approval gate is retired;
            # curation writes memory directly via koan_memorize/koan_forget.

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
                # Replace-all: {models: [{model_id, dimensions, default_dimension}, ...]}.
                # Pushed once at startup; static for the process lifetime.
                # The frontend uses this to populate the dimension selector.
                raw_models = payload.get("models", [])
                new_ems = [
                    EmbeddingModelWire(
                        model_id=m.get("model_id", ""),
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
