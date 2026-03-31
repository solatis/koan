# Projection event-sourcing machinery.
# Pure -- zero koan domain imports. All fold logic lives here.

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger("koan.projections")

EventType = Literal[
    # Lifecycle
    "phase_started",
    "agent_spawned",
    "agent_spawn_failed",
    "agent_step_advanced",
    "agent_exited",
    "workflow_completed",
    # Activity
    "tool_called",
    "tool_completed",
    "thinking",
    "stream_delta",
    "stream_cleared",
    # Interactions
    "questions_asked",
    "questions_answered",
    "artifact_review_requested",
    "artifact_reviewed",
    "workflow_decision_requested",
    "workflow_decided",
    # Resources
    "artifact_created",
    "artifact_modified",
    "artifact_removed",
    # Configuration
    "probe_completed",
    "installation_created",
    "installation_modified",
    "installation_removed",
    "profile_created",
    "profile_modified",
    "profile_removed",
    "active_profile_changed",
    "scout_concurrency_changed",
]


class VersionedEvent(BaseModel):
    version: int
    event_type: str  # EventType string; stored as str so unknown types deserialise safely
    timestamp: str
    agent_id: str | None = None
    payload: dict


class AgentProjection(BaseModel):
    agent_id: str
    role: str
    model: str | None = None
    step: int = 0
    step_name: str = ""
    started_at_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class Projection(BaseModel):
    # Run state
    run_started: bool = False
    phase: str = ""

    # Agents
    primary_agent: AgentProjection | None = None
    scouts: dict[str, AgentProjection] = Field(default_factory=dict)
    completed_agents: list[AgentProjection] = Field(default_factory=list)

    # Activity (raw events appended as-is: tool_called, tool_completed, thinking)
    activity_log: list[dict] = Field(default_factory=list)
    stream_buffer: str = ""

    # Interactions
    active_interaction: dict | None = None

    # Resources
    artifacts: dict[str, dict] = Field(default_factory=dict)  # keyed by path
    notifications: list[dict] = Field(default_factory=list)   # derived from error events

    # Completion
    completion: dict | None = None

    # Configuration
    config_runners: list[dict] = Field(default_factory=list)
    config_profiles: list[dict] = Field(default_factory=list)
    config_installations: list[dict] = Field(default_factory=list)
    config_active_profile: str = "balanced"
    config_scout_concurrency: int = 8


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _accumulate_usage(agent: AgentProjection, usage: dict | None) -> AgentProjection:
    if not usage:
        return agent
    return agent.model_copy(update={
        "input_tokens": agent.input_tokens + usage.get("input_tokens", 0),
        "output_tokens": agent.output_tokens + usage.get("output_tokens", 0),
    })


