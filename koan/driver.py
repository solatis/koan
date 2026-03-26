# Driver FSM -- coordinates phase transitions for an epic run.
# Pure routing logic (route_from_state) plus async orchestration helpers.
# push_sse is a T8 stub.

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

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


# -- SSE push -----------------------------------------------------------------

def push_sse(app_state: AppState, event_type: str, payload: Any) -> None:
    """Push an SSE event to all connected clients with replay caching."""
    # Render HTML fragment for low-frequency structural events
    html_payload = _render_fragment(app_state, event_type, payload)

    # Cache the rendered payload (not the raw input) so reconnect replay
    # sends exactly what live clients received.
    STATEFUL_EVENTS = {
        "phase", "subagent", "subagent-idle", "agents", "artifacts",
        "interaction", "intake-progress", "pipeline-end",
    }
    if event_type in STATEFUL_EVENTS:
        app_state.last_sse_values[event_type] = html_payload

    # Enqueue to all connected SSE clients
    for queue in app_state.sse_clients:
        try:
            queue.put_nowait((event_type, html_payload))
        except Exception:
            pass  # queue full or closed -- skip


def _render_fragment(app_state: AppState, event_type: str, payload: Any) -> Any:
    """Render Jinja2 fragment for structural events; pass through for stream events."""
    from .web.app import _get_jinja, _build_artifact_tree, _format_size, _format_elapsed_ms
    from .web.app import _format_tokens, _build_subagent_display, _build_agents_list, ALL_PHASES, _done_phases

    env = _get_jinja()

    if event_type == "phase":
        # payload is a phase string
        phase = payload if isinstance(payload, str) else payload.get("phase", "")
        app_state.phase = phase
        tmpl = env.get_template("fragments/status_sidebar.html")
        html = tmpl.render(
            subagent=_build_subagent_display(app_state),
            phase_status={"phase": phase},
        )
        return {"phase": phase, "html": html, "target": "status-sidebar"}

    if event_type == "subagent":
        tmpl = env.get_template("fragments/status_sidebar.html")
        subagent_data = _build_subagent_display(app_state)
        html = tmpl.render(
            subagent=subagent_data,
            phase_status={"phase": app_state.phase or "intake"},
        )
        return {**(payload if isinstance(payload, dict) else {}), "html": html, "target": "status-sidebar"}

    if event_type == "subagent-idle":
        tmpl = env.get_template("fragments/status_sidebar.html")
        html = tmpl.render(
            subagent=None,
            phase_status={"phase": app_state.phase or "intake"},
        )
        return {"html": html, "target": "status-sidebar"}

    if event_type == "agents":
        tmpl = env.get_template("fragments/monitor.html")
        agents = _build_agents_list(app_state)
        html = tmpl.render(agents=agents)
        return {**(payload if isinstance(payload, dict) else {}), "html": html, "target": "monitor"}

    if event_type == "artifacts":
        epic_dir = app_state.epic_dir
        artifacts = []
        if epic_dir:
            try:
                from .artifacts import list_artifacts as _list
                artifacts = _list(epic_dir)
            except Exception:
                pass
        tree = _build_artifact_tree(artifacts)
        tmpl = env.get_template("fragments/artifacts_sidebar.html")
        html = tmpl.render(artifacts=artifacts, artifact_tree=tree)
        return {**(payload if isinstance(payload, dict) else {}), "html": html, "target": "artifacts-sidebar"}

    if event_type == "interaction":
        if isinstance(payload, dict):
            itype = payload.get("type", "")
            if itype == "ask":
                tmpl = env.get_template("fragments/interaction_ask.html")
                html = tmpl.render(
                    questions=payload.get("questions", []),
                    token=payload.get("token", ""),
                )
                return {**payload, "html": html, "target": "workspace-main-content"}
            if itype == "artifact-review":
                tmpl = env.get_template("fragments/interaction_artifact_review.html")
                html = tmpl.render(
                    content=payload.get("content", ""),
                    description=payload.get("description", ""),
                    token=payload.get("token", ""),
                )
                return {**payload, "html": html, "target": "workspace-main-content"}
            if itype == "workflow-decision":
                tmpl = env.get_template("fragments/interaction_workflow.html")
                html = tmpl.render(
                    chat_turns=payload.get("chat_turns", []),
                    token=payload.get("token", ""),
                )
                return {**payload, "html": html, "target": "workspace-main-content"}
            if itype == "cleared":
                # Restore activity feed
                html = '<div id="workspace-main-content"><div class="activity-feed-scroll"><div id="activity-feed-inner" class="activity-feed-inner"></div></div></div>'
                return {"type": "cleared", "html": html, "target": "workspace-main-content"}
        return payload

    if event_type == "pipeline-end":
        tmpl = env.get_template("fragments/completion.html")
        if isinstance(payload, dict):
            artifacts = payload.get("artifacts", [])
            for a in artifacts:
                if "formatted_size" not in a:
                    a["formatted_size"] = _format_size(a.get("size", 0))
            html = tmpl.render(
                success=payload.get("success", False),
                summary=payload.get("summary", ""),
                error=payload.get("error", ""),
                phase=payload.get("phase", ""),
                artifacts=artifacts,
            )
            return {**payload, "html": html, "target": "workspace-main-content"}
        return payload

    if event_type == "intake-progress":
        tmpl = env.get_template("fragments/status_sidebar.html")
        phase_status = {"phase": "intake"}
        if isinstance(payload, dict):
            phase_status["sub_phase"] = payload.get("subPhase", "")
            phase_status["confidence"] = payload.get("confidence")
            phase_status["summary"] = payload.get("summary", "")
        html = tmpl.render(
            subagent=_build_subagent_display(app_state),
            phase_status=phase_status,
        )
        return {**(payload if isinstance(payload, dict) else {}), "html": html, "target": "status-sidebar"}

    # High-frequency events: pass through without HTML
    # token-delta, token-clear, logs, notification, stream, story, error
    return payload



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
    push_sse(app_state, "story", {"storyId": story_id, "status": "planning"})

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
        push_sse(app_state, "story", {"storyId": story_id, "status": "executing"})

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
    push_sse(app_state, "story", {"storyId": story_id, "status": "verifying"})

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
        push_sse(app_state, "story", {"storyId": story_id, "status": "retry"})

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
    push_sse(app_state, "story", {"storyId": story_id, "status": "executing"})

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
    push_sse(app_state, "story", {"storyId": story_id, "status": "verifying"})

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
        push_sse(app_state, "story", {"storyId": story_id, "status": "retry"})

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
                push_sse(app_state, "story", {"storyId": sid, "status": "skipped"})
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
        push_sse(app_state, "phase", phase)

        # Push artifacts update at start of each phase
        push_sse(app_state, "artifacts", {})

        if is_stub_phase(phase):
            pass  # carry forward pending_instructions
        else:
            ok = await run_phase(phase, app_state, pending_instructions)
            pending_instructions = None
            if not ok:
                push_sse(app_state, "pipeline-end", {
                    "success": False,
                    "phase": phase,
                    "error": f"Phase {phase} failed",
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
            push_sse(app_state, "pipeline-end", {
                "success": False,
                "phase": phase,
                "error": "Workflow orchestrator failed",
            })
            return
        phase = decision["next_phase"]
        pending_instructions = decision.get("instructions")

    epic_state = await load_epic_state(epic_dir)
    await save_epic_state(epic_dir, {**epic_state, "phase": "completed"})
    push_sse(app_state, "phase", "completed")

    # Push completion event with artifact list
    push_sse(app_state, "pipeline-end", {
        "success": True,
        "summary": "All phases completed successfully",
        "artifacts": list_artifacts(epic_dir),
    })
