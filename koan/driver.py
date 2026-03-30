# Driver FSM -- coordinates phase transitions for an epic run.
# Pure routing logic (route_from_state) plus async orchestration helpers.

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiofiles

from .artifacts import list_artifacts
from .epic_state import (
    atomic_write_json,
    ensure_subagent_directory,
    load_all_story_states,
    load_epic_state,
    load_story_state,
    read_workflow_decision,
    save_epic_state,
    save_story_state,
)
from .events import build_artifact_diff
from .lib.phase_dag import (
    PHASE_DESCRIPTIONS,
    get_successor_phases,
    is_auto_advance,
    is_stub_phase,
    is_valid_transition,
)
from .logger import get_logger
from .subagent import spawn_subagent
from .types import DEFAULT_MAX_RETRIES, EpicPhase, SubagentRole

if TYPE_CHECKING:
    from pathlib import Path

    from .state import AppState

log = get_logger("driver")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- Phase-to-role mapping ----------------------------------------------------

PHASE_ROLE: dict[str, SubagentRole] = {
    "intake": "intake",
    "brief-generation": "brief-writer",
    "core-flows": "decomposer",
    "tech-plan": "planner",
    "ticket-breakdown": "ticket-breakdown",
    "cross-artifact-validation": "cross-artifact-validator",
    "execution": "executor",
    "implementation-validation": "cross-artifact-validator",
}


# -- Pure routing function ----------------------------------------------------

def route_from_state(stories: list[dict]) -> dict:
    """Determine the next action from a list of story state dicts.

    Returns a dict with 'action' and optionally 'story_id' or 'error'.
    Pure function -- no I/O, no mutation of inputs.
    """
    # Retry takes priority
    for s in stories:
        if s.get("status") == "retry":
            return {"action": "retry", "story_id": s.get("storyId")}

    # Then selected
    for s in stories:
        if s.get("status") == "selected":
            return {"action": "execute", "story_id": s.get("storyId")}

    # All terminal?
    terminal = {"done", "skipped"}
    if stories and all(s.get("status") in terminal for s in stories):
        return {"action": "complete"}

    return {"action": "error", "error": "no actionable stories found"}


# -- Artifact diff helper ------------------------------------------------------

def _push_artifact_diff(app_state: AppState) -> None:
    """Scan epic artifacts and emit per-file diff events against current projection."""
    if not app_state.epic_dir:
        return
    try:
        new_artifacts = list_artifacts(app_state.epic_dir)
    except Exception:
        return
    old = app_state.projection_store.projection.artifacts
    for event_type, payload in build_artifact_diff(old, new_artifacts):
        app_state.projection_store.push_event(event_type, payload)


# -- Workflow status ----------------------------------------------------------

async def write_workflow_status(
    epic_dir: str | Path,
    completed_phase: EpicPhase,
    available_phases: list[EpicPhase],
) -> None:
    """Write workflow-status.md with completed phase, available phases, and artifacts."""
    lines: list[str] = []
    lines.append(f"# Workflow Status")
    lines.append("")
    lines.append(f"## Completed Phase")
    lines.append(f"**{completed_phase}**: {PHASE_DESCRIPTIONS.get(completed_phase, '')}")
    lines.append("")
    lines.append("## Available Next Phases")
    for p in available_phases:
        desc = PHASE_DESCRIPTIONS.get(p, "")
        lines.append(f"- **{p}**: {desc}")
    lines.append("")
    lines.append("## Artifacts")

    artifacts = list_artifacts(epic_dir)
    if artifacts:
        for a in artifacts:
            lines.append(f"- `{a['path']}` ({a['size']} bytes)")
    else:
        lines.append("(none)")
    lines.append("")

    from pathlib import Path as P
    out = P(epic_dir) / "workflow-status.md"
    tmp = out.with_suffix(".tmp")
    async with aiofiles.open(tmp, "w") as f:
        await f.write("\n".join(lines))
    import os
    os.rename(tmp, out)


# -- Workflow orchestrator ----------------------------------------------------