def fold(projection: Projection, event: VersionedEvent) -> Projection:
    """Pure fold: (Projection, VersionedEvent) -> Projection.

    Unknown event types return projection unchanged with a logged warning.
    Unknown agent_ids for agent-specific events return projection unchanged with a logged warning.
    Any exception within a handler returns projection unchanged, with the exception logged.
    The event is always appended to the log before fold() is called; fold exceptions do not
    prevent appending.
    """
    event_type = event.event_type
    payload = event.payload
    agent_id = event.agent_id

    try:
        match event_type:

            # ── Lifecycle ──────────────────────────────────────────────────────

            case "phase_started":
                return projection.model_copy(update={
                    "phase": payload.get("phase", ""),
                    "run_started": True,
                })

            case "agent_spawned":
                eid = agent_id or payload.get("agent_id", "")
                new_agent = AgentProjection(
                    agent_id=eid,
                    role=payload.get("role", ""),
                    model=payload.get("model"),
                    step=0,
                    started_at_ms=payload.get("started_at_ms", 0),
                )
                if payload.get("is_primary", True):
                    return projection.model_copy(update={"primary_agent": new_agent})
                else:
                    new_scouts = dict(projection.scouts)
                    new_scouts[eid] = new_agent
                    return projection.model_copy(update={"scouts": new_scouts})

            case "agent_spawn_failed":
                notification = {
                    "type": "agent_spawn_failed",
                    "role": payload.get("role", ""),
                    "error_code": payload.get("error_code", ""),
                    "message": payload.get("message", ""),
                    "details": payload.get("details"),
                }
                return projection.model_copy(update={
                    "notifications": [*projection.notifications, notification],
                })

            case "agent_step_advanced":
                usage = payload.get("usage")
                step = payload.get("step", 0)
                step_name = payload.get("step_name", "")

                if projection.primary_agent and projection.primary_agent.agent_id == agent_id:
                    updated = projection.primary_agent.model_copy(update={
                        "step": step,
                        "step_name": step_name,
                    })
                    updated = _accumulate_usage(updated, usage)
                    return projection.model_copy(update={"primary_agent": updated})
                elif agent_id and agent_id in projection.scouts:
                    updated = projection.scouts[agent_id].model_copy(update={
                        "step": step,
                        "step_name": step_name,
                    })
                    updated = _accumulate_usage(updated, usage)
                    new_scouts = dict(projection.scouts)
                    new_scouts[agent_id] = updated
                    return projection.model_copy(update={"scouts": new_scouts})
                else:
                    log.warning("fold agent_step_advanced: unknown agent_id=%s", agent_id)
                    return projection

            case "agent_exited":
                usage = payload.get("usage")
                error = payload.get("error")

                new_notifications = list(projection.notifications)
                if error:
                    new_notifications.append({
                        "type": "agent_exited_error",
                        "agent_id": agent_id,
                        "exit_code": payload.get("exit_code", 1),
                        "error": error,
                    })

                new_completed = list(projection.completed_agents)

                if projection.primary_agent and projection.primary_agent.agent_id == agent_id:
                    # Accumulate final tokens, preserve in completed_agents, then clear
                    final_agent = _accumulate_usage(projection.primary_agent, usage)
                    new_completed.append(final_agent)
                    return projection.model_copy(update={
                        "primary_agent": None,
                        "completed_agents": new_completed,
                        "notifications": new_notifications,
                    })
                elif agent_id and agent_id in projection.scouts:
                    final_agent = _accumulate_usage(projection.scouts[agent_id], usage)
                    new_completed.append(final_agent)
                    new_scouts = {k: v for k, v in projection.scouts.items() if k != agent_id}
                    return projection.model_copy(update={
                        "scouts": new_scouts,
                        "completed_agents": new_completed,
                        "notifications": new_notifications,
                    })
                else:
                    # Unknown agent_id: return unchanged per plan semantics.
                    # Error notifications are still recorded — the fact of an
                    # error exit is worth preserving even if the agent wasn't
                    # tracked (e.g. late-arriving event after projection reset).
                    if new_notifications != projection.notifications:
                        log.warning("fold agent_exited: unknown agent_id=%s, preserving error notification", agent_id)
                        return projection.model_copy(update={"notifications": new_notifications})
                    log.warning("fold agent_exited: unknown agent_id=%s", agent_id)
                    return projection

            case "workflow_completed":
                return projection.model_copy(update={"completion": payload})

            # ── Activity ───────────────────────────────────────────────────────

            case "tool_called":
                entry = {"event_type": event_type, "agent_id": agent_id, **payload}
                return projection.model_copy(update={
                    "activity_log": [*projection.activity_log, entry],
                })

            case "tool_completed":
                entry = {"event_type": event_type, "agent_id": agent_id, **payload}
                return projection.model_copy(update={
                    "activity_log": [*projection.activity_log, entry],
                })

            case "thinking":
                entry = {"event_type": event_type, "agent_id": agent_id, **payload}
                return projection.model_copy(update={
                    "activity_log": [*projection.activity_log, entry],
                })

            case "stream_delta":
                return projection.model_copy(update={
                    "stream_buffer": projection.stream_buffer + payload.get("delta", ""),
                })

            case "stream_cleared":
                return projection.model_copy(update={"stream_buffer": ""})

            # ── Interactions ───────────────────────────────────────────────────

            case "questions_asked":
                active = {"interaction_type": "questions_asked", **payload}
                return projection.model_copy(update={"active_interaction": active})

            case "questions_answered":
                return projection.model_copy(update={"active_interaction": None})

            case "artifact_review_requested":
                active = {"interaction_type": "artifact_review_requested", **payload}
                return projection.model_copy(update={"active_interaction": active})

            case "artifact_reviewed":
                return projection.model_copy(update={"active_interaction": None})

            case "workflow_decision_requested":
                active = {"interaction_type": "workflow_decision_requested", **payload}
                return projection.model_copy(update={"active_interaction": active})

            case "workflow_decided":
                return projection.model_copy(update={"active_interaction": None})

            # ── Resources ──────────────────────────────────────────────────────

            case "artifact_created":
                path = payload.get("path", "")
                new_artifacts = dict(projection.artifacts)
                new_artifacts[path] = {
                    "path": path,
                    "size": payload.get("size", 0),
                    "modified_at": payload.get("modified_at", 0),
                }
                return projection.model_copy(update={"artifacts": new_artifacts})

            case "artifact_modified":
                path = payload.get("path", "")
                new_artifacts = dict(projection.artifacts)
                new_artifacts[path] = {
                    "path": path,
                    "size": payload.get("size", 0),
                    "modified_at": payload.get("modified_at", 0),
                }
                return projection.model_copy(update={"artifacts": new_artifacts})

            case "artifact_removed":
                path = payload.get("path", "")
                new_artifacts = {k: v for k, v in projection.artifacts.items() if k != path}
                return projection.model_copy(update={"artifacts": new_artifacts})

            # ── Configuration ──────────────────────────────────────────────────

            case "probe_completed":
                return projection.model_copy(update={
                    "config_runners": payload.get("runners", []),
                })

            case "installation_created":
                new_inst = {
                    "alias": payload.get("alias", ""),
                    "runner_type": payload.get("runner_type", ""),
                    "binary": payload.get("binary", ""),
                    "extra_args": payload.get("extra_args", []),
                }
                return projection.model_copy(update={
                    "config_installations": [*projection.config_installations, new_inst],
                })

            case "installation_modified":
                alias = payload.get("alias", "")
                updated_inst = {
                    "alias": alias,
                    "runner_type": payload.get("runner_type", ""),
                    "binary": payload.get("binary", ""),
                    "extra_args": payload.get("extra_args", []),
                }
                new_insts = [
                    updated_inst if inst.get("alias") == alias else inst
                    for inst in projection.config_installations
                ]
                return projection.model_copy(update={"config_installations": new_insts})

            case "installation_removed":
                alias = payload.get("alias", "")
                new_insts = [
                    inst for inst in projection.config_installations
                    if inst.get("alias") != alias
                ]
                return projection.model_copy(update={"config_installations": new_insts})

            case "profile_created":
                new_profile = {
                    "name": payload.get("name", ""),
                    "read_only": payload.get("read_only", False),
                    "tiers": payload.get("tiers", {}),
                }
                return projection.model_copy(update={
                    "config_profiles": [*projection.config_profiles, new_profile],
                })

            case "profile_modified":
                name = payload.get("name", "")
                updated_profile = {
                    "name": name,
                    "read_only": payload.get("read_only", False),
                    "tiers": payload.get("tiers", {}),
                }
                if any(p.get("name") == name for p in projection.config_profiles):
                    new_profiles = [
                        updated_profile if p.get("name") == name else p
                        for p in projection.config_profiles
                    ]
                else:
                    # First time (e.g. balanced on startup)
                    new_profiles = [*projection.config_profiles, updated_profile]
                return projection.model_copy(update={"config_profiles": new_profiles})

            case "profile_removed":
                name = payload.get("name", "")
                new_profiles = [
                    p for p in projection.config_profiles if p.get("name") != name
                ]
                return projection.model_copy(update={"config_profiles": new_profiles})

            case "active_profile_changed":
                return projection.model_copy(update={
                    "config_active_profile": payload.get("name", "balanced"),
                })

            case "scout_concurrency_changed":
                return projection.model_copy(update={
                    "config_scout_concurrency": payload.get("value", 8),
                })

            case _:
                log.warning("fold: unknown event_type=%r", event_type)
                return projection

    except Exception:
        log.exception(
            "fold: exception handling event_type=%r version=%d event=%r",
            event_type, event.version, event,
        )
        return projection


