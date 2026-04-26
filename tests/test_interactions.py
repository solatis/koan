# Tests for interaction queue, FIFO activation, stale submission, and cancellation.

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any
from unittest.mock import patch

import pytest

from koan.state import AppState, PendingInteraction


def _make_interaction(
    interaction_type: str = "ask",
    agent_id: str = "agent-1",
    future: asyncio.Future | None = None,
    payload: dict | None = None,
) -> PendingInteraction:
    if future is None:
        future = asyncio.get_event_loop().create_future()
    return PendingInteraction(
        type=interaction_type,
        agent_id=agent_id,
        future=future,
        payload=payload or {},
    )


# -- TestQueueCap -------------------------------------------------------------

class TestQueueCap:
    @pytest.mark.anyio
    async def test_9th_request_raises_queue_full(self):
        from fastmcp.exceptions import ToolError

        from koan.state import AgentState
        from koan.web.interactions import enqueue_interaction

        app_state = AppState()
        app_state.interactions.active_interaction = _make_interaction(agent_id="other")

        for i in range(8):
            app_state.interactions.interaction_queue.append(
                _make_interaction(agent_id=f"q-{i}")
            )

        agent = AgentState(
            agent_id="overflow",
            role="intake",
            subagent_dir="/tmp/test",
        )

        with pytest.raises(ToolError) as exc_info:
            await enqueue_interaction(agent, app_state, "ask", {"questions": []})

        err = json.loads(str(exc_info.value))
        assert err["error"] == "interaction_queue_full"

    @pytest.mark.anyio
    async def test_8th_request_succeeds(self):
        from koan.state import AgentState
        from koan.web.interactions import enqueue_interaction

        app_state = AppState()
        app_state.interactions.active_interaction = _make_interaction(agent_id="other")

        for i in range(7):
            app_state.interactions.interaction_queue.append(
                _make_interaction(agent_id=f"q-{i}")
            )

        agent = AgentState(
            agent_id="ok",
            role="intake",
            subagent_dir="/tmp/test",
        )

        future = await enqueue_interaction(agent, app_state, "ask", {"questions": []})

        assert not future.done()
        assert len(app_state.interactions.interaction_queue) == 8


# -- TestStaleSubmit ----------------------------------------------------------

class TestStaleSubmit:
    @pytest.mark.anyio
    async def test_answer_with_no_active_interaction_returns_409(self):
        from starlette.testclient import TestClient

        from koan.state import AppState
        from koan.web.app import create_app

        app_state = AppState()
        app = create_app(app_state)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/answer", json={"answers": []})
        assert resp.status_code == 409
        assert resp.json()["error"] == "stale_interaction"

    @pytest.mark.anyio
    async def test_artifact_comment_route_exists_and_validates(self):
        """POST /api/artifact-comment route exists (M5 replacement for /api/artifact-review).
        Returns 422 when path or comment is missing."""
        from starlette.testclient import TestClient

        from koan.state import AppState
        from koan.web.app import create_app

        app_state = AppState()
        app = create_app(app_state)
        client = TestClient(app, raise_server_exceptions=False)
        # Missing path -> 422
        resp = client.post("/api/artifact-comment", json={"comment": "hello"})
        assert resp.status_code == 422
        assert resp.json()["error"] == "missing_path"
        # Missing comment -> 422
        resp2 = client.post("/api/artifact-comment", json={"path": "plan.md"})
        assert resp2.status_code == 422
        assert resp2.json()["error"] == "missing_comment"


# -- TestFIFOActivation -------------------------------------------------------

class TestFIFOActivation:
    @pytest.mark.anyio
    async def test_fifo_order_preserved(self):
        from koan.web.interactions import activate_next_interaction

        app_state = AppState()

        a = _make_interaction(agent_id="A")
        b = _make_interaction(agent_id="B")
        c = _make_interaction(agent_id="C")

        app_state.interactions.active_interaction = _make_interaction(agent_id="initial")
        app_state.interactions.interaction_queue.extend([a, b, c])

        # Resolve initial -> A becomes active
        activate_next_interaction(app_state)
        assert app_state.interactions.active_interaction is a

        # Resolve A -> B becomes active
        activate_next_interaction(app_state)
        assert app_state.interactions.active_interaction is b

        # Resolve B -> C becomes active
        activate_next_interaction(app_state)
        assert app_state.interactions.active_interaction is c

        # Resolve C -> None
        activate_next_interaction(app_state)
        assert app_state.interactions.active_interaction is None


# -- TestCancellationOnExit ---------------------------------------------------

class TestCancellationOnExit:
    @pytest.mark.anyio
    async def test_cancel_active_interaction_on_agent_exit(self):
        from koan.subagent import _cancel_pending_interactions

        app_state = AppState()
        interaction = _make_interaction(agent_id="agent-1")
        app_state.interactions.active_interaction = interaction

        _cancel_pending_interactions("agent-1", app_state)

        assert interaction.future.done()
        assert interaction.future.result()["error"] == "agent_exited"
        assert app_state.interactions.active_interaction is None

    @pytest.mark.anyio
    async def test_cancel_queued_interactions_on_agent_exit(self):
        from koan.subagent import _cancel_pending_interactions

        app_state = AppState()
        mine_1 = _make_interaction(agent_id="agent-1")
        mine_2 = _make_interaction(agent_id="agent-1")
        other = _make_interaction(agent_id="agent-2")
        app_state.interactions.interaction_queue.extend([mine_1, other, mine_2])

        _cancel_pending_interactions("agent-1", app_state)

        assert mine_1.future.done()
        assert mine_1.future.result()["error"] == "agent_exited"
        assert mine_2.future.done()
        assert mine_2.future.result()["error"] == "agent_exited"

        assert not other.future.done()
        assert len(app_state.interactions.interaction_queue) == 1
        assert app_state.interactions.interaction_queue[0] is other

    @pytest.mark.anyio
    async def test_next_queued_activated_after_cancel(self):
        from koan.subagent import _cancel_pending_interactions

        app_state = AppState()
        active_a = _make_interaction(agent_id="agent-A")
        queued_b = _make_interaction(agent_id="agent-B")

        app_state.interactions.active_interaction = active_a
        app_state.interactions.interaction_queue.append(queued_b)

        _cancel_pending_interactions("agent-A", app_state)

        assert active_a.future.done()
        assert app_state.interactions.active_interaction is queued_b

    @pytest.mark.anyio
    async def test_yield_future_cleared_on_exit(self):
        """_cancel_pending_interactions clears yield_future."""
        from koan.subagent import _cancel_pending_interactions

        app_state = AppState()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        app_state.interactions.yield_future = future

        _cancel_pending_interactions("agent-1", app_state)

        assert future.done()
        assert app_state.interactions.yield_future is None