async def run_workflow_orchestrator(
    completed_phase: EpicPhase,
    available_phases: list[EpicPhase],
    app_state: AppState,
) -> dict | None:
    """Spawn a workflow-orchestrator subagent and return its decision."""
    epic_dir = app_state.epic_dir
    await write_workflow_status(epic_dir, completed_phase, available_phases)

    label = f"workflow-orch-{completed_phase}-{int(time.time() * 1000)}"
    subagent_dir = await ensure_subagent_directory(epic_dir, label)

    task = {
        "role": "workflow-orchestrator",
        "epic_dir": epic_dir,
        "subagent_dir": subagent_dir,
        "completed_phase": completed_phase,
        "available_phases": available_phases,
    }

    try:
        exit_code = await spawn_subagent(task, app_state)
    except NotImplementedError:
        log.warning("spawn_subagent not implemented; workflow orchestrator skipped")
        return None

    if exit_code != 0:
        log.error("workflow orchestrator exited with code %d", exit_code)
        return None

    decision = await read_workflow_decision(subagent_dir)
    if decision is None:
        log.error("no workflow decision found in %s", subagent_dir)
        return None

    next_phase = decision.get("next_phase")
    if not is_valid_transition(completed_phase, next_phase):
        log.error(
            "invalid transition %s -> %s", completed_phase, next_phase
        )
        return None

    return {
        "next_phase": next_phase,
        "instructions": decision.get("instructions"),
    }


# -- Story execution helpers --------------------------------------------------

async def run_story_execution(
    story_id: str, app_state: AppState
) -> bool:
    """Run planner + executor + post-execution orchestrator for a story."""
    epic_dir = app_state.epic_dir

    # Planner
    await save_story_state(epic_dir, story_id, {"storyId": story_id, "status": "planning", "updatedAt": _now()})
    # story events deferred -- execution phase UI is a known gap

    planner_dir = await ensure_subagent_directory(
        epic_dir, f"planner-{story_id}-{int(time.time() * 1000)}"
    )
    planner_task = {
        "role": "planner",
        "epic_dir": epic_dir,
        "subagent_dir": planner_dir,
        "story_id": story_id,
    }

    try:
        planner_exit = await spawn_subagent(planner_task, app_state)
    except NotImplementedError:
        log.warning("spawn_subagent not implemented; story execution skipped")
        return False

    planner_ok = planner_exit == 0

    # Executor (skip if planner failed)
    if planner_ok:
        await save_story_state(epic_dir, story_id, {"storyId": story_id, "status": "executing", "updatedAt": _now()})

        executor_dir = await ensure_subagent_directory(
            epic_dir, f"executor-{story_id}-{int(time.time() * 1000)}"
        )
        executor_task = {
            "role": "executor",
            "epic_dir": epic_dir,
            "subagent_dir": executor_dir,
            "story_id": story_id,
        }
        executor_exit = await spawn_subagent(executor_task, app_state)
        executor_ok = executor_exit == 0
    else:
        executor_ok = False

    # Post-execution orchestrator
    await save_story_state(epic_dir, story_id, {"storyId": story_id, "status": "verifying", "updatedAt": _now()})

    orch_dir = await ensure_subagent_directory(
        epic_dir, f"orch-post-{story_id}-{int(time.time() * 1000)}"
    )
    orch_task = {
        "role": "orchestrator",
        "epic_dir": epic_dir,
        "subagent_dir": orch_dir,
        "story_id": story_id,
        "step_sequence": "post-execution",
        "planner_ok": planner_ok,
        "executor_ok": executor_ok,
    }
    await spawn_subagent(orch_task, app_state)

    # Validate that orchestrator committed a verdict via story state
    story = await load_story_state(epic_dir, story_id)
    status = story.get("status")
    if status not in ("done", "retry", "skipped"):
        log.error(
            "post-execution orchestrator did not commit a valid verdict for %s (status=%s)",
            story_id, status,
        )
        await save_story_state(epic_dir, story_id, {
            "storyId": story_id,
            "status": "retry",
            "failureSummary": "post-execution orchestrator exited without committing a verdict",
            "updatedAt": _now(),
        })

    return True


