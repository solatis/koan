# Tests for reflect_core.
#
# Calls the in-process core directly via ToolDeps. run_reflect_agent is
# monkeypatched at koan.memory.retrieval (the origin module).

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from koan.memory.retrieval.reflect import Citation, IterationCapExceeded, ReflectResult
from koan.state import AgentState, AppState


def _json(result: str) -> dict:
    """JSON-decode a core result string."""
    return json.loads(result)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_env(tmp_path):
    """Build a minimal in-process environment for reflect tests."""
    from koan.tools.koan_tools import ToolDeps

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

    # reflect_core resolves embed from memory_models.embedding and standard
    # from frozen_models["standard"]; both must be non-None or it raises.
    from koan.types import ModelSpec
    from koan.memory.bindings import MemoryModels
    app_state.run.memory_models = MemoryModels(embedding=ModelSpec(
        provider="voyage", model="voyage-4-large", thinking="disabled",
        connection_id="v", embedding_dim=1024, api_key="k"))
    app_state.run.frozen_models = {"standard": ModelSpec(
        provider="google", model="gemini-flash-latest", thinking="disabled",
        connection_id="g", api_key="k")}

    deps = ToolDeps(app_state=app_state, agent=agent)

    yield {
        "agent": agent,
        "app_state": app_state,
        "deps": deps,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKoanReflect:
    @pytest.mark.anyio
    async def test_happy_path_returns_expected_shape(self, mem_env, monkeypatch):
        import koan.memory.retrieval as retrieval_mod

        fake_result = ReflectResult(
            answer="The memory system uses VoyageAI embeddings.",
            citations=[Citation(id=1, title="Memory architecture",
                               type="decision", modified_ms=1704067200000)],
            iterations=2,
        )
        monkeypatch.setattr(
            retrieval_mod, "run_reflect_agent",
            AsyncMock(return_value=fake_result),
        )

        from koan.tools.koan_tools import reflect_core
        body = _json(await reflect_core(mem_env["deps"], question="How does memory work?"))
        # Answer is not in the tool return JSON -- it arrives via
        # streamed reflect_inline_trace text deltas in the projection fold.
        assert "answer" not in body
        assert body["citations"] == [{
            "id": 1,
            "title": "Memory architecture",
            "type": "decision",
            "modifiedMs": 1704067200000,
        }]
        assert body["iterations"] == 2

    @pytest.mark.anyio
    async def test_iteration_cap_raises(self, mem_env, monkeypatch):
        import koan.memory.retrieval as retrieval_mod

        monkeypatch.setattr(
            retrieval_mod, "run_reflect_agent",
            AsyncMock(side_effect=IterationCapExceeded(iterations=10)),
        )

        from koan.memory.retrieval import IterationCapExceeded as ICE
        from koan.tools.koan_tools import reflect_core
        # Cores re-raise IterationCapExceeded (not ToolError).
        with pytest.raises(ICE) as exc:
            await reflect_core(mem_env["deps"], question="too hard")
        assert exc.value.iterations == 10

    @pytest.mark.anyio
    async def test_runtime_error_raises(self, mem_env, monkeypatch):
        import koan.memory.retrieval as retrieval_mod

        monkeypatch.setattr(
            retrieval_mod, "run_reflect_agent",
            AsyncMock(side_effect=RuntimeError("no api key")),
        )

        from koan.tools.koan_tools import reflect_core
        with pytest.raises(RuntimeError) as exc:
            await reflect_core(mem_env["deps"], question="anything")
        assert "no api key" in str(exc.value)

