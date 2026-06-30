# In-process koan tool cores: apply_set_phase, suggest_next_core, and the
# step-machine cores (_step_phase_handshake_core, _step_within_phase_core).
#
# These functions extract the business logic from the deleted HTTP MCP handlers
# so the logic has a single home. The PydanticAI in-process tools call these
# cores directly; the HTTP MCP layer (mcp_endpoint.py) is gone as of M1.
# The step-advancement tool was removed in M6; end-of-turn drives advancement.
#
# Circular-import discipline: this module imports from koan.phases, koan.events,
# koan.driver, and koan.run_state -- all stable, non-circular. It does NOT import
# from koan.web.* at module load (that would be circular via subagent.py). Helpers
# formerly imported from koan.web.mcp_endpoint are now local (relocated in M1) or
# imported from koan.web.uploads. Tests patch koan.memory.retrieval.search and
# koan.memory.retrieval.run_reflect_agent (the origin modules, not any re-export).

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..state import AgentState, AppState


@dataclass
class ToolDeps:
    """Per-run dependency object passed to pydantic-ai agent.iter(deps=...).

    Carries the live app state and the calling agent's state so in-process
    tools can read and mutate driver state without an HTTP transport.
    Both fields are typed Any at module load to avoid circular imports;
    the actual types are AgentState and AppState from koan.state.
    """

    app_state: Any  # AppState -- Any avoids a circular import at module load
    agent: Any      # AgentState -- same reasoning


# -- Relocated pure helpers ---------------------------------------------------
# These were in koan/web/mcp_endpoint.py; relocated here in M1 so the MCP
# module can be deleted without leaving dangling imports in this module.

_FILENAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*\.md$")


def _validate_artifact_filename(filename: str) -> str | None:
    """Return an error message if the filename is invalid, else None."""
    if not isinstance(filename, str) or not filename:
        return "filename is required"
    if "/" in filename or "\\" in filename:
        return "filename must be a root basename, no slashes"
    if not _FILENAME_PATTERN.fullmatch(filename):
        return (
            "filename must match [a-z0-9][a-z0-9_-]*.md "
            f"(got {filename!r})"
        )
    return None


