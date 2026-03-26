# Subagent manager -- spawn, monitor, and cleanup subagent processes.
# Replaces the T6 stub in driver.py with a complete lifecycle implementation.

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

from .audit import EventLog
from .epic_state import ensure_subagent_directory
from .logger import get_logger
from .phases import PHASE_MODULE_MAP, PhaseContext
from .runners import RunnerDiagnostic, RunnerError, resolve_runner
from .types import ROLE_MODEL_TIER

if TYPE_CHECKING:
    from .runners.base import Runner
    from .state import AppState

log = get_logger("subagent")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# -- Boot prompt ---------------------------------------------------------------

def boot_prompt(role: str) -> str:
    return f"You are a koan {role} agent. Call koan_complete_step to receive your instructions."


# -- task.json writer ----------------------------------------------------------

async def write_task_json(subagent_dir: str, task_dict: dict) -> None:
    p = Path(subagent_dir) / "task.json"
    tmp = p.with_suffix(".tmp")
    async with aiofiles.open(tmp, "w") as f:
        await f.write(json.dumps(task_dict, indent=2))
    os.rename(tmp, p)


# -- PhaseContext builder ------------------------------------------------------

def _build_phase_ctx(task: dict, subagent_dir: str) -> PhaseContext:
    return PhaseContext(
        epic_dir=task.get("epic_dir", ""),
        subagent_dir=subagent_dir,
        phase_instructions=task.get("instructions") or task.get("phase_instructions"),
        story_id=task.get("story_id"),
        step_sequence=task.get("step_sequence"),
        completed_phase=task.get("completed_phase"),
        available_phases=task.get("available_phases", []),
        scout_question=task.get("question"),
        scout_output_file=task.get("output_file"),
        scout_investigator_role=task.get("investigator_role"),
        retry_context=task.get("retryContext") or task.get("retry_context"),
    )


# -- Main spawn function -------------------------------------------------------