async def run_story_reexecution(
    story_id: str, app_state: AppState
) -> bool:
    """Re-execute a story: executor with retry context + post-execution orchestrator.

    Skips planner -- retry uses the existing plan with failure context injected
    into the executor task manifest.
    """
    epic_dir = app_state.epic_dir

    story = await load_story_state(epic_dir, story_id)
    retry_context = story.get("failureSummary")
    retry_count = story.get("retryCount", 0)

    # Executor with retry context
    await save_story_state(epic_dir, story_id, {"storyId": story_id, "status": "executing", "updatedAt": _now()})

    executor_dir = await ensure_subagent_directory(
        epic_dir, f"executor-{story_id}-retry-{retry_count}-{int(time.time() * 1000)}"
    )
    executor_task = {
        "role": "executor",
        "epic_dir": epic_dir,
        "subagent_dir": executor_dir,
        "story_id": story_id,
        "retryContext": retry_context,
    }

    try:
        await spawn_subagent(executor_task, app_state)
    except NotImplementedError:
        log.warning("spawn_subagent not implemented; story re-execution skipped")
        return False

    # Post-execution orchestrator
    await save_story_state(epic_dir, story_id, {"storyId": story_id, "status": "verifying", "updatedAt": _now()})

    orch_dir = await ensure_subagent_directory(
        epic_dir, f"orch-post-{story_id}-retry-{retry_count}-{int(time.time() * 1000)}"
    )
    orch_task = {
        "role": "orchestrator",
        "epic_dir": epic_dir,
        "subagent_dir": orch_dir,
        "story_id": story_id,
        "step_sequence": "post-execution",
    }
    await spawn_subagent(orch_task, app_state)

    # Validate orchestrator committed a verdict via story state
    updated = await load_story_state(epic_dir, story_id)
    status = updated.get("status")
    if status not in ("done", "retry", "skipped"):
        log.error(
            "post-execution orchestrator did not commit a valid verdict for %s (status=%s)",
            story_id, status,
        )
        await save_story_state(epic_dir, story_id, {
            "storyId": story_id,
            "status": "retry",
            "failureSummary": "post-execution orchestrator exited without committing a verdict",
            "updatedAt": _now(),
        })

    return True


# -- Story loop ---------------------------------------------------------------

async def run_story_loop(app_state: AppState, instructions: str | None) -> dict:
    """Run the execution story loop until all stories complete or error."""
    epic_dir = app_state.epic_dir

    # Pre-execution orchestrator
    pre_dir = await ensure_subagent_directory(
        epic_dir, f"orch-pre-{int(time.time() * 1000)}"
    )
    pre_task = {
        "role": "orchestrator",
        "epic_dir": epic_dir,
        "subagent_dir": pre_dir,
        "step_sequence": "pre-execution",
        "instructions": instructions,
    }

    try:
        pre_exit = await spawn_subagent(pre_task, app_state)
    except NotImplementedError:
        log.warning("spawn_subagent not implemented; story loop skipped")
        return {"success": False, "summary": "spawn_subagent not implemented"}

    if pre_exit != 0:
        log.error("pre-execution orchestrator exited with code %d", pre_exit)
        return {"success": False, "summary": "pre-execution orchestrator failed"}

    while True:
        stories = await load_all_story_states(epic_dir)
        decision = route_from_state(stories)
        action = decision["action"]

        if action == "execute":
            sid = decision["story_id"]
            log.info("executing story %s", sid)
            await run_story_execution(sid, app_state)

        elif action == "retry":
            sid = decision["story_id"]
            story = next((s for s in stories if s.get("storyId") == sid), {})
            retry_count = story.get("retryCount", 0)
            max_retries = story.get("maxRetries", DEFAULT_MAX_RETRIES)
            if retry_count >= max_retries:
                log.warning("story %s exceeded retry budget, skipping", sid)
                await save_story_state(
                    epic_dir, sid,
                    {
                        "storyId": sid,
                        "status": "skipped",
                        "skipReason": f"Retry budget exhausted after {retry_count} attempt(s). Last failure: {story.get('failureSummary', '(none recorded)')}",
                        "updatedAt": _now(),
                    },
                )
            else:
                log.info("retrying story %s (attempt %d)", sid, retry_count + 1)
                await save_story_state(
                    epic_dir, sid,
                    {
                        "storyId": sid,
                        "status": "executing",
                        "retryCount": retry_count + 1,
                        "updatedAt": _now(),
                    },
                )
                await run_story_reexecution(sid, app_state)

        elif action == "complete":
            log.info("all stories complete")
            return {"success": True, "summary": "all stories completed"}

        else:
            log.error("route_from_state returned error: %s", decision.get("error"))
            return {"success": False, "summary": decision.get("error", "unknown routing error")}