def _compose_rag_anchor(
    task_description: str,
    run_dir: str | None,
) -> str:
    """Compose the anchor string fed to rag.generate_queries().

    Order: task -> artifacts (mtime ascending). Chronological artifact ordering
    puts the most recent artifact closest to the end (where attention is
    strongest). brief.md (written by intake) is the de facto initiative anchor;
    it appears among the run-dir markdown sorted by mtime.
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

    return "\n\n".join(sections)


# _yolo_memory_propose_response removed in M7: the koan_memory_propose approval
# gate is retired; curation writes memory directly via koan_memorize/koan_forget.

# -- Private helpers -----------------------------------------------------------


def _resolve_run_dir_core(agent: AgentState, app_state: AppState) -> str | None:
    """Resolve run_dir from agent phase_ctx, agent.run_dir, or app_state.run.run_dir.

    Extracted from mcp_endpoint.py's _resolve_run_dir closure so apply_set_phase
    can call it without going through the HTTP MCP path.
    """
    phase_ctx = agent.phase_ctx
    if phase_ctx is not None and phase_ctx.run_dir:
        return phase_ctx.run_dir
    if agent.run_dir:
        return agent.run_dir
    if app_state.run.run_dir:
        return app_state.run.run_dir
    return None


async def _compute_memory_injection_core(app_state: AppState, agent: AgentState) -> str:
    """Run the mechanical RAG injection pipeline for the current phase.

    Returns a rendered markdown block, or "" when the phase has no retrieval
    directive, memory is unavailable, or retrieval fails. Retrieval is
    best-effort: failure must never block the phase handshake.

    Mirrors mcp_endpoint.py's _compute_memory_injection closure; extracting it
    here allows the resolver in loop.py to call it from the in-process path
    without the HTTP layer.
    """
    workflow = app_state.run.workflow
    if workflow is None:
        return ""
    binding = workflow.get_binding(app_state.run.phase)
    if binding is None or not binding.retrieval_directive:
        return ""

    # Use the module-local _compose_rag_anchor (relocated from mcp_endpoint in M1).
    anchor = _compose_rag_anchor(
        task_description=app_state.run.task_description or "",
        run_dir=(
            (agent.phase_ctx.run_dir if agent.phase_ctx else None)
            or app_state.run.run_dir
        ),
    )

    try:
        from ..memory.retrieval.rag import inject, render_injection_block
        index = app_state.memory.retrieval_index
        models = app_state.run.memory_models
        if models is None:
            return ""
        results = await inject(
            index=index,
            models=models,
            directive=binding.retrieval_directive,
            anchor=anchor,
            k=5,
        )
        return render_injection_block(results)
    except Exception:
        from ..logger import get_logger
        get_logger("koan_tools").warning(
            "mechanical memory injection failed for phase %r; continuing without injection",
            app_state.run.phase,
            exc_info=True,
        )
        return ""


async def _step_phase_handshake_core(agent: AgentState, app_state: AppState) -> str:
    """Handle step 0 -> 1: deliver step 1 guidance prepended with phase role context.

    Mirrors mcp_endpoint.py's _step_phase_handshake nested function; the
    difference is that app_state is passed explicitly rather than captured via
    closure. Called by resolve_turn_outcome (loop.py) for the initial step of
    every phase.

    At phase entry, calls reset_phase_context to clear the accumulated
    conversation and all injection-dedup state, so the new phase starts with a
    minimal context. This must happen before the pending-artifact computation
    below, which reads agent.injected_artifacts to select what to re-inject.
    The reset is a no-op at bootstrap (empty history and sets).

    The read-on-demand artifact listing is queued on agent.pending_listing
    rather than appended to the returned guidance string, so it lands as a
    separate message (injected by preseed_pending_listing in run_agent_loop)
    and its cache entry does not couple to the per-step-variable guidance.
    """
    from .handoff_artifacts import reset_phase_context
    reset_phase_context(agent)

    from ..events import build_step_advanced
    from ..lib.workflows import get_suggested_phases
    from ..phases import StepGuidance
    from ..phases.format_step import format_step

    phase_module = agent.phase_module
    ctx = agent.phase_ctx

    step_names = getattr(phase_module, "STEP_NAMES", {})
    step_name = step_names.get(1, "")

    # Audit log
    if agent.event_log is not None:
        await agent.event_log.emit_step_transition(1, step_name, phase_module.TOTAL_STEPS)

    # Projection event
    app_state.projection_store.push_event(
        "agent_step_advanced",
        build_step_advanced(1, step_name, total_steps=phase_module.TOTAL_STEPS),
        agent_id=agent.agent_id,
    )

    # Mechanical memory injection runs once per phase, at the step 0 -> 1 handshake.
    ctx.memory_injection = await _compute_memory_injection_core(app_state, agent)

    # Populate auto-advance context for the last-step invoke_after.
    workflow = app_state.run.workflow
    if workflow:
        binding = workflow.get_binding(app_state.run.phase)
        ctx.next_phase = binding.next_phase if binding else None
        ctx.suggested_phases = get_suggested_phases(workflow, app_state.run.phase)
    else:
        ctx.next_phase = None
        ctx.suggested_phases = []

    agent.step = 1
    guidance = phase_module.step_guidance(1, ctx)

    # Prepend PHASE_ROLE_CONTEXT so the orchestrator receives phase role context.
    role_context = getattr(phase_module, "PHASE_ROLE_CONTEXT", "") or ""
    if role_context:
        guidance = StepGuidance(
            title=guidance.title,
            instructions=[role_context, ""] + list(guidance.instructions),
            invoke_after=guidance.invoke_after,
        )

    result = format_step(guidance)

    # Queue immutable handovers for pre-seeding and append the read-on-demand
    # listing to the step prompt.  Serves the orchestrator, executor, and reviewer;
    # scouts are explicitly excluded (they take no artifacts and receive neither
    # injection nor a listing).
    if agent.role != "scout":
        from .handoff_artifacts import (
            build_handover_listing,
            select_immutable_handovers,
            subagent_candidates,
        )
        # Orchestrator candidates come from PhaseBinding.required_artifacts;
        # subagent (executor/reviewer) candidates are resolved from PhaseContext
        # fields already populated at spawn -- no task.json schema change needed.
        if agent.is_primary:
            workflow = app_state.run.workflow
            binding = workflow.get_binding(app_state.run.phase) if workflow else None
            candidates = binding.required_artifacts if binding else ()
        else:
            candidates = subagent_candidates(ctx)
        pending = select_immutable_handovers(candidates, agent.injected_artifacts)
        agent.pending_artifacts = list(pending)
        run_dir = (ctx.run_dir if ctx else "") or agent.run_dir or app_state.run.run_dir or ""
        # Exclude both already-injected and pending (about to be injected) from
        # the listing so the agent is not offered what it already has in-context.
        listing = build_handover_listing(run_dir, set(agent.injected_artifacts) | set(pending))
        # Queue listing as its own pending message (not bundled into guidance)
        # so it remains independently cacheable across steps within a phase.
        agent.pending_listing = listing or None

    if app_state.server.debug:
        app_state.projection_store.push_event(
            "debug_step_guidance",
            {"content": result},
            agent_id=agent.agent_id,
        )

    return result


async def _step_within_phase_core(
    agent: AgentState,
    app_state: AppState,
    phase_module: Any,
    ctx: Any,
    next_step: int,
) -> str:
    """Handle normal within-phase step advancement.

    Mirrors mcp_endpoint.py's _step_within_phase nested function; app_state
    is passed explicitly rather than captured via closure.
    """
    from ..driver import _push_artifact_diff
    from ..events import build_step_advanced
    from ..phases.format_step import format_step

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
    app_state.projection_store.push_event(
        "agent_step_advanced",
        build_step_advanced(next_step, step_name, total_steps=phase_module.TOTAL_STEPS),
        agent_id=agent.agent_id,
    )

    # Scan for artifacts between steps (e.g. after a write step).
    _push_artifact_diff(app_state)

    guidance = phase_module.step_guidance(next_step, ctx)
    result = format_step(guidance)

    if app_state.server.debug:
        app_state.projection_store.push_event(
            "debug_step_guidance",
            {"content": result},
            agent_id=agent.agent_id,
        )

    return result


# -- Step-machine cores --------------------------------------------------------
# The step-advancement tool was removed in M6: end-of-turn is the signal.
# _step_phase_handshake_core and _step_within_phase_core are kept; they are
# called by resolve_turn_outcome in loop.py via function-local imports (to
# avoid the circular-import cycle between loop.py and koan_tools.py).


async def apply_set_phase(deps: ToolDeps, phase: str) -> str:
    """Core phase-transition logic for koan_set_phase.

    Pure routing: validates the transition, updates driver state, emits
    projection events, and rebuilds PhaseContext. Returns a confirmation
    string for the model.

    M5: execute handoff removed. koan_set_phase is now parameter-free routing;
    execution is launched via koan_request_executor from within the execute
    phase. Bare koan_set_phase("execute") is now the correct call.

    The milestone phase is one-time: milestones.md is a living document edited
    in place for the life of the initiative. No discard hook fires on milestone
    re-entry (M2: discard hook removed).

    Agent-correctable validation failures (invalid_transition) are RETURNED as
    the {"ok": false, "error": {...}} envelope so the model can self-correct
    without crashing the run. Infrastructure and internal-config faults
    (no_run_dir, unknown_phase) still raise.

    Called by the in-process koan_set_phase PydanticAI tool.
    """
    from ..driver import _push_artifact_diff
    from ..events import build_step_advanced
    from ..lib.workflows import is_valid_transition as wf_is_valid
    from ..logger import get_logger
    from ..phases import PhaseContext
    # ValidationError is used by all transition-error branches below; imported
    # here rather than at module level to keep circular-import discipline intact.
    from .artifact_registry import ValidationError

    log = get_logger("koan_tools")

    agent = deps.agent
    app_state = deps.app_state

    current = app_state.run.phase
    workflow = app_state.run.workflow

    # "done" tombstone: cleanly ends the workflow without a phase transition.
    if phase == "done":
        app_state.run.workflow_done = True
        app_state.projection_store.push_event("yield_cleared", {})
        app_state.projection_store.push_event("workflow_completed", {
            "success": True,
            "phase": current,
            "summary": f"Workflow completed from phase '{current}'",
        })
        return "Workflow complete. End your turn to finish."

    # Validate transition using workflow membership check.
    if workflow is None or not wf_is_valid(workflow, current, phase):
        phases = list(workflow.available_phases) if workflow else []
        # Recoverable: the agent can retry with a phase name from the available list.
        return _permission_error_result(ValidationError(
            code="invalid_transition",
            message=(
                f"'{phase}' is not available from '{current}' "
                f"in the current workflow. Available phases: {phases}"
            ),
            allowed=f"Choose a phase available from the current one: {phases}.",
        ))

    # Look up new phase module from the workflow's bindings.
    new_module = workflow.get_module(phase) if workflow else None
    if new_module is None:
        raise ValueError(
            f"unknown_phase: Phase '{phase}' has no module in workflow "
            f"'{workflow.name if workflow else '?'}'"
        )

    log.info(
        "phase transition: agent=%s from=%s to=%s",
        agent.agent_id[:8], current, phase,
    )

    # Update driver state atomically.
    app_state.run.phase = phase
    run_dir = _resolve_run_dir_core(agent, app_state)
    if run_dir:
        from ..run_state import load_run_state, save_run_state
        run_state = await load_run_state(run_dir)
        await save_run_state(run_dir, {**run_state, "phase": phase})

    # Push artifact diff and projection events in the same order as the MCP handler.
    _push_artifact_diff(app_state)
    app_state.projection_store.push_event(
        "phase_started",
        {"phase": phase},
        agent_id=agent.agent_id,
    )
    app_state.projection_store.push_event("yield_cleared", {})

    # Step-advanced visual marker (mirrors mcp_endpoint.py L1007-L1013).
    phase_label = phase.replace("-", " ").title()
    app_state.projection_store.push_event(
        "agent_step_advanced",
        build_step_advanced(0, f"-> {phase_label}"),
        agent_id=agent.agent_id,
    )

    # Inject per-workflow phase guidance for the new phase.
    binding = workflow.get_binding(phase) if workflow else None
    phase_guidance = binding.guidance if binding else ""

    # Switch phase module and reset step counter (mirrors mcp_endpoint.py L1019-L1031).
    agent.phase_module = new_module
    agent.step = 0
    agent.phase_ctx = PhaseContext(
        run_dir=run_dir or "",
        subagent_dir=agent.subagent_dir,
        project_dir=app_state.run.project_dir,
        additional_dirs=app_state.run.additional_dirs,
        task_description=app_state.run.task_description,
        workflow_name=workflow.name if workflow else "",
        phase_instructions=phase_guidance,
        completed_phase=current,
    )

    return f"Phase set to '{phase}'. End your turn now -- the new phase's first step will be delivered automatically."


# -- Suggest-next core ---------------------------------------------------------


async def suggest_next_core(deps: ToolDeps, suggestions: list[dict]) -> str:
    """Record orchestrator-authored hand-back suggestions for the upcoming phase-boundary.

    Stores suggestions on app_state.interactions.next_suggestions so the loop can
    consume them at the next hand-back. build_phase_suggestions is the fallback when
    this is never called. Coerces None to [] so callers need not guard for None.

    Each suggestion is a dict with keys: id, label, command, and optionally
    recommended (bool). No strict schema validation -- permissive to avoid
    blocking the orchestrator on schema changes.
    """
    app_state = deps.app_state
    # Coerce None to [] so the loop's `recorded if recorded` check works correctly
    # (an empty list is falsy and falls back to build_phase_suggestions, which is
    # the intended behaviour when the orchestrator calls with an empty list).
    app_state.interactions.next_suggestions = suggestions if suggestions else []
    n = len(suggestions)
    return f"Recorded {n} next-step suggestion(s) for the hand-back."


# -- Workflow core -------------------------------------------------------------


async def apply_set_workflow(deps: ToolDeps, workflow: str) -> str:
    """Core workflow-switch logic for koan_set_workflow.

    Validates the workflow name, swaps app_state.run.workflow/phase, appends
    the new entry to the orchestrator's task.json workflow_history, persists
    the phase to run-state.json, emits projection events (workflow_selected,
    phase_started, yield_cleared, agent_step_advanced), and rebuilds
    PhaseContext for the new phase.

    Agent-correctable validation failure (unknown_workflow) is RETURNED as the
    {"ok": false, "error": {...}} envelope so the model can self-correct without
    crashing the run.  The internal_error fault (missing initial-phase module --
    an internal config bug) still raises because the agent cannot fix it.

    Called by the in-process koan_set_workflow PydanticAI tool.
    """
    import json as _json
    from pathlib import Path

    import aiofiles

    from ..driver import _push_artifact_diff
    from ..events import build_step_advanced, build_workflow_selected
    from ..lib.task_json import make_workflow_history_entry
    from ..lib.workflows import WORKFLOWS, get_workflow
    from ..logger import get_logger
    from ..phases import PhaseContext
    from ..run_state import load_run_state, save_run_state
    from ..subagent import write_task_json
    # ValidationError is used for the unknown_workflow recoverable return below.
    from .artifact_registry import ValidationError

    log = get_logger("koan_tools")
    agent = deps.agent
    app_state = deps.app_state

    current_workflow_obj = app_state.run.workflow
    current_phase = app_state.run.phase

    try:
        new_workflow = get_workflow(workflow)
    except ValueError:
        # Recoverable: the agent can retry with a registered workflow name.
        return _permission_error_result(ValidationError(
            code="unknown_workflow",
            message=(
                f"'{workflow}' is not a registered workflow. "
                f"Available workflows: {list(WORKFLOWS.keys())}"
            ),
            allowed=f"Pass a registered workflow name: {list(WORKFLOWS.keys())}.",
        ))

    new_initial_phase = new_workflow.initial_phase
    new_module = new_workflow.get_module(new_initial_phase)
    if new_module is None:
        raise ValueError(
            f"internal_error: Workflow '{workflow}' has no module for its "
            f"initial_phase '{new_initial_phase}'"
        )

    log.info(
        "workflow transition: agent=%s from=%s to=%s entering_phase=%s",
        agent.agent_id[:8],
        current_workflow_obj.name if current_workflow_obj else "?",
        workflow,
        new_initial_phase,
    )

    # Swap run state before emitting projection events so fold consumers see the
    # new workflow immediately.
    app_state.run.workflow = new_workflow
    app_state.run.phase = new_initial_phase

    # Append to orchestrator task.json's workflow_history.  The atomic write
    # helper is shared with the MCP path so both paths produce identical files.
    orchestrator_task_path = Path(agent.subagent_dir) / "task.json"
    async with aiofiles.open(orchestrator_task_path, "r") as _f:
        task_dict = _json.loads(await _f.read())
    history = list(task_dict.get("workflow_history", []))
    history.append(make_workflow_history_entry(workflow, new_initial_phase))
    task_dict["workflow_history"] = history
    await write_task_json(agent.subagent_dir, task_dict)

    # Persist phase to run-state.json (mirrors apply_set_phase's path).
    run_dir = _resolve_run_dir_core(agent, app_state)
    if run_dir:
        run_state = await load_run_state(run_dir)
        await save_run_state(run_dir, {**run_state, "phase": new_initial_phase})

    # Projection events in the same order as the MCP handler so the frontend
    # fold sees a consistent event stream regardless of which path is used.
    _push_artifact_diff(app_state)
    app_state.projection_store.push_event(
        "workflow_selected",
        build_workflow_selected(workflow),
    )
    app_state.projection_store.push_event(
        "phase_started",
        {"phase": new_initial_phase},
        agent_id=agent.agent_id,
    )
    app_state.projection_store.push_event("yield_cleared", {})
    phase_label = new_initial_phase.replace("-", " ").title()
    app_state.projection_store.push_event(
        "agent_step_advanced",
        build_step_advanced(0, f"-> {workflow}: {phase_label}"),
        agent_id=agent.agent_id,
    )

    # Rebuild PhaseContext for the new workflow's initial phase.
    binding = new_workflow.get_binding(new_initial_phase)
    phase_guidance = binding.guidance if binding else ""
    agent.phase_module = new_module
    agent.step = 0
    agent.phase_ctx = PhaseContext(
        run_dir=run_dir or "",
        subagent_dir=agent.subagent_dir,
        project_dir=app_state.run.project_dir,
        additional_dirs=app_state.run.additional_dirs,
        task_description=app_state.run.task_description,
        workflow_name=new_workflow.name,
        phase_instructions=phase_guidance,
        completed_phase=current_phase,
    )

    return (
        f"Workflow set to '{workflow}'. Now in phase "
        f"'{new_initial_phase}'. End your turn now -- the new phase's first step will be delivered automatically."
    )


# Story tool cores (select_story, complete_story, retry_story, skip_story)
# deleted in M1: the legacy "execution" phase that used them is bound to no
# active workflow since the T4 Phases commit and is removed here.


# -- Memory tool cores ---------------------------------------------------------


async def memorize_core(
    deps: ToolDeps,
    type: str,
    title: str,
    body: str,
    related: list[str] | None = None,
    entry_id: int | None = None,
) -> str:
    """Core logic for koan_memorize.

    Delegates to memory_ops.memorize and emits the appropriate projection
    event (memory_entry_created or memory_entry_updated). Returns a JSON
    string of the result dict.

    Re-raises EntryNotFoundError, TypeMismatchError, and ValueError so
    callers (MCP handler, in-process tool) can map them to their error shapes.
    """
    import json

    from ..events import build_memory_entry_created, build_memory_entry_updated
    from ..memory import ops as memory_ops
    from ..memory.timestamps import iso_to_ms as _iso_to_ms
    from ..projections import MemoryEntrySummary

    agent = deps.agent
    app_state = deps.app_state
    store = app_state.memory.memory_store

    result = memory_ops.memorize(store, type, title, body, related, entry_id)

    eid = result.get("entry_id")
    if eid is not None:
        seq = f"{eid:04d}"
        summary = MemoryEntrySummary(
            seq=seq,
            type=result.get("type", type),
            title=title,
            created_ms=_iso_to_ms(result.get("created", "")),
            modified_ms=_iso_to_ms(result.get("modified", "")),
        )
        builder = (
            build_memory_entry_created
            if result.get("op") == "created"
            else build_memory_entry_updated
        )
        app_state.projection_store.push_event(
            "memory_entry_created" if result.get("op") == "created" else "memory_entry_updated",
            builder(summary.to_wire()),
            agent_id=agent.agent_id,
        )

    return json.dumps(result)


async def forget_core(deps: ToolDeps, entry_id: int, type: str | None = None) -> str:
    """Core logic for koan_forget.

    Delegates to memory_ops.forget and emits memory_entry_deleted.
    Returns a JSON string of the result dict.

    Re-raises EntryNotFoundError, TypeMismatchError, and ValueError.
    """
    import json

    from ..events import build_memory_entry_deleted
    from ..memory import ops as memory_ops

    agent = deps.agent
    app_state = deps.app_state
    store = app_state.memory.memory_store

    result = memory_ops.forget(store, entry_id, type)

    seq = f"{result.get('entry_id', entry_id):04d}"
    app_state.projection_store.push_event(
        "memory_entry_deleted",
        build_memory_entry_deleted(seq),
        agent_id=agent.agent_id,
    )

    return json.dumps(result)


async def memory_status_core(deps: ToolDeps, type: str | None = None) -> str:
    """Core logic for koan_memory_status.

    Delegates to memory_ops.status (may regenerate summary.md just-in-time)
    and emits memory_summary_updated when regeneration occurred.
    Returns a JSON string of the result dict.

    Re-raises ValueError for invalid type values.
    """
    import json

    from ..events import build_memory_summary_updated
    from ..memory import ops as memory_ops

    agent = deps.agent
    app_state = deps.app_state
    store = app_state.memory.memory_store
    models = app_state.run.memory_models

    result = await memory_ops.status(store, model=(models.memory_llm if models else None), type=type)

    if result.get("regenerated"):
        app_state.projection_store.push_event(
            "memory_summary_updated",
            build_memory_summary_updated(result.get("summary", "")),
            agent_id=agent.agent_id,
        )

    return json.dumps(result)


async def search_core(
    deps: ToolDeps,
    query: str,
    type: str | None = None,
    k: int = 5,
) -> str:
    """Core logic for koan_search.

    Validates the type filter, then delegates to retrieval_search.
    Returns a JSON string with a "results" list.

    Raises ValueError("invalid type: ...") for unknown memory type values.
    Re-raises RuntimeError on search failures.

    Imports retrieval_search from koan.memory.retrieval (the origin module).
    Tests patch koan.memory.retrieval.search to intercept calls here.
    The lazy import inside the function body re-evaluates the module attribute
    on each call, picking up any active monkeypatch.
    """
    import json

    from ..memory.types import MEMORY_TYPES

    # Import directly from the origin module; tests patch
    # koan.memory.retrieval.search (not the deleted mcp_endpoint namespace).
    from ..memory.retrieval import search as retrieval_search
    from ..memory.bindings import require_memory_model

    app_state = deps.app_state

    if type is not None and type not in MEMORY_TYPES:
        raise ValueError(f"invalid type: {type!r}")

    models = app_state.run.memory_models
    embed = require_memory_model(models.embedding if models else None, "embedding")
    index = app_state.memory.retrieval_index
    results = await retrieval_search(index, query, embed, k=k, type_filter=type)
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
    return json.dumps(out)


async def reflect_core(
    deps: ToolDeps,
    question: str,
    context: str | None = None,
) -> str:
    """Core logic for koan_reflect.

    Runs run_reflect_agent with a trace callback that emits reflect_delta
    projection events for text-kind deltas (keeping the live streaming feed
    in sync). Returns a JSON string with answer, citations, and iterations.

    Re-raises IterationCapExceeded and RuntimeError so callers can map them
    to their error shapes.
    """
    import json

    from ..events import build_reflect_delta
    from ..memory.retrieval import ReflectTraceEvent, run_reflect_agent

    agent = deps.agent
    app_state = deps.app_state

    # Only text-kind deltas flow into the projection feed; other kinds (search,
    # done, thinking) are consumed by /api/memory/reflect instead.
    def _on_trace(ev: ReflectTraceEvent) -> None:
        if ev.kind != "text" or not ev.delta:
            return
        app_state.projection_store.push_event(
            "reflect_delta",
            build_reflect_delta(ev.delta),
            agent_id=agent.agent_id,
        )

    models = app_state.run.memory_models
    index = app_state.memory.retrieval_index
    result = await run_reflect_agent(index, models, question, context=context, on_trace=_on_trace)
    out = {
        "answer": result.answer,
        "citations": [
            {"id": c.id, "title": c.title, "type": c.type, "modifiedMs": c.modified_ms}
            for c in result.citations
        ],
        "iterations": result.iterations,
    }
    return json.dumps(out)


# -- Artifact tool cores -------------------------------------------------------
# koan_artifact_read/write/edit are thin, run-dir-scoped wrappers over the
# built-in read/write/edit tools (koan/tools/builtin_tools.py). They exist to
# give planning roles (e.g. the orchestrator) a file interface limited to their
# run directory's artifacts -- the orchestrator can produce and revise artifacts
# but cannot write or edit arbitrary project files. Artifacts are plain markdown
# (no frontmatter), so the wrappers add only filename validation, run-dir
# containment, and the artifact_diff projection event around the shared tools.


class _DepsCtx:
    """Minimal RunContext stand-in exposing `.deps`.

    The built-in tools read their dependencies off `ctx.deps`; the artifact
    wrappers hold `deps` directly, so they pass this shim to delegate.
    """

    __slots__ = ("deps",)

    def __init__(self, deps: ToolDeps) -> None:
        self.deps = deps


def _resolve_artifact_path(deps: ToolDeps, filename: str) -> Path:
    """Validate *filename* and resolve it to an absolute path inside run_dir.

    Shared guard for the artifact wrappers: rejects malformed filenames and any
    path that escapes run_dir, so the wrapped read/write/edit can only touch
    run-directory artifacts. Raises ValueError("code: message").
    """
    import os

    err = _validate_artifact_filename(filename)
    if err:
        raise ValueError(f"invalid_filename: {err}")

    run_dir = _resolve_run_dir_core(deps.agent, deps.app_state)
    if not run_dir:
        raise ValueError("no_run_dir: No run directory available")

    run_root = Path(run_dir).resolve()
    target = (run_root / filename).resolve()
    if target != run_root and not str(target).startswith(str(run_root) + os.sep):
        raise ValueError("invalid_path: filename escapes run_dir")
    return target



async def _spawn_reviewer(
    app_state: "AppState",
    run_dir: str,
    target_name: str,
    reviewer_prompt: str,
) -> str:
    """Spawn a blocking reviewer sub-agent and return its freeform findings.

    Mirrors request_executor_core's spawn mechanics: creates a subagent
    directory, pushes an agents_cleared projection event, builds the task
    dict, awaits spawn_tracked_subagent, and returns result.final_response
    (the reviewer's freeform findings text), NOT a status JSON.

    On a failed reviewer run (exit_code != 0), returns a short marker string
    that the caller can surface as the sidecar content.

    Args:
        app_state: Live application state (projection store, run config, etc.).
        run_dir: Absolute path to the current run directory.
        target_name: Filename of the artifact being reviewed (e.g. "tech-plan.md").
        reviewer_prompt: Charter tag ("PLAN_REVIEWER", etc.) selecting the charter.
    """
    import time

    from ..events import build_agents_cleared
    from ..run_state import ensure_subagent_directory

    subagent_dir = await ensure_subagent_directory(
        run_dir, f"reviewer-{int(time.time() * 1000)}"
    )

    # Clear stale non-primary agents before spawning, mirroring request_executor_core.
    app_state.projection_store.push_event("agents_cleared", build_agents_cleared())

    task = {
        "role": "reviewer",
        "run_dir": run_dir,
        "subagent_dir": subagent_dir,
        "project_dir": app_state.run.project_dir,
        "additional_dirs": app_state.run.additional_dirs,
        "reviewer_target": target_name,
        "reviewer_prompt": reviewer_prompt,
        # M6: reviewer task is purely "filename -> review it"; the remediation chain
        # concept has been dropped so no predecessor context is passed here.
    }

    result = await spawn_tracked_subagent(app_state, task)
    if result.exit_code != 0:
        # reviewer_proceeded_unreviewed is a deliberate user choice (not a failure)
        # emitted by _stream_model_request_with_retry when retry budget is exhausted
        # and the reviewer role opts to skip the review. spawn_subagent converts the
        # AgentError to SubagentResult(exit_code=1, error=diagnostic.message), so
        # the sentinel is detectable via the error string.
        if result.error and "reviewer_proceeded_unreviewed" in result.error:
            return "[review skipped: user chose to proceed unreviewed after retry budget exhausted]"
        return f"[reviewer failed: {result.error or 'exit_code=' + str(result.exit_code)}]"
    return result.final_response or ""


async def _spawn_executor(
    app_state: "AppState",
    run_dir: str,
    artifacts: list[str],
    instructions: str = "",
) -> tuple[str, int]:
    """Spawn a blocking executor sub-agent and return (deviation_report, exit_code).

    Mirrors _spawn_reviewer's mechanics: clears stale non-primary agents, creates
    an executor subagent directory, builds the task dict, awaits
    spawn_tracked_subagent, and returns the executor's final_response (the
    deviation report the plan instructs the executor to produce) plus its
    exit_code so the caller can compute the execute_completion outcome.

    Args:
        app_state: Live application state (projection store, run config, etc.).
        run_dir: Absolute path to the current run directory.
        artifacts: Ordered list of run-dir artifact filenames for the executor.
        instructions: Free-form orchestrator instructions passed to the executor.
            Defaults to "" so the legacy caller _spawn_executor(app_state, run_dir,
            artifacts) is unaffected; request_executor_core composes and passes
            instructions explicitly.
    """
    import time

    from ..events import build_agents_cleared
    from ..run_state import ensure_subagent_directory

    subagent_dir = await ensure_subagent_directory(
        run_dir, f"executor-{int(time.time() * 1000)}"
    )

    # Clear stale non-primary agents before spawning, mirroring request_executor_core.
    app_state.projection_store.push_event("agents_cleared", build_agents_cleared())

    task = {
        "role": "executor",
        "run_dir": run_dir,
        "subagent_dir": subagent_dir,
        "project_dir": app_state.run.project_dir,
        "additional_dirs": app_state.run.additional_dirs,
        "artifacts": artifacts,
        "instructions": instructions,
    }

    result = await spawn_tracked_subagent(app_state, task)
    return (result.final_response or "", result.exit_code)


def _current_step_name(agent: "AgentState") -> str | None:
    """Resolve the current step's stable name from the agent's phase module.

    Returns STEP_NAMES[agent.step] from the phase module set on the agent, or
    None when the phase module is absent, has no STEP_NAMES, or the current step
    integer has no entry.  None causes the per-step gate to be skipped (fail-open)
    so unresolved step metadata never produces a false rejection.
    """
    phase_module = getattr(agent, "phase_module", None)
    if phase_module is None:
        return None
    step_names = getattr(phase_module, "STEP_NAMES", None)
    if step_names is None:
        return None
    return step_names.get(getattr(agent, "step", 0))


def _permission_error_result(err: "ValidationError") -> str:
    """Shape a recoverable registry ValidationError into the uniform tool-result envelope.

    Returns a JSON string {"ok": false, "error": {...}} that is passed directly
    back to the model as the tool result.  The model reads it, learns when/where
    the call IS legal (err.allowed), and re-issues.  This path is never raised
    so a recoverable permission denial cannot crash the run.
    """
    import json

    return json.dumps({
        "ok": False,
        "error": {
            "reason": err.code,
            "message": err.message,
            "allowed": err.allowed,
            "suggested_name": err.suggested_name,
        },
    })


def _tool_phase_gate_result(deps: "ToolDeps", tool_name: str) -> str | None:
    """Return a recoverable error envelope when tool_name is barred in the current phase.

    Reads the calling agent's role and the run's current phase from deps,
    delegates to phase_gate_message for the decision, and wraps any denial in
    the standard _permission_error_result envelope so the model can self-correct.
    Returns None when the call is permitted (no gate triggered).

    Args:
        deps: ToolDeps carrying the agent's role and app_state.run.phase.
        tool_name: The koan tool name being invoked.
    """
    from .tool_policy import build_tool_policy, phase_gate_message
    from .artifact_registry import ValidationError

    role = getattr(deps.agent, "role", "")
    phase = getattr(getattr(deps, "app_state", None), "run", None)
    phase = getattr(phase, "phase", "") or ""
    msg = phase_gate_message(build_tool_policy(), role, phase, tool_name)
    if msg is None:
        return None
    return _permission_error_result(
        ValidationError(code="tool_unavailable_in_phase", message=msg, allowed=msg)
    )


async def artifact_write_core(deps: ToolDeps, filename: str, content: str) -> str:
    """Core logic for koan_artifact_write -- write-once, validate, classify, spawn reviewer.

    Validates the filename against the artifact registry (rejects sidecars,
    wrong-phase/wrong-step writes, and overwrite attempts). Writes the file once
    via write_tool. Classifies the artifact's reviewer via the registry; when a
    reviewer is configured, spawns a blocking reviewer sub-agent (mirroring
    request_executor_core) and returns the findings string to the caller for
    inline reconciliation. When no reviewer is configured, returns the standard
    written-OK JSON.

    Recoverable validation failures are RETURNED as {"ok": false, "error": {...}}
    so the model can self-correct without crashing the run.  Only genuine
    infrastructure faults raise: no_run_dir, invalid_path, write_failed.
    """
    import json

    from ..artifacts import list_artifacts
    from ..driver import _push_artifact_diff
    from ..tools import artifact_registry
    from .builtin_tools import write_tool

    agent = deps.agent
    app_state = deps.app_state

    # Resolve and guard the run directory before anything else.
    run_dir = _resolve_run_dir_core(agent, app_state)
    if not run_dir:
        raise ValueError("no_run_dir: No run directory available")

    # Validate + classify via the artifact registry.
    # validate_write handles sidecar writes (name_malformed) and all policy checks.
    # The inline sidecar reject was removed here; it now flows as a recoverable envelope.
    phase = app_state.run.phase or ""
    workflow = app_state.run.workflow
    # requires_discriminator: True when the active workflow fans out to
    # per-milestone plans, requiring plan-milestone-N.md over bare plan.md.
    requires_discriminator = (
        workflow is not None and "milestone" in (workflow.available_phases or ())
    )
    # list_artifacts returns {path, size, modified_at} dicts; extract the
    # root-level filename (path is relative to run_dir).
    existing_names = frozenset(
        a["path"] for a in list_artifacts(run_dir) if "/" not in a["path"]
    )
    # Resolve step name for the per-step gate; None means skip the step check.
    step_name = _current_step_name(agent)

    err = artifact_registry.validate_write(
        filename,
        phase=phase,
        requires_discriminator=requires_discriminator,
        existing_names=existing_names,
        step_name=step_name,
    )
    if err is not None:
        # Recoverable: return the envelope so the model self-corrects.
        return _permission_error_result(err)

    # Write the file once (write-once guarantee -- validation already rejected
    # existing names above).
    import os
    run_root = Path(run_dir).resolve()
    target = (run_root / filename).resolve()
    if target != run_root and not str(target).startswith(str(run_root) + os.sep):
        raise ValueError("invalid_path: filename escapes run_dir")

    result = await write_tool(_DepsCtx(deps), str(target), content or "")
    if result.startswith("Error"):
        raise ValueError(f"write_failed: {result}")

    _push_artifact_diff(app_state)

    # Classify: does this artifact family have a reviewer?
    reviewer_prompt_tag = artifact_registry.reviewer_for(filename)
    if reviewer_prompt_tag is None:
        # No reviewer configured for this family -- return the simple OK response.
        return json.dumps({"ok": True, "filename": filename})

    # Spawn the reviewer (blocking) -- returns its freeform findings text.
    # The findings are returned directly; the orchestrator reconciles them inline
    # in the reviewed artifact via koan_artifact_edit. No sidecar is created.
    findings = await _spawn_reviewer(
        app_state, run_dir, filename, reviewer_prompt_tag
    )

    return findings


async def artifact_edit_core(
    deps: ToolDeps,
    filename: str,
    anchor: str,
    text: str,
    end_anchor: str | None = None,
    edit_type: str = "replace",
) -> str:
    """Core logic for koan_artifact_edit -- run-dir-scoped wrapper over edit_tool.

    Validates the filename, resolves it inside run_dir, and checks per-step
    legality via the artifact registry.

    Recoverable validation failures are RETURNED as {"ok": false, "error": {...}}
    so the model can self-correct without crashing the run.  Engine edit failures
    (edit_failed: anchor not found, content drift, bad edit_type) are also returned
    as the recoverable envelope -- a mis-copied anchor lets the model re-read and
    retry instead of crashing the run.  Only path-resolution faults raise:
    no_run_dir, invalid_path.

    Returns {"ok": true, "filename"} on success.
    """
    import json

    from ..artifacts import list_artifacts
    from ..driver import _push_artifact_diff
    from ..tools import artifact_registry
    from .builtin_tools import edit_tool

    # Resolve path (validates filename and run-dir containment).
    target = _resolve_artifact_path(deps, filename)

    # Validate via the registry. validate_edit handles not_found and per-step legality.
    run_dir = str(target.parent)
    existing_names = frozenset(
        a["path"] for a in list_artifacts(run_dir) if "/" not in a["path"]
    )
    # Resolve phase and step name for the per-step gate.
    phase = deps.app_state.run.phase or ""
    step_name = _current_step_name(deps.agent)
    err = artifact_registry.validate_edit(
        filename,
        existing_names=existing_names,
        phase=phase,
        step_name=step_name,
    )
    if err is not None:
        # Recoverable: return the envelope so the model self-corrects.
        return _permission_error_result(err)

    result = await edit_tool(_DepsCtx(deps), str(target), anchor, text, end_anchor, edit_type)
    if result.startswith("Error"):
        # Engine edit failures (anchor not found, content drift, bad edit_type) are
        # recoverable: return the standard envelope so a mis-copied anchor lets the
        # model re-read and retry instead of crashing the run.
        return _permission_error_result(
            artifact_registry.ValidationError(
                code="edit_failed",
                message=result,
                allowed="Re-read the artifact with koan_artifact_read for current anchors, then retry.",
            )
        )

    _push_artifact_diff(deps.app_state)
    return json.dumps({"ok": True, "filename": filename})


async def artifact_list_core(deps: ToolDeps) -> str:
    """Core logic for koan_artifact_list.

    Resolves the run directory and returns a JSON string {"artifacts": [...]}.
    Returns an empty list when no run directory is available (safe for all roles).
    """
    import json

    from ..artifacts import list_artifacts

    agent = deps.agent
    app_state = deps.app_state

    run_dir = _resolve_run_dir_core(agent, app_state)
    if not run_dir:
        return json.dumps({"artifacts": []})

    artifacts = list_artifacts(run_dir)
    return json.dumps({"artifacts": artifacts})


async def artifact_read_core(
    deps: ToolDeps,
    filename: str,
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Core logic for koan_artifact_read -- run-dir-scoped wrapper over read_tool.

    Validates the filename, resolves it inside run_dir, and delegates to the
    built-in read tool, returning anchored, line-numbered content
    ("{lineno}\\t{anchor}§{content}"). The anchor lets koan_artifact_edit target a
    line; offset/limit page large artifacts.

    koan_artifact_read is a TRUSTED command (Decision 6) -- exempt from the
    Milestone-2 reject ceiling. enforce_limits=False bypasses _enforce_output_limits
    so large artifacts are not rejected; the reject ceiling only applies to untrusted
    built-in tool calls.

    Raises ValueError("invalid_filename"/"no_run_dir"/"invalid_path"/"not_found").
    """
    from .builtin_tools import read_tool

    target = _resolve_artifact_path(deps, filename)
    if not target.is_file():
        raise ValueError(f"not_found: {filename} not found")

    # enforce_limits=False is load-bearing: artifact reads are trusted and must
    # not be rejected for size (brief.md Decision 6).
    return await read_tool(_DepsCtx(deps), str(target), offset, limit, enforce_limits=False)