async def spawn_subagent(task: dict, app_state: AppState, runner: Runner | None = None) -> int:
    role = task["role"]
    agent_id = str(uuid.uuid4())

    # Own directory creation -- derive if not provided, ensure it exists
    subagent_dir = task.get("subagent_dir", "")
    if not subagent_dir:
        epic_dir = task.get("epic_dir", "")
        label = f"{role}-{agent_id[:8]}"
        subagent_dir = await ensure_subagent_directory(epic_dir, label)
        task["subagent_dir"] = subagent_dir
    else:
        Path(subagent_dir).mkdir(parents=True, exist_ok=True)

    # Resolve runner
    if runner is None:
        runner = resolve_runner(role, app_state.config, subagent_dir)

    # Determine model from config
    tier = ROLE_MODEL_TIER.get(role, "standard")
    model = None
    if app_state.config.model_tiers is not None:
        model = getattr(app_state.config.model_tiers, tier, None)

    # Write task.json
    mcp_url = f"http://127.0.0.1:{app_state.port}/mcp?agent_id={agent_id}"
    task_on_disk = {**task, "mcp_url": mcp_url}
    await write_task_json(subagent_dir, task_on_disk)

    # Build PhaseContext
    phase_ctx = _build_phase_ctx(task, subagent_dir)

    # Look up phase module
    phase_module = PHASE_MODULE_MAP.get(role)
    if phase_module is None:
        log.error("no phase module for role %s", role)
        return 1

    # Create EventLog
    event_log = EventLog(subagent_dir, role, phase=role, model=model)
    await event_log.open()

    # Register AgentState
    from .state import AgentState
    agent = AgentState(
        agent_id=agent_id,
        role=role,
        subagent_dir=subagent_dir,
        epic_dir=task.get("epic_dir", ""),
        step=0,
        phase_module=phase_module,
        phase_ctx=phase_ctx,
        event_log=event_log,
        model=model,
    )
    app_state.agents[agent_id] = agent

    # Emit phase start
    await event_log.emit_phase_start(phase_module.TOTAL_STEPS)

    # Build command
    try:
        cmd = runner.build_command(boot_prompt(role), mcp_url, model)
    except RunnerError as e:
        await event_log.emit_runner_diagnostic(e.diagnostic)
        _push_sse(app_state, "notification", {
            "type": "runner_error",
            "agent_id": agent_id,
            "role": role,
            "code": e.diagnostic.code,
            "runner": e.diagnostic.runner,
            "stage": e.diagnostic.stage,
            "message": e.diagnostic.message,
            "details": e.diagnostic.details,
        })
        await event_log.close()
        del app_state.agents[agent_id]
        return 1

    # Spawn process
    log.info("spawning %s (agent_id=%s): %s", role, agent_id, " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=subagent_dir,
    )

    # Emit agent spawn to SSE
    _push_sse(app_state, "subagent", {
        "agent_id": agent_id,
        "role": role,
        "model": model,
        "step": 0,
        "startedAt": agent.started_at.isoformat(),
    })
    _push_sse(app_state, "agents", {
        "agents": [{"agent_id": a.agent_id, "role": a.role} for a in app_state.agents.values()]
    })

    # Stream tracking (telemetry only -- handshake detected via MCP path)
    async def stream_stdout():
        assert proc.stdout is not None
        last_tool: str | None = None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            events = runner.parse_stream_event(line)
            for ev in events:
                if ev.type == "token_delta":
                    agent.token_count["received"] = agent.token_count.get("received", 0) + len(ev.content or "")
                    _push_sse(app_state, "token-delta", {
                        "delta": ev.content,
                        "agent_id": agent_id,
                    })
                elif ev.type == "thinking":
                    _push_sse(app_state, "logs", {
                        "line": {
                            "tool": "thinking",
                            "summary": "thinking...",
                            "inFlight": True,
                            "ts": _now_iso(),
                        },
                        "agent_id": agent_id,
                    })
                elif ev.type == "tool_call":
                    agent.token_count["sent"] = agent.token_count.get("sent", 0) + len(ev.content or "")
                    # Close previous in-flight tool
                    if last_tool:
                        _push_sse(app_state, "logs", {
                            "line": {
                                "tool": last_tool,
                                "summary": "completed",
                                "inFlight": False,
                            },
                            "agent_id": agent_id,
                        })
                    last_tool = ev.tool_name
                    _push_sse(app_state, "logs", {
                        "line": {
                            "tool": ev.tool_name or "tool",
                            "summary": ev.content or "",
                            "inFlight": True,
                        },
                        "agent_id": agent_id,
                    })
                else:
                    _push_sse(app_state, "stream", {
                        "agent_id": agent_id,
                        "role": role,
                        "type": ev.type,
                        "content": ev.content,
                        "tool_name": ev.tool_name,
                    })

    async def drain_stderr():
        assert proc.stderr is not None
        buf: list[str] = []
        async for raw in proc.stderr:
            buf.append(raw.decode("utf-8", errors="replace"))
        return "".join(buf)

    stdout_task = asyncio.create_task(stream_stdout())
    stderr_task = asyncio.create_task(drain_stderr())

    # Wait for exit
    exit_code = await proc.wait()
    await stdout_task
    stderr_output = await stderr_task

    if stderr_output.strip():
        log.warning("stderr from %s (agent_id=%s): %s", role, agent_id, stderr_output[:500])

    # Handshake check (uses MCP-path flag, works for all runners)
    if not agent.handshake_observed:
        diag = RunnerDiagnostic(
            code="bootstrap_failure",
            runner=runner.name,
            stage="handshake",
            message="Process exited before first koan_complete_step call",
        )
        await event_log.emit_runner_diagnostic(diag)
        _push_sse(app_state, "notification", {
            "type": "bootstrap_failure",
            "agent_id": agent_id,
            "role": role,
            "code": diag.code,
            "runner": diag.runner,
            "stage": diag.stage,
            "message": diag.message,
            "details": diag.details,
        })
        exit_code = 1

    # Cleanup: resolve pending interactions for this agent
    _cancel_pending_interactions(agent_id, app_state)

    # Finalize
    outcome = "completed" if exit_code == 0 else "failed"
    await event_log.emit_phase_end(outcome)
    await event_log.close()
    del app_state.agents[agent_id]

    # Emit subagent-idle and updated agents list
    _push_sse(app_state, "subagent-idle", {})
    _push_sse(app_state, "agents", {
        "agents": [{"agent_id": a.agent_id, "role": a.role} for a in app_state.agents.values()]
    })

    log.info("%s (agent_id=%s) exited with code %d", role, agent_id, exit_code)
    return exit_code


# -- SSE push helper -----------------------------------------------------------

def _push_sse(app_state: AppState, event_type: str, payload: dict) -> None:
    """Forward to driver.push_sse (imported lazily to avoid circular imports)."""
    from .driver import push_sse
    push_sse(app_state, event_type, payload)


# -- Interaction cleanup -------------------------------------------------------

def _cancel_pending_interactions(agent_id: str, app_state: AppState) -> None:
    """Resolve any pending/queued blocking interactions for this agent."""
    from .web.interactions import activate_next_interaction

    error_result = {"error": "agent_exited", "message": "Agent process exited"}

    # Collect and cancel all interactions belonging to agent_id (queue first,
    # then active) before promoting any next interaction.  This prevents
    # activate_next_interaction() from promoting another queued interaction
    # from the same exiting agent into the active slot.

    remaining = []
    for item in app_state.interaction_queue:
        if item.agent_id == agent_id:
            if not item.future.done():
                item.future.set_result(error_result)
            _push_sse(app_state, "notification", {
                "type": "interaction_cancelled",
                "agent_id": agent_id,
            })
        else:
            remaining.append(item)
    app_state.interaction_queue.clear()
    app_state.interaction_queue.extend(remaining)

    active = app_state.active_interaction
    if active is not None and active.agent_id == agent_id:
        if not active.future.done():
            active.future.set_result(error_result)
        _push_sse(app_state, "notification", {
            "type": "interaction_cancelled",
            "agent_id": agent_id,
        })
        activate_next_interaction(app_state)
