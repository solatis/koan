# MCP handler tests for koan_reflect.
# run_reflect_agent is monkeypatched so no LLM calls are made.

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError

from koan.memory.retrieval.reflect import Citation, IterationCapExceeded, ReflectResult
from koan.state import AgentState, AppState


def _json(blocks):
    """Unwrap the first TextContent block and JSON-decode it."""
    return json.loads(blocks[0].text)


# ---------------------------------------------------------------------------
# Shared fake context (same pattern as test_mcp_search.py)
# ---------------------------------------------------------------------------

class _FakeContext:
    def __init__(self, agent):
        self._agent = agent

    async def get_state(self, key):
        if key == "agent":
            return self._agent
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_env(tmp_path):
    from koan.web.mcp_endpoint import build_mcp_server

    app_state = AppState()
    app_state.run.project_dir = str(tmp_path)
    app_state.run.phase = "curation"

    agent = AgentState(
        agent_id="test-reflect-agent",
        role="orchestrator",
        subagent_dir=str(tmp_path / "sub"),
    )
    agent.run_dir = str(tmp_path)
    agent.step = 2
    app_state.agents[agent.agent_id] = agent
    app_state.init_memory_services()

    _, handlers = build_mcp_server(app_state)
    ctx = _FakeContext(agent)

    yield {
        "agent": agent,
        "app_state": app_state,
        "ctx": ctx,
        "handlers": handlers,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKoanReflect:
    @pytest.mark.anyio
    async def test_happy_path_returns_expected_shape(self, mem_env, monkeypatch):
        from koan.web import mcp_endpoint

        fake_result = ReflectResult(
            answer="The memory system uses VoyageAI embeddings.",
            citations=[Citation(id=1, title="Memory architecture",
                               type="decision", modified_ms=1704067200000)],
            iterations=2,
        )
        monkeypatch.setattr(
            mcp_endpoint, "run_reflect_agent",
            AsyncMock(return_value=fake_result),
        )

        raw = await mem_env["handlers"].koan_reflect(
            mem_env["ctx"], question="How does memory work?"
        )
        body = _json(raw)
        assert body["answer"] == "The memory system uses VoyageAI embeddings."
        assert body["citations"] == [{
            "id": 1,
            "title": "Memory architecture",
            "type": "decision",
            "modifiedMs": 1704067200000,
        }]
        assert body["iterations"] == 2

    @pytest.mark.anyio
    async def test_iteration_cap_raises_tool_error(self, mem_env, monkeypatch):
        from koan.web import mcp_endpoint

        monkeypatch.setattr(
            mcp_endpoint, "run_reflect_agent",
            AsyncMock(side_effect=IterationCapExceeded(iterations=10)),
        )

        with pytest.raises(ToolError) as exc:
            await mem_env["handlers"].koan_reflect(
                mem_env["ctx"], question="too hard"
            )
        body = json.loads(str(exc.value))
        assert body["error"] == "iteration_cap_exceeded"
        assert body["iterations"] == 10

    @pytest.mark.anyio
    async def test_runtime_error_raises_tool_error(self, mem_env, monkeypatch):
        from koan.web import mcp_endpoint

        monkeypatch.setattr(
            mcp_endpoint, "run_reflect_agent",
            AsyncMock(side_effect=RuntimeError("no api key")),
        )

        with pytest.raises(ToolError) as exc:
            await mem_env["handlers"].koan_reflect(
                mem_env["ctx"], question="anything"
            )
        body = json.loads(str(exc.value))
        assert body["error"] == "reflect_failed"
        assert "no api key" in body["message"]

    @pytest.mark.anyio
    async def test_permission_denied_without_agent(self, mem_env, monkeypatch):
        from koan.web import mcp_endpoint

        monkeypatch.setattr(
            mcp_endpoint, "run_reflect_agent",
            AsyncMock(return_value=ReflectResult("x", [], 1)),
        )

        no_agent_ctx = _FakeContext(None)
        with pytest.raises(ToolError) as exc:
            await mem_env["handlers"].koan_reflect(no_agent_ctx, question="x")
        body = json.loads(str(exc.value))
        assert body["error"] == "permission_denied"

    @pytest.mark.anyio
    async def test_on_trace_text_emits_reflect_delta(self, mem_env, monkeypatch):
        """koan_reflect passes _on_trace to run_reflect_agent; text deltas produce
        reflect_delta projection events targeted at the agent. Other kinds do not.
        """
        from koan.web import mcp_endpoint
        from koan.memory.retrieval.reflect import ReflectTraceEvent

        captured_on_trace = []

        async def _fake_run_reflect(index, question, context=None, *, on_trace=None, max_iterations=10):
            # Capture the callback so we can call it in the test
            captured_on_trace.append(on_trace)
            return ReflectResult(
                answer="The answer.",
                citations=[],
                iterations=1,
            )

        monkeypatch.setattr(mcp_endpoint, "run_reflect_agent", _fake_run_reflect)

        agent = mem_env["agent"]
        app_state = mem_env["app_state"]

        # Prime the projection with agent_spawned so fold can find the agent
        from koan.events import build_agent_spawned
        from koan.state import AgentState
        app_state.projection_store.push_event(
            "run_started",
            {"profile": "balanced", "installations": {}, "scout_concurrency": 8},
        )
        app_state.projection_store.push_event(
            "agent_spawned",
            {
                "agent_id": agent.agent_id,
                "role": agent.role,
                "label": "",
                "model": None,
                "is_primary": True,
                "started_at_ms": 0,
            },
            agent_id=agent.agent_id,
        )
        # Push a tool_request so there is an in-flight ToolKoanEntry for the agent
        app_state.projection_store.push_event(
            "tool_request",
            {"call_id": "test-call-1", "tool": "koan_reflect"},
            agent_id=agent.agent_id,
        )

        await mem_env["handlers"].koan_reflect(mem_env["ctx"], question="test?")

        # The fake captured the on_trace callback
        assert len(captured_on_trace) == 1
        on_trace = captured_on_trace[0]
        assert on_trace is not None

        # Count reflect_delta events before calling on_trace
        events_before = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]

        # Call with kind="text" -- should produce reflect_delta
        on_trace(ReflectTraceEvent(iteration=1, kind="text", delta="Hello "))
        events_text = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_text) == len(events_before) + 1
        assert events_text[-1].payload == {"delta": "Hello "}
        assert events_text[-1].agent_id == agent.agent_id

        # Call with kind="search" -- should NOT produce reflect_delta
        on_trace(ReflectTraceEvent(iteration=1, kind="search", query="memory"))
        events_search = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_search) == len(events_text), "search kind must not produce reflect_delta"

        # Call with kind="thinking" -- should NOT produce reflect_delta
        on_trace(ReflectTraceEvent(iteration=1, kind="thinking", delta="thinking..."))
        events_thinking = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_thinking) == len(events_search), "thinking kind must not produce reflect_delta"

        # Call with empty delta text -- should NOT produce reflect_delta
        on_trace(ReflectTraceEvent(iteration=1, kind="text", delta=""))
        events_empty = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_empty) == len(events_thinking), "empty text delta must not produce reflect_delta"