# -- Interaction tool cores ----------------------------------------------------


async def ask_question_core(deps: ToolDeps, questions: list[dict]) -> str:
    """Core logic for koan_ask_question -- async blocking part plus Q/A formatting.

    Enqueues the ask interaction (which emits the questions_asked projection
    event via enqueue_interaction -> _emit_interaction_request) then parks on
    the future.  Under yolo, the future is pre-resolved with synthesised
    answers from _yolo_ask_answer before the await, so the call returns
    without blocking on a user POST.

    Returns a plain-text Q/A string.  The MCP handler adds per-answer
    attachment blocks on top; the in-process pydantic-ai tool returns this
    string directly to the model.

    Raises RuntimeError when the interaction queue is full.
    """
    agent = deps.agent
    app_state = deps.app_state

    # enqueue_interaction also emits the questions_asked projection event.
    from ..web.interactions import enqueue_interaction
    try:
        future = await enqueue_interaction(agent, app_state, "ask", {"questions": questions or []})
    except Exception as exc:
        # convert to RuntimeError so pydantic-ai receives a standard exception type.
        raise RuntimeError(f"ask_question_enqueue_failed: {exc}") from exc

    if app_state.server.yolo:
        # Pre-resolve before awaiting so no event-loop park occurs.
        from ..agents.loop import _yolo_ask_answer
        future.set_result(_yolo_ask_answer(questions or []))

    result = await future

    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"{result['error']}: {result.get('message', '')}")

    answers = result.get("answers", []) if isinstance(result, dict) else []
    questions_list = questions or []
    parts = []
    for i, a in enumerate(answers):
        q_text = questions_list[i].get("question", f"Q{i+1}") if i < len(questions_list) else f"Q{i+1}"
        a_text = a.get("answer", "") if isinstance(a, dict) else str(a)
        parts.append(f"Q: {q_text}\nA: {a_text}")
    return "\n\n".join(parts) if parts else "No answers provided."


