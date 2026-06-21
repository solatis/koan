# Integration tests for the M4 artifact freeze/execute lifecycle.
#
# Covers:
#   (a) apply_set_phase("execute", plan_file=X) on a valid plan emits
#       execute_entry then execute_completion, spawns the executor, returns
#       the stub's final_response, and leaves ArtifactInfo.frozen/.executed true.
#   (b) Invalid targets (execute_not_found, execute_not_plan, already_executed)
#       return the {"ok": false, "error": {...}} envelope with no side effects.
#   (c) Bare set_phase("execute") with no plan_file returns execute_requires_plan_file envelope.
#   (d) An invalid phase transition returns the invalid_transition envelope.
#   (e) artifact_edit_core returns a "frozen" envelope when editing a frozen plan artifact,
#       but succeeds on that plan's .review.md sidecar.
#   (f) The fold sets frozen/executed/exec_outcome correctly on both events.
#
# The subagent spawner is stubbed; no real LLM call is made.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import koan.subagent as subagent_mod
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
from koan.subagent import SubagentResult
from koan.tools.koan_tools import ToolDeps, apply_set_phase, artifact_edit_core


# -- Helpers ------------------------------------------------------------------


def _make_run(artifacts: dict[str, ArtifactInfo] | None = None) -> Run:
    """Build a minimal Run with an optional artifact dict."""
    return Run(
        config=RunConfig(active_preset="default"),
        artifacts=artifacts or {},
    )


def _make_deps(tmp_path: Path, phase: str = "execute") -> tuple[ToolDeps, AppState]:
    """Build a minimal ToolDeps + AppState for lifecycle tests.

    Creates a live PLAN_WORKFLOW-equivalent context: execute phase, no workflow
    object (so requires_discriminator=False and koan_set_phase can validate the
    transition -- tests that call apply_set_phase need a workflow set).
    """
    from koan.lib.workflows import PLAN_WORKFLOW

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.project_dir = str(tmp_path)
    app_state.run.phase = "plan-review"   # coming from plan-review -> execute
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


def _write_artifact(tmp_path: Path, name: str, content: str = "# Content\n") -> None:
    """Write a file into tmp_path and push artifact_created into the projection store."""
    (tmp_path / name).write_text(content, encoding="utf-8")


def _push_artifact_created(app_state: AppState, name: str, tmp_path: Path) -> None:
    """Push an artifact_created event so the projection knows the file exists."""
    import os
    p = tmp_path / name
    size = p.stat().st_size if p.exists() else 0
    mtime = int(os.stat(p).st_mtime * 1000) if p.exists() else 0
    app_state.projection_store.push_event(
        "artifact_created",
        {"path": name, "size": size, "modified_at": mtime},
    )


# -- Tests: fold correctness --------------------------------------------------


def test_fold_execute_entry_sets_frozen() -> None:
    """execute_entry event must set ArtifactInfo.frozen=True for the named plan."""
    proj = Projection(run=_make_run({"plan.md": ArtifactInfo(path="plan.md")}))
    event = VersionedEvent(
        version=1,
        event_type="execute_entry",
        timestamp="2026-01-01T00:00:00+00:00",
        agent_id=None,
        payload={"plan_file": "plan.md"},
    )
    result = fold(proj, event)
    assert result.run is not None
    info = result.run.artifacts.get("plan.md")
    assert info is not None
    assert info.frozen is True
    assert info.executed is False
    assert info.exec_outcome == ""


def test_fold_execute_completion_sets_executed_clean() -> None:
    """execute_completion with outcome='clean' sets executed=True and exec_outcome='clean'."""
    proj = Projection(run=_make_run({"plan.md": ArtifactInfo(path="plan.md", frozen=True)}))
    event = VersionedEvent(
        version=2,
        event_type="execute_completion",
        timestamp="2026-01-01T00:00:01+00:00",
        agent_id=None,
        payload={"plan_file": "plan.md", "outcome": "clean"},
    )
    result = fold(proj, event)
    assert result.run is not None
    info = result.run.artifacts.get("plan.md")
    assert info is not None
    assert info.frozen is True
    assert info.executed is True
    assert info.exec_outcome == "clean"


def test_fold_execute_completion_sets_executed_non_conforming() -> None:
    """execute_completion with outcome='non_conforming' sets exec_outcome accordingly."""
    proj = Projection(run=_make_run({"plan.md": ArtifactInfo(path="plan.md", frozen=True)}))
    event = VersionedEvent(
        version=2,
        event_type="execute_completion",
        timestamp="2026-01-01T00:00:01+00:00",
        agent_id=None,
        payload={"plan_file": "plan.md", "outcome": "non_conforming"},
    )
    result = fold(proj, event)
    assert result.run is not None
    info = result.run.artifacts["plan.md"]
    assert info.executed is True
    assert info.exec_outcome == "non_conforming"


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


