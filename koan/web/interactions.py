# Interaction queue helpers -- enqueue blocking interactions and drain FIFO.
#
# Extracted from mcp_endpoint.py so both mcp_endpoint.py and subagent.py
# can import without circular dependencies.

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Literal

from fastmcp.exceptions import ToolError

from ..state import PendingInteraction

if TYPE_CHECKING:
    from ..state import AgentState, AppState


# -- SSE push (lazy import to avoid circular deps) ----------------------------

def _push_sse(app_state: AppState, event_type: str, payload: dict) -> None:
    from ..driver import push_sse
    push_sse(app_state, event_type, payload)


# -- Queue helpers ------------------------------------------------------------

async def enqueue_interaction(
    agent: AgentState,
    app_state: AppState,
    interaction_type: Literal["ask", "artifact-review", "workflow-decision"],
    payload: dict,
) -> asyncio.Future:
    total = len(app_state.interaction_queue) + (1 if app_state.active_interaction else 0)
    cap = app_state.interaction_queue_max + 1  # 1 active + N queued
    if total >= cap:
        raise ToolError(
            json.dumps({"error": "interaction_queue_full", "message": "interaction_queue_full"})
        )

    future: asyncio.Future = asyncio.get_running_loop().create_future()
    interaction = PendingInteraction(
        type=interaction_type,
        agent_id=agent.agent_id,
        future=future,
        payload=payload,
    )
    agent.pending_tool = future

    if app_state.active_interaction is None:
        app_state.active_interaction = interaction
        _push_sse(app_state, "interaction", {"type": interaction_type, "token": interaction.token, **payload})
    else:
        app_state.interaction_queue.append(interaction)

    return future


def activate_next_interaction(app_state: AppState) -> None:
    _push_sse(app_state, "interaction", {"type": "cleared"})

    if app_state.interaction_queue:
        nxt = app_state.interaction_queue.popleft()
        app_state.active_interaction = nxt
        _push_sse(app_state, "interaction", {"type": nxt.type, "token": nxt.token, **nxt.payload})
    else:
        app_state.active_interaction = None