# propose_memory_core removed in M7: the koan_memory_propose approval gate is
# retired; curation writes memory directly via koan_memorize/koan_forget with
# the self-critique checklist as the quality gate.

# -- M6: in-process subagent spawning ------------------------------------------
# koan_request_scouts / koan_request_executor spawn subagents as in-process
# asyncio tasks rather than CLI subprocesses. spawn_subagent itself runs the
# child's PydanticAIAgent loop in-process; these cores own the task registry
# (AppState._active_tasks, for shutdown cancellation), scout concurrency, and
# crash containment (a subagent failure becomes a failed result, never an
# exception that unwinds the parent orchestrator loop).


async def spawn_tracked_subagent(
    app_state: AppState,
    task: dict,
    semaphore: "Any | None" = None,
):
    """Run spawn_subagent as a tracked, crash-contained asyncio task.

    Registers the task in app_state._active_tasks (keyed by the subagent dir)
    so shutdown can cancel it, and converts any unexpected exception into a
    failed SubagentResult. Cancellation propagates (shutdown must win).
    """
    import asyncio
    from ..subagent import spawn_subagent, SubagentResult

    async def _run():
        if semaphore is not None:
            async with semaphore:
                return await spawn_subagent(task, app_state)
        return await spawn_subagent(task, app_state)

    key = task.get("subagent_dir") or task.get("label") or str(id(task))
    t = asyncio.ensure_future(_run())
    app_state._active_tasks[key] = t
    try:
        return await t
    except asyncio.CancelledError:
        raise
    except Exception as e:  # belt-and-suspenders: spawn_subagent already
        # converts AgentError into a result; this guards any other escape.
        return SubagentResult(exit_code=1, error=f"subagent crashed: {e}")
    finally:
        app_state._active_tasks.pop(key, None)


