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
        assert body["answer"] == "The memory system uses VoyageAI embeddings."
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

    @pytest.mark.anyio
    async def test_on_trace_text_emits_reflect_delta(self, mem_env, monkeypatch):
        """reflect_core passes _on_trace to run_reflect_agent; text deltas produce
        reflect_delta projection events targeted at the agent. Other kinds do not.
        """
        import koan.memory.retrieval as retrieval_mod
        from koan.memory.retrieval.reflect import ReflectTraceEvent

        captured_on_trace = []

        async def _fake_run_reflect(index, question, context=None, *, on_trace=None, max_iterations=10):
            captured_on_trace.append(on_trace)
            return ReflectResult(
                answer="The answer.",
                citations=[],
                iterations=1,
            )

        monkeypatch.setattr(retrieval_mod, "run_reflect_agent", _fake_run_reflect)

        agent = mem_env["agent"]
        app_state = mem_env["app_state"]

        from koan.events import build_agent_spawned
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
        app_state.projection_store.push_event(
            "tool_request",
            {"call_id": "test-call-1", "tool": "koan_reflect"},
            agent_id=agent.agent_id,
        )

        from koan.tools.koan_tools import reflect_core
        await reflect_core(mem_env["deps"], question="test?")

        assert len(captured_on_trace) == 1
        on_trace = captured_on_trace[0]
        assert on_trace is not None

        events_before = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]

        on_trace(ReflectTraceEvent(iteration=1, kind="text", delta="Hello "))
        events_text = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_text) == len(events_before) + 1
        assert events_text[-1].payload == {"delta": "Hello "}
        assert events_text[-1].agent_id == agent.agent_id

        on_trace(ReflectTraceEvent(iteration=1, kind="search", query="memory"))
        events_search = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_search) == len(events_text), "search kind must not produce reflect_delta"

        on_trace(ReflectTraceEvent(iteration=1, kind="thinking", delta="thinking..."))
        events_thinking = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_thinking) == len(events_search), "thinking kind must not produce reflect_delta"

        on_trace(ReflectTraceEvent(iteration=1, kind="text", delta=""))
        events_empty = [e for e in app_state.projection_store.events if e.event_type == "reflect_delta"]
        assert len(events_empty) == len(events_thinking), "empty text delta must not produce reflect_delta"
