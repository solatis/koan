# Driver -- coordinates the persistent orchestrator for a workflow run.
# Simplified: spawns one long-lived orchestrator process for the entire run.

from __future__ import annotations

from typing import TYPE_CHECKING

from .artifacts import list_artifacts
from .run_state import ensure_subagent_directory
from .events import build_artifact_diff
from .lib.task_json import make_initial_workflow_history
from .logger import get_logger
from .subagent import spawn_subagent

if TYPE_CHECKING:
    from .state import AppState

log = get_logger("driver")


# -- Artifact diff helper ------------------------------------------------------

def _push_artifact_diff(app_state: AppState) -> None:
    """Scan run artifacts and emit per-file diff events against current projection."""
    if not app_state.run.run_dir:
        return
    try:
        new_artifacts = list_artifacts(app_state.run.run_dir)
    except Exception:
        return
    run = app_state.projection_store.projection.run
    if run is None:
        old = {}
    else:
        # build_artifact_diff expects dict[str, dict] with 'modified_at' and 'size' keys
        old = {path: {"path": info.path, "size": info.size, "modified_at": info.modified_at}
               for path, info in run.artifacts.items()}
    emitted = 0
    for event_type, payload in build_artifact_diff(old, new_artifacts):
        app_state.projection_store.push_event(event_type, payload)
        emitted += 1
    log.debug(
        "artifact diff pushed: new=%d existing=%d emitted=%d",
        len(new_artifacts), len(old), emitted,
    )


# -- Main driver loop ---------------------------------------------------------

async def driver_main(app_state: AppState) -> None:
    """Spawn the persistent orchestrator for one workflow run.

    Called per-run by api_start_run after all run-scoped state is committed,
    so run_dir and related fields are guaranteed to be populated on entry.
    The orchestrator's task.json carries workflow_history (an append-only list
    whose most-recent entry is the active workflow) rather than a single
    workflow string.
    """
    log.info("driver_main starting for run_dir=%s", app_state.run.run_dir)

    run_dir = app_state.run.run_dir
    if run_dir is None:
        log.error("run_dir is None after start event -- aborting")
        return

    # Use workflow's initial phase; default to "intake" if no workflow set
    workflow = app_state.run.workflow
    initial_phase = workflow.initial_phase if workflow else "intake"
    workflow_name = workflow.name if workflow else "plan"

    log.info(
        "run starting: run_dir=%s workflow=%s initial_phase=%s",
        run_dir, workflow_name, initial_phase,
    )
    app_state.run.phase = initial_phase
    app_state.projection_store.push_event("phase_started", {"phase": initial_phase})
    subagent_dir = await ensure_subagent_directory(run_dir, "orchestrator")

    # Inject phase_guidance for the initial phase so intake adapts to workflow scope
    initial_guidance = workflow.phase_guidance.get(initial_phase, "") if workflow else ""

    task = {
        "role": "orchestrator",
        "run_dir": run_dir,
        "subagent_dir": subagent_dir,
        "project_dir": app_state.run.project_dir,
        "additional_dirs": app_state.run.additional_dirs,
        "task_description": app_state.run.task_description,
        # workflow_history replaces the old single "workflow" string field.
        # koan_set_workflow appends entries on each switch.
        "workflow_history": make_initial_workflow_history(workflow_name, initial_phase),
        "phase_instructions": initial_guidance,   # scope framing for initial phase
    }

    log.info("spawning orchestrator: subagent_dir=%s", subagent_dir)
    result = await spawn_subagent(task, app_state)

    log.info(
        "workflow complete: exit_code=%d final_phase=%s",
        result.exit_code, app_state.run.phase,
    )
    # Orchestrator exited -- workflow is over
    app_state.projection_store.push_event("workflow_completed", {
        "success": result.exit_code == 0,
        "phase": app_state.run.phase,
        "summary": f"Workflow ended in phase '{app_state.run.phase}'",
    })
