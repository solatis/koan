# AppState and AgentState -- in-process mutable state for the koan server.
# These are plain dataclasses mutated in place; no persistence layer here.

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .config import KoanConfig
from .types import EpicPhase, SubagentRole


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
    step: int = 0
    phase_module: Any = None
    phase_ctx: Any = None
    event_log: Any = None
    handshake_observed: bool = False
    pending_tool: asyncio.Future | None = None
    token_count: dict = field(default_factory=lambda: {"sent": 0, "received": 0})
    started_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AppState:
    phase: EpicPhase = "intake"
    epic_dir: str | None = None
    start_event: asyncio.Event = field(default_factory=asyncio.Event)
    agents: dict[str, AgentState] = field(default_factory=dict)
    sse_clients: list = field(default_factory=list)
    active_interaction: PendingInteraction | None = None
    interaction_queue: deque[PendingInteraction] = field(default_factory=deque)
    interaction_queue_max: int = 8
    frozen_logs: list = field(default_factory=list)
    config: KoanConfig = field(default_factory=KoanConfig)
    port: int = 8000
    last_sse_values: dict[str, Any] = field(default_factory=dict)