def test_fold_execute_entry_creates_artifact_if_absent() -> None:
    """execute_entry on an artifact not yet in the projection creates a frozen stub."""
    proj = Projection(run=_make_run())  # no artifacts yet
    event = VersionedEvent(
        version=1,
        event_type="execute_entry",
        timestamp="2026-01-01T00:00:00+00:00",
        agent_id=None,
        payload={"plan_file": "plan.md"},
    )
    result = fold(proj, event)
    assert result.run is not None
    info = result.run.artifacts.get("plan.md")
    assert info is not None and info.frozen is True


# -- Tests: apply_set_phase execute handoff -----------------------------------


@pytest.mark.anyio
async def test_execute_handoff_success(tmp_path: Path, monkeypatch: Any) -> None:
    """apply_set_phase('execute', plan_file='plan.md') on a valid plan emits
    execute_entry and execute_completion, spawns the executor, and returns the
    deviation report. ArtifactInfo is frozen and executed in the projection.
    """
    deviation_report = "Implemented as planned. No deviations."

    async def fake_spawn(task: dict, app_state: AppState) -> SubagentResult:
        """Stub that asserts executor task shape and returns a canned report."""
        assert task["role"] == "executor"
        assert "plan.md" in task["artifacts"]
        assert task["instructions"] == ""
        return SubagentResult(exit_code=0, final_response=deviation_report)

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fake_spawn)

    deps, app_state = _make_deps(tmp_path)
    _write_artifact(tmp_path, "plan.md")
    _push_artifact_created(app_state, "plan.md", tmp_path)

    result = await apply_set_phase(deps, "execute", plan_file="plan.md")

    # Returned text is the deviation report.
    assert result == deviation_report

    # Projection reflects the freeze + executed state.
    run = app_state.projection_store.projection.run
    assert run is not None
    info = run.artifacts.get("plan.md")
    assert info is not None
    assert info.frozen is True
    assert info.executed is True
    assert info.exec_outcome == "clean"


@pytest.mark.anyio
async def test_execute_handoff_non_conforming_outcome(tmp_path: Path, monkeypatch: Any) -> None:
    """A non-zero executor exit code produces exec_outcome='non_conforming'."""
    async def fail_spawn(task: dict, app_state: AppState) -> SubagentResult:
        return SubagentResult(exit_code=1, final_response="Build failed: tests red.")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fail_spawn)

    deps, app_state = _make_deps(tmp_path)
    _write_artifact(tmp_path, "plan.md")
    _push_artifact_created(app_state, "plan.md", tmp_path)

    result = await apply_set_phase(deps, "execute", plan_file="plan.md")

    assert "Build failed" in result

    run = app_state.projection_store.projection.run
    assert run is not None
    info = run.artifacts.get("plan.md")
    assert info is not None
    assert info.frozen is True
    assert info.executed is True
    assert info.exec_outcome == "non_conforming"


# -- Tests: validation before side effects ------------------------------------


@pytest.mark.anyio
async def test_execute_not_found_returns_envelope_no_side_effects(tmp_path: Path) -> None:
    """A missing plan_file returns the execute_not_found envelope and emits no events."""
    import json

    deps, app_state = _make_deps(tmp_path)
    # plan.md does not exist in run_dir

    event_types_before = [e.event_type for e in app_state.projection_store.events]

    result = await apply_set_phase(deps, "execute", plan_file="plan.md")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "execute_not_found"

    # No execute_entry event was emitted.
    event_types_after = [e.event_type for e in app_state.projection_store.events]
    new_events = event_types_after[len(event_types_before):]
    assert "execute_entry" not in new_events, (
        "execute_entry must not be emitted when validation fails"
    )


@pytest.mark.anyio
async def test_execute_not_plan_returns_envelope(tmp_path: Path) -> None:
    """Naming a non-plan artifact (milestones.md) returns the execute_not_plan envelope."""
    import json

    deps, app_state = _make_deps(tmp_path)
    _write_artifact(tmp_path, "milestones.md")
    _push_artifact_created(app_state, "milestones.md", tmp_path)

    result = await apply_set_phase(deps, "execute", plan_file="milestones.md")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "execute_not_plan"


