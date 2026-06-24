# Integration tests for the artifact execute lifecycle.
#
# M5 removes the bundled-execute-handoff from apply_set_phase. This file
# now covers:
#   (a) execute_entry fold is a no-op (started-marker only).
#   (b) execute_completion fold is a no-op (M5: ArtifactInfo has no
#       lifecycle fields; the case is kept to keep the event recognized).
#   (c) An invalid phase transition returns the invalid_transition envelope.
#
# Removed in M5:
#   - apply_set_phase("execute", plan_file=X) handoff tests (bundled spawn removed)
#   - fold tests for executed/exec_outcome (fields dropped from ArtifactInfo)
#   - execute_not_found/execute_not_plan/already_executed envelope tests
#   - execute_requires_plan_file envelope test
#
# The subagent spawner is stubbed; no real LLM call is made.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from koan.phases import PhaseContext
from koan.projections import (
    ArtifactInfo,
    Projection,
    Run,
    RunConfig,
    VersionedEvent,
    fold,
)
from koan.state import AgentState, AppState
from koan.tools.koan_tools import ToolDeps, apply_set_phase


# -- Helpers ------------------------------------------------------------------


def _make_run(artifacts: dict[str, ArtifactInfo] | None = None) -> Run:
    """Build a minimal Run with an optional artifact dict."""
    return Run(
        config=RunConfig(active_preset="default"),
        artifacts=artifacts or {},
    )


def _make_deps(tmp_path: Path, phase: str = "plan") -> tuple[ToolDeps, AppState]:
    """Build a minimal ToolDeps + AppState for lifecycle tests."""
    from koan.lib.workflows import PLAN_WORKFLOW

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.project_dir = str(tmp_path)
    app_state.run.phase = phase
    app_state.run.workflow = PLAN_WORKFLOW  # type: ignore[assignment]

    agent = AgentState(
        agent_id="orch",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir=str(tmp_path),
        is_primary=True,
        phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
    )
    from koan.phases import execute as execute_phase
    agent.phase_module = execute_phase
    app_state.agents["orch"] = agent

    # Inject a run_started event so projection.run is not None.
    app_state.projection_store.push_event("run_started", {"active_preset": "default"})

    return ToolDeps(app_state=app_state, agent=agent), app_state


# -- Tests: fold correctness --------------------------------------------------


def test_fold_execute_entry_no_op_when_run_is_none() -> None:
    """execute_entry must be a no-op when projection.run is None."""
    proj = Projection()  # run=None
    event = VersionedEvent(
        version=1,
        event_type="execute_entry",
        timestamp="2026-01-01T00:00:00+00:00",
        agent_id=None,
        payload={"plan_file": "plan.md"},
    )
    result = fold(proj, event)
    assert result.run is None


def test_fold_execute_completion_no_op() -> None:
    """M5: execute_completion is a no-op fold -- ArtifactInfo carries no lifecycle fields."""
    proj = Projection(run=_make_run({"plan.md": ArtifactInfo(path="plan.md")}))
    event = VersionedEvent(
        version=2,
        event_type="execute_completion",
        timestamp="2026-01-01T00:00:01+00:00",
        agent_id=None,
        payload={"plan_file": "plan.md", "outcome": "clean"},
    )
    result = fold(proj, event)
    assert result.run is not None
    # The artifact still exists; no lifecycle mutation occurred.
    info = result.run.artifacts.get("plan.md")
    assert info is not None
    assert info.path == "plan.md"
    # ArtifactInfo has no executed/exec_outcome fields.
    assert not hasattr(info, "executed")
    assert not hasattr(info, "exec_outcome")


def test_fold_execute_completion_no_op_when_run_is_none() -> None:
    """execute_completion must be a no-op when projection.run is None."""
    proj = Projection()  # run=None
    event = VersionedEvent(
        version=2,
        event_type="execute_completion",
        timestamp="2026-01-01T00:00:01+00:00",
        agent_id=None,
        payload={"plan_file": "plan.md", "outcome": "non_conforming"},
    )
    result = fold(proj, event)
    assert result.run is None


# -- Tests: apply_set_phase transition validation -----------------------------


@pytest.mark.anyio
async def test_bare_execute_transition_succeeds(tmp_path: Path) -> None:
    """M5: bare set_phase('execute') with no plan_file now succeeds (pure routing)."""
    deps, _ = _make_deps(tmp_path)

    result = await apply_set_phase(deps, "execute")
    # Pure routing returns a confirmation string -- not an error envelope.
    assert "execute" in result
    assert '"ok": false' not in result


@pytest.mark.anyio
async def test_invalid_transition_returns_envelope(tmp_path: Path) -> None:
    """set_phase with a phase not in the current workflow returns the invalid_transition envelope."""
    import json

    deps, _ = _make_deps(tmp_path)
    # "core-flows" is not in PLAN_WORKFLOW's available phases.
    result = await apply_set_phase(deps, "core-flows")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "invalid_transition"
