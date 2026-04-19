# Subagent manager -- spawn, monitor, and cleanup subagent processes.

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

from .audit import EventLog
from .run_state import ensure_subagent_directory
from .events import (
    build_agent_exited,
    build_agent_spawn_failed,
    build_agent_spawned,
    build_questions_answered,
    build_tool_bash,
    build_tool_called,
    build_tool_completed,
    build_tool_edit,
    build_tool_grep,
    build_tool_ls,
    build_tool_read,
    build_tool_result_captured,
    build_tool_started,
    build_tool_stopped,
    build_tool_write,
)
from .logger import get_logger
from .lib.workflows import get_workflow
from .phases import PHASE_MODULE_MAP, PhaseContext
from .prompts import AGENT_TYPE_PROMPTS
from .runners import RunnerDiagnostic, RunnerError
from .runners.registry import RunnerRegistry

if TYPE_CHECKING:
    from .runners.base import Runner
    from .state import AppState

log = get_logger("subagent")


def _emit_exploration_tool_completion(
    store,
    agent_id: str,
    call_id: str,
    tool_name: str,
    summary: str,
    now_ms: int,
) -> None:
    """Emit the typed projection event + tool_completed for a streaming read/grep/ls.

    Called from stream_stdout's tool_stop handler when Claude's streaming path
    finishes an exploration tool. The args are finalized at tool_stop, so this
    helper can create the aggregate child and close it in one step. Child
    metric fields stay None until a matching tool_result_captured arrives
    from a later user message.
    """
    if tool_name == "read":
        file_part, lines_part = summary, ""
        if ":" in summary:
            head, tail = summary.rsplit(":", 1)
            if tail and (tail[0].isdigit() or "-" in tail):
                file_part, lines_part = head, tail
        store.push_event(
            "tool_read",
            build_tool_read(call_id, file_part, lines_part, ts_ms=now_ms),
            agent_id=agent_id,
        )
    elif tool_name == "grep":
        store.push_event(
            "tool_grep",
            build_tool_grep(call_id, summary, ts_ms=now_ms),
            agent_id=agent_id,
        )
    else:  # ls
        store.push_event(
            "tool_ls",
            build_tool_ls(call_id, summary, ts_ms=now_ms),
            agent_id=agent_id,
        )
    store.push_event(
        "tool_completed",
        build_tool_completed(call_id, tool_name, ts_ms=now_ms),
        agent_id=agent_id,
    )

# -- Tool whitelists (Claude Code --tools) -------------------------------------
#
# Agents should not have access to tools they are never intended to need.
# Restricting the tool vocabulary at the CLI level prevents the model from
# even seeing irrelevant tools (EnterPlanMode, Agent, TaskCreate, etc.),
# which reduces misbehavior and token waste.  The MCP permission fence
# remains the authority for koan-specific tools; this whitelist controls
# only Claude Code built-in tools.
#
# These are Claude Code PascalCase tool names.  Other runners (codex, gemini)
# have their own mechanisms and are not affected by this whitelist.

CLAUDE_TOOL_WHITELISTS: dict[str, str] = {
    "orchestrator": "Read,Write,Edit,Bash,Glob,Grep,WebFetch,WebSearch",
    "executor":     "Read,Write,Edit,Bash,Glob,Grep,TaskCreate,TaskUpdate,TaskList,TaskGet,TaskStop,TaskOutput",
    "scout":        "Read,Bash,Glob,Grep",
}


