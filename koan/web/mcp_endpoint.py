# MCP endpoint -- fastmcp server with permission-fenced tool handlers.
#
# Exposes build_mcp_asgi_app() which returns an ASGI sub-app that:
#   1. Validates agent_id from query params before reaching fastmcp.
#   2. Runs check_permission() on every tool call.
#   3. Implements koan_complete_step, koan_yield, koan_request_scouts,
#      koan_ask_question, koan_set_phase, koan_request_executor,
#      and story management tools.
#
# Phase boundary flow:
#   koan_complete_step (last step) → format_phase_complete (non-blocking)
#   → orchestrator calls koan_yield(suggestions=[...])
#   → blocks on AppState.yield_future until POST /api/chat resolves it
#   → orchestrator converses, then calls koan_set_phase(phase) or koan_set_phase("done")
#
# koan_yield is phase-agnostic — it works wherever the orchestrator needs to
# pause for user input, not only at phase boundaries.
#
# koan_set_phase("done") is a tombstone: sets AppState.workflow_done = True,
# emits workflow_completed, and causes the next koan_complete_step to return
# an exit signal so the orchestrator process terminates cleanly.

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..run_state import (
    atomic_write_json,
    ensure_subagent_directory,
    load_story_state,
    save_run_state,
    save_story_state,
    load_run_state,
)
from ..lib.permissions import check_permission
from ..lib.workflows import get_suggested_phases, is_valid_transition as wf_is_valid
from ..logger import get_logger
from ..memory import MEMORY_TYPES, MemoryStore
from ..phases import PhaseContext, StepGuidance
from ..phases.format_step import format_phase_complete, format_steering_messages, format_step, format_user_messages
from .interactions import activate_next_interaction, enqueue_interaction
from ..projections import TextEntry

if TYPE_CHECKING:
    from ..state import AgentState, AppState

log = get_logger("mcp")

# Request-scoped agent state, set by the ASGI wrapper before fastmcp runs.
_agent_ctx: ContextVar[AgentState | None] = ContextVar("_agent_ctx", default=None)

# Module-level app_state reference, set by build_mcp_asgi_app().
_app_state: AppState | None = None

# Lazy-initialized per-process memory store, scoped to app_state.project_dir.
_memory_store: MemoryStore | None = None


def _get_memory_store() -> MemoryStore:
    """Return a MemoryStore bound to the current project directory."""
    global _memory_store
    if _memory_store is None:
        assert _app_state is not None
        store = MemoryStore(_app_state.project_dir or ".")
        store.init()
        _memory_store = store
    return _memory_store


def _reset_memory_store() -> None:
    """Test hook: clear the cached MemoryStore."""
    global _memory_store
    _memory_store = None

# -- fastmcp server -----------------------------------------------------------

mcp = FastMCP(name="koan")


def _check_or_raise(agent: AgentState, tool_name: str, tool_args: dict | None = None) -> None:
    phase_ctx = agent.phase_ctx
    resolved_run_dir = (
        phase_ctx.run_dir if phase_ctx is not None and phase_ctx.run_dir
        else agent.run_dir or None
    )
    current_phase = _app_state.phase if _app_state is not None else None
    result = check_permission(
        role=agent.role,
        tool_name=tool_name,
        run_dir=resolved_run_dir,
        tool_args=tool_args,
        current_step=agent.step,
        current_phase=current_phase,
    )
    if not result["allowed"]:
        raise ToolError(
            json.dumps({"error": "permission_denied", "message": result["reason"]})
        )


def _get_agent() -> AgentState:
    agent = _agent_ctx.get()
    if agent is None:
        raise ToolError(
            json.dumps({"error": "permission_denied", "message": "No agent context"})
        )
    return agent


def _log_tool_call(agent: AgentState, tool: str, summary: str) -> None:
    """Log an info-level message for every koan tool invocation."""
    phase = _app_state.phase if _app_state else "?"
    log.info(
        "tool %s | agent=%s role=%s phase=%s | %s",
        tool, agent.agent_id[:8], agent.role, phase, summary,
    )


def begin_tool_call(
    agent: AgentState,
    tool: str,
    args: dict | str,
    summary: str = "",
) -> str:
    """Log and emit tool_called event. Returns call_id."""
    call_id = str(uuid.uuid4())
    _log_tool_call(agent, tool, summary)
    if _app_state is None:
        return call_id
    from ..events import build_tool_called
    _app_state.projection_store.push_event(
        "tool_called",
        build_tool_called(call_id, tool, args, summary),
        agent_id=agent.agent_id,
    )
    return call_id


