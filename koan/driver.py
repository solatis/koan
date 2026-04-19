# Driver -- coordinates the persistent orchestrator for a workflow run.
# Simplified: spawns one long-lived orchestrator process for the entire run.

from __future__ import annotations

from typing import TYPE_CHECKING

from .artifacts import list_artifacts
from .run_state import ensure_subagent_directory
from .events import build_artifact_diff
from .logger import get_logger
from .subagent import spawn_subagent

if TYPE_CHECKING:
    from .state import AppState

log = get_logger("driver")


# -- Artifact diff helper ------------------------------------------------------

def _push_artifact_diff(app_state: AppState) -> None:
    """Scan run artifacts and emit per-file diff events against current projection."""
    if not app_state.run_dir:
        return
    try:
        new_artifacts = list_artifacts(app_state.run_dir)
    except Exception:
        return
    run = app_state.projection_store.projection.run
    if run is None:
        old = {}
    else:
        # build_artifact_diff expects dict[str, dict] with 'modified_at' and 'size' keys
        old = {path: {"path": info.path, "size": info.size, "modified_at": info.modified_at}
               for path, info in run.artifacts.items()}
    for event_type, payload in build_artifact_diff(old, new_artifacts):
        app_state.projection_store.push_event(event_type, payload)


# -- Main driver loop ---------------------------------------------------------

async def driver_main(app_state: AppState) -> None:
    """Wait for start event, then spawn the persistent orchestrator for the entire run."""
    log.info("Driver waiting for start event...")
    await app_state.start_event.wait()

    run_dir = app_state.run_dir
    if run_dir is None:
        log.error("run_dir is None after start event -- aborting")
        return

    # Use workflow's initial phase; default to "intake" if no workflow set
    workflow = app_state.workflow
    initial_phase = workflow.initial_phase if workflow else "intake"
    workflow_name = workflow.name if workflow else "plan"

    app_state.phase = initial_phase
    app_state.projection_store.push_event("phase_started", {"phase": initial_phase})
    subagent_dir = await ensure_subagent_directory(run_dir, "orchestrator")

    # Inject phase_guidance for the initial phase so intake adapts to workflow scope
    initial_guidance = workflow.phase_guidance.get(initial_phase, "") if workflow else ""

    task = {
        "role": "orchestrator",
        "run_dir": run_dir,
        "subagent_dir": subagent_dir,
        "project_dir": app_state.project_dir,
        "task_description": app_state.task_description,
        "workflow": workflow_name,
        "phase_instructions": initial_guidance,   # scope framing for initial phase
    }

    result = await spawn_subagent(task, app_state)

    # Orchestrator exited — workflow is over
    app_state.projection_store.push_event("workflow_completed", {
        "success": result.exit_code == 0,
        "phase": app_state.phase,
        "summary": f"Workflow ended in phase '{app_state.phase}'",
    })
