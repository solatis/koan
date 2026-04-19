# AppState and AgentState -- in-process mutable state for the koan server.
# These are plain dataclasses mutated in place; no persistence layer here.

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from .config import KoanConfig
from .probe import ProbeResult
from .projections import ProjectionStore
from .types import WorkflowPhase, Profile, SubagentRole


@dataclass
class ChatMessage:
    content: str
    timestamp_ms: int


@dataclass
class PendingInteraction:
    type: Literal["ask"]
    agent_id: str
    future: asyncio.Future
    payload: dict
    token: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class AgentState:
    agent_id: str
    role: SubagentRole
    subagent_dir: str
    run_dir: str = ""
    label: str = ""
    step: int = 0
    phase_module: Any = None
    phase_ctx: Any = None
    event_log: Any = None
    handshake_observed: bool = False
    pending_tool: asyncio.Future | None = None
    model: str | None = None
    token_count: dict = field(default_factory=lambda: {"sent": 0, "received": 0})
    final_response: str = ""
    is_primary: bool = True
    started_at: datetime = field(default_factory=_utcnow)


@dataclass
class AppState:
    phase: WorkflowPhase = "intake"
    run_dir: str | None = None
    project_dir: str = ""
    task_description: str = ""
    workflow: Any = None  # Workflow | None — imported lazily to avoid circular deps
    start_event: asyncio.Event = field(default_factory=asyncio.Event)
    agents: dict[str, AgentState] = field(default_factory=dict)
    projection_store: ProjectionStore = field(default_factory=ProjectionStore)
    active_interaction: PendingInteraction | None = None
    interaction_queue: deque[PendingInteraction] = field(default_factory=deque)
    interaction_queue_max: int = 8
    config: KoanConfig = field(default_factory=KoanConfig)
    builtin_profiles: dict[str, Profile] = field(default_factory=dict)
    probe_results: list[ProbeResult] = field(default_factory=list)
    port: int = 8000
    open_browser: bool = True
    initial_prompt: str = ""
    yolo: bool = False
    debug: bool = False
    config_write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Installation selections for the current run: runner_type -> alias.
    # Set when a run starts; cleared when a new run begins.
    run_installations: dict[str, str] = field(default_factory=dict)
    # Track running subprocess handles so shutdown can kill them.
    _active_processes: dict[str, asyncio.subprocess.Process] = field(
        default_factory=dict, repr=False,
    )
    # Buffered user chat messages — drained when koan_yield unblocks.
    user_message_buffer: list[ChatMessage] = field(default_factory=list)
    # Non-None while koan_yield is blocking, waiting for a user message.
    yield_future: asyncio.Future | None = None
    # True after koan_set_phase("done") — signals the orchestrator to exit.
    workflow_done: bool = False
    # Steering queue — user messages delivered on the next koan_* tool response.
    # Separate from user_message_buffer so yield blocking and steering
    # can be drained independently without double-delivery.
    steering_queue: list[ChatMessage] = field(default_factory=list)


def drain_user_messages(app_state: AppState) -> list[ChatMessage]:
    """Atomically drain the user message buffer. Returns all buffered messages."""
    messages = list(app_state.user_message_buffer)
    app_state.user_message_buffer.clear()
    return messages


def drain_steering_messages(app_state: AppState) -> list[ChatMessage]:
    """Atomically drain the steering queue. Returns all buffered messages."""
    messages = list(app_state.steering_queue)
    app_state.steering_queue.clear()
    return messages
