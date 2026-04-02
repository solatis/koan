# Subagent manager -- spawn, monitor, and cleanup subagent processes.
# Replaces the T6 stub in driver.py with a complete lifecycle implementation.

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

from .audit import EventLog
from .epic_state import ensure_subagent_directory
from .events import (
    build_agent_exited,
    build_agent_spawn_failed,
    build_agent_spawned,
    build_artifact_reviewed,
    build_questions_answered,
    build_tool_bash,
    build_tool_called,
    build_tool_completed,
    build_tool_edit,
    build_tool_grep,
    build_tool_ls,
    build_tool_read,
    build_tool_write,
    build_workflow_decided,
)
from .logger import get_logger
from .phases import PHASE_MODULE_MAP, PhaseContext
from .runners import RunnerDiagnostic, RunnerError
from .runners.registry import RunnerRegistry

if TYPE_CHECKING:
    from .runners.base import Runner
    from .state import AppState

log = get_logger("subagent")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubagentResult:
    exit_code: int
    final_response: str = ""


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
        project_dir=task.get("project_dir", ""),
        task_description=task.get("task_description", ""),
        phase_instructions=task.get("instructions") or task.get("phase_instructions") or task.get("task"),
        story_id=task.get("story_id"),
        step_sequence=task.get("step_sequence"),
        completed_phase=task.get("completed_phase"),
        available_phases=task.get("available_phases", []),
        scout_question=task.get("question"),
        scout_investigator_role=task.get("investigator_role"),
        retry_context=task.get("retryContext") or task.get("retry_context"),
    )


# -- Main spawn function -------------------------------------------------------

