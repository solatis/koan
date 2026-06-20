# Tests for M6 in-process subagent spawning (koan/tools/koan_tools.py).
#
# spawn_subagent itself is mocked here -- these tests pin the cores' contract:
# the request_scouts payload shape, scout-failure dropping, crash containment
# (a subagent exception becomes a failed result, not an escaped exception),
# the _active_tasks registry lifecycle, and that koan_request_scouts is registered.
#
# koan_request_executor was removed in M4: execution rides on
# koan_set_phase("execute", plan_file=...). The request_executor_core tests
# are replaced by the artifact lifecycle tests in test_artifact_lifecycle.py.

from __future__ import annotations

import pytest

import koan.subagent as subagent_mod
from koan.phases import PhaseContext
from koan.state import AgentState, AppState
from koan.subagent import SubagentResult
from koan.tools.koan_tools import (
    ToolDeps,
    build_koan_toolset,
    request_scouts_core,
    spawn_tracked_subagent,
)


def _deps(tmp_path) -> tuple[ToolDeps, AppState]:
    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.project_dir = str(tmp_path)
    agent = AgentState(
        agent_id="orch",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir=str(tmp_path),
        is_primary=True,
        phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
    )
    app_state.agents["orch"] = agent
    return ToolDeps(app_state=app_state, agent=agent), app_state


@pytest.mark.anyio
async def test_spawn_tracked_contains_crash(tmp_path, monkeypatch):
    async def boom(task, app_state):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(subagent_mod, "spawn_subagent", boom)

    _, app_state = _deps(tmp_path)
    result = await spawn_tracked_subagent(app_state, {"subagent_dir": "x"})
    assert result.exit_code == 1
    assert "kaboom" in (result.error or "")
    assert app_state._active_tasks == {}  # registry cleaned up even on crash


@pytest.mark.anyio
async def test_scouts_core_collects_and_drops_failures(tmp_path, monkeypatch):
    async def fake_spawn(task, app_state):
        if task["label"] == "q2":
            return SubagentResult(exit_code=1, error="fail")
        return SubagentResult(exit_code=0, final_response=f"finding-{task['label']}")
    monkeypatch.setattr(subagent_mod, "spawn_subagent", fake_spawn)

    deps, app_state = _deps(tmp_path)
    questions = [
        {"id": "q1", "prompt": "a"},
        {"id": "q2", "prompt": "b"},
        {"id": "q3", "prompt": "c"},
    ]
    out = await request_scouts_core(deps, questions)
    assert "finding-q1" in out
    assert "finding-q3" in out
    assert "finding-q2" not in out  # the failed scout contributes no finding
    assert app_state._active_tasks == {}


@pytest.mark.anyio
async def test_scouts_core_empty_questions(tmp_path):
    deps, _ = _deps(tmp_path)
    assert await request_scouts_core(deps, []) == "No scouts requested."
    assert await request_scouts_core(deps, None) == "No scouts requested."


@pytest.mark.anyio
async def test_scouts_core_no_findings(tmp_path, monkeypatch):
    async def all_fail(task, app_state):
        return SubagentResult(exit_code=1, error="x")
    monkeypatch.setattr(subagent_mod, "spawn_subagent", all_fail)
    deps, _ = _deps(tmp_path)
    out = await request_scouts_core(deps, [{"id": "q1", "prompt": "a"}])
    assert out == "No findings returned."


def test_scout_tool_registered_executor_tool_absent():
    """koan_request_scouts is registered; koan_request_executor was removed in M4.

    Execution now rides on koan_set_phase("execute", plan_file=...) -- no
    separate executor tool exists.
    """
    names = set(build_koan_toolset().tools.keys())
    assert "koan_request_scouts" in names
    assert "koan_request_executor" not in names, (
        "koan_request_executor must not be registered after M4 removal"
    )
