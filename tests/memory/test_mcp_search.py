# Tests for search_core.
#
# Calls the in-process core directly via ToolDeps. run_reflect_agent and
# retrieval_search are monkeypatched at the origin module
# (koan.memory.retrieval) since search_core imports from there directly.

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koan.memory.bindings import MemoryModels
from koan.memory.retrieval.types import SearchResult
from koan.memory.types import MemoryEntry
from koan.state import AgentState, AppState
from koan.types import ModelSpec
from koan.models.offering import resolve_offering


def _fake_embed() -> ModelSpec:
    return ModelSpec(offering=resolve_offering("voyage", "voyage-4-large"), thinking="disabled",
                     connection_id="v", embedding_dim=1024, api_key="k")


def _fake_models() -> MemoryModels:
    return MemoryModels(embedding=_fake_embed())


def _json(result: str) -> dict:
    """JSON-decode a core result string."""
    return json.loads(result)


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
    """Build a minimal in-process environment for memory tests.

    Builds ToolDeps directly; init_memory_services() is called so
    memory.retrieval_index is populated and tests can replace it with a mock.
    """
    from koan.tools.koan_tools import ToolDeps

    app_state = AppState()
    app_state.run.project_dir = str(tmp_path)
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
    # Provide fake memory models so search_core can resolve the embedding binding.
    app_state.run.memory_models = _fake_models()

    deps = ToolDeps(app_state=app_state, agent=agent)

    yield {
        "agent": agent,
        "app_state": app_state,
        "project_dir": tmp_path,
        "deps": deps,
    }


@pytest.fixture
def search_env(mem_env, monkeypatch):
    """Extend mem_env with a mock retrieval index.

    Patches koan.memory.retrieval.search (the origin module) since
    search_core imports from there directly. Tests that previously
    patched mcp_endpoint.retrieval_search now patch the origin.
    """
    import koan.memory.retrieval as retrieval_mod

    fixed_results = [_make_result(1), _make_result(2)]

    mock_index = MagicMock()
    mock_search = AsyncMock(return_value=fixed_results)

    mem_env["app_state"].memory.retrieval_index = mock_index
    monkeypatch.setattr(retrieval_mod, "search", mock_search)

    yield {**mem_env, "mock_index": mock_index, "mock_search": mock_search, "fixed_results": fixed_results}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKoanSearch:
    @pytest.mark.anyio
    async def test_search_returns_json_with_results(self, search_env):
        from koan.tools.koan_tools import search_core
        result = _json(await search_core(search_env["deps"], query="test"))
        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["entry_id"] == 1

    @pytest.mark.anyio
    async def test_search_type_filter_forwarded(self, search_env):
        from koan.tools.koan_tools import search_core
        await search_core(search_env["deps"], query="x", type="procedure")
        mock_search = search_env["mock_search"]
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("type_filter") == "procedure"

    @pytest.mark.anyio
    async def test_search_invalid_type_raises(self, search_env):
        from koan.tools.koan_tools import search_core
        # Cores raise ValueError for invalid types (not ToolError).
        with pytest.raises(ValueError) as exc:
            await search_core(search_env["deps"], query="x", type="nonsense")
        assert "invalid" in str(exc.value).lower() or "nonsense" in str(exc.value)

    @pytest.mark.anyio
    async def test_search_api_error_raises_runtime_error(self, mem_env, monkeypatch):
        import koan.memory.retrieval as retrieval_mod

        mock_index = MagicMock()
        mem_env["app_state"].memory.retrieval_index = mock_index
        monkeypatch.setattr(
            retrieval_mod, "search",
            AsyncMock(side_effect=RuntimeError("API key missing")),
        )
        from koan.tools.koan_tools import search_core
        # Cores re-raise RuntimeError (not ToolError).
        with pytest.raises(RuntimeError) as exc:
            await search_core(mem_env["deps"], query="x")
        assert "API key missing" in str(exc.value)