class ProjectionStore:
    """In-memory versioned event log + materialized projection + asyncio.Queue subscribers."""

    def __init__(self) -> None:
        self.events: list[VersionedEvent] = []
        self.projection: Projection = Projection()
        self.version: int = 0
        self.subscribers: list[asyncio.Queue] = []

    def push_event(
        self,
        event_type: str,
        payload: dict,
        agent_id: str | None = None,
    ) -> VersionedEvent:
        """Append event, fold into projection, broadcast to subscribers."""
        self.version += 1
        event = VersionedEvent(
            version=self.version,
            event_type=event_type,
            timestamp=_utcnow(),
            agent_id=agent_id,
            payload=payload,
        )
        self.events.append(event)

        # Fold — event is in the log regardless of fold success
        try:
            self.projection = fold(self.projection, event)
        except Exception:
            log.exception(
                "ProjectionStore: fold raised for event version=%d type=%r",
                self.version, event_type,
            )

        # Broadcast — snapshot list to avoid RuntimeError on concurrent subscribe/unsubscribe
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning(
                    "ProjectionStore: subscriber queue full, dropping event version=%d",
                    self.version,
                )
            except Exception:
                pass

        return event

    def get_snapshot(self) -> dict:
        """Return {version, state} for SSE snapshot."""
        return {
            "version": self.version,
            "state": self.projection.model_dump(),
        }

    def events_since(self, version: int) -> list[VersionedEvent]:
        """Return all events with version > given version."""
        return [e for e in self.events if e.version > version]

    def subscribe(self) -> asyncio.Queue:
        """Create and register a subscriber queue."""
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        try:
            self.subscribers.remove(queue)
        except ValueError:
            pass