def end_tool_call(
    agent: AgentState,
    call_id: str,
    tool: str,
    result: str | None = None,
) -> None:
    """Emit tool_completed event. No-op if app_state is not set."""
    if _app_state is None:
        return
    from ..events import build_tool_completed
    _app_state.projection_store.push_event(
        "tool_completed",
        build_tool_completed(call_id, tool, result),
        agent_id=agent.agent_id,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_run_dir(agent: AgentState) -> str | None:
    phase_ctx = agent.phase_ctx
    if phase_ctx is not None and phase_ctx.run_dir:
        return phase_ctx.run_dir
    if agent.run_dir:
        return agent.run_dir
    if _app_state is not None and _app_state.run_dir:
        return _app_state.run_dir
    return None


# -- Steering queue helper -----------------------------------------------------

def _drain_and_append_steering(result: str, agent: AgentState | None = None) -> str:
    """Drain any queued steering messages and append to a tool result string.

    Only the primary agent (orchestrator) receives steering. Subagents
    (scouts, planners, executors) never see user steering messages.
    """
    if _app_state is None:
        return result
    if agent is not None and not agent.is_primary:
        return result
    from ..state import drain_steering_messages
    messages = drain_steering_messages(_app_state)
    if messages:
        previews = [m.content[:80] for m in messages]
        log.info(
            "steering delivered | %d message(s): %s",
            len(messages), previews,
        )
        result += format_steering_messages(messages)
        from ..events import build_steering_delivered
        _app_state.projection_store.push_event(
            "steering_delivered", build_steering_delivered(len(messages)),
        )
    return result


# -- RAG injection helpers ----------------------------------------------------

def _compose_rag_anchor(
    task_description: str,
    run_dir: str | None,
    prior_phase: str | None,
    phase_summaries: dict[str, str],
) -> str:
    """Compose the anchor string fed to rag.generate_queries().

    Order: task -> artifacts (mtime ascending) -> immediate prior-phase summary.
    Chronological artifact ordering puts the most recent artifact closest to
    the summary, placing the most directly relevant content last (where
    attention is strongest).
    """
    sections: list[str] = []
    if task_description:
        sections.append(f"# Task description\n\n{task_description}")

    if run_dir:
        run_dir_path = Path(run_dir)
        if run_dir_path.is_dir():
            md_files = sorted(
                (p for p in run_dir_path.glob("*.md") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
            for p in md_files:
                try:
                    body = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                sections.append(f"# Artifact: {p.name}\n\n{body}")

    if prior_phase:
        summary = phase_summaries.get(prior_phase, "")
        if summary:
            sections.append(f"# Prior phase summary ({prior_phase})\n\n{summary}")

    return "\n\n".join(sections)


async def _compute_memory_injection(agent: AgentState) -> str:
    """Run the mechanical RAG injection pipeline for the current phase.

    Returns a rendered markdown block, or "" if the phase has no retrieval
    directive, memory is unavailable, or retrieval fails. Retrieval is
    best-effort: failure must never block the phase handshake.
    """
    assert _app_state is not None
    workflow = _app_state.workflow
    if workflow is None:
        return ""
    binding = workflow.get_binding(_app_state.phase)
    if binding is None or not binding.retrieval_directive:
        return ""

    run = _app_state.projection_store.projection.run
    prior_phase = agent.phase_ctx.completed_phase
    phase_summaries = dict(run.phase_summaries) if run else {}

    anchor = _compose_rag_anchor(
        task_description=_app_state.task_description or "",
        run_dir=agent.phase_ctx.run_dir or _app_state.run_dir,
        prior_phase=prior_phase,
        phase_summaries=phase_summaries,
    )

    try:
        from ..memory.retrieval.rag import inject, render_injection_block
        index = _get_retrieval_index()
        results = await inject(
            index=index,
            directive=binding.retrieval_directive,
            anchor=anchor,
            k=5,
        )
        return render_injection_block(results)
    except Exception:
        log.warning(
            "mechanical memory injection failed for phase %r; continuing without injection",
            _app_state.phase,
            exc_info=True,
        )
        return ""


# -- koan_complete_step private helpers ----------------------------------------

async def _step_phase_handshake(agent: AgentState) -> str:
    """Handle step 0 -> 1: deliver step 1 guidance prepended with phase role context."""
    assert _app_state is not None

    phase_module = agent.phase_module
    ctx = agent.phase_ctx

    step_names = getattr(phase_module, "STEP_NAMES", {})
    step_name = step_names.get(1, "")

    # Audit log
    if agent.event_log is not None:
        await agent.event_log.emit_step_transition(1, step_name, phase_module.TOTAL_STEPS)

    # Projection event
    from ..events import build_step_advanced
    _app_state.projection_store.push_event(
        "agent_step_advanced",
        build_step_advanced(1, step_name, total_steps=phase_module.TOTAL_STEPS),
        agent_id=agent.agent_id,
    )

    # Mechanical memory injection runs once per phase, at the step 0 -> 1
    # handshake. The rendered block is stashed on ctx.memory_injection and
    # phase modules prepend it to their step 1 instructions.
    ctx.memory_injection = await _compute_memory_injection(agent)

    agent.step = 1
    guidance = phase_module.step_guidance(1, ctx)

    # Prepend PHASE_ROLE_CONTEXT so the orchestrator receives the phase role context
    role_context = getattr(phase_module, "PHASE_ROLE_CONTEXT", "") or ""
    if role_context:
        guidance = StepGuidance(
            title=guidance.title,
            instructions=[role_context, ""] + list(guidance.instructions),
            invoke_after=guidance.invoke_after,
        )

    result = format_step(guidance)

    if _app_state.debug:
        _app_state.projection_store.push_event(
            "debug_step_guidance",
            {"content": result},
            agent_id=agent.agent_id,
        )

    return result


async def _step_within_phase(
    agent: AgentState,
    phase_module: object,
    ctx: PhaseContext,
    next_step: int,
) -> str:
    """Handle normal within-phase step advancement."""
    assert _app_state is not None

    current_step = agent.step

    # Loop-back handling
    if next_step <= current_step:
        await phase_module.on_loop_back(current_step, next_step, ctx)

    agent.step = next_step

    step_names = getattr(phase_module, "STEP_NAMES", {})
    step_name = step_names.get(next_step, "")

    # Audit log
    if agent.event_log is not None:
        await agent.event_log.emit_step_transition(next_step, step_name, phase_module.TOTAL_STEPS)

    # Projection event
    from ..events import build_step_advanced
    _app_state.projection_store.push_event(
        "agent_step_advanced",
        build_step_advanced(next_step, step_name, total_steps=phase_module.TOTAL_STEPS),
        agent_id=agent.agent_id,
    )

    # Scan for artifacts between steps (e.g. after a write step)
    from ..driver import _push_artifact_diff
    _push_artifact_diff(_app_state)

    guidance = phase_module.step_guidance(next_step, ctx)
    result = format_step(guidance)

    if _app_state.debug:
        _app_state.projection_store.push_event(
            "debug_step_guidance",
            {"content": result},
            agent_id=agent.agent_id,
        )

    return result




# -- koan_complete_step -------------------------------------------------------


@mcp.tool(name="koan_complete_step")
async def koan_complete_step(thoughts: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_complete_step", {"thoughts": thoughts})

    call_id = begin_tool_call(agent, "koan_complete_step", {"thoughts": thoughts}, f"step {agent.step} → next")
    result_str: str | None = None
    try:
        agent.handshake_observed = True

        # workflow_done tombstone — orchestrator called koan_set_phase("done") earlier
        if _app_state is not None and _app_state.workflow_done:
            result_str = "All phases complete. You may now exit."
            return result_str

        # Step 0: phase handshake (initial call or post-koan_set_phase)
        if agent.step == 0:
            result_str = await _step_phase_handshake(agent)
            result_str = _drain_and_append_steering(result_str, agent)
            return result_str

        phase_module = agent.phase_module
        ctx = agent.phase_ctx
        current_step = agent.step

        # Validate current step completion
        err = phase_module.validate_step_completion(current_step, ctx)
        if err:
            raise ToolError(
                json.dumps({"error": "step_validation_failed", "message": err})
            )

        # Get next step
        next_step = phase_module.get_next_step(current_step, ctx)

        if next_step is None:
            if not agent.is_primary:
                # Non-primary agents (scouts) are done — signal completion
                result_str = "All steps complete. You may now exit."
                return result_str
            # Phase complete — flush conversation and return non-blocking instructions
            from ..events import build_step_advanced
            _app_state.projection_store.push_event(
                "agent_step_advanced",
                build_step_advanced(agent.step, "", total_steps=phase_module.TOTAL_STEPS),
                agent_id=agent.agent_id,
            )
            from ..driver import _push_artifact_diff
            _push_artifact_diff(_app_state)
            workflow = _app_state.workflow
            suggested = get_suggested_phases(workflow, _app_state.phase) if workflow else []
            descs = workflow.phase_descriptions if workflow else {}
            result_str = format_phase_complete(_app_state.phase, suggested, descs)
            result_str = _drain_and_append_steering(result_str, agent)
            return result_str

        # Normal within-phase advancement
        result_str = await _step_within_phase(agent, phase_module, ctx, next_step)
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str

    finally:
        end_tool_call(agent, call_id, "koan_complete_step", result_str)


# -- Summary extraction -------------------------------------------------------

def _extract_last_orchestrator_text(agent: AgentState) -> str:
    """Return the most recent textual turn from the primary agent.

    Concatenates any completed TextEntry at the tail of conversation.entries
    with the current pending_text (which has not yet been flushed by a
    subsequent tool call). Returns "" if neither is present.

    Runner buffering may deliver the tool call before the final text deltas
    are folded into the projection. This is observable: suspiciously short
    captures are logged as warnings by the caller.
    """
    assert _app_state is not None
    run = _app_state.projection_store.projection.run
    if run is None:
        return ""
    proj_agent = run.agents.get(agent.agent_id)
    if proj_agent is None:
        return ""
    conv = proj_agent.conversation
    # Walk entries backward to find the tail TextEntry chain (same turn).
    tail: list[str] = []
    for entry in reversed(conv.entries):
        if isinstance(entry, TextEntry):
            tail.insert(0, entry.text)
        else:
            break
    pending = conv.pending_text or ""
    combined = "\n".join([*tail, pending]).strip()
    return combined


# -- koan_yield ---------------------------------------------------------------

@mcp.tool(name="koan_yield")
async def koan_yield(
    summary: str = "",
    suggestions: list[dict] | None = None,
) -> str:
    """Yield to the user and wait for their reply. ORCHESTRATOR-ONLY.

    This tool is reserved for the persistent orchestrator agent. Scouts and
    executors are denied by the permission fence -- if you are a subagent,
    do not call this, return your findings as your final text response
    instead.

    Blocks until the user sends a message; returns it as the tool result.
    For the orchestrator, this is the sole human-in-the-loop checkpoint --
    call it after finishing an artifact and whenever you need user
    direction. Call in a loop for multi-turn conversation.

    REVIEW FEEDBACK LOOP: if the returned message begins with
    "I've reviewed `<path>`", the user has inspected the artifact you just
    produced. There are three response types:

    1. APPROVAL -- message says "approve it as-is". The artifact is accepted.
       Proceed normally (call koan_complete_step or continue the workflow).
    2. STRUCTURED FEEDBACK -- message contains inline comments citing specific
       sections. Revise each cited section to address its comments. Preserve
       everything not called out. Then call koan_yield again.
    3. FREE-FORM FEEDBACK -- message contains a summary without inline
       comments. Understand the requested changes, apply them to the artifact,
       then call koan_yield again.

    For types 2 and 3: do NOT call koan_complete_step between review rounds.
    Stay in the yield loop until the user approves or steers elsewhere.

    TEMPORAL CONTAMINATION RULE: when revising an artifact after feedback,
    rewrite it as though it was correct from the start. Never reference the
    previous version, the feedback, or the fact that a revision occurred.
    The artifact must read as a clean first draft that incorporates the
    requested changes. Do not add labels like "(revised)", "(updated)",
    or "(deduplicated)" -- these leak prior state into the output.

    Suggestions (optional) render as clickable pills that pre-fill the chat.
    Each dict: id (phase name or "done"), label (short display), command
    (pre-filled text on click).

    Args:
        summary: Brief context about what the agent is waiting for.
        suggestions: Pills shown above the chat input.
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_yield", {"summary": summary, "suggestions": suggestions})

    call_id = begin_tool_call(
        agent, "koan_yield", {"summary": summary},
        f"{len(suggestions or [])} suggestion(s)",
    )
    result_str: str | None = None
    try:
        assert _app_state is not None
        from ..state import drain_user_messages, drain_steering_messages

        # Capture phase summary on the FIRST yield of each phase.
        # Contract: the orchestrator's assistant text immediately preceding
        # koan_yield is treated as the phase summary. Subsequent yields in the
        # same phase do not overwrite.
        #
        # Ordering note: stream_delta events and tool calls both flow through the
        # same asyncio event loop, but runner buffering may deliver the tool call
        # before the final text deltas have been folded into the projection. When
        # the captured summary is suspiciously short we log a warning so the
        # failure is observable; we do NOT block the yield on it.
        if agent.is_primary and _app_state.phase:
            run = _app_state.projection_store.projection.run
            already_captured = bool(run and run.phase_summaries.get(_app_state.phase))
            if not already_captured:
                summary_text = _extract_last_orchestrator_text(agent)
                if summary_text:
                    if len(summary_text) < 50:
                        log.warning(
                            "phase summary for %r is suspiciously short (%d chars);"
                            " text deltas may not have been fully flushed before"
                            " koan_yield fired",
                            _app_state.phase, len(summary_text),
                        )
                    from ..events import build_phase_summary_captured
                    _app_state.projection_store.push_event(
                        "phase_summary_captured",
                        build_phase_summary_captured(_app_state.phase, summary_text),
                        agent_id=agent.agent_id,
                    )
                else:
                    log.warning(
                        "phase summary for %r not captured: no assistant text found"
                        " before koan_yield",
                        _app_state.phase,
                    )

        # Emit yield_started — renders YieldEntry in the conversation stream and
        # sets run.active_yield so the UI pins pills above the chat input.
        from ..events import build_yield_started
        _app_state.projection_store.push_event(
            "yield_started",
            build_yield_started(suggestions or []),
            agent_id=agent.agent_id,
        )

        # Check for already-buffered messages (user typed before we yielded)
        messages = drain_user_messages(_app_state) + drain_steering_messages(_app_state)

        if not messages:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            _app_state.yield_future = future

            await future  # yields to event loop; POST /api/chat resolves it

            _app_state.yield_future = None
            messages = drain_user_messages(_app_state)

        result_str = format_user_messages(messages) if messages else "No message received."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_yield", result_str)



# -- koan_set_phase -----------------------------------------------------------

@mcp.tool(name="koan_set_phase")
async def koan_set_phase(phase: str) -> str:
    """Commit transition to the next workflow phase.

    Call this after the user has confirmed what to do next. The next
    koan_complete_step call will return step 1 guidance for the new
    phase, including the role context for that phase.

    The available phases and their descriptions are listed in the
    koan_complete_step response when a phase completes. Any phase in
    the current workflow is a valid target (not just the suggested ones).

    Args:
        phase: Target phase name from the current workflow's available
               phases. The phase boundary response from koan_complete_step
               lists suggested phases with descriptions.
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_set_phase", {"phase": phase})

    call_id = begin_tool_call(agent, "koan_set_phase", {"phase": phase}, phase)
    result_str: str | None = None
    try:
        assert _app_state is not None

        current = _app_state.phase
        workflow = _app_state.workflow

        # "done" tombstone — cleanly ends the workflow without a phase transition
        if phase == "done":
            _app_state.workflow_done = True
            _app_state.projection_store.push_event("yield_cleared", {})
            _app_state.projection_store.push_event("workflow_completed", {
                "success": True,
                "phase": current,
                "summary": f"Workflow completed from phase '{current}'",
            })
            result_str = "Workflow complete. Call koan_complete_step to finish."
            result_str = _drain_and_append_steering(result_str, agent)
            return result_str

        # Validate transition using workflow membership check
        if workflow is None or not wf_is_valid(workflow, current, phase):
            phases = list(workflow.available_phases) if workflow else []
            raise ToolError(json.dumps({
                "error": "invalid_transition",
                "message": (
                    f"'{phase}' is not available from '{current}' in the current workflow. "
                    f"Available phases: {phases}"
                ),
            }))

        # Look up new phase module from the workflow's bindings
        new_module = workflow.get_module(phase) if workflow else None
        if new_module is None:
            raise ToolError(json.dumps({
                "error": "unknown_phase",
                "message": f"Phase '{phase}' has no module in workflow '{workflow.name if workflow else '?'}'",
            }))

        # Update driver state
        _app_state.phase = phase
        run_dir = _resolve_run_dir(agent)
        if run_dir:
            run_state = await load_run_state(run_dir)
            await save_run_state(run_dir, {**run_state, "phase": phase})

        # Push artifact diff and phase_started event
        from ..driver import _push_artifact_diff
        _push_artifact_diff(_app_state)
        _app_state.projection_store.push_event(
            "phase_started",
            {"phase": phase},
            agent_id=agent.agent_id,
        )
        # Clear any active yield now that a phase transition is committed
        _app_state.projection_store.push_event("yield_cleared", {})

        # Emit a step-advanced event (step=0) as visual phase-transition marker in the feed
        phase_label = phase.replace("-", " ").title()
        from ..events import build_step_advanced
        _app_state.projection_store.push_event(
            "agent_step_advanced",
            build_step_advanced(0, f"→ {phase_label}"),
            agent_id=agent.agent_id,
        )

        # Inject per-workflow phase guidance for the new phase
        binding = workflow.get_binding(phase) if workflow else None
        phase_guidance = binding.guidance if binding else ""

        # Switch phase module and reset step counter
        agent.phase_module = new_module
        agent.step = 0
        agent.phase_ctx = PhaseContext(
            run_dir=run_dir or "",
            subagent_dir=agent.subagent_dir,
            project_dir=_app_state.project_dir,
            task_description=_app_state.task_description,
            workflow_name=workflow.name if workflow else "",
            phase_instructions=phase_guidance,   # scope framing from workflow
            completed_phase=current,
        )

        result_str = f"Phase set to '{phase}'. Call koan_complete_step to begin."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_set_phase", result_str)


# -- koan_request_scouts -------------------------------------------------------

@mcp.tool(name="koan_request_scouts")
async def koan_request_scouts(questions: list[dict] | None = None) -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_request_scouts", {"questions": questions})

    call_id = begin_tool_call(
        agent, "koan_request_scouts", {"questions": questions or []},
        f"{len(questions or [])} scouts",
    )
    result_str: str | None = None
    try:
        if not questions:
            result_str = "No scouts requested."
            result_str = _drain_and_append_steering(result_str, agent)
            return result_str

        assert _app_state is not None

        semaphore = asyncio.Semaphore(_app_state.config.scout_concurrency)
        run_dir = agent.phase_ctx.run_dir

        scout_tasks = []
        for q in questions:
            scout_id = q.get("id", str(uuid.uuid4())[:8])
            subagent_dir = await ensure_subagent_directory(
                run_dir, f"scout-{scout_id}-{uuid.uuid4().hex[:8]}"
            )
            scout_tasks.append({
                "role": "scout",
                "label": scout_id,
                "run_dir": run_dir,
                "subagent_dir": subagent_dir,
                "project_dir": _app_state.project_dir,
                "question": q.get("prompt", ""),
                "investigator_role": q.get("role", "investigator"),
            })

        async def run_scout(scout_task: dict) -> str | None:
            async with semaphore:
                from ..subagent import spawn_subagent
                result = await spawn_subagent(scout_task, _app_state)

                if result.exit_code != 0:
                    return None

                return result.final_response or None

        # Emit queued events for all scouts before concurrency-limited execution
        from ..events import build_scout_queued
        for st in scout_tasks:
            _app_state.projection_store.push_event(
                "scout_queued",
                build_scout_queued(
                    scout_id=st.get("label", ""),
                    label=st.get("label", ""),
                ),
            )

        results = await asyncio.gather(*[run_scout(t) for t in scout_tasks])
        findings = [r for r in results if r is not None]

        if not findings:
            result_str = "No findings returned."
            result_str = _drain_and_append_steering(result_str, agent)
            return result_str

        result_str = "\n\n---\n\n".join(findings)
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_request_scouts", result_str)


# -- koan_ask_question ---------------------------------------------------------

@mcp.tool(name="koan_ask_question")
async def koan_ask_question(questions: list[dict] | None = None) -> str:
    """Ask the user one or more clarifying questions.

    The UI renders a split-panel card for each question:
      - LEFT PANEL ("Context"): reference material the user reads while
        deciding. Write markdown here — code snippets, bullet lists, bold
        terms, file references. This is your chance to show the user what
        you found and why the question matters. Think of it as an
        illustration panel, not a preamble.
      - RIGHT PANEL ("Decision"): the question text and selectable options.
        This is the action side — keep the question crisp.

    When context is omitted, the card renders as a single column with
    just the question and options.

    Each dict in `questions` must have:
      - question (str): The decision question (rendered as markdown).
      - options (list[dict]): Choices. Each option has:
          - value (str): Machine key returned in the answer.
          - label (str): Human-readable label shown in the UI.
          - recommended (bool, optional): Pre-select this option.

    Optional fields:
      - context (str): Background shown in the left reference panel
        (markdown). Include codebase findings, tradeoff summaries,
        or relevant code snippets that inform the decision.
      - multi (bool): Allow selecting multiple options (default false).

    Format rules for options:
      - Labels are plain descriptions. Do NOT prefix with letters, numbers,
        or bullets — the UI adds its own selection controls.
          WRONG:  "(a) Stateless wrapper"  /  "A: Stateless wrapper"
          RIGHT:  "Stateless wrapper — compile per request, optimize later"
      - Do NOT include an "Other" or "None of the above" option.
        The UI always provides a free-text alternative automatically.
      - Keep labels concise (one line). Put rationale in `context`, not
        in the label.
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_ask_question", {"questions": questions})

    call_id = begin_tool_call(
        agent, "koan_ask_question", {"questions": questions or []},
        f"{len(questions or [])} questions",
    )
    result_str: str | None = None
    try:
        assert _app_state is not None

        future = await enqueue_interaction(agent, _app_state, "ask", {"questions": questions or []})
        result = await future

        if isinstance(result, dict) and "error" in result:
            raise ToolError(json.dumps(result))

        answers = result.get("answers", [])
        questions_list = questions or []
        lines = []
        for i, a in enumerate(answers):
            q_text = questions_list[i].get("question", f"Q{i+1}") if i < len(questions_list) else f"Q{i+1}"
            a_text = a.get("answer", "") if isinstance(a, dict) else str(a)
            lines.append(f"Q: {q_text}\nA: {a_text}")
        result_str = "\n\n".join(lines) if lines else "No answers provided."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_ask_question", result_str)


# -- koan_request_executor -----------------------------------------------------

@mcp.tool(name="koan_request_executor")
async def koan_request_executor(
    artifacts: list[str] | None = None,
    instructions: str = "",
) -> str:
    """Spawn a coding agent to implement changes.

    The executor reads the listed artifacts from the run directory,
    plans its approach internally, then implements. Blocks until
    the executor exits and returns a result summary.

    Args:
        artifacts: File paths relative to run directory that the
                   executor must read before coding.
                   Example: ["plan.md"]
        instructions: Free-form context for the executor — key
                      decisions, constraints, or user direction
                      not captured in the artifact files.
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_request_executor", {"artifacts": artifacts, "instructions": instructions})

    call_id = begin_tool_call(
        agent, "koan_request_executor",
        {"artifacts": artifacts or [], "instructions": instructions},
        f"{len(artifacts or [])} artifact(s)",
    )
    result_str: str | None = None
    try:
        assert _app_state is not None

        run_dir = _resolve_run_dir(agent)
        if not run_dir:
            raise ToolError(json.dumps({"error": "no_run_dir", "message": "No run directory available"}))

        ts_suffix = int(time.time() * 1000)
        subagent_dir = await ensure_subagent_directory(
            run_dir, f"executor-{ts_suffix}"
        )

        task = {
            "role": "executor",
            "run_dir": run_dir,
            "subagent_dir": subagent_dir,
            "project_dir": _app_state.project_dir,
            "artifacts": artifacts or [],
            "instructions": instructions,
        }

        from ..subagent import spawn_subagent
        result = await spawn_subagent(task, _app_state)

        status = "succeeded" if result.exit_code == 0 else f"failed (exit {result.exit_code})"
        result_str = f"Executor {status}."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_request_executor", result_str)


# -- Story management tools (legacy execution phase) ---------------------------

@mcp.tool(name="koan_select_story")
async def koan_select_story(story_id: str) -> str:
    """Select the next story for execution."""
    agent = _get_agent()
    _check_or_raise(agent, "koan_select_story", {"story_id": story_id})

    call_id = begin_tool_call(agent, "koan_select_story", {"story_id": story_id}, story_id)
    result_str: str | None = None
    try:
        assert _app_state is not None
        run_dir = _resolve_run_dir(agent)
        if not run_dir:
            raise ToolError(json.dumps({"error": "no_run_dir"}))

        await save_story_state(run_dir, story_id, {
            "storyId": story_id,
            "status": "selected",
            "updatedAt": _now_iso(),
        })
        result_str = f"Story '{story_id}' selected for execution."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_select_story", result_str)


@mcp.tool(name="koan_complete_story")
async def koan_complete_story(story_id: str) -> str:
    """Mark a story as successfully verified and completed."""
    agent = _get_agent()
    _check_or_raise(agent, "koan_complete_story", {"story_id": story_id})

    call_id = begin_tool_call(agent, "koan_complete_story", {"story_id": story_id}, story_id)
    result_str: str | None = None
    try:
        assert _app_state is not None
        run_dir = _resolve_run_dir(agent)
        if not run_dir:
            raise ToolError(json.dumps({"error": "no_run_dir"}))

        await save_story_state(run_dir, story_id, {
            "storyId": story_id,
            "status": "done",
            "updatedAt": _now_iso(),
        })
        result_str = f"Story '{story_id}' marked as done."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_complete_story", result_str)


@mcp.tool(name="koan_retry_story")
async def koan_retry_story(story_id: str, failure_summary: str) -> str:
    """Send a story back for retry with a detailed failure summary."""
    agent = _get_agent()
    _check_or_raise(agent, "koan_retry_story", {"story_id": story_id, "failure_summary": failure_summary})

    call_id = begin_tool_call(agent, "koan_retry_story", {"story_id": story_id}, story_id)
    result_str: str | None = None
    try:
        assert _app_state is not None
        run_dir = _resolve_run_dir(agent)
        if not run_dir:
            raise ToolError(json.dumps({"error": "no_run_dir"}))

        existing = await load_story_state(run_dir, story_id)
        retry_count = existing.get("retryCount", 0) + 1

        await save_story_state(run_dir, story_id, {
            "storyId": story_id,
            "status": "retry",
            "failureSummary": failure_summary,
            "retryCount": retry_count,
            "updatedAt": _now_iso(),
        })
        result_str = f"Story '{story_id}' queued for retry (attempt {retry_count})."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_retry_story", result_str)


@mcp.tool(name="koan_skip_story")
async def koan_skip_story(story_id: str, reason: str = "") -> str:
    """Skip a story that is superseded or no longer needed."""
    agent = _get_agent()
    _check_or_raise(agent, "koan_skip_story", {"story_id": story_id, "reason": reason})

    call_id = begin_tool_call(agent, "koan_skip_story", {"story_id": story_id}, story_id)
    result_str: str | None = None
    try:
        assert _app_state is not None
        run_dir = _resolve_run_dir(agent)
        if not run_dir:
            raise ToolError(json.dumps({"error": "no_run_dir"}))

        state: dict = {
            "storyId": story_id,
            "status": "skipped",
            "updatedAt": _now_iso(),
        }
        if reason:
            state["skipReason"] = reason

        await save_story_state(run_dir, story_id, state)
        result_str = f"Story '{story_id}' skipped."
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_skip_story", result_str)


# -- Memory tools --------------------------------------------------------------

from ..memory import ops as memory_ops
from ..memory.ops import EntryNotFoundError, TypeMismatchError
from ..memory.types import MEMORY_TYPES
from ..memory.retrieval import RetrievalIndex, search as retrieval_search

_retrieval_index: RetrievalIndex | None = None


def _get_retrieval_index() -> RetrievalIndex:
    global _retrieval_index
    if _retrieval_index is None:
        assert _app_state is not None
        project_dir = _app_state.project_dir or "."
        memory_dir = Path(project_dir) / ".koan" / "memory"
        _retrieval_index = RetrievalIndex(memory_dir)
    return _retrieval_index


def _reset_retrieval_index() -> None:
    """Test hook: clear the cached RetrievalIndex."""
    global _retrieval_index
    _retrieval_index = None


@mcp.tool(name="koan_memorize")
async def koan_memorize(
    type: str,
    title: str,
    body: str,
    related: list[str] | None = None,
    entry_id: int | None = None,
) -> str:
    """Write a memory entry.

    Creates a new entry when entry_id is omitted. Updates an existing
    entry when entry_id is provided (the NNNN sequence number from
    the entry's filename).

    New entries: assigns the next sequence number, generates a filename
    slug, sets created/modified timestamps automatically.

    Updates: reads the existing entry, replaces the provided fields,
    updates the modified timestamp. Original filename and created
    timestamp are preserved.

    The body should begin with 1-3 sentences situating the entry in
    the project -- this opening context improves semantic search
    matching. The rest is event-style prose: temporally grounded,
    attributed, self-contained.

    Args:
        type: Memory type (decision, context, lesson, procedure)
        title: Short descriptive name
        body: Prose content (100-500 tokens). Begin with 1-3 sentences
              of project context for search matching.
        related: Filenames of related entries (optional)
        entry_id: Sequence number for updates (omit for creates)
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_memorize", {
        "type": type, "title": title, "entry_id": entry_id,
    })
    call_id = begin_tool_call(
        agent, "koan_memorize",
        {"type": type, "title": title, "entry_id": entry_id},
        f"{type}: {title}",
    )
    result_str: str | None = None
    try:
        store = _get_memory_store()
        result = memory_ops.memorize(store, type, title, body, related, entry_id)
        result_str = json.dumps(result)
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    except EntryNotFoundError as e:
        raise ToolError(json.dumps({"error": "entry_not_found", "message": str(e)}))
    except TypeMismatchError as e:
        raise ToolError(json.dumps({"error": "type_mismatch", "message": str(e)}))
    except ValueError as e:
        raise ToolError(json.dumps({"error": "invalid_type", "message": str(e)}))
    finally:
        end_tool_call(agent, call_id, "koan_memorize", result_str)


@mcp.tool(name="koan_forget")
async def koan_forget(entry_id: int, type: str | None = None) -> str:
    """Remove a memory entry.

    Deletes the entry file from disk. Git preserves history.

    Args:
        entry_id: Sequence number (NNNN prefix from filename)
        type: Memory type (optional). When provided, the found entry's
              type must match or a type_mismatch error is raised.
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_forget", {"type": type, "entry_id": entry_id})
    call_id = begin_tool_call(
        agent, "koan_forget",
        {"type": type, "entry_id": entry_id},
        f"{type or '*'}/{entry_id}",
    )
    result_str: str | None = None
    try:
        store = _get_memory_store()
        result = memory_ops.forget(store, entry_id, type)
        result_str = json.dumps(result)
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    except EntryNotFoundError as e:
        raise ToolError(json.dumps({"error": "entry_not_found", "message": str(e)}))
    except TypeMismatchError as e:
        raise ToolError(json.dumps({"error": "type_mismatch", "message": str(e)}))
    except ValueError as e:
        raise ToolError(json.dumps({"error": "invalid_type", "message": str(e)}))
    finally:
        end_tool_call(agent, call_id, "koan_forget", result_str)


@mcp.tool(name="koan_memory_status")
async def koan_memory_status(type: str | None = None) -> str:
    """Get an orientation view of project memory.

    Returns the project summary and a flat listing of all entries.
    Checks whether summary.md is stale (older than the most recent
    entry) and regenerates it just-in-time before returning.

    Args:
        type: Filter listing to a specific memory type (optional).
              The summary is always project-wide regardless of filter.
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_memory_status", {"type": type})
    call_id = begin_tool_call(
        agent, "koan_memory_status", {"type": type}, type or "all",
    )
    result_str: str | None = None
    try:
        store = _get_memory_store()
        result = await memory_ops.status(store, type=type)
        result_str = json.dumps(result)
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    except ValueError as e:
        raise ToolError(json.dumps({
            "error": "invalid_type",
            "message": str(e),
        }))
    finally:
        end_tool_call(agent, call_id, "koan_memory_status", result_str)


@mcp.tool(name="koan_search")
async def koan_search(
    query: str,
    type: str | None = None,
    k: int = 5,
) -> str:
    """Search memory entries by semantic similarity.

    Runs hybrid dense + BM25 search with cross-encoder reranking.
    Returns the top k entries most relevant to the query.

    Args:
        query: Search query string
        type: Filter results to a specific memory type (optional)
        k: Number of results to return (default: 5)
    """
    agent = _get_agent()
    _check_or_raise(agent, "koan_search", {"type": type})
    call_id = begin_tool_call(
        agent, "koan_search",
        {"query": query, "type": type, "k": k},
        f"query={query!r} type={type or 'all'} k={k}",
    )
    result_str: str | None = None
    try:
        if type is not None and type not in MEMORY_TYPES:
            raise ValueError(f"invalid type: {type!r}")
        index = _get_retrieval_index()
        results = await retrieval_search(index, query, k=k, type_filter=type)
        out = {
            "results": [
                {
                    "entry_id": r.entry_id,
                    "title": r.entry.title,
                    "type": r.entry.type,
                    "score": r.score,
                    "created": r.entry.created,
                    "modified": r.entry.modified,
                    "body": r.entry.body,
                }
                for r in results
            ]
        }
        result_str = json.dumps(out)
        result_str = _drain_and_append_steering(result_str, agent)
        return result_str
    except ValueError as e:
        raise ToolError(json.dumps({"error": "invalid_type", "message": str(e)}))
    except RuntimeError as e:
        raise ToolError(json.dumps({"error": "search_failed", "message": str(e)}))
    finally:
        end_tool_call(agent, call_id, "koan_search", result_str)


# -- ASGI wrapper --------------------------------------------------------------

def build_mcp_asgi_app(app_state: AppState):
    """Return an ASGI app that validates agent_id then delegates to fastmcp."""
    global _app_state
    _app_state = app_state

    inner = mcp.http_app(path="/")

    async def asgi_wrapper(scope, receive, send):
        if scope["type"] == "http":
            qs = parse_qs(scope.get("query_string", b"").decode())
            agent_id = (qs.get("agent_id") or [None])[0]

            agent = app_state.agents.get(agent_id) if agent_id else None
            if agent is None:
                log.warning("Unknown agent_id %s", agent_id)
                body = json.dumps({
                    "error": "permission_denied",
                    "message": "Unknown or inactive agent",
                }).encode()
                await send({
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"content-length", str(len(body)).encode()],
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return

            token = _agent_ctx.set(agent)
            try:
                await inner(scope, receive, send)
            finally:
                _agent_ctx.reset(token)
        else:
            await inner(scope, receive, send)

    return asgi_wrapper, inner
