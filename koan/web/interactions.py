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


# -- Request event emitter ----------------------------------------------------

def _emit_interaction_request(app_state: AppState, interaction: PendingInteraction) -> None:
    """Emit the typed request event for an interaction becoming active."""
    from ..events import build_questions_asked

    store = app_state.projection_store
    token = interaction.token
    payload = interaction.payload
    agent_id = interaction.agent_id

    if interaction.type == "ask":
        store.push_event(
            "questions_asked",
            build_questions_asked(token, payload.get("questions", [])),
            agent_id=agent_id,
        )


# -- Queue helpers ------------------------------------------------------------

async def enqueue_interaction(
    agent: AgentState,
    app_state: AppState,
    interaction_type: Literal["ask"],
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
        _emit_interaction_request(app_state, interaction)
    else:
        app_state.interaction_queue.append(interaction)

    return future


def activate_next_interaction(app_state: AppState) -> None:
    """Promote the next queued interaction to active, emitting its request event."""
    if app_state.interaction_queue:
        nxt = app_state.interaction_queue.popleft()
        app_state.active_interaction = nxt
        _emit_interaction_request(app_state, nxt)
    else:
        app_state.active_interaction = None
