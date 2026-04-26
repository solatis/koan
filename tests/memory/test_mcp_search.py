from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from koan.memory.retrieval.types import SearchResult
from koan.memory.types import MemoryEntry
from koan.state import AgentState, AppState


def _json(blocks):
    """Unwrap the first TextContent block and JSON-decode it."""
    return json.loads(blocks[0].text)


# ---------------------------------------------------------------------------
# Shared fake context
# ---------------------------------------------------------------------------

class _FakeContext:
    """Minimal fastmcp Context substitute for calling handler closures in tests."""
    def __init__(self, agent):
        self._agent = agent

    async def get_state(self, key):
        if key == "agent":
            return self._agent
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
def mem_env(tmp_path):
    """Build a minimal server environment for memory tests.

    Uses build_mcp_server so handler closures capture the real app_state.
    init_memory_services() is called so memory.retrieval_index is populated
    and tests can replace it with a mock before calling koan_search.
    """
    from koan.web.mcp_endpoint import build_mcp_server

    app_state = AppState()
    app_state.run.project_dir = str(tmp_path)
    # curation is a valid phase for all memory tools per permissions.py
    app_state.run.phase = "curation"

    agent = AgentState(
        agent_id="test-search-agent",
        role="orchestrator",
        subagent_dir=str(tmp_path / "sub"),
    )
    agent.run_dir = str(tmp_path)
    agent.step = 1
    app_state.agents[agent.agent_id] = agent
    app_state.init_memory_services()

    _, handlers = build_mcp_server(app_state)
    ctx = _FakeContext(agent)

    yield {
        "agent": agent,
        "app_state": app_state,
        "project_dir": tmp_path,
        "ctx": ctx,
        "handlers": handlers,
    }


@pytest.fixture
def search_env(mem_env, monkeypatch):
    """Extend mem_env with a mock retrieval index.

    Sets app_state.memory.retrieval_index directly (no module-global monkeyatch)
    and patches the module-level retrieval_search function (still module-level
    even though the index is now on AppState).
    """
    from koan.web import mcp_endpoint

    fixed_results = [_make_result(1), _make_result(2)]

    mock_index = MagicMock()
    mock_search = AsyncMock(return_value=fixed_results)

    # Replace the index on app_state directly -- no module-global to patch
    mem_env["app_state"].memory.retrieval_index = mock_index
    # retrieval_search is still a module-level import, so monkeypatch still works
    monkeypatch.setattr(mcp_endpoint, "retrieval_search", mock_search)

    yield {**mem_env, "mock_index": mock_index, "mock_search": mock_search, "fixed_results": fixed_results}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKoanSearch:
    @pytest.mark.anyio
    async def test_search_returns_json_with_results(self, search_env):
        raw = await search_env["handlers"].koan_search(search_env["ctx"], query="test")
        result = _json(raw)
        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["entry_id"] == 1

    @pytest.mark.anyio
    async def test_search_type_filter_forwarded(self, search_env):
        await search_env["handlers"].koan_search(search_env["ctx"], query="x", type="procedure")
        mock_search = search_env["mock_search"]
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("type_filter") == "procedure"

    @pytest.mark.anyio
    async def test_search_invalid_type_raises(self, search_env):
        with pytest.raises(ToolError) as exc:
            await search_env["handlers"].koan_search(search_env["ctx"], query="x", type="nonsense")
        body = json.loads(str(exc.value))
        assert body["error"] == "invalid_type"

    @pytest.mark.anyio
    async def test_search_api_error_raises_tool_error(self, mem_env, monkeypatch):
        from koan.web import mcp_endpoint

        mock_index = MagicMock()
        # Set mock index directly on app_state
        mem_env["app_state"].memory.retrieval_index = mock_index
        monkeypatch.setattr(
            mcp_endpoint, "retrieval_search",
            AsyncMock(side_effect=RuntimeError("API key missing"))
        )
        with pytest.raises(ToolError) as exc:
            await mem_env["handlers"].koan_search(mem_env["ctx"], query="x")
        body = json.loads(str(exc.value))
        assert body["error"] == "search_failed"

    @pytest.mark.anyio
    async def test_search_permission_denied_without_agent(self, search_env):
        # A FakeContext that returns None for agent triggers permission_denied
        no_agent_ctx = _FakeContext(None)
        with pytest.raises(ToolError) as exc:
            await search_env["handlers"].koan_search(no_agent_ctx, query="x")
        body = json.loads(str(exc.value))
        assert body["error"] == "permission_denied"