async def spawn_subagent(task: dict, app_state: AppState, runner: Runner | None = None) -> SubagentResult:
    role = task["role"]
    agent_id = str(uuid.uuid4())
    store = app_state.projection_store

    # Own directory creation -- derive if not provided, ensure it exists
    subagent_dir = task.get("subagent_dir", "")
    if not subagent_dir:
        epic_dir = task.get("epic_dir", "")
        label = f"{role}-{agent_id[:8]}"
        subagent_dir = await ensure_subagent_directory(epic_dir, label)
        task["subagent_dir"] = subagent_dir
    else:
        Path(subagent_dir).mkdir(parents=True, exist_ok=True)

    # Resolve runner via registry
    if runner is None:
        try:
            config = app_state.config
            registry = RunnerRegistry()
            installation, model_alias, thinking_mode = registry.resolve_agent_config(
                role, config,
                balanced_profile=app_state.balanced_profile,
                run_installations=app_state.run_installations,
            )

            runner = registry.get_runner(installation.runner_type, subagent_dir)
            model = model_alias
        except RunnerError as e:
            log.error("runner resolution failed for %s: %s", role, e.diagnostic.message)
            # Write diagnostic to EventLog
            try:
                event_log = EventLog(subagent_dir, role, phase=role, model=None)
                await event_log.open()
                await event_log.emit_runner_diagnostic(e.diagnostic)
                await event_log.close()
            except Exception:
                log.warning("failed to write diagnostic event log for %s", role)
            store.push_event(
                "agent_spawn_failed",
                build_agent_spawn_failed(role, e.diagnostic),
            )
            return SubagentResult(exit_code=1)
    else:
        model = None
        installation = None
        thinking_mode = None

    # Write task.json
    mcp_url = f"http://127.0.0.1:{app_state.port}/mcp/?agent_id={agent_id}"
    task_on_disk = {**task, "mcp_url": mcp_url}
    await write_task_json(subagent_dir, task_on_disk)

    # Build PhaseContext
    phase_ctx = _build_phase_ctx(task, subagent_dir)

    # Look up phase module
    phase_module = PHASE_MODULE_MAP.get(role)
    if phase_module is None:
        log.error("no phase module for role %s", role)
        return SubagentResult(exit_code=1)

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
        label=task.get("label", ""),
        step=0,
        phase_module=phase_module,
        phase_ctx=phase_ctx,
        event_log=event_log,
        model=model,
        is_primary=(role != "scout"),
    )
    app_state.agents[agent_id] = agent

    # Emit phase start to audit log
    await event_log.emit_phase_start(phase_module.TOTAL_STEPS)

    # Build command before emitting agent_spawned -- if build_command fails, no
    # agent_spawned event is emitted (per plan: "the agent was never launched").
    system_prompt = getattr(phase_module, "SYSTEM_PROMPT", "") or ""
    try:
        if installation is not None and thinking_mode is not None:
            cmd = runner.build_command(
                boot_prompt(role), mcp_url, installation, model, thinking_mode,
                system_prompt=system_prompt,
            )
        else:
            cmd = runner.build_command(boot_prompt(role), mcp_url, model,
                                       system_prompt=system_prompt)
    except RunnerError as e:
        await event_log.emit_runner_diagnostic(e.diagnostic)
        store.push_event(
            "agent_spawn_failed",
            build_agent_spawn_failed(role, e.diagnostic),
        )
        await event_log.close()
        del app_state.agents[agent_id]
        return SubagentResult(exit_code=1)

    # Emit agent_spawned only after build_command succeeds -- process is about to start
    store.push_event("agent_spawned", build_agent_spawned(agent), agent_id=agent_id)

    # Spawn process — cwd is the project directory so that tools like
    # `find .`, `ls`, `grep -r` naturally scope to the user's codebase.
    # Falls back to subagent_dir if project_dir is unavailable.
    spawn_cwd = task.get("project_dir") or subagent_dir
    log.info("spawning %s (agent_id=%s) cwd=%s: %s", role, agent_id, spawn_cwd, " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=spawn_cwd,
    )
    app_state._active_processes[agent_id] = proc

    # Stream tracking
    async def stream_stdout():
        assert proc.stdout is not None
        last_tool_name: str | None = None
        last_call_id: str | None = None

        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            events = runner.parse_stream_event(line)
            for ev in events:
                # Close in-flight tool when the LLM moves on to thinking
                # or text output -- those signal the previous tool is done.
                if ev.type in ("token_delta", "thinking") and last_call_id is not None:
                    store.push_event(
                        "tool_completed",
                        build_tool_completed(last_call_id, last_tool_name),
                        agent_id=agent_id,
                    )
                    last_call_id = None
                    last_tool_name = None

                if ev.type == "token_delta":
                    agent.token_count["received"] = agent.token_count.get("received", 0) + len(ev.content or "")
                    store.push_event("stream_delta", {"delta": ev.content or ""}, agent_id=agent_id)
                elif ev.type == "thinking":
                    store.push_event("thinking", {"delta": ev.content or ""}, agent_id=agent_id)
                elif ev.type == "assistant_text":
                    if ev.content:
                        agent.final_response = ev.content
                elif ev.type == "tool_call":
                    # Close previous in-flight tool
                    if last_call_id is not None and last_tool_name is not None:
                        store.push_event(
                            "tool_completed",
                            build_tool_completed(last_call_id, last_tool_name),
                            agent_id=agent_id,
                        )
                    # Open new tool call — emit typed event for recognized tools
                    call_id = str(uuid.uuid4())
                    tool_name = ev.tool_name or "tool"
                    summary = ev.summary or ""
                    if tool_name == "read":
                        # Separate file path from optional line range (e.g. "foo.py:10-20")
                        file_part, lines_part = summary, ""
                        if ":" in summary:
                            head, tail = summary.rsplit(":", 1)
                            if tail and (tail[0].isdigit() or "-" in tail):
                                file_part, lines_part = head, tail
                        store.push_event(
                            "tool_read",
                            build_tool_read(call_id, file_part, lines_part),
                            agent_id=agent_id,
                        )
                    elif tool_name == "write":
                        store.push_event("tool_write", build_tool_write(call_id, summary), agent_id=agent_id)
                    elif tool_name == "edit":
                        store.push_event("tool_edit", build_tool_edit(call_id, summary), agent_id=agent_id)
                    elif tool_name == "bash":
                        store.push_event("tool_bash", build_tool_bash(call_id, summary), agent_id=agent_id)
                    elif tool_name == "grep":
                        store.push_event("tool_grep", build_tool_grep(call_id, summary), agent_id=agent_id)
                    elif tool_name == "ls":
                        store.push_event("tool_ls", build_tool_ls(call_id, summary), agent_id=agent_id)
                    else:
                        store.push_event(
                            "tool_called",
                            build_tool_called(call_id, tool_name, ev.tool_args or {}, summary),
                            agent_id=agent_id,
                        )
                    last_call_id = call_id
                    last_tool_name = tool_name
                elif ev.type == "turn_complete":
                    # Dropped -- stream_cleared at stdout EOF covers end-of-stream
                    pass
                # All other unrecognized types are silently dropped

        # Close any in-flight tool at stdout EOF
        if last_call_id is not None and last_tool_name is not None:
            store.push_event(
                "tool_completed",
                build_tool_completed(last_call_id, last_tool_name),
                agent_id=agent_id,
            )

        # Tombstone: mark end of this agent's stream
        store.push_event("stream_cleared", {}, agent_id=agent_id)

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

    # Handshake check
    error_str: str | None = None
    if not agent.handshake_observed:
        diag = RunnerDiagnostic(
            code="bootstrap_failure",
            runner=runner.name,
            stage="handshake",
            message="Process exited before first koan_complete_step call",
        )
        await event_log.emit_runner_diagnostic(diag)
        error_str = "bootstrap_failure"
        exit_code = 1

    # Cleanup: remove from active processes, resolve pending interactions
    app_state._active_processes.pop(agent_id, None)
    _cancel_pending_interactions(agent_id, app_state)

    # Finalize audit log
    outcome = "completed" if exit_code == 0 else "failed"
    await event_log.emit_phase_end(outcome)
    await event_log.close()

    final_response = agent.final_response
    del app_state.agents[agent_id]

    # Emit agent_exited to projection
    token_usage = {
        "input_tokens": agent.token_count.get("sent", 0),
        "output_tokens": agent.token_count.get("received", 0),
    }
    store.push_event(
        "agent_exited",
        build_agent_exited(exit_code, error=error_str, usage=token_usage),
        agent_id=agent_id,
    )

    log.info("%s (agent_id=%s) exited with code %d", role, agent_id, exit_code)
    return SubagentResult(exit_code=exit_code, final_response=final_response)