def _claude_post_build_args(role: str, run_dir: str, project_dir: str) -> list[str]:
    """Compose claude-only post-build args: tool whitelist, slash-command disable,
    strict MCP config, additional directories, and permission mode.

    Returns a list of argv entries to append to a claude command. Pure function --
    no I/O, no globals beyond the CLAUDE_TOOL_WHITELISTS module constant.

    project_dir is listed before run_dir so the project is searched first.
    Empty dir strings are skipped to avoid passing --add-dir "" to the CLI.
    """
    args: list[str] = []
    whitelist = CLAUDE_TOOL_WHITELISTS.get(role)
    if whitelist is not None:
        args.extend(["--tools", whitelist])
    args.append("--disable-slash-commands")
    args.append("--strict-mcp-config")
    # Add project and run directories so the CLI can read/edit files in both
    # locations without prompting; acceptEdits gates writes at the tool level.
    if project_dir:
        args.extend(["--add-dir", project_dir])
    if run_dir:
        args.extend(["--add-dir", run_dir])
    # acceptEdits is safe for all roles: the CLAUDE_TOOL_WHITELISTS already
    # restrict which roles receive Write/Edit in their tool vocabulary, so
    # scouts cannot write even though the permission mode is permissive.
    args.extend(["--permission-mode", "acceptEdits"])
    return args


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
        run_dir=task.get("run_dir", ""),
        subagent_dir=subagent_dir,
        project_dir=task.get("project_dir", ""),
        task_description=task.get("task_description", ""),
        workflow_name=task.get("workflow", ""),
        phase_instructions=task.get("instructions") or task.get("phase_instructions") or task.get("task"),
        executor_artifacts=task.get("artifacts", []),
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
        run_dir = task.get("run_dir", "")
        label = f"{role}-{agent_id[:8]}"
        subagent_dir = await ensure_subagent_directory(run_dir, label)
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
                builtin_profiles=app_state.builtin_profiles,
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

    # Look up phase module and system prompt.
    # Persistent orchestrator: uses the workflow's initial_phase to select
    # the step-guidance module. This must agree with driver.py which sets
    # app_state.phase = workflow.initial_phase. Falls back to "plan"
    # workflow when no workflow name is on the task.
    if role == "orchestrator":
        workflow_name = task.get("workflow", "plan")
        workflow = get_workflow(workflow_name)
        phase_module = workflow.get_module(workflow.initial_phase)
    else:
        phase_module = PHASE_MODULE_MAP.get(role)

    # Agent-type system prompt -- per role, not per phase.
    system_prompt = AGENT_TYPE_PROMPTS.get(role, "")

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
        run_dir=task.get("run_dir", ""),
        label=task.get("label", ""),
        step=0,
        phase_module=phase_module,
        phase_ctx=phase_ctx,
        event_log=event_log,
        model=model,
        is_primary=(role == "orchestrator"),
    )
    app_state.agents[agent_id] = agent

    # Emit phase start to audit log
    await event_log.emit_phase_start(phase_module.TOTAL_STEPS)

    # Build command before emitting agent_spawned -- if build_command fails, no
    # agent_spawned event is emitted (per plan: "the agent was never launched").
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

    # Claude-specific post-build: tool whitelist, slash-command disable,
    # strict MCP config, additional working directories, and permission mode.
    if runner.name == "claude":
        cmd.extend(_claude_post_build_args(
            role=role,
            run_dir=task.get("run_dir", ""),
            project_dir=task.get("project_dir", ""),
        ))

    # Emit agent_spawned only after build_command succeeds -- process is about to start
    store.push_event("agent_spawned", build_agent_spawned(agent), agent_id=agent_id)

    # Spawn process — cwd is the project directory so that tools like
    # `find .`, `ls`, `grep -r` naturally scope to the user's codebase.
    # Falls back to subagent_dir if project_dir is unavailable.
    spawn_cwd = task.get("project_dir") or subagent_dir
    log.info("spawning %s (agent_id=%s) cwd=%s: %s", role, agent_id, spawn_cwd, " ".join(cmd))
    # limit= raises the asyncio StreamReader per-line buffer above its 64 KB
    # default. A single stream-json event from the child CLI (long thinking
    # block, fat tool result, large assistant content envelope) routinely
    # exceeds 64 KB; readline() then raises LimitOverrunError and the scout's
    # output becomes unreadable mid-run.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=spawn_cwd,
        limit=4 * 1024 * 1024,
    )
    app_state._active_processes[agent_id] = proc

    # Stream tracking
    async def stream_stdout():
        assert proc.stdout is not None
        last_tool_name: str | None = None
        last_call_id: str | None = None
        streaming_call_ids: dict[int, tuple[str, str]] = {}
        # Map Claude's tool_use_id -> our local call_id so that later
        # tool_result events can be attributed to the correct projection entry.
        call_id_by_tool_use_id: dict[str, str] = {}

        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            try:
                events = runner.parse_stream_event(line)
            except Exception as exc:
                log.warning(
                    "parse_stream_event failed for %s (agent_id=%s): %s",
                    role, agent_id, exc,
                )
                for _idx, (cid, tname) in streaming_call_ids.items():
                    store.push_event(
                        "tool_stopped",
                        build_tool_stopped(cid, tname),
                        agent_id=agent_id,
                    )
                streaming_call_ids.clear()
                continue
            for ev in events:
                # Close implicit in-flight tool (non-streaming path) when
                # the LLM moves on to thinking or text output.
                if ev.type in ("token_delta", "thinking") and last_call_id is not None:
                    store.push_event(
                        "tool_completed",
                        build_tool_completed(
                            last_call_id, last_tool_name,
                            ts_ms=int(time.time() * 1000),
                        ),
                        agent_id=agent_id,
                    )
                    last_call_id = None
                    last_tool_name = None

                if ev.type == "tool_start":
                    if last_call_id is not None and last_tool_name is not None:
                        store.push_event(
                            "tool_completed",
                            build_tool_completed(
                                last_call_id, last_tool_name,
                                ts_ms=int(time.time() * 1000),
                            ),
                            agent_id=agent_id,
                        )
                        last_call_id = None
                        last_tool_name = None
                    call_id = str(uuid.uuid4())
                    tool_name = ev.tool_name or "tool"
                    block_idx = ev.block_index if ev.block_index is not None else -1
                    streaming_call_ids[block_idx] = (call_id, tool_name)
                    if tool_name in ("read", "grep", "ls"):
                        # Exploration tools defer their projection emission to
                        # tool_stop, where the full args are available. Capture
                        # the tool_use_id → call_id mapping now so a later
                        # tool_result block can find its aggregate child.
                        if ev.tool_use_id:
                            call_id_by_tool_use_id[ev.tool_use_id] = call_id
                    else:
                        # Non-exploration tools (bash/write/edit/custom) keep
                        # the ToolGenericEntry flow — tool_started creates the
                        # entry, tool_stopped attaches the summary.
                        store.push_event(
                            "tool_started",
                            build_tool_started(call_id, tool_name),
                            agent_id=agent_id,
                        )
                elif ev.type == "tool_input_delta":
                    pass
                elif ev.type == "tool_stop":
                    block_idx = ev.block_index if ev.block_index is not None else -1
                    pair = streaming_call_ids.pop(block_idx, None)
                    if pair is not None:
                        call_id, tool_name = pair
                        summary = ev.summary or ""
                        if tool_name in ("read", "grep", "ls"):
                            _emit_exploration_tool_completion(
                                store, agent_id, call_id, tool_name, summary,
                                now_ms=int(time.time() * 1000),
                            )
                        else:
                            store.push_event(
                                "tool_stopped",
                                build_tool_stopped(call_id, tool_name, summary),
                                agent_id=agent_id,
                            )
                elif ev.type == "token_delta":
                    agent.token_count["received"] = agent.token_count.get("received", 0) + len(ev.content or "")
                    store.push_event("stream_delta", {"delta": ev.content or ""}, agent_id=agent_id)
                elif ev.type == "thinking":
                    store.push_event("thinking", {"delta": ev.content or ""}, agent_id=agent_id)
                elif ev.type == "assistant_text":
                    if ev.content:
                        agent.final_response = ev.content
                elif ev.type == "tool_call":
                    if last_call_id is not None and last_tool_name is not None:
                        store.push_event(
                            "tool_completed",
                            build_tool_completed(
                                last_call_id, last_tool_name,
                                ts_ms=int(time.time() * 1000),
                            ),
                            agent_id=agent_id,
                        )
                    call_id = str(uuid.uuid4())
                    tool_name = ev.tool_name or "tool"
                    summary = ev.summary or ""
                    now_ms = int(time.time() * 1000)
                    if tool_name == "read":
                        file_part, lines_part = summary, ""
                        if ":" in summary:
                            head, tail = summary.rsplit(":", 1)
                            if tail and (tail[0].isdigit() or "-" in tail):
                                file_part, lines_part = head, tail
                        # tool_use_id lets tool_result_captured match this call
                        # later even though the call_id we assigned is local.
                        if ev.tool_use_id:
                            call_id_by_tool_use_id[ev.tool_use_id] = call_id
                        store.push_event(
                            "tool_read",
                            build_tool_read(call_id, file_part, lines_part, ts_ms=now_ms),
                            agent_id=agent_id,
                        )
                    elif tool_name == "write":
                        store.push_event("tool_write", build_tool_write(call_id, summary), agent_id=agent_id)
                    elif tool_name == "edit":
                        store.push_event("tool_edit", build_tool_edit(call_id, summary), agent_id=agent_id)
                    elif tool_name == "bash":
                        store.push_event("tool_bash", build_tool_bash(call_id, summary), agent_id=agent_id)
                    elif tool_name == "grep":
                        if ev.tool_use_id:
                            call_id_by_tool_use_id[ev.tool_use_id] = call_id
                        store.push_event(
                            "tool_grep",
                            build_tool_grep(call_id, summary, ts_ms=now_ms),
                            agent_id=agent_id,
                        )
                    elif tool_name == "ls":
                        if ev.tool_use_id:
                            call_id_by_tool_use_id[ev.tool_use_id] = call_id
                        store.push_event(
                            "tool_ls",
                            build_tool_ls(call_id, summary, ts_ms=now_ms),
                            agent_id=agent_id,
                        )
                    else:
                        store.push_event(
                            "tool_called",
                            build_tool_called(call_id, tool_name, ev.tool_args or {}, summary),
                            agent_id=agent_id,
                        )
                    last_call_id = call_id
                    last_tool_name = tool_name
                elif ev.type == "tool_result":
                    # Runner parsed a tool_result block from a user message.
                    # Map the LLM's tool_use_id back to our local call_id and
                    # emit a projection event carrying the parsed metrics.
                    tool_use_id = ev.tool_use_id or ""
                    cid = call_id_by_tool_use_id.get(tool_use_id)
                    if cid is not None:
                        store.push_event(
                            "tool_result_captured",
                            build_tool_result_captured(
                                cid,
                                ev.tool_name or "",
                                metrics=ev.metrics,
                            ),
                            agent_id=agent_id,
                        )
                elif ev.type == "turn_complete":
                    pass

        # Close any in-flight streaming tools at stdout EOF
        for _idx, (cid, tname) in streaming_call_ids.items():
            store.push_event(
                "tool_stopped",
                build_tool_stopped(cid, tname),
                agent_id=agent_id,
            )
        streaming_call_ids.clear()

        # Close any implicit in-flight tool at stdout EOF
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
    elif exit_code != 0:
        final = (agent.final_response or "").strip()
        stderr_lines = [l.strip() for l in stderr_output.splitlines() if l.strip()]
        stderr_tail = stderr_lines[-1] if stderr_lines else ""
        error_str = final or stderr_tail or f"exit_code={exit_code}"
        log.error(
            "%s (agent_id=%s) exited unexpectedly (exit_code=%d): %s",
            role, agent_id, exit_code, error_str,
        )

    # Cleanup: remove from active processes, resolve pending interactions
    app_state._active_processes.pop(agent_id, None)
    _cancel_pending_interactions(agent_id, app_state)

    # Finalize audit log
    outcome = "completed" if exit_code == 0 else "failed"
    await event_log.emit_phase_end(outcome, detail=error_str)
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

    log_fn = log.info if exit_code == 0 else log.warning
    log_fn("%s (agent_id=%s) exited with code %d", role, agent_id, exit_code)
    return SubagentResult(exit_code=exit_code, final_response=final_response)


# -- Interaction cleanup -------------------------------------------------------

def _cancel_pending_interactions(agent_id: str, app_state: AppState) -> None:
    """Resolve any pending/queued blocking interactions for this agent.

    Queued interactions are cancelled silently (no projection event).
    The active interaction (if it belongs to this agent) emits a typed
    cancellation resolution event.

    Also clears yield_future if the agent was blocked at a phase boundary.
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

        if not active.future.done():
            active.future.set_result(error_result)
        activate_next_interaction(app_state)

    # Clear yield_future if it was set (orchestrator crashed at phase boundary)
    if app_state.yield_future is not None and not app_state.yield_future.done():
        app_state.yield_future.set_result(False)
    app_state.yield_future = None