async def request_scouts_core(deps: ToolDeps, questions: list[dict] | None) -> str:
    """Spawn one scout subagent per question (bounded by scout_concurrency) and
    return their concatenated findings. Cores never raise on subagent failure --
    a failed scout simply contributes no finding.

    A wrong-phase call by the orchestrator returns a recoverable
    tool_unavailable_in_phase envelope before any scouts are spawned.
    """
    import asyncio
    import uuid
    app_state = deps.app_state
    agent = deps.agent

    gate = _tool_phase_gate_result(deps, "koan_request_scouts")
    if gate is not None:
        return gate

    if not questions:
        return "No scouts requested."

    from ..run_state import ensure_subagent_directory
    from ..events import build_agents_cleared, build_scout_queued

    semaphore = asyncio.Semaphore(app_state.provider_config.config.scout_concurrency)
    run_dir = _resolve_run_dir_core(agent, app_state) or ""

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
            "project_dir": app_state.run.project_dir,
            "additional_dirs": app_state.run.additional_dirs,
            "question": q.get("prompt", ""),
            "investigator_role": q.get("role", "investigator"),
        })

    # Clear stale non-primary agents before queuing the new batch.
    app_state.projection_store.push_event("agents_cleared", build_agents_cleared())
    for st in scout_tasks:
        app_state.projection_store.push_event(
            "scout_queued",
            build_scout_queued(scout_id=st.get("label", ""), label=st.get("label", "")),
        )

    async def _one(scout_task: dict) -> str | None:
        result = await spawn_tracked_subagent(app_state, scout_task, semaphore)
        if result.exit_code != 0:
            return None
        return result.final_response or None

    results = await asyncio.gather(*[_one(t) for t in scout_tasks])
    findings = [r for r in results if r is not None]
    if not findings:
        return "No findings returned."
    return "\n\n---\n\n".join(findings)