# -- Phase runner -------------------------------------------------------------

async def run_phase(
    phase: EpicPhase,
    app_state: AppState,
    instructions: str | None,
) -> bool:
    """Run a single phase. Returns True on success."""
    epic_dir = app_state.epic_dir

    if phase == "execution":
        result = await run_story_loop(app_state, instructions)
        return result.get("success", False)

    role = PHASE_ROLE.get(phase)
    if role is None:
        log.error("no role mapping for phase %s", phase)
        return False

    subagent_dir = await ensure_subagent_directory(
        epic_dir, f"{role}-{int(time.time() * 1000)}"
    )
    task = {
        "role": role,
        "epic_dir": epic_dir,
        "subagent_dir": subagent_dir,
        "instructions": instructions,
    }

    try:
        exit_code = await spawn_subagent(task, app_state)
    except NotImplementedError:
        log.warning("spawn_subagent not implemented; phase %s skipped", phase)
        return False

    return exit_code == 0


# -- Main driver loop ---------------------------------------------------------

async def driver_main(app_state: AppState) -> None:
    """Main FSM loop -- waits for start event, then runs phases until completion."""
    log.info("Driver waiting for start event...")
    await app_state.start_event.wait()

    epic_dir = app_state.epic_dir
    if epic_dir is None:
        log.error("epic_dir is None after start event -- aborting")
        return

    phase: EpicPhase = "intake"
    pending_instructions: str | None = None

    while phase != "completed":
        epic_state = await load_epic_state(epic_dir)
        await save_epic_state(epic_dir, {**epic_state, "phase": phase})

        # Set app_state.phase before emitting phase_started (driver mutation, not projection)
        app_state.phase = phase
        app_state.projection_store.push_event("phase_started", {"phase": phase})

        # Push artifact diff at start of each phase
        _push_artifact_diff(app_state)

        if is_stub_phase(phase):
            pass  # carry forward pending_instructions
        else:
            ok = await run_phase(phase, app_state, pending_instructions)
            pending_instructions = None
            if not ok:
                app_state.projection_store.push_event("workflow_completed", {
                    "success": False,
                    "phase": phase,
                    "error": f"Phase {phase} failed",
                    "summary": f"Phase {phase} failed",
                })
                return

        successors = get_successor_phases(phase)
        if not successors:
            break

        if is_auto_advance(phase):
            phase = successors[0]
            continue

        # Freeze logs snapshot for orchestrator
        app_state.frozen_logs = list(app_state.frozen_logs)
        decision = await run_workflow_orchestrator(phase, successors, app_state)
        if not decision:
            app_state.projection_store.push_event("workflow_completed", {
                "success": False,
                "phase": phase,
                "error": "Workflow orchestrator failed",
                "summary": "Workflow orchestrator failed",
            })
            return
        phase = decision["next_phase"]
        pending_instructions = decision.get("instructions")

    epic_state = await load_epic_state(epic_dir)
    await save_epic_state(epic_dir, {**epic_state, "phase": "completed"})
    app_state.phase = "completed"
    app_state.projection_store.push_event("phase_started", {"phase": "completed"})

    # Final artifact diff before completion
    _push_artifact_diff(app_state)

    app_state.projection_store.push_event("workflow_completed", {
        "success": True,
        "summary": "All phases completed successfully",
    })