# -- Interaction cleanup -------------------------------------------------------

def _cancel_pending_interactions(agent_id: str, app_state: AppState) -> None:
    """Resolve any pending/queued blocking interactions for this agent.

    Queued interactions are cancelled silently (no projection event).
    The active interaction (if it belongs to this agent) emits a typed
    cancellation resolution event.
    """
    from .web.interactions import activate_next_interaction

    error_result = {"error": "agent_exited", "message": "Agent process exited"}
    store = app_state.projection_store

    # Cancel queued interactions belonging to this agent silently
    remaining = []
    for item in app_state.interaction_queue:
        if item.agent_id == agent_id:
            if not item.future.done():
                item.future.set_result(error_result)
            # No projection event for queued (never-active) interactions
        else:
            remaining.append(item)
    app_state.interaction_queue.clear()
    app_state.interaction_queue.extend(remaining)

    # Cancel active interaction with a typed cancellation event
    active = app_state.active_interaction
    if active is not None and active.agent_id == agent_id:
        token = active.token

        if active.type == "ask":
            store.push_event(
                "questions_answered",
                build_questions_answered(token, answers=None, cancelled=True),
                agent_id=agent_id,
            )
        elif active.type == "artifact-review":
            store.push_event(
                "artifact_reviewed",
                build_artifact_reviewed(token, accepted=None, response=None, cancelled=True),
                agent_id=agent_id,
            )
        elif active.type == "workflow-decision":
            store.push_event(
                "workflow_decided",
                build_workflow_decided(token, decision=None, cancelled=True),
                agent_id=agent_id,
            )

        if not active.future.done():
            active.future.set_result(error_result)
        activate_next_interaction(app_state)
