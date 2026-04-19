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
import logging
from datetime import datetime, timezone
from typing import Annotated, Literal

import jsonpatch
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .lib.workflows import WORKFLOWS

log = logging.getLogger("koan.projections")

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
    "workflow_selected",
    "scout_queued",
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
    "tool_result_captured",
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
    "phase_summary_captured",
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
    "probe_completed",
    "installation_created",
    "installation_modified",
    "installation_removed",
    "profile_created",
    "profile_modified",
    "profile_removed",
    "default_profile_changed",
    "default_scout_concurrency_changed",
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

class BaseToolEntry(KoanBaseModel):
    """Shared fields for all tool entries and aggregate children."""
    call_id: str                           # unique per tool invocation
    in_flight: bool                        # True until tool_completed

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

AggregateChild = Annotated[
    AggregateReadChild | AggregateGrepChild | AggregateLsChild,
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
    ToolAggregateEntry |
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

class Installation(KoanBaseModel):
    """A configured LLM CLI installation."""
    alias: str
    runner_type: str
    binary: str
    extra_args: list[str] = []
    available: bool = False                # probe result: binary exists and responds

class Profile(KoanBaseModel):
    """Maps roles to installations for a workflow run."""
    name: str
    read_only: bool = False
    tiers: dict[str, str] = {}             # role → installation alias

class Settings(KoanBaseModel):
    installations: dict[str, Installation] = {}   # alias → Installation
    profiles: dict[str, Profile] = {}             # name → Profile
    default_profile: str = "balanced"
    default_scout_concurrency: int = 8

class RunConfig(KoanBaseModel):
    """Resolved configuration frozen at run start."""
    profile: str
    installations: dict[str, str] = {}     # role → installation alias
    scout_concurrency: int = 8


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

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
    content: str

class PhaseInfo(KoanBaseModel):
    """A phase the user can transition to, as shown in the command palette."""
    id: str                                # phase key (e.g. "plan-spec")
    description: str                       # one-line description from the workflow

class Run(KoanBaseModel):
    config: RunConfig
    phase: str = ""
    workflow: str = ""    # active workflow name
    available_phases: list[PhaseInfo] = []  # populated on workflow_selected; drives the / command palette
    agents: dict[str, Agent] = {}          # all agents by ID — queued, running, done, failed
    focus: Focus | None = None             # None before first agent spawns
    artifacts: dict[str, ArtifactInfo] = {}
    completion: CompletionInfo | None = None
    steering: list[SteeringMessage] = []   # pending steering messages shown above chat
    active_yield: ActiveYield | None = None  # non-None while orchestrator is in koan_yield
    # Keyed by phase name. Populated on the first koan_yield of each phase
    # from the orchestrator's last assistant text. Used as context anchor for
    # the next phase's mechanical RAG injection. Wire-visible; frontend ignores.
    phase_summaries: dict[str, str] = {}

class Projection(KoanBaseModel):
    settings: Settings = Field(default_factory=Settings)
    run: Run | None = None                 # None → show landing page
    notifications: list[Notification] = []


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
                config = RunConfig(
                    profile=payload.get("profile", ""),
                    installations=payload.get("installations", {}),
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
                    "active_yield": None,  # clear yield when a new phase starts
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
                    "active_yield": None,  # clear yield on completion
                })
                return projection.model_copy(update={"run": new_run})

            # ── Agent lifecycle ────────────────────────────────────────────

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

                # Accumulate final usage into conversation
                new_conv = agent.conversation
                if usage:
                    new_conv = new_conv.model_copy(update={
                        "input_tokens": new_conv.input_tokens + usage.get("input_tokens", 0),
                        "output_tokens": new_conv.output_tokens + usage.get("output_tokens", 0),
                    })

                new_agent = agent.model_copy(update={
                    "status": status,
                    "error": error,
                    "conversation": new_conv,
                    "completed_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
                })
                new_agents = dict(projection.run.agents)
                new_agents[agent_id] = new_agent
                new_run = projection.run.model_copy(update={"agents": new_agents})
                new_projection = projection.model_copy(update={"run": new_run})

                # Append error notification
                if error:
                    notif = Notification(
                        message=f"Agent {agent_id} exited with error: {error}",
                        level="error",
                        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                    )
                    new_projection = new_projection.model_copy(update={
                        "notifications": [*new_projection.notifications, notif],
                    })
                return new_projection

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
                # Skip koan MCP tools — they are infrastructure, not user-visible activity
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
                for entry in agent.conversation.entries:
                    if (
                        isinstance(entry, BaseToolEntry)
                        and entry.call_id == call_id
                        and not isinstance(entry, ToolAggregateEntry)
                    ):
                        new_entries.append(entry.model_copy(update={"in_flight": False}))
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
                entry = SteeringMessage(content=payload.get("content", ""))
                return projection.model_copy(update={
                    "run": projection.run.model_copy(update={
                        "steering": [*projection.run.steering, entry],
                    }),
                })

            case "steering_delivered":
                if projection.run is None:
                    return projection
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

                # Accumulate token usage from step
                if usage:
                    new_conv = new_conv.model_copy(update={
                        "input_tokens": new_conv.input_tokens + usage.get("input_tokens", 0),
                        "output_tokens": new_conv.output_tokens + usage.get("output_tokens", 0),
                    })

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

            case "probe_completed":
                # Payload: {results: {alias: bool, ...}}
                results: dict[str, bool] = payload.get("results", {})
                new_insts = dict(projection.settings.installations)
                for alias, available in results.items():
                    if alias in new_insts:
                        new_insts[alias] = new_insts[alias].model_copy(update={"available": available})
                new_settings = projection.settings.model_copy(update={"installations": new_insts})
                return projection.model_copy(update={"settings": new_settings})

            case "installation_created":
                alias = payload.get("alias", "")
                inst = Installation(
                    alias=alias,
                    runner_type=payload.get("runner_type", ""),
                    binary=payload.get("binary", ""),
                    extra_args=payload.get("extra_args", []),
                    available=False,  # availability set by probe_completed
                )
                new_insts = dict(projection.settings.installations)
                new_insts[alias] = inst
                new_settings = projection.settings.model_copy(update={"installations": new_insts})
                return projection.model_copy(update={"settings": new_settings})

            case "installation_modified":
                alias = payload.get("alias", "")
                existing = projection.settings.installations.get(alias)
                available = existing.available if existing else False
                inst = Installation(
                    alias=alias,
                    runner_type=payload.get("runner_type", ""),
                    binary=payload.get("binary", ""),
                    extra_args=payload.get("extra_args", []),
                    available=available,  # preserve probe result
                )
                new_insts = dict(projection.settings.installations)
                new_insts[alias] = inst
                new_settings = projection.settings.model_copy(update={"installations": new_insts})
                return projection.model_copy(update={"settings": new_settings})

            case "installation_removed":
                alias = payload.get("alias", "")
                new_insts = {k: v for k, v in projection.settings.installations.items() if k != alias}
                new_settings = projection.settings.model_copy(update={"installations": new_insts})
                return projection.model_copy(update={"settings": new_settings})

            case "profile_created":
                name = payload.get("name", "")
                # tiers in the projection are stored as dict[str, str] (role → alias).
                # The payload tiers may be nested dicts from the old ProfileTier structure
                # or simple string values from the new structure. Normalise to str.
                raw_tiers = payload.get("tiers", {})
                tiers: dict[str, str] = {}
                for role, val in raw_tiers.items():
                    if isinstance(val, str):
                        tiers[role] = val
                    elif isinstance(val, dict):
                        # Legacy: extract alias or runner_type as a best-effort fallback
                        tiers[role] = val.get("alias", val.get("runner_type", str(val)))
                    else:
                        tiers[role] = str(val)
                profile = Profile(
                    name=name,
                    read_only=payload.get("read_only", False),
                    tiers=tiers,
                )
                new_profiles = dict(projection.settings.profiles)
                new_profiles[name] = profile
                new_settings = projection.settings.model_copy(update={"profiles": new_profiles})
                return projection.model_copy(update={"settings": new_settings})

            case "profile_modified":
                name = payload.get("name", "")
                raw_tiers = payload.get("tiers", {})
                tiers = {}
                for role, val in raw_tiers.items():
                    if isinstance(val, str):
                        tiers[role] = val
                    elif isinstance(val, dict):
                        tiers[role] = val.get("alias", val.get("runner_type", str(val)))
                    else:
                        tiers[role] = str(val)
                profile = Profile(
                    name=name,
                    read_only=payload.get("read_only", False),
                    tiers=tiers,
                )
                new_profiles = dict(projection.settings.profiles)
                new_profiles[name] = profile
                new_settings = projection.settings.model_copy(update={"profiles": new_profiles})
                return projection.model_copy(update={"settings": new_settings})

            case "profile_removed":
                name = payload.get("name", "")
                new_profiles = {k: v for k, v in projection.settings.profiles.items() if k != name}
                new_settings = projection.settings.model_copy(update={"profiles": new_profiles})
                return projection.model_copy(update={"settings": new_settings})

            case "default_profile_changed":
                new_settings = projection.settings.model_copy(update={
                    "default_profile": payload.get("name", "balanced"),
                })
                return projection.model_copy(update={"settings": new_settings})

            case "default_scout_concurrency_changed":
                new_settings = projection.settings.model_copy(update={
                    "default_scout_concurrency": payload.get("value", 8),
                })
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

            case "phase_summary_captured":
                # agent_id is carried for audit only; phase_summaries is run-scoped.
                if projection.run is None:
                    return projection
                phase = payload.get("phase", "")
                summary = payload.get("summary", "")
                if not phase:
                    return projection
                new_summaries = dict(projection.run.phase_summaries)
                new_summaries[phase] = summary
                new_run = projection.run.model_copy(update={"phase_summaries": new_summaries})
                return projection.model_copy(update={"run": new_run})

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