async def request_executor_core(
    deps: "ToolDeps",
    plan_file: str | None = None,
    instructions: str | None = None,
) -> str:
    """Validate, emit events, spawn the executor, and return the deviation report.

    Flow: validate -> execute_entry event -> spawn (blocking) -> execute_completion
    event -> return deviation report.

    A wrong-phase call by the orchestrator returns a recoverable
    tool_unavailable_in_phase envelope before any validation or spawning.

    Artifact listing is always the standing context set (brief, tech-plan,
    core-flows, milestones). When plan_file is given it is prepended to the
    listing and a "Read and implement the plan in <plan_file>" directive is
    prepended to any caller-supplied instructions. When plan_file is absent the
    executor is driven purely by the free-form instructions (required in that
    case -- enforced by validate_executor_request).

    Re-execution is intentionally allowed; the same plan may be passed multiple
    times without error.

    Args:
        deps: Tool dependencies (app_state + agent).
        plan_file: Optional plan artifact to implement.
        instructions: Optional free-form fix instructions. Required when
            plan_file is absent.
    """
    from pathlib import Path

    from ..artifacts import list_artifacts
    from ..tools import artifact_registry

    agent = deps.agent
    app_state = deps.app_state

    gate = _tool_phase_gate_result(deps, "koan_request_executor")
    if gate is not None:
        return gate

    run_dir = _resolve_run_dir_core(agent, app_state)
    if not run_dir:
        raise ValueError("no_run_dir: No run directory available")

    existing_names = frozenset(
        a["path"] for a in list_artifacts(run_dir) if "/" not in a["path"]
    )

    err = artifact_registry.validate_executor_request(
        plan_file, instructions, existing_names=existing_names
    )
    if err is not None:
        return _permission_error_result(err)

    # Build artifact listing: plan first (when given), then standing context files.
    context_files = ("brief.md", "tech-plan.md", "core-flows.md", "milestones.md")
    artifacts = (
        ([plan_file] if plan_file else [])
        + [f for f in context_files if (Path(run_dir) / f).is_file() and f != plan_file]
    )

    # Compose the executor instructions: prepend the read-this-plan directive
    # when a plan is named so the executor knows its primary directive.
    if plan_file:
        composed = f"Read and implement the plan in `{plan_file}`.\n\n" + (instructions or "")
    else:
        composed = instructions or ""

    app_state.projection_store.push_event(
        "execute_entry",
        {"plan_file": plan_file or ""},
    )

    deviation_report, exit_code = await _spawn_executor(
        app_state, run_dir, artifacts, instructions=composed
    )

    outcome = "clean" if exit_code == 0 else "non_conforming"
    app_state.projection_store.push_event(
        "execute_completion",
        {"plan_file": plan_file or "", "outcome": outcome},
    )

    return deviation_report