@pytest.mark.anyio
async def test_already_executed_returns_envelope(tmp_path: Path, monkeypatch: Any) -> None:
    """A plan that has already been executed returns the already_executed envelope."""
    import json

    async def ok_spawn(task: dict, app_state: AppState) -> SubagentResult:
        return SubagentResult(exit_code=0, final_response="done")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", ok_spawn)

    deps, app_state = _make_deps(tmp_path)
    _write_artifact(tmp_path, "plan.md")
    _push_artifact_created(app_state, "plan.md", tmp_path)

    # First execution succeeds.
    await apply_set_phase(deps, "execute", plan_file="plan.md")

    # Second execution attempt must return the already_executed envelope, not raise.
    result = await apply_set_phase(deps, "execute", plan_file="plan.md")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "already_executed"


@pytest.mark.anyio
async def test_bare_execute_without_plan_file_returns_envelope(tmp_path: Path) -> None:
    """set_phase('execute') with no plan_file returns the execute_requires_plan_file envelope."""
    import json

    deps, _ = _make_deps(tmp_path)

    result = await apply_set_phase(deps, "execute")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "execute_requires_plan_file"


@pytest.mark.anyio
async def test_invalid_transition_returns_envelope(tmp_path: Path) -> None:
    """set_phase with a phase not reachable from the current one returns the invalid_transition envelope."""
    import json

    deps, _ = _make_deps(tmp_path)
    # The fixture starts in "plan-review" within PLAN_WORKFLOW.
    # "intake" is a valid phase but transitions are any-to-any in the workflow;
    # however we can test with a phase that is genuinely not in the workflow.
    # Use a phase name that is not in PLAN_WORKFLOW's available_phases.
    result = await apply_set_phase(deps, "core-flows")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "invalid_transition"


# -- Tests: artifact_edit_core frozen check -----------------------------------


@pytest.mark.anyio
async def test_edit_frozen_plan_raises(tmp_path: Path, monkeypatch: Any) -> None:
    """artifact_edit_core returns a frozen envelope when the target plan is frozen.

    The plan artifact is frozen by emitting an execute_entry event, which the
    _frozen_artifact_names helper reads from the projection.  The failure is
    returned as a recoverable {"ok": false} envelope rather than raised so the
    run is not crashed by a model mistake.
    """
    import json

    async def ok_spawn(task: dict, app_state: AppState) -> SubagentResult:
        return SubagentResult(exit_code=0, final_response="done")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", ok_spawn)

    deps, app_state = _make_deps(tmp_path)
    _write_artifact(tmp_path, "plan.md", "# Plan\n\nStep 1: do the thing.\n")
    _push_artifact_created(app_state, "plan.md", tmp_path)

    # Execute the plan to freeze it.
    await apply_set_phase(deps, "execute", plan_file="plan.md")

    # Attempt to edit the frozen artifact must return a recoverable envelope.
    result = await artifact_edit_core(deps, "plan.md", "1\tStep 1", "Step 1: revised.")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "frozen"


@pytest.mark.anyio
async def test_edit_frozen_plan_sidecar_succeeds(tmp_path: Path, monkeypatch: Any) -> None:
    """artifact_edit_core succeeds on a frozen plan's .review.md sidecar.

    The sidecar is exempt from the frozen check so the orchestrator can append
    post-execution conformance notes to a frozen plan's review record.
    """
    async def ok_spawn(task: dict, app_state: AppState) -> SubagentResult:
        return SubagentResult(exit_code=0, final_response="done")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", ok_spawn)

    deps, app_state = _make_deps(tmp_path)
    _write_artifact(tmp_path, "plan.md", "# Plan\n\nContent.\n")
    _push_artifact_created(app_state, "plan.md", tmp_path)

    # Freeze the plan via execution.
    await apply_set_phase(deps, "execute", plan_file="plan.md")

    # Create a sidecar file for the test (koan normally creates it, but we do it
    # directly here since the reviewer is not wired in this test).
    sidecar_content = "## Plan review (pre-exec)\n\nFindings here.\n"
    sidecar = tmp_path / "plan.review.md"
    sidecar.write_text(sidecar_content, encoding="utf-8")

    # Build the correct hash-anchored token for the first line so edit_tool
    # accepts it.  The anchor format is "{fnv1a32(line)}{ANCHOR_DELIMITER}{line}".
    from koan.tools.line_anchors import ANCHOR_DELIMITER, fnv1a32
    first_line = "## Plan review (pre-exec)"
    anchor_token = f"{fnv1a32(first_line)}{ANCHOR_DELIMITER}{first_line}"

    # Edit the sidecar -- must succeed despite the plan being frozen.
    import json
    result_json = await artifact_edit_core(
        deps,
        "plan.review.md",
        anchor_token,
        "## Plan review (pre-exec)\n\n## Execution review (post-exec)\n\nImplemented cleanly.",
    )
    payload = json.loads(result_json)
    assert payload["ok"] is True
    assert payload["filename"] == "plan.review.md"
