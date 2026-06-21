# Integration-leaning tests for the M3 artifact write path.
#
# Covers:
#   (a) write-once: a second write of an existing name raises exists_draft.
#   (b) reviewed family: writing tech-plan.md in tech-plan phase spawns a
#       reviewer and creates tech-plan.review.md containing the findings.
#   (c) unreviewed family: writing brief.md in intake phase writes the artifact
#       and creates NO sidecar.
#   (d) wrong-phase validation: writing plan.md outside the plan phase surfaces
#       the wrong_phase code.
#
# Subagent spawning is stubbed via monkeypatching spawn_subagent so no real
# LLM call is made. Tests focus on mechanical triggering (subagent spawned,
# sidecar written), not on prompt text.

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import koan.subagent as subagent_mod
from koan.phases import PhaseContext
from koan.state import AgentState, AppState
from koan.subagent import SubagentResult
from koan.tools.koan_tools import ToolDeps, artifact_write_core


# -- Helpers ------------------------------------------------------------------


def _make_deps(tmp_path: Path, phase: str) -> tuple[ToolDeps, AppState]:
    """Build a minimal ToolDeps + AppState for artifact_write_core tests.

    Sets up a run with the given phase and tmp_path as run_dir.
    workflow is set to None so requires_discriminator defaults to False
    (simulates the plan workflow where bare plan.md is legal).
    """
    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.project_dir = str(tmp_path)
    app_state.run.phase = phase  # type: ignore[assignment]
    app_state.run.workflow = None  # no workflow -> requires_discriminator=False

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


# -- Tests: write-once enforcement --------------------------------------------


@pytest.mark.anyio
async def test_write_once_rejects_existing_name(tmp_path: Path, monkeypatch) -> None:
    """Second write of an existing artifact name returns an exists_draft envelope.

    Write-once is the core M3 guarantee: once an artifact exists it must be
    revised via koan_artifact_edit, not overwritten.  The failure is returned as
    a recoverable {"ok": false} envelope rather than raised so the run is not
    crashed by a model mistake.
    """
    deps, _ = _make_deps(tmp_path, "intake")

    # First write succeeds.
    await artifact_write_core(deps, "brief.md", "# Brief\n\nContent.")

    # Second write of the same name is rejected with a recoverable envelope.
    result = await artifact_write_core(deps, "brief.md", "# Brief\n\nRevised.")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "exists_draft"


@pytest.mark.anyio
async def test_double_write_returns_envelope_not_raises(tmp_path: Path) -> None:
    """Regression: a second artifact_write_core call returns the envelope and does NOT raise.

    This is the literal bug this initiative fixes: the original implementation
    raised ValueError on the second write, which crashed the agent run.  After
    the fix, the model receives a structured error and can self-correct.
    """
    deps, _ = _make_deps(tmp_path, "intake")

    first = await artifact_write_core(deps, "brief.md", "# Brief\n\nFirst.")
    assert json.loads(first)["ok"] is True

    second = await artifact_write_core(deps, "brief.md", "# Brief\n\nSecond.")
    payload = json.loads(second)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "exists_draft"
    assert "allowed" in payload["error"]


@pytest.mark.anyio
async def test_write_rejects_sidecar_filename(tmp_path: Path) -> None:
    """Writing a .review.md filename directly returns a name_malformed envelope.

    koan owns sidecars; a model attempt to write one returns a recoverable error
    envelope so the run is not crashed.
    """
    deps, _ = _make_deps(tmp_path, "tech-plan")

    result = await artifact_write_core(deps, "tech-plan.review.md", "# Review\n")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "name_malformed"


# -- Tests: reviewed family (tech-plan.md) ------------------------------------


@pytest.mark.anyio
async def test_reviewed_artifact_spawns_reviewer_and_creates_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    """Writing tech-plan.md in the tech-plan phase spawns a reviewer and creates sidecar.

    The reviewer sub-agent's findings are written to tech-plan.review.md by
    artifact_write_core (koan writes the sidecar, not the reviewer).
    The findings string is also returned to the caller.
    """
    canned_findings = "Critical: The architecture is missing a retry layer."

    async def fake_spawn(task: dict, app_state: AppState) -> SubagentResult:
        """Stub that returns canned findings without a real LLM call."""
        assert task["role"] == "reviewer"
        assert task["reviewer_target"] == "tech-plan.md"
        assert task["reviewer_prompt"] == "TECH_PLAN_REVIEWER"
        return SubagentResult(exit_code=0, final_response=canned_findings)

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fake_spawn)

    deps, _ = _make_deps(tmp_path, "tech-plan")

    result = await artifact_write_core(deps, "tech-plan.md", "# Tech Plan\n\nContent.")

    # Caller receives the freeform findings (not a JSON status object).
    assert result == canned_findings

    # Sidecar exists and contains the findings.
    sidecar = tmp_path / "tech-plan.review.md"
    assert sidecar.is_file(), "sidecar file not created"
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert "## Plan review (pre-exec)" in sidecar_text
    assert canned_findings in sidecar_text


@pytest.mark.anyio
async def test_reviewed_artifact_returns_findings_on_reviewer_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed reviewer run produces a marker string, not a crash.

    The sidecar is still created so the orchestrator can inspect it.
    """
    async def fail_spawn(task: dict, app_state: AppState) -> SubagentResult:
        return SubagentResult(exit_code=1, error="model timeout")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fail_spawn)

    deps, _ = _make_deps(tmp_path, "tech-plan")
    result = await artifact_write_core(deps, "tech-plan.md", "# Tech Plan\n\nContent.")

    # Result contains the failure marker (not an exception).
    assert "reviewer failed" in result

    # Sidecar is still created.
    sidecar = tmp_path / "tech-plan.review.md"
    assert sidecar.is_file()


# -- Tests: unreviewed family (brief.md) --------------------------------------


@pytest.mark.anyio
async def test_unreviewed_artifact_writes_and_creates_no_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    """Writing brief.md in the intake phase creates the artifact but no sidecar.

    brief.md has no reviewer_prompt in the registry; artifact_write_core must
    not spawn a reviewer and must not create brief.review.md.
    """
    spawn_called = []

    async def fail_if_called(task: dict, app_state: AppState) -> SubagentResult:
        spawn_called.append(task)
        return SubagentResult(exit_code=0, final_response="should not happen")

    monkeypatch.setattr(subagent_mod, "spawn_subagent", fail_if_called)

    deps, _ = _make_deps(tmp_path, "intake")
    result = await artifact_write_core(deps, "brief.md", "# Brief\n\nContent.")

    # Returns the standard written-OK JSON (not freeform findings).
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["filename"] == "brief.md"

    # No reviewer spawned.
    assert spawn_called == [], "reviewer must not be spawned for brief.md"

    # No sidecar created.
    assert not (tmp_path / "brief.review.md").exists()


# -- Tests: wrong-phase validation --------------------------------------------


@pytest.mark.anyio
async def test_wrong_phase_write_surfaces_wrong_phase_code(tmp_path: Path) -> None:
    """Writing plan.md outside the plan phase returns a wrong_phase envelope.

    validate_write checks origin_phases for the family; plan.md is only legal
    in the "plan" phase.  The failure is returned as a recoverable envelope so
    the model can self-correct without crashing the run.
    """
    deps, _ = _make_deps(tmp_path, "intake")  # wrong phase for plan.md

    result = await artifact_write_core(deps, "plan.md", "# Plan\n\nContent.")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "wrong_phase"