# -- Full koan toolset builder -------------------------------------------------


def build_koan_toolset(allowed_names: "frozenset[str] | None" = None) -> Any:
    """Build a koan FunctionToolset with all implemented koan tools.

    Registers koan_set_phase, koan_suggest_next, koan_set_workflow, the 5
    memory tools, the 4 artifact tools, the interaction tool
    (koan_ask_question), koan_request_scouts, and koan_request_executor
    (phase-gated to execute; re-addition in M4 of this initiative).
    koan_memory_propose was removed in M7: curation writes memory directly.
    The step-advancement tool was removed in M6; end-of-turn drives advancement.

    Args:
        allowed_names: When provided, only tools whose names are in this set
            are registered.  Pass compose_toolset(policy, role, phase) here to
            get a phase-correct toolset.  When None, all implemented tools
            are registered (useful for tests that want the full vocabulary).

    Returns a FunctionToolset[ToolDeps].
    """
    from pydantic_ai.toolsets.function import FunctionToolset

    ts: FunctionToolset[ToolDeps] = FunctionToolset()

    # _reg is a local helper that respects the optional allowed_names filter.
    # All tool inner functions omit the ctx annotation for the same reason as
    # build_minimal_koan_toolset: 'from __future__ import annotations' turns
    # annotations into strings resolved against module globals, and RunContext
    # is not in module globals.  takes_ctx=True in add_function() informs
    # pydantic-ai without triggering get_type_hints() resolution.
    def _reg(func: Any, name: str, description: str) -> None:
        if allowed_names is None or name in allowed_names:
            ts.add_function(func, takes_ctx=True, name=name, description=description)

    # ---- M2 tools ----
    # The step-advancement tool was removed in M6. The resolver in run_agent_loop
    # calls _step_phase_handshake_core and _step_within_phase_core directly;
    # no tool entrypoint is needed -- end-of-turn drives step advancement.

    async def _koan_set_phase(ctx, phase: str) -> str:
        """Transition to a new workflow phase, or tombstone the workflow with 'done'.

        M5: pure routing -- no plan_file parameter. Execution is launched from
        within the execute phase via koan_request_executor.
        """
        return await apply_set_phase(ctx.deps, phase)

    _reg(
        _koan_set_phase,
        "koan_set_phase",
        (
            "Commit transition to the next workflow phase. Call after the user "
            "has confirmed a direction. End your turn after calling this tool -- "
            "the new phase's first step will be delivered automatically. "
            "Pass 'done' to end the workflow. "
            "To execute a plan, call koan_set_phase('execute') first, then call "
            "koan_request_executor from within the execute phase."
        ),
    )

    # ---- M6: koan_suggest_next ----

    async def _koan_suggest_next(ctx, suggestions: list[dict] | None = None) -> str:
        """Record the next-step suggestions to show the user at the upcoming phase-boundary hand-back."""
        return await suggest_next_core(ctx.deps, suggestions or [])

    _reg(
        _koan_suggest_next,
        "koan_suggest_next",
        (
            "Record the next-step suggestions to show the user at the upcoming "
            "phase-boundary hand-back. Call before ending your final turn of a phase. "
            "Args: suggestions (list of {id, label, command, recommended?})."
        ),
    )

    # ---- M3: workflow tool ----

    async def _koan_set_workflow(ctx, workflow: str) -> str:
        """Switch the active workflow mid-run, preserving all run-directory context."""
        return await apply_set_workflow(ctx.deps, workflow)

    _reg(
        _koan_set_workflow,
        "koan_set_workflow",
        (
            "Switch the active workflow mid-run. The new workflow's initial_phase "
            "becomes active; end your turn after calling this tool to begin. "
            "Pass a workflow name registered in koan/lib/workflows.py."
        ),
    )

    # Story tool wrappers (_koan_select/complete/retry/skip_story) and their
    # _reg() calls deleted in M1: see deletion note above the core functions.

    # ---- M3: memory tools ----

    async def _koan_memorize(
        ctx,
        type: str,
        title: str,
        body: str,
        related: list[str] | None = None,
        entry_id: int | None = None,
    ) -> str:
        """Write a memory entry.

        Creates a new entry when entry_id is omitted. Updates an existing
        entry when entry_id is provided.
        """
        return await memorize_core(ctx.deps, type, title, body, related, entry_id)

    async def _koan_forget(ctx, entry_id: int, type: str | None = None) -> str:
        """Remove a memory entry. Deletes the entry file from disk."""
        return await forget_core(ctx.deps, entry_id, type)

    async def _koan_memory_status(ctx, type: str | None = None) -> str:
        """Get an orientation view of project memory."""
        return await memory_status_core(ctx.deps, type)

    async def _koan_search(ctx, query: str, type: str | None = None, k: int = 5) -> str:
        """Search memory entries by semantic similarity."""
        return await search_core(ctx.deps, query, type, k)

    async def _koan_reflect(ctx, question: str, context: str | None = None) -> str:
        """Synthesize a cited briefing over project memory."""
        return await reflect_core(ctx.deps, question, context)

    _reg(
        _koan_memorize,
        "koan_memorize",
        (
            "Write a memory entry. Creates a new entry when entry_id is omitted; "
            "updates when entry_id is provided. Args: type, title, body, related, entry_id."
        ),
    )
    _reg(
        _koan_forget,
        "koan_forget",
        "Remove a memory entry by sequence number (entry_id). Optionally assert type.",
    )
    _reg(
        _koan_memory_status,
        "koan_memory_status",
        "Get project memory summary and entry listing. Optionally filter by type.",
    )
    _reg(
        _koan_search,
        "koan_search",
        (
            "Search memory entries by semantic similarity. "
            "Args: query (str), type (optional filter), k (number of results, default 5)."
        ),
    )
    _reg(
        _koan_reflect,
        "koan_reflect",
        (
            "Synthesize a cited briefing over project memory using an LLM loop. "
            "Args: question (str), context (optional str)."
        ),
    )

    # ---- M3: artifact tools ----

    async def _koan_artifact_write(ctx, filename: str, content: str) -> str:
        """Write or update a run-directory artifact (plain markdown, no frontmatter)."""
        return await artifact_write_core(ctx.deps, filename, content)

    async def _koan_artifact_edit(
        ctx,
        filename: str,
        anchor: str,
        text: str,
        end_anchor: str | None = None,
        edit_type: str = "replace",
    ) -> str:
        """Anchored in-place edit of an artifact body (anchor from koan_artifact_read)."""
        return await artifact_edit_core(ctx.deps, filename, anchor, text, end_anchor, edit_type)

    async def _koan_artifact_list(ctx) -> str:
        """List artifacts in the run directory."""
        return await artifact_list_core(ctx.deps)

    async def _koan_artifact_read(ctx, filename: str, offset: int = 0, limit: int = 2000) -> str:
        """Return anchored, line-numbered artifact content (run-dir scoped read)."""
        return await artifact_read_core(ctx.deps, filename, offset, limit)

    _reg(
        _koan_artifact_write,
        "koan_artifact_write",
        (
            "Write or update a run-directory artifact. Writes the body verbatim as plain "
            "markdown (no frontmatter). "
            "Args: filename (must match [a-z0-9][a-z0-9_-]*.md), content (markdown body)."
        ),
    )
    _reg(
        _koan_artifact_edit,
        "koan_artifact_edit",
        (
            "Anchored in-place edit of an artifact body. Read the artifact first "
            "(koan_artifact_read); "
            "copy the target line's anchor token ({anchor}§{line}) into `anchor`. "
            "edit_type='replace' (default) replaces the line, or the inclusive range "
            "[anchor, end_anchor]; empty `text` deletes. 'insert_before'/'insert_after' "
            "insert `text`. Args: filename, anchor, text, end_anchor?, edit_type?."
        ),
    )
    _reg(
        _koan_artifact_list,
        "koan_artifact_list",
        "List run-directory artifacts with path, size, and modification time.",
    )
    _reg(
        _koan_artifact_read,
        "koan_artifact_read",
        (
            "Read a run-directory artifact as anchored, line-numbered content "
            "({lineno}\\t{anchor}§{line}). Copy an anchor into koan_artifact_edit to "
            "change a line; page large artifacts with offset/limit. "
            "Args: filename, offset?, limit?."
        ),
    )

    # ---- M5: in-process interaction tools ----
    # koan_ask_question parks on a future resolved by the /api/interact endpoint.
    # koan_memory_propose was removed in M7: curation writes memory directly;
    # the /api/memory/curation endpoint and its future are both gone.

    async def _koan_ask_question(ctx, questions: list[dict] | None = None) -> str:
        """Ask the user one or more clarifying questions and return the answers."""
        return await ask_question_core(ctx.deps, questions or [])

    _reg(
        _koan_ask_question,
        "koan_ask_question",
        (
            "Ask the user one or more clarifying questions and receive answers. "
            "Blocks until the user responds (or yolo auto-answers). "
            "Args: questions (list of {question, options, context?, multi?})."
        ),
    )

    # ---- M6: in-process subagent spawning ----

    async def _koan_request_scouts(ctx, questions: list[dict] | None = None) -> str:
        """Spawn scout subagents to investigate questions; return their findings."""
        return await request_scouts_core(ctx.deps, questions)

    async def _koan_request_executor(
        ctx,
        plan_file: str | None = None,
        instructions: str | None = None,
    ) -> str:
        """Spawn the executor and return its deviation report."""
        return await request_executor_core(ctx.deps, plan_file, instructions)

    _reg(
        _koan_request_executor,
        "koan_request_executor",
        (
            "Spawn the executor (blocking) to implement changes and return its "
            "deviation report. Args: plan_file (optional -- a plan artifact to "
            "implement), instructions (optional free-form fix instructions). "
            "instructions is required when plan_file is omitted. "
            "Repeatable -- the same plan may be re-run."
        ),
    )

    _reg(
        _koan_request_scouts,
        "koan_request_scouts",
        (
            "Spawn one read-only scout subagent per question (bounded by "
            "scout_concurrency) to investigate the codebase in parallel; blocks "
            "until all return, then yields their concatenated findings. "
            "Args: questions (list of {id, prompt, role?})."
        ),
    )

    return ts


# -- PydanticAI toolset builder ------------------------------------------------


def build_minimal_koan_toolset() -> Any:
    """Build a minimal toolset with only koan_set_phase and koan_suggest_next.

    Kept for backwards compatibility; callers that need the full toolset should
    use build_koan_toolset() directly.  PydanticAIAgent.run() uses
    build_koan_toolset() in M3+.
    The step-advancement tool was removed in M6.
    """
    return build_koan_toolset(allowed_names=frozenset({"koan_set_phase", "koan_suggest_next"}))
