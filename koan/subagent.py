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
    build_tool_failed,
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
# (or tool_failed, when argument validation rejects the call) events emitted by
# the streaming loop. No per-tool-type emission path remains.
#
# CLAUDE_TOOL_WHITELISTS and _build_claude_tool_lists removed in M4: the HTTP
# MCP transport and the CLI Claude agent are deleted; the in-process PydanticAI
# agent has no use for per-role CLI tool whitelists.


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubagentResult:
    exit_code: int
    final_response: str = ""
    error: str | None = None


# -- Boot prompt ---------------------------------------------------------------
# boot_prompt removed in M6: the loop bootstrap calls _step_phase_handshake_core
# directly, so no one-sentence boot directive is needed. The first step's
# guidance is injected as the first turn's prompt.

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
        # Reviewer sub-agent fields: populated from task.json written by
        # _spawn_reviewer in koan/tools/koan_tools.py.
        reviewer_target=task.get("reviewer_target"),
        reviewer_prompt=task.get("reviewer_prompt"),
    )


# -- Main spawn function -------------------------------------------------------

async def spawn_subagent(
    task: dict,
    app_state: AppState,
    agent_impl: Agent | None = None,
) -> SubagentResult:
    """Spawn an in-process subagent via the Agent abstraction.

    Resolves a PydanticAIAgent (via AgentRegistry) when none is injected.
    Model resolution reads app_state.run.frozen_config (the per-run frozen
    snapshot denormalized at /api/start-run) so mid-run settings changes
    never affect an active run.

    Opens an event log, registers AgentState, drives agent_impl.run(options)
    to completion, and translates yielded StreamEvents into projection events.

    The handshake gate (agent.first_turn_completed on the AgentState) is
    enforced at exit; bootstrap_failure diagnostics are emitted when not set.
    first_turn_completed is set by run_agent_loop once the first turn reaches
    the End node.

    M4: mcp_url plumbing, installation field, and available_tools/allowed_tools
    removed -- the HTTP MCP transport and CLI/SDK agent path are deleted.

    Variable-naming discipline: 'agent' always refers to the AgentState
    instance (e.g. agent.first_turn_completed). The Agent Protocol instance
    is always 'agent_impl'. They must never be confused -- the handshake
    check reads agent.first_turn_completed (AgentState), not agent_impl.
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

    # M1->M2 seam: resolve the ModelSpec for the role, then raise NotImplementedError.
    # Legacy SDK/CLI agent construction is intentionally non-functional after the
    # M1 config reshape -- the new spawn path is wired to PydanticAIAgent in M2.
    # agent_impl is still accepted as an injection point for tests that bypass
    # the registry entirely (FakeAgent path).
    if agent_impl is None:
        try:
            # The spawn path reads the per-run frozen config (denormalized at
            # start-run) so the run is immune to mid-run settings changes.
            if app_state.run.frozen_config is None:
                raise AgentError(AgentDiagnostic(
                    code="unconfigured",
                    agent="",
                    stage="resolve_model_spec",
                    message=(
                        "No frozen run config available. "
                        "/api/start-run must complete before spawning agents."
                    ),
                ))
            config = app_state.run.frozen_config
            registry = AgentRegistry()
            # resolve_model_spec replaces resolve_agent_config; returns a ModelSpec.
            # M5: builtin_profiles param removed from resolve_model_spec.
            # The spec now carries its baked api_key resolved from the frozen store.
            model_spec = registry.resolve_model_spec(role, config, app_state.run.frozen_credential_store)
            # M2 seam: PydanticAIAgent wired here; the legacy binary spawn path
            # is non-functional after the M1 config reshape.
            # Lazy import to avoid a circular dependency: koan/agents imports from
            # koan/subagent (indirectly via events/state), so importing PydanticAIAgent
            # at module level would create a cycle.
            from .agents.pydantic_ai import PydanticAIAgent
            agent_impl = PydanticAIAgent(
                model_spec=model_spec,
                app_state=app_state,
                subagent_dir=subagent_dir,
            )
            # model, installation, thinking_mode are legacy fields consumed by
            # the AgentOptions constructor below. PydanticAIAgent does not use
            # them (it reads model_spec directly); set them to None so the
            # AgentOptions is constructed cleanly without AttributeError.
            model = model_spec.model
            installation = None
            thinking_mode = None
            # Carry provider for the fold's cost derivation.
            provider = model_spec.provider
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
        # No model_spec when agent_impl is injected (test path); provider=None
        # signals the fold that cost derivation is unavailable for this agent.
        provider = None

    # Write task.json. mcp_url omitted in M4: the HTTP MCP transport is deleted
    # and the in-process agent reads tools from the PydanticAI toolset, not MCP.
    task_on_disk = dict(task)
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
        provider=provider,
        is_primary=(role == "orchestrator"),
        # runner_type carries the agent name ('claude', 'codex', 'gemini', 'fake'
        # in tests). Used by upload_ids_to_blocks and steering-drain routing (M2).
        runner_type=agent_impl.name if agent_impl is not None else "",
    )
    app_state.agents[agent_id] = agent

    # Emit phase start to audit log
    await event_log.emit_phase_start(phase_module.TOTAL_STEPS)

    # Construct AgentOptions. M4: mcp_url, available_tools, allowed_tools, and
    # installation removed -- the CLI/SDK agent path is deleted; PydanticAIAgent
    # reads model_spec directly.
    options = AgentOptions(
        role=role,
        agent_id=agent_id,
        model=model,
        thinking=thinking_mode,
        system_prompt=system_prompt,
        project_dir=task.get("project_dir", ""),
        run_dir=task.get("run_dir", ""),
        additional_dirs=task.get("additional_dirs", []),
        cwd=task.get("project_dir") or subagent_dir,
        extras={},
    )

    # In-process agents have no subprocess to register (M9 rip-out dropped the
    # register_process / active-process plumbing); spawn_subagent derives
    # success/failure from a raised AgentError or the handshake check below.

    # Emit agent_spawned now that AgentState is fully registered and we are
    # about to start iterating. build_command errors that used to abort before
    # this point now surface from within agent_impl.run() as AgentError.
    store.push_event("agent_spawned", build_agent_spawned(agent), agent_id=agent_id)

    log.info("running %s (agent_id=%s) via %s", role, agent_id, agent_impl.name)

    # Stream tracking -- same dicts as before; only the iteration source changes.
    call_ids_by_block: dict[int, tuple[str, str]] = {}
    call_id_by_tool_use_id: dict[str, str] = {}
    # Accumulate real token usage from StreamEvent.usage (set on turn_complete by
    # PydanticAIAgent). When populated, replaces the char-length token_count
    # approximation at agent_exited. CLI runners leave this None.
    accumulated_usage: dict | None = None
    # Captured if agent_impl.run() raises AgentError -- the in-process
    # replacement for the old agent_impl.exit_code / stderr_output reads.
    run_error: AgentError | None = None

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
                    build_tool_request(
                        call_id, tool_name, ev.tool_use_id or "",
                        ts_ms=int(time.time() * 1000),
                        tool_args=ev.tool_args,
                    ),
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
                    # to tool_result and both fire for read/grep/glob/bash/web_search/web_fetch).
                    if ev.tool_name in ("read", "grep", "glob", "bash", "web_search", "web_fetch"):
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
            elif ev.type == "tool_failed":
                # Argument validation rejected the call; the tool body never ran.
                # Same correlation as tool_result; both maps must be cleaned or
                # EOF cleanup re-emits a synthetic tool_result for a call whose
                # entry the fold has already replaced with a ToolFailedEntry.
                tool_use_id = ev.tool_use_id or ""
                cid = call_id_by_tool_use_id.pop(tool_use_id, None)
                if cid is not None:
                    store.push_event(
                        "tool_failed",
                        build_tool_failed(
                            cid,
                            ev.tool_name or "",
                            error=ev.content or "",
                            ts_ms=int(time.time() * 1000),
                        ),
                        agent_id=agent_id,
                    )
                    to_remove = [k for k, (v, _) in call_ids_by_block.items() if v == cid]
                    for k in to_remove:
                        del call_ids_by_block[k]
            elif ev.type == "turn_complete":
                # Accumulate real token usage from PydanticAIAgent's RequestUsage.
                # CLI runners emit turn_complete without usage; None is ignored here
                # so the char-length fallback at agent_exited remains for those paths.
                # cache_read/write_tokens are SUMMED (billing is cumulative).
                # last_input_tokens is OVERWRITTEN each turn (not summed): the latest
                # request's input embeds the full conversation history, so it reflects
                # current context fullness for the context-window gauge.
                if ev.usage is not None:
                    if accumulated_usage is None:
                        accumulated_usage = {
                            "input_tokens": ev.usage.input_tokens,
                            "output_tokens": ev.usage.output_tokens,
                            "cache_read_tokens": ev.usage.cache_read_tokens or 0,
                            "cache_write_tokens": ev.usage.cache_write_tokens or 0,
                            "last_input_tokens": ev.usage.input_tokens,
                        }
                    else:
                        accumulated_usage["input_tokens"] += ev.usage.input_tokens
                        accumulated_usage["output_tokens"] += ev.usage.output_tokens
                        accumulated_usage["cache_read_tokens"] = (
                            accumulated_usage.get("cache_read_tokens", 0)
                            + (ev.usage.cache_read_tokens or 0)
                        )
                        accumulated_usage["cache_write_tokens"] = (
                            accumulated_usage.get("cache_write_tokens", 0)
                            + (ev.usage.cache_write_tokens or 0)
                        )
                        # Overwrite last_input_tokens each turn (not cumulative sum).
                        accumulated_usage["last_input_tokens"] = ev.usage.input_tokens
            else:
                log.debug(
                    "unknown stream event type=%s agent=%s",
                    ev.type, agent_id[:8],
                )

    except AgentError as e:
        # Agent raised a structured failure during run(). Write to event log
        # and emit a spawn_failed projection event.
        run_error = e
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

    # Derive exit code + failure detail from the run. In-process agents have no
    # subprocess: a clean run() is success (0), a raised AgentError is failure
    # (1, with the diagnostic as the stderr-equivalent). The handshake check
    # below can still override to 1 (bootstrap failure).
    exit_code = 1 if run_error is not None else 0
    stderr_output = run_error.diagnostic.message if run_error is not None else ""

    if stderr_output.strip():
        log.warning("stderr from %s (agent_id=%s): %s", role, agent_id, stderr_output[:500])

    # Handshake check -- uses agent (AgentState), NOT agent_impl.
    # agent.first_turn_completed is set by run_agent_loop at end-of-turn-1;
    # failure to set it means the agent exited before completing its first turn.
    # Confusing agent with agent_impl here would silently break detection.
    error_str: str | None = None
    if not agent.first_turn_completed:
        diag = AgentDiagnostic(
            code="bootstrap_failure",
            agent=agent_impl.name,
            stage="handshake",
            message="Process exited before completing its first turn",
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

    # Cleanup: resolve pending interactions for this agent.
    _cancel_pending_interactions(agent_id, app_state)

    # Finalize audit log
    outcome = "completed" if exit_code == 0 else "failed"
    await event_log.emit_phase_end(outcome, detail=error_str)
    await event_log.close()

    final_response = agent.final_response
    del app_state.agents[agent_id]

    # Emit agent_exited to projection.
    # Use real token usage from PydanticAIAgent's StreamEvent.usage when available;
    # fall back to the char-length token_count approximation for CLI runners that
    # do not carry RequestUsage on turn_complete events.
    if accumulated_usage is not None:
        token_usage = accumulated_usage
    else:
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
