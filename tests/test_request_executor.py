# Integration-leaning tests for request_executor_core (M4, living-documents initiative).
#
# Covers:
#   (a) plan-based run: plan is first in the artifact listing, read-this-plan
#       directive is prepended to instructions, events are emitted, deviation
#       report is returned.
#   (b) free-form run (no plan_file): standing listing only, no read-this-plan
#       directive, executor receives free-form instructions directly.
#   (c) neither plan_file nor instructions: returns execute_requires_instructions
#       envelope without spawning.
#   (d) re-execution: same plan submitted twice; both succeed (no
#       already_executed block).
#
# spawn_subagent is stubbed via monkeypatching so no real LLM call is made.

from __future__ import annotations

import json
from pathlib import Path

import pytest

import koan.subagent as subagent_mod
from koan.phases import PhaseContext
from koan.state import AgentState, AppState
from koan.subagent import SubagentResult
from koan.tools.koan_tools import request_executor_core, ToolDeps


# -- Helpers ------------------------------------------------------------------


def _make_deps(tmp_path: Path, phase: str = "execute") -> tuple[ToolDeps, AppState]:
    """Build a minimal ToolDeps + AppState for request_executor_core tests.

    Mirrors the _make_deps helper in test_artifact_write_review.py.
    """
    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.project_dir = str(tmp_path)
    app_state.run.phase = phase  # type: ignore[assignment]
    app_state.run.workflow = None

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


def _write_plan(tmp_path: Path, name: str = "plan.md") -> None:
    """Write a minimal plan artifact to tmp_path."""
    (tmp_path / name).write_text(f"# Plan\n\nContent of {name}.\n")


def _write_context(tmp_path: Path) -> None:
    """Write standing context files to tmp_path."""
    (tmp_path / "brief.md").write_text("# Brief\n\nBrief content.\n")
    (tmp_path / "milestones.md").write_text("# Milestones\n\nMilestone content.\n")


def _collected_events(app_state: AppState) -> list[tuple[str, dict]]:
    """Extract (event_type, payload) pairs from the projection event log."""
    return [
        (ev.event_type, ev.payload)
        for ev in app_state.projection_store.events
    ]


# -- Tests: plan-based run ----------------------------------------------------


@pytest.mark.anyio
async def test_plan_run_prepends_directive_and_includes_plan_first(
    tmp_path: Path, monkeypatch
) -> None:
    """Plan-based run: plan is first in artifact listing; read-this-plan directive prepended."""
    _write_plan(tmp_path, "plan.md")
    _write_context(tmp_path)

    captured: list[dict] = []

    async def fake_spawn(task: dict, app_state: AppState) -> SubagentResult:
        captured.append(task)
        return SubagentResult(exit_code=0, final_response="No deviations.")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fake_spawn)

    deps, _ = _make_deps(tmp_path)
    result = await request_executor_core(deps, plan_file="plan.md", instructions="Also run linting.")

    assert result == "No deviations."
    assert len(captured) == 1
    task = captured[0]
    assert task["role"] == "executor"

    # plan.md must be first in the artifact listing.
    assert task["artifacts"][0] == "plan.md"

    # The read-this-plan directive must be prepended to the caller's instructions.
    assert task["instructions"].startswith("Read and implement the plan in `plan.md`.")
    assert "Also run linting." in task["instructions"]


@pytest.mark.anyio
async def test_plan_run_emits_entry_and_completion_events(
    tmp_path: Path, monkeypatch
) -> None:
    """Plan-based run emits execute_entry and execute_completion events."""
    _write_plan(tmp_path)

    async def fake_spawn(task: dict, app_state: AppState) -> SubagentResult:
        return SubagentResult(exit_code=0, final_response="Clean.")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fake_spawn)

    deps, app_state = _make_deps(tmp_path)
    await request_executor_core(deps, plan_file="plan.md")

    event_types = [et for et, _ in _collected_events(app_state)]
    assert "execute_entry" in event_types
    assert "execute_completion" in event_types

    # entry must come before completion.
    entry_idx = event_types.index("execute_entry")
    completion_idx = event_types.index("execute_completion")
    assert entry_idx < completion_idx


# -- Tests: free-form run (no plan_file) --------------------------------------


@pytest.mark.anyio
async def test_free_form_run_omits_read_this_plan_directive(
    tmp_path: Path, monkeypatch
) -> None:
    """Free-form run (no plan_file): no read-this-plan directive; instructions passed as-is."""
    _write_context(tmp_path)

    captured: list[dict] = []

    async def fake_spawn(task: dict, app_state: AppState) -> SubagentResult:
        captured.append(task)
        return SubagentResult(exit_code=0, final_response="Addressed.")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fake_spawn)

    deps, _ = _make_deps(tmp_path)
    result = await request_executor_core(deps, plan_file=None, instructions="Fix the flaky test.")

    assert result == "Addressed."
    task = captured[0]

    # No plan in the listing.
    assert all("plan" not in a for a in task["artifacts"])

    # Instructions are the free-form text only -- no prepended directive.
    assert task["instructions"] == "Fix the flaky test."
    assert "Read and implement the plan" not in task["instructions"]


# -- Tests: validation rejection ----------------------------------------------


@pytest.mark.anyio
async def test_neither_plan_nor_instructions_returns_envelope(
    tmp_path: Path,
) -> None:
    """Neither plan_file nor instructions returns execute_requires_instructions envelope."""
    deps, _ = _make_deps(tmp_path)
    result = await request_executor_core(deps, plan_file=None, instructions=None)

    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "execute_requires_instructions"


# -- Tests: re-execution ------------------------------------------------------


@pytest.mark.anyio
async def test_same_plan_re_executed_twice_both_succeed(
    tmp_path: Path, monkeypatch
) -> None:
    """Re-running the same plan twice succeeds both times (no already_executed block)."""
    _write_plan(tmp_path, "plan.md")

    async def fake_spawn(task: dict, app_state: AppState) -> SubagentResult:
        return SubagentResult(exit_code=0, final_response="Done.")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fake_spawn)

    deps, _ = _make_deps(tmp_path)

    for attempt in range(2):
        result = await request_executor_core(deps, plan_file="plan.md")
        assert result == "Done.", f"Attempt {attempt + 1} was blocked or failed"


# -- Tests: call-time phase gate ----------------------------------------------


@pytest.mark.anyio
async def test_wrong_phase_returns_tool_unavailable_envelope(
    tmp_path: Path,
) -> None:
    """request_executor_core in a non-execute phase returns a recoverable phase-gate envelope.

    With phase="plan" the call-time gate fires before any validation or spawn;
    the returned JSON envelope must have ok=False and
    error.reason == "tool_unavailable_in_phase". No executor is spawned.
    """
    deps, _ = _make_deps(tmp_path, phase="plan")
    result = await request_executor_core(deps, plan_file="plan.md", instructions="fix it")

    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "tool_unavailable_in_phase"
    assert "koan_request_executor" in payload["error"]["message"]
