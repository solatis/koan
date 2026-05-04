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

from .agents.base import Agent, AgentDiagnostic, AgentError, AgentOptions
from .agents.registry import AgentRegistry
from .audit import EventLog
from .run_state import ensure_subagent_directory
from .events import (
    build_agent_exited,
    build_agent_spawn_failed,
    build_agent_spawned,
    build_questions_answered,
    build_tool_input_delta,
    build_tool_request,
    build_tool_result,
    build_tool_result_captured,
)
from .logger import get_logger
from .lib.task_json import current_workflow
from .lib.workflows import get_workflow
from .phases import PHASE_MODULE_MAP, PhaseContext
from .prompts import AGENT_TYPE_PROMPTS

if TYPE_CHECKING:
    from .state import AppState

log = get_logger("subagent")


# _emit_exploration_tool_completion removed in M1: exploration tool lifecycle
# is now handled uniformly by the tool_request / tool_input_delta / tool_result
# events emitted by the streaming loop. No per-tool-type emission path remains.

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
#
# CLAUDE_TOOL_WHITELISTS stays in koan/subagent.py for M1 (Plan Decision 9).
# AgentOptions.available_tools is read from this dict at spawn time. A future
# milestone may move it into the agent registry once a clear consumer pattern
# emerges.

CLAUDE_TOOL_WHITELISTS: dict[str, str] = {
    "orchestrator": "Read,Write,Edit,Bash,Glob,Grep,WebFetch,WebSearch",
    "executor":     "Read,Write,Edit,Bash,Glob,Grep,TaskCreate,TaskUpdate,TaskList,TaskGet,TaskStop,TaskOutput",
    "scout":        "Read,Bash,Glob,Grep",
}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubagentResult:
    exit_code: int
    final_response: str = ""
    error: str | None = None


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
    """Build a PhaseContext from a task.json dict for any subagent role.

    Resolves workflow_name from workflow_history for the orchestrator and
    defaults to empty string for executor/scout subagents whose task.json
    does not carry the field. project_dir and additional_dirs are read
    from task.json verbatim and stored on the context so phase modules
    can render them in step prompts.
    """
    return PhaseContext(
        run_dir=task.get("run_dir", ""),
        subagent_dir=subagent_dir,
        project_dir=task.get("project_dir", ""),
        additional_dirs=task.get("additional_dirs", []),
        task_description=task.get("task_description", ""),
        # current_workflow reads workflow_history[-1]["name"]; returns "" when
        # absent so executor/scout task.json files behave identically to before.
        workflow_name=current_workflow(task, default=""),
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

async def spawn_subagent(
    task: dict,
    app_state: AppState,
    agent_impl: Agent | None = None,
) -> SubagentResult:
    """Spawn a subagent process via the Agent abstraction.

    Resolves an Agent (via AgentRegistry) when none is injected, opens an
    event log, registers AgentState, drives agent_impl.run(options) to
    completion, and translates yielded StreamEvents into projection events.

    The handshake gate (agent.handshake_observed on the AgentState) is
    enforced at exit; bootstrap_failure diagnostics are emitted when not
    observed.

    agent_impl.register_process registers the underlying process (if any)
    into app_state._active_processes for shutdown cancellation.

    Variable-naming discipline: 'agent' always refers to the AgentState
    instance (e.g. agent.handshake_observed). The Agent Protocol instance
    is always 'agent_impl'. They must never be confused -- the handshake
    check reads agent.handshake_observed (AgentState), not agent_impl.
    """
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

    # Resolve Agent via registry when not injected. model/installation/thinking
    # are None in the test-injection else-branch; AgentOptions receives dummy
    # values that FakeAgent ignores.
    if agent_impl is None:
        try:
            config = app_state.runner_config.config
            registry = AgentRegistry()
            installation, model_alias, thinking_mode = registry.resolve_agent_config(
                role, config,
                builtin_profiles=app_state.runner_config.builtin_profiles,
                run_installations=app_state.run.run_installations,
            )
            # Pass app_state so ClaudeSDKAgent can capture it in its PostToolUse
            # hook closure. CommandLineAgent ignores the extra parameter.
            agent_impl = registry.get_agent(installation.runner_type, subagent_dir, app_state)
            model = model_alias
        except AgentError as e:
            log.error("agent resolution failed for %s: %s", role, e.diagnostic.message)
            # Write diagnostic to EventLog
            try:
                event_log = EventLog(subagent_dir, role, phase=role, model=None)
                await event_log.open()
                await event_log.emit_agent_diagnostic(e.diagnostic)
                await event_log.close()
            except Exception:
                log.warning("failed to write diagnostic event log for %s", role)
            store.push_event(
                "agent_spawn_failed",
                build_agent_spawn_failed(role, e.diagnostic),
            )
            return SubagentResult(exit_code=1, error=e.diagnostic.message)
    else:
        model = None
        installation = None
        thinking_mode = None

    # Write task.json
    mcp_url = app_state.server.connect_back_url(f"/mcp/?agent_id={agent_id}")
    task_on_disk = {**task, "mcp_url": mcp_url}
    await write_task_json(subagent_dir, task_on_disk)
    log.debug(
        "task.json written: path=%s bytes=%d",
        subagent_dir, len(json.dumps(task_on_disk)),
    )

    # Build PhaseContext
    phase_ctx = _build_phase_ctx(task, subagent_dir)

    # Look up phase module and system prompt.
    # Persistent orchestrator: uses the workflow's initial_phase to select
    # the step-guidance module. This must agree with driver.py which sets
    # app_state.phase = workflow.initial_phase. Falls back to "plan" via
    # current_workflow when workflow_history is absent or empty.
    if role == "orchestrator":
        workflow_name = current_workflow(task, default="plan")
        workflow = get_workflow(workflow_name)
        phase_module = workflow.get_module(workflow.initial_phase)
    else:
        phase_module = PHASE_MODULE_MAP.get(role)

    # Agent-type system prompt -- per role, not per phase.
    system_prompt = AGENT_TYPE_PROMPTS.get(role, "")

    if phase_module is None:
        log.error("no phase module for role %s", role)
        return SubagentResult(exit_code=1, error=f"no phase module for role {role}")

    # Create EventLog
    event_log = EventLog(subagent_dir, role, phase=role, model=model)
    await event_log.open()

    # Register AgentState.
    # 'agent' (AgentState) is deliberately named distinct from 'agent_impl'
    # (Agent Protocol). All handshake checks, token tracking, and final_response
    # reads use 'agent'. All Protocol calls use 'agent_impl'.
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
        # runner_type carries the agent name ('claude', 'codex', 'gemini', 'fake'
        # in tests). Used by upload_ids_to_blocks and steering-drain routing (M2).
        runner_type=agent_impl.name if agent_impl is not None else "",
    )
    app_state.agents[agent_id] = agent

    # Emit phase start to audit log
    await event_log.emit_phase_start(phase_module.TOTAL_STEPS)

    # Construct AgentOptions. CLAUDE_TOOL_WHITELISTS stays in this file (Plan
    # Decision 9); AgentOptions.available_tools is built from it here.
    # In the test-injection else-branch, installation/thinking/model are None;
    # FakeAgent.run() ignores these fields, so dummy values are acceptable.
    from .types import AgentInstallation as _AgentInstallation
    options = AgentOptions(
        role=role,
        agent_id=agent_id,
        model=model,
        thinking=thinking_mode,
        system_prompt=system_prompt,
        boot_prompt=boot_prompt(role),
        mcp_url=mcp_url,
        available_tools=(
            CLAUDE_TOOL_WHITELISTS[role].split(",")
            if role in CLAUDE_TOOL_WHITELISTS else []
        ),
        # allowed_tools: claude requires pre-approval for MCP+Bash; others
        # have no equivalent flag and leave this empty.
        allowed_tools=(
            ["mcp__koan__*", "Bash"]
            if (installation is not None and installation.runner_type == "claude")
            else []
        ),
        project_dir=task.get("project_dir", ""),
        run_dir=task.get("run_dir", ""),
        additional_dirs=task.get("additional_dirs", []),
        cwd=task.get("project_dir") or subagent_dir,
        permission_mode="acceptEdits",
        installation=installation,
        extras={},
    )

    # Register the process into the active-process registry before iteration.
    # CommandLineAgent stores the registry reference and populates it as soon
    # as the subprocess is spawned inside run(). FakeAgent is a no-op.
    agent_impl.register_process(app_state._active_processes, agent_id)

    # Emit agent_spawned now that AgentState is fully registered and we are
    # about to start iterating. build_command errors that used to abort before
    # this point now surface from within agent_impl.run() as AgentError.
    store.push_event("agent_spawned", build_agent_spawned(agent), agent_id=agent_id)

    log.info("running %s (agent_id=%s) via %s", role, agent_id, agent_impl.name)

    # Stream tracking -- same dicts as before; only the iteration source changes.
    call_ids_by_block: dict[int, tuple[str, str]] = {}
    call_id_by_tool_use_id: dict[str, str] = {}

    try:
        async for ev in agent_impl.run(options):
            if ev.type == "tool_start":
                call_id = str(uuid.uuid4())
                tool_name = ev.tool_name or "tool"
                block_idx = ev.block_index if ev.block_index is not None else -1
                call_ids_by_block[block_idx] = (call_id, tool_name)
                # Record tool_use_id -> call_id so tool_result events
                # arriving later (from user message) can be correlated.
                if ev.tool_use_id:
                    call_id_by_tool_use_id[ev.tool_use_id] = call_id
                store.push_event(
                    "tool_request",
                    build_tool_request(call_id, tool_name, ev.tool_use_id or ""),
                    agent_id=agent_id,
                )
            elif ev.type == "tool_input_delta":
                block_idx = ev.block_index if ev.block_index is not None else -1
                pair = call_ids_by_block.get(block_idx)
                if pair is not None:
                    cid, tname = pair
                    store.push_event(
                        "tool_input_delta",
                        build_tool_input_delta(cid, tname, ev.tool_args, ev.content),
                        agent_id=agent_id,
                    )
            elif ev.type == "tool_stop":
                # content_block_stop signals args are final; no projection
                # event emitted (per intake decision 2 -- no tool_stop event).
                # Pop from call_ids_by_block to prevent EOF re-emit; the
                # tool_result projection event fires later when the user
                # message with the tool_result block arrives.
                block_idx = ev.block_index if ev.block_index is not None else -1
                call_ids_by_block.pop(block_idx, None)
            elif ev.type == "token_delta":
                agent.token_count["received"] = agent.token_count.get("received", 0) + len(ev.content or "")
                store.push_event("stream_delta", {"delta": ev.content or ""}, agent_id=agent_id)
            elif ev.type == "thinking":
                store.push_event("thinking", {"delta": ev.content or ""}, agent_id=agent_id)
            elif ev.type == "assistant_text":
                if ev.content:
                    agent.final_response = ev.content
            elif ev.type == "tool_result":
                # Agent parsed a tool_result block from a user message.
                # Map the LLM's tool_use_id back to our local call_id.
                tool_use_id = ev.tool_use_id or ""
                cid = call_id_by_tool_use_id.pop(tool_use_id, None)
                if cid is not None:
                    store.push_event(
                        "tool_result",
                        build_tool_result(
                            cid,
                            ev.tool_name or "",
                            result=ev.content,
                            attachments=ev.attachments,
                            metrics=ev.metrics,
                            ts_ms=int(time.time() * 1000),
                        ),
                        agent_id=agent_id,
                    )
                    # Also emit tool_result_captured for exploration tools so
                    # aggregate child metrics continue to populate (preserved
                    # per intake constraint -- tool_result_captured is orthogonal
                    # to tool_result and both fire for read/grep/ls).
                    if ev.tool_name in ("read", "grep", "ls"):
                        store.push_event(
                            "tool_result_captured",
                            build_tool_result_captured(
                                cid,
                                ev.tool_name,
                                metrics=ev.metrics,
                            ),
                            agent_id=agent_id,
                        )
                    # Remove from call_ids_by_block too (batch path: Codex/Gemini
                    # synthesize tool_result without a preceding tool_stop, so
                    # the block entry persists otherwise and EOF cleanup re-emits).
                    to_remove = [k for k, (v, _) in call_ids_by_block.items() if v == cid]
                    for k in to_remove:
                        del call_ids_by_block[k]
            elif ev.type == "turn_complete":
                pass
            else:
                log.debug(
                    "unknown stream event type=%s agent=%s",
                    ev.type, agent_id[:8],
                )

    except AgentError as e:
        # Agent raised a structured failure during run(). Write to event log
        # and emit a spawn_failed projection event.
        log.error(
            "AgentError during run for %s (agent_id=%s): %s",
            role, agent_id, e.diagnostic.message,
        )
        await event_log.emit_agent_diagnostic(e.diagnostic)
        store.push_event(
            "agent_spawn_failed",
            build_agent_spawn_failed(role, e.diagnostic),
        )

    # EOF cleanup -- degrade any in-flight streaming tools still open at EOF.
    # Under normal operation this dict is empty: streaming tools get their
    # block popped at tool_stop, and non-streaming at tool_result.
    # This path fires only on abnormal termination (process killed mid-stream).
    for _idx, (cid, tname) in call_ids_by_block.items():
        store.push_event(
            "tool_result",
            build_tool_result(cid, tname),
            agent_id=agent_id,
        )
    call_ids_by_block.clear()

    # Tombstone: mark end of this agent's stream
    store.push_event("stream_cleared", {}, agent_id=agent_id)

    # Collect exit code and stderr from agent_impl.
    # exit_code is None for FakeAgent (which does not spawn a process);
    # default to 0 so test doubles that set handshake_observed work correctly.
    raw_exit_code = agent_impl.exit_code
    exit_code = raw_exit_code if raw_exit_code is not None else 0
    stderr_output = agent_impl.stderr_output

    if stderr_output.strip():
        log.warning("stderr from %s (agent_id=%s): %s", role, agent_id, stderr_output[:500])

    # Handshake check -- uses agent (AgentState), NOT agent_impl.
    # This check must reference agent.handshake_observed (the MCP-path flag
    # set when koan_complete_step fires). Confusing agent with agent_impl here
    # would silently break bootstrap_failure detection.
    error_str: str | None = None
    if not agent.handshake_observed:
        diag = AgentDiagnostic(
            code="bootstrap_failure",
            agent=agent_impl.name,
            stage="handshake",
            message="Process exited before first koan_complete_step call",
        )
        await event_log.emit_agent_diagnostic(diag)
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
    return SubagentResult(exit_code=exit_code, final_response=final_response, error=error_str)


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
    original_queue_len = len(app_state.interactions.interaction_queue)
    remaining = []
    for item in app_state.interactions.interaction_queue:
        if item.agent_id == agent_id:
            if not item.future.done():
                item.future.set_result(error_result)
            # No projection event for queued (never-active) interactions
        else:
            remaining.append(item)
    app_state.interactions.interaction_queue.clear()
    app_state.interactions.interaction_queue.extend(remaining)

    cancelled_count = original_queue_len - len(remaining)
    if cancelled_count:
        log.debug(
            "cancelled %d queued interactions for agent=%s",
            cancelled_count, agent_id[:8],
        )

    # Cancel active interaction with a typed cancellation event
    active = app_state.interactions.active_interaction
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
        log.debug(
            "cancelled active interaction type=%s token=%s for agent=%s",
            active.type, active.token, agent_id[:8],
        )

    # Clear yield_future if it was set (orchestrator crashed at phase boundary)
    if app_state.interactions.yield_future is not None and not app_state.interactions.yield_future.done():
        app_state.interactions.yield_future.set_result(False)
    app_state.interactions.yield_future = None
