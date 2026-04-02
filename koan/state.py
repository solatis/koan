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
from .types import EpicPhase, Profile, SubagentRole


@dataclass
class PendingInteraction:
    type: Literal["ask", "artifact-review", "workflow-decision"]
    agent_id: str
    future: asyncio.Future
    payload: dict
    token: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class AgentState:
    agent_id: str
    role: SubagentRole
    subagent_dir: str
    epic_dir: str = ""
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
    phase: EpicPhase = "intake"
    epic_dir: str | None = None
    start_event: asyncio.Event = field(default_factory=asyncio.Event)
    agents: dict[str, AgentState] = field(default_factory=dict)
    projection_store: ProjectionStore = field(default_factory=ProjectionStore)
    active_interaction: PendingInteraction | None = None
    interaction_queue: deque[PendingInteraction] = field(default_factory=deque)
    interaction_queue_max: int = 8
    frozen_logs: list = field(default_factory=list)
    config: KoanConfig = field(default_factory=KoanConfig)
    balanced_profile: Profile | None = None
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
