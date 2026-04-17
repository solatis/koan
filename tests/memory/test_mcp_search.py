from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from koan.memory.retrieval.types import SearchResult
from koan.memory.types import MemoryEntry
from koan.state import AgentState, AppState
from koan.web import mcp_endpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unwrap(tool):
    for attr in ("fn", "func", "_fn", "_func", "__wrapped__", "callback"):
        candidate = getattr(tool, attr, None)
        if callable(candidate):
            return candidate
    if callable(tool):
        return tool
    raise RuntimeError(f"Cannot unwrap FastMCP tool: {tool!r}")


koan_search = _unwrap(mcp_endpoint.koan_search)


def _make_entry(n: int = 1, etype: str = "context") -> MemoryEntry:
    return MemoryEntry(
        title=f"Entry {n}",
        type=etype,
        body=f"Body of entry {n}.",
        created="2024-01-01",
        modified="2024-01-01",
    )


def _make_result(n: int = 1, etype: str = "context") -> SearchResult:
    return SearchResult(entry=_make_entry(n, etype), entry_id=n, score=0.9)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_env(tmp_path, monkeypatch):
    app_state = AppState()
    app_state.project_dir = str(tmp_path)
    app_state.phase = "curation"

    agent = AgentState(
        agent_id="test-search-agent",
        role="orchestrator",
        subagent_dir=str(tmp_path / "sub"),
    )
    agent.run_dir = str(tmp_path)
    agent.step = 1
    app_state.agents[agent.agent_id] = agent

    monkeypatch.setattr(mcp_endpoint, "_app_state", app_state)
    monkeypatch.setattr(mcp_endpoint, "_memory_store", None)
    token = mcp_endpoint._agent_ctx.set(agent)

    yield {"agent": agent, "app_state": app_state, "project_dir": tmp_path}

    mcp_endpoint._agent_ctx.reset(token)
    mcp_endpoint._reset_memory_store()


@pytest.fixture
def search_env(mem_env, monkeypatch):
    fixed_results = [_make_result(1), _make_result(2)]

    mock_index = MagicMock()
    mock_search = AsyncMock(return_value=fixed_results)

    monkeypatch.setattr(mcp_endpoint, "_retrieval_index", mock_index)
    monkeypatch.setattr(mcp_endpoint, "retrieval_search", mock_search)

    yield {**mem_env, "mock_index": mock_index, "mock_search": mock_search, "fixed_results": fixed_results}

    mcp_endpoint._reset_retrieval_index()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKoanSearch:
    @pytest.mark.anyio
    async def test_search_returns_json_with_results(self, search_env):
        raw = await koan_search(query="test")
        result = json.loads(raw)
        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["entry_id"] == 1

    @pytest.mark.anyio
    async def test_search_type_filter_forwarded(self, search_env):
        await koan_search(query="x", type="procedure")
        mock_search = search_env["mock_search"]
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("type_filter") == "procedure"

    @pytest.mark.anyio
    async def test_search_invalid_type_raises(self, search_env):
        with pytest.raises(ToolError) as exc:
            await koan_search(query="x", type="nonsense")
        body = json.loads(str(exc.value))
        assert body["error"] == "invalid_type"

    @pytest.mark.anyio
    async def test_search_api_error_raises_tool_error(self, mem_env, monkeypatch):
        mock_index = MagicMock()
        monkeypatch.setattr(mcp_endpoint, "_retrieval_index", mock_index)
        monkeypatch.setattr(
            mcp_endpoint, "retrieval_search",
            AsyncMock(side_effect=RuntimeError("API key missing"))
        )
        with pytest.raises(ToolError) as exc:
            await koan_search(query="x")
        body = json.loads(str(exc.value))
        assert body["error"] == "search_failed"
        mcp_endpoint._reset_retrieval_index()

    @pytest.mark.anyio
    async def test_search_permission_denied_without_agent(self, search_env):
        token = mcp_endpoint._agent_ctx.set(None)
        try:
            with pytest.raises(ToolError) as exc:
                await koan_search(query="x")
            body = json.loads(str(exc.value))
            assert body["error"] == "permission_denied"
        finally:
            mcp_endpoint._agent_ctx.reset(token)
