# MCP handler tests for koan_reflect.
# run_reflect_agent is monkeypatched so no LLM calls are made.

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError

from koan.memory.retrieval.reflect import Citation, IterationCapExceeded, ReflectResult
from koan.state import AgentState, AppState


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
            citations=[Citation(id=1, title="Memory architecture")],
            iterations=2,
        )
        monkeypatch.setattr(
            mcp_endpoint, "run_reflect_agent",
            AsyncMock(return_value=fake_result),
        )

        raw = await mem_env["handlers"].koan_reflect(
            mem_env["ctx"], question="How does memory work?"
        )
        body = json.loads(raw)
        assert body["answer"] == "The memory system uses VoyageAI embeddings."
        assert body["citations"] == [{"id": 1, "title": "Memory architecture"}]
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
