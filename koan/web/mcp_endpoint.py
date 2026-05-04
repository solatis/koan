# MCP endpoint -- fastmcp server with permission-fenced tool handlers.
#
# Exposes build_mcp_asgi_app() which returns an ASGI sub-app that:
#   1. Validates agent_id from query params before reaching fastmcp.
#   2. Runs check_permission() on every tool call via AgentResolutionMiddleware.
#   3. Implements koan_complete_step, koan_yield, koan_request_scouts,
#      koan_ask_question, koan_set_phase, koan_set_workflow, koan_request_executor,
#      and story management tools.
#
# Phase boundary flow:
#   koan_complete_step (last step) -> invoke_after from terminal_invoke() tells the
#   orchestrator to call koan_set_phase (auto-advance) or koan_yield (full yield).
#   If the orchestrator accidentally calls koan_complete_step instead, a defensive
#   fallback nudges it back to the right path.
#   -> koan_yield blocks on AppState.interactions.yield_future until POST /api/chat resolves it
#   -> orchestrator converses, then calls koan_set_phase(phase) or koan_set_phase("done")
#      (or koan_set_workflow(workflow) for a mid-run workflow switch)
#
# koan_yield is phase-agnostic -- it works wherever the orchestrator needs to
# pause for user input, not only at phase boundaries.
#
# koan_set_phase("done") is a tombstone: sets AppState.run.workflow_done = True,
# emits workflow_completed, and causes the next koan_complete_step to return
# an exit signal so the orchestrator process terminates cleanly.

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Literal
from urllib.parse import parse_qs

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_request
from mcp.types import ContentBlock, TextContent

from ..run_state import (
    atomic_write_json,
    ensure_subagent_directory,
    load_story_state,
    save_run_state,
    save_story_state,
    load_run_state,
)
from ..lib.permissions import check_permission
from ..lib.task_json import make_workflow_history_entry
from ..lib.workflows import WORKFLOWS, get_suggested_phases, get_workflow, is_valid_transition as wf_is_valid
from ..logger import get_logger, truncate_payload
from ..memory import MEMORY_TYPES, MemoryStore
from ..memory.timestamps import iso_to_ms as _iso_to_ms
from ..phases import PhaseContext, StepGuidance
from ..phases.format_step import (
    format_step,
    format_user_messages,
    steering_envelope_open,
    steering_envelope_close,
    steering_message_block,
)
from .interactions import activate_next_interaction, enqueue_interaction
from ..projections import (
    ActiveCurationBatch, MemoryEntrySummary, Proposal,
    BaseToolEntry, TextEntry, ThinkingEntry, YieldEntry,
)

if TYPE_CHECKING:
    from ..state import AgentState, AppState

log = get_logger("mcp")


# -- Module-level pure helpers (no app_state dependency) ----------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_block(s: str) -> TextContent:
    """Wrap a plain string as a TextContent block.

    Single-text-block returns are wire-identical to plain string tool returns
    in fastmcp; this helper keeps the wrap site uniform across ~20 handlers
    so a future annotation change (e.g. adding metadata) touches one place.
    """
    return TextContent(type="text", text=s)




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


def _yolo_yield_response(suggestions: list[dict] | None) -> str:
    """Return the auto-response text for koan_yield when running in yolo mode.

    Priority: first recommended non-done suggestion's command
              -> first non-done suggestion's command
              -> "proceed"

    Driving by suggestion command keeps the orchestrator on the workflow's
    intended path without hardcoding any phase names here.
    """
    if not suggestions:
        return "proceed"
    for s in suggestions:
        if s.get("recommended") and s.get("id") != "done":
            return s.get("command", "proceed")
    for s in suggestions:
        if s.get("id") != "done":
            return s.get("command", "proceed")
    return "proceed"


def _yolo_ask_answer(questions: list[dict]) -> dict:
    """Return a synthetic answer dict for koan_ask_question when running in yolo mode.

    For each question, selects the option marked recommended: true (using its
    label). Falls back to "use your best judgement" when no option is
    recommended, giving the orchestrator latitude to decide.

    Returns a dict matching the shape expected by the existing answer-formatting
    loop: {"answers": [{"answer": "..."}]}.
    """
    answers = []
    for q in questions:
        options = q.get("options") or []
        recommended = next((o for o in options if o.get("recommended")), None)
        if recommended:
            answers.append({"answer": recommended.get("label", recommended.get("value", ""))})
        else:
            answers.append({"answer": "use your best judgement"})
    return {"answers": answers}


def _directed_yolo_response(directed_phases: list[str], current_phase: str) -> str:
    """Build the auto-response text when directed_phases is set.

    Finds current_phase in directed_phases and returns a command that steers
    the orchestrator toward the next phase in the list. Returns "proceed" when
    current_phase is not found or is already the last entry.

    Pure function -- keeps AppState out of the helper, consistent with the
    _yolo_yield_response pattern and easy to unit-test independently.
    """
    try:
        idx = directed_phases.index(current_phase)
    except ValueError:
        return "proceed"
    if idx + 1 >= len(directed_phases):
        return "proceed"
    next_phase = directed_phases[idx + 1]
    if next_phase == "done":
        return 'The workflow is complete. Call koan_set_phase("done") to end.'
    return f"Proceed to the {next_phase} phase."


# -- Artifact tool helpers (pure, no app_state) --------------------------------

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


def _render_curation_payload(
    batch: ActiveCurationBatch,
    decisions: list[dict],
    uploads: "UploadState",
    run_dir: str,
    runner_type: str,
) -> tuple[list[ContentBlock], list[dict]]:
    """Render a curation payload into MCP content blocks and an audit manifest.

    Block 0 is always the JSON blob (preserves json.loads(result[0].text) parse
    in the orchestrator). Per-decision attachment sections follow as separate
    blocks so the orchestrator receives file content adjacent to each decision.

    Moved from app.py so uploads and runner_type are in scope. Callers in
    app.py now set future.set_result(decisions) (raw list); koan_memory_propose
    calls this function after the future resolves.
    """
    from .uploads import upload_ids_to_blocks

    by_id = {p.id: p for p in batch.proposals}
    items = []
    for d in decisions:
        pid = d.get("proposal_id", "")
        p = by_id.get(pid)
        if p is None:
            continue
        items.append({
            "proposal_id": pid,
            "op": p.op,
            "seq": p.seq,
            "type": p.type,
            "title": p.title,
            "decision": d.get("decision", "rejected"),
            "feedback": d.get("feedback", ""),
        })
    payload_json = {"batch_id": batch.batch_id, "decisions": items}

    blocks: list[ContentBlock] = [_text_block(json.dumps(payload_json, indent=2))]
    manifest: list[dict] = []

    # Append per-decision attachment sections after the JSON blob.
    # The label block preserves adjacency between context and attachments
    # so the orchestrator can correlate files with the decision they annotate.
    for d in decisions:
        attach_ids = d.get("attachments") or []
        if attach_ids:
            pid = d.get("proposal_id", "?")
            blocks.append(_text_block(f"-- Attachments for proposal {pid} --"))
            bs, ms = upload_ids_to_blocks(uploads, run_dir, attach_ids, runner_type)
            blocks.extend(bs)
            manifest.extend(ms)

    return blocks, manifest


def _yolo_memory_propose_response(batch: ActiveCurationBatch) -> str:
    """Return a synthetic curation payload for yolo mode -- all proposals approved.

    Mirrors _render_curation_payload output so the orchestrator sees identical
    structure in yolo and interactive runs.
    """
    items = [
        {
            "proposal_id": p.id,
            "op": p.op,
            "seq": p.seq,
            "type": p.type,
            "title": p.title,
            "decision": "approved",
            "feedback": "",
        }
        for p in batch.proposals
    ]
    payload = {"batch_id": batch.batch_id, "decisions": items}
    return json.dumps(payload, indent=2)


# -- Permission check (module-level so test_mcp_check_or_raise.py can import it directly) --

def _check_or_raise(
    agent: AgentState,
    app_state: AppState,
    tool_name: str,
    tool_args: dict | None = None,
) -> None:
    """Enforce permission fence. Raises ToolError on denial."""
    phase_ctx = agent.phase_ctx
    resolved_run_dir = (
        phase_ctx.run_dir if phase_ctx is not None and phase_ctx.run_dir
        else agent.run_dir or None
    )
    current_phase = app_state.run.phase if app_state is not None else None
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


# -- Memory ops imports (module-level; referenced from closures inside factory) --

from ..memory import ops as memory_ops
from ..memory.ops import EntryNotFoundError, TypeMismatchError
from ..memory.types import MEMORY_TYPES
from ..memory.retrieval import RetrievalIndex, search as retrieval_search
from ..memory.retrieval import (
    IterationCapExceeded,
    ReflectResult,
    ReflectTraceEvent,
    run_reflect_agent,
)


# -- Handlers dataclass -------------------------------------------------------

@dataclass
class Handlers:
    """Record of every tool handler closure returned by build_mcp_server.

    Used by tests to invoke handlers directly without going through fastmcp's
    HTTP dispatch. Each field is the raw async closure that the factory defined
    and registered with mcp.tool().
    """
    koan_complete_step: Callable[..., Awaitable[str]]
    koan_yield: Callable[..., Awaitable[str]]
    koan_set_phase: Callable[..., Awaitable[str]]
    koan_set_workflow: Callable[..., Awaitable[str]]
    koan_request_scouts: Callable[..., Awaitable[str]]
    koan_ask_question: Callable[..., Awaitable[str]]
    koan_request_executor: Callable[..., Awaitable[str]]
    koan_select_story: Callable[..., Awaitable[str]]
    koan_complete_story: Callable[..., Awaitable[str]]
    koan_retry_story: Callable[..., Awaitable[str]]
    koan_skip_story: Callable[..., Awaitable[str]]
    koan_memorize: Callable[..., Awaitable[str]]
    koan_forget: Callable[..., Awaitable[str]]
    koan_memory_status: Callable[..., Awaitable[str]]
    koan_search: Callable[..., Awaitable[str]]
    koan_reflect: Callable[..., Awaitable[str]]
    koan_artifact_write: Callable[..., Awaitable[str]]
    koan_memory_propose: Callable[..., Awaitable[str]]
    koan_artifact_list: Callable[..., Awaitable[str]]
    koan_artifact_view: Callable[..., Awaitable[str]]


# -- AgentResolutionMiddleware ------------------------------------------------

class AgentResolutionMiddleware(Middleware):
    """Resolve the per-request AgentState from the HTTP query string and stash
    it on the fastmcp Context state-bag before the tool handler runs.

    Using request-scoped state (serializable=False) ensures the agent object
    lives only for the duration of the tool call, matching the ContextVar
    lifetime it replaces. Tool handlers read it via ctx.get_state("agent").
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        ctx = context.fastmcp_context
        if ctx is None:
            # Defensive: fastmcp_context is typed Optional. In the HTTP
            # tool-call path it is always set, but we guard here so a future
            # fastmcp refactor does not silently break us.
            raise ToolError(json.dumps({
                "error": "internal_error",
                "message": "fastmcp_context not attached to tool-call middleware",
            }))
        req = get_http_request()
        agent_id = req.query_params.get("agent_id")
        agent = self._app_state.agents.get(agent_id) if agent_id else None
        if agent is None:
            raise ToolError(json.dumps({
                "error": "permission_denied",
                "message": "Unknown or inactive agent",
            }))
        await ctx.set_state("agent", agent, serializable=False)
        return await call_next(context)


# -- Factory ------------------------------------------------------------------

def build_mcp_server(app_state: AppState) -> tuple[FastMCP, Handlers]:
    """Build a fully-wired FastMCP server instance bound to app_state.

    All tool handlers are closures that capture app_state lexically.
    The factory is called exactly once per live server from build_mcp_asgi_app().
    Returns (mcp, handlers) where handlers exposes every closure for tests.
    """
    mcp = FastMCP(name="koan")
    mcp.add_middleware(AgentResolutionMiddleware(app_state))

    # -- Agent resolution helper ----------------------------------------------

    async def _get_agent(ctx: Context) -> AgentState:
        agent = await ctx.get_state("agent")
        if agent is None:
            raise ToolError(json.dumps({
                "error": "permission_denied", "message": "No agent context",
            }))
        return agent

    # -- Block utility helpers ------------------------------------------------

    def _text_of(blocks: list[ContentBlock] | None) -> str:
        """Concatenate the text of all TextContent blocks in a list.

        Used to derive a loggable/auditable string from a block list without
        reimplementing the join logic in each call site.
        """
        if not blocks:
            return ""
        return "\n\n".join(b.text for b in blocks if isinstance(b, TextContent))

    # -- Logging / projection helpers (capture app_state) ---------------------

    def _log_tool_call(agent: AgentState, tool: str, summary: str) -> None:
        phase = app_state.run.phase
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
        """Log the start of a tool call. Returns call_id for audit correlation.

        # tool_called/tool_completed projection emission removed in M1: the
        # streaming stdout path is the single source of truth for tool lifecycle
        # events. begin_tool_call/end_tool_call retain audit-logging duties only.
        """
        call_id = str(uuid.uuid4())
        _log_tool_call(agent, tool, summary)
        return call_id

    def end_tool_call(
        agent: AgentState,
        call_id: str,
        tool: str,
        result: list[ContentBlock] | None = None,
        attachments: list[dict] | None = None,
    ) -> None:
        """Log the end of a tool call (audit only -- no projection event emitted).

        # tool_called/tool_completed projection emission removed in M1: the
        # streaming stdout path is the single source of truth for tool lifecycle
        # events. The call_id returned by begin_tool_call is a logging tag only.
        """
        text_portion: str | None = None
        if result is not None:
            text_parts: list[str] = [
                block.text
                for block in result
                if isinstance(block, TextContent)
            ]
            text_portion = "\n\n".join(text_parts) if text_parts else ""
        if text_portion:
            log.debug("tool %s call_id=%s result_len=%d", tool, call_id, len(text_portion))

    def _push_tool_attachments(manifest: list[dict], agent: AgentState) -> None:
        """Push tool_attachments domain event if manifest is non-empty.

        M3 tool_attachments: koan-side full manifests (with upload_id and path)
        flow to the projection through this dedicated domain event, separate from
        the runner-extracted partial manifest on tool_result content blocks. Fold
        targets the in-flight tool entry by agent_id. See plan-milestone-3.md
        decision 4.
        """
        if not manifest:
            return
        from ..events import build_tool_attachments
        app_state.projection_store.push_event(
            "tool_attachments",
            build_tool_attachments(manifest),
            agent_id=agent.agent_id,
        )

    def _resolve_run_dir(agent: AgentState) -> str | None:
        phase_ctx = agent.phase_ctx
        if phase_ctx is not None and phase_ctx.run_dir:
            return phase_ctx.run_dir
        if agent.run_dir:
            return agent.run_dir
        if app_state.run.run_dir:
            return app_state.run.run_dir
        return None

    def _drain_and_append_steering(
        blocks: list[ContentBlock],
        agent: AgentState | None = None,
    ) -> tuple[list[ContentBlock], list[dict]]:
        """Drain queued steering messages and append to a block list, for
        codex/gemini agents only.

        Claude agents receive steering via the ClaudeSDKAgent PostToolUse hook
        (koan/agents/claude.py) and bypass this path. Returning blocks unchanged
        for Claude leaves the steering queue intact for the hook to drain -- the
        two paths are mutually exclusive per agent, so there is no race.

        Returns (new_blocks, manifest); does not mutate the input so callers
        with aliased references stay consistent.
        """
        # Gate 1: only primary agents (orchestrators) receive steering.
        if agent is not None and not agent.is_primary:
            return blocks, []
        # Gate 2: Claude receives steering via the SDK PostToolUse hook; the
        # MCP-handler path is a no-op for Claude to prevent double-delivery.
        if agent is not None and agent.runner_type == "claude":
            return blocks, []
        from ..agents.steering import drain_for_primary, render_blocks
        messages = drain_for_primary(app_state, agent)
        if not messages:
            return blocks, []
        previews = [m.content[:80] for m in messages]
        log.info(
            "steering delivered via MCP handler | %d message(s): %s",
            len(messages), previews,
        )
        from ..events import build_steering_delivered
        app_state.projection_store.push_event(
            "steering_delivered", build_steering_delivered(len(messages)),
        )
        steering_blocks, steer_manifest = render_blocks(messages, app_state, agent)
        new_blocks: list[ContentBlock] = list(blocks) + steering_blocks
        return new_blocks, steer_manifest

    async def _compute_memory_injection(agent: AgentState) -> str:
        """Run the mechanical RAG injection pipeline for the current phase.

        Returns a rendered markdown block, or "" if the phase has no retrieval
        directive, memory is unavailable, or retrieval fails. Retrieval is
        best-effort: failure must never block the phase handshake.
        """
        workflow = app_state.run.workflow
        if workflow is None:
            return ""
        binding = workflow.get_binding(app_state.run.phase)
        if binding is None or not binding.retrieval_directive:
            return ""

        anchor = _compose_rag_anchor(
            task_description=app_state.run.task_description or "",
            run_dir=agent.phase_ctx.run_dir or app_state.run.run_dir,
        )

        try:
            from ..memory.retrieval.rag import inject, render_injection_block
            index = app_state.memory.retrieval_index
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
                app_state.run.phase,
                exc_info=True,
            )
            return ""

    # -- koan_complete_step private helpers (capture app_state) ---------------

    async def _step_phase_handshake(agent: AgentState) -> str:
        """Handle step 0 -> 1: deliver step 1 guidance prepended with phase role context."""
        phase_module = agent.phase_module
        ctx = agent.phase_ctx

        step_names = getattr(phase_module, "STEP_NAMES", {})
        step_name = step_names.get(1, "")

        # Audit log
        if agent.event_log is not None:
            await agent.event_log.emit_step_transition(1, step_name, phase_module.TOTAL_STEPS)

        # Projection event
        from ..events import build_step_advanced
        app_state.projection_store.push_event(
            "agent_step_advanced",
            build_step_advanced(1, step_name, total_steps=phase_module.TOTAL_STEPS),
            agent_id=agent.agent_id,
        )

        # Mechanical memory injection runs once per phase, at the step 0 -> 1
        # handshake. The rendered block is stashed on ctx.memory_injection and
        # phase modules prepend it to their step 1 instructions.
        ctx.memory_injection = await _compute_memory_injection(agent)

        # Populate auto-advance context for terminal_invoke in each phase's
        # last-step invoke_after. Done here (not in koan_set_phase) so the
        # values are available when step_guidance(TOTAL_STEPS, ctx) is called.
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

        # Prepend PHASE_ROLE_CONTEXT so the orchestrator receives the phase role context
        role_context = getattr(phase_module, "PHASE_ROLE_CONTEXT", "") or ""
        if role_context:
            guidance = StepGuidance(
                title=guidance.title,
                instructions=[role_context, ""] + list(guidance.instructions),
                invoke_after=guidance.invoke_after,
            )

        result = format_step(guidance)

        if app_state.server.debug:
            app_state.projection_store.push_event(
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
        app_state.projection_store.push_event(
            "agent_step_advanced",
            build_step_advanced(next_step, step_name, total_steps=phase_module.TOTAL_STEPS),
            agent_id=agent.agent_id,
        )

        # Scan for artifacts between steps (e.g. after a write step)
        from ..driver import _push_artifact_diff
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

    # -- Tool handlers (async closures capturing app_state) -------------------

    async def koan_complete_step(ctx: Context, thoughts: str = "") -> list[ContentBlock]:
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_complete_step", {"thoughts": thoughts})

        call_id = begin_tool_call(agent, "koan_complete_step", {"thoughts": thoughts}, f"step {agent.step} -> next")
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            agent.handshake_observed = True

            # workflow_done tombstone -- orchestrator called koan_set_phase("done") earlier
            if app_state.run.workflow_done:
                result_blocks = [_text_block("All phases complete. You may now exit.")]
                return result_blocks

            # Step 0: phase handshake (initial call or post-koan_set_phase)
            if agent.step == 0:
                result_blocks = [_text_block(await _step_phase_handshake(agent))]

                # Inject start-run attachments on the primary agent's very first
                # step-0 call. Guard on is_primary so scouts/executors never see
                # boot-time attachments. Clear after delivery so phase re-entries
                # (each koan_set_phase resets step to 0) do not re-emit them.
                if agent.is_primary and app_state.run.start_attachments:
                    from .uploads import upload_ids_to_blocks
                    attach_blocks, attach_manifest = upload_ids_to_blocks(
                        app_state.uploads,
                        "",  # run_dir is vestigial in upload_ids_to_blocks (M3)
                        app_state.run.start_attachments,
                        agent.runner_type,
                    )
                    result_blocks.extend(attach_blocks)
                    steer_manifest.extend(attach_manifest)
                    app_state.run.start_attachments = []
                    log.info(
                        "start-run attachments delivered: agent=%s count=%d",
                        agent.agent_id[:8], len(attach_blocks),
                    )

                result_blocks, drain_manifest = _drain_and_append_steering(result_blocks, agent)
                steer_manifest.extend(drain_manifest)
                _push_tool_attachments(steer_manifest, agent)
                return result_blocks

            phase_module = agent.phase_module
            ctx_phase = agent.phase_ctx
            current_step = agent.step

            # Validate current step completion
            err = phase_module.validate_step_completion(current_step, ctx_phase)
            if err:
                raise ToolError(
                    json.dumps({"error": "step_validation_failed", "message": err})
                )

            # Get next step
            next_step = phase_module.get_next_step(current_step, ctx_phase)

            if next_step is None:
                if not agent.is_primary:
                    # Non-primary agents (scouts) are done -- signal completion
                    result_blocks = [_text_block("All steps complete. You may now exit.")]
                    return result_blocks
                # Phase boundary defensive fallback. After M3 the orchestrator should
                # never land here -- the prior step's invoke_after (from terminal_invoke)
                # directed it to call koan_set_phase or koan_yield directly. If it
                # accidentally calls koan_complete_step anyway, nudge it back.
                from ..events import build_step_advanced
                app_state.projection_store.push_event(
                    "agent_step_advanced",
                    build_step_advanced(agent.step, "", total_steps=phase_module.TOTAL_STEPS),
                    agent_id=agent.agent_id,
                )
                from ..driver import _push_artifact_diff
                _push_artifact_diff(app_state)
                result_blocks = [_text_block(
                    "This phase has no further steps. The directive at the end of your"
                    " prior step's guidance instructed you to call koan_set_phase or"
                    " koan_yield -- follow that directive now."
                )]
                result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
                _push_tool_attachments(steer_manifest, agent)
                return result_blocks

            # Normal within-phase advancement
            result_blocks = [_text_block(await _step_within_phase(agent, phase_module, ctx_phase, next_step))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks

        finally:
            end_tool_call(agent, call_id, "koan_complete_step", result_blocks, steer_manifest or None)

    async def koan_yield(
        ctx: Context,
        suggestions: list[dict] | None = None,
    ) -> list[ContentBlock]:
        """Yield to the user and wait for their reply. ORCHESTRATOR-ONLY.

        This tool is reserved for the persistent orchestrator agent. Scouts and
        executors are denied by the permission fence -- if you are a subagent,
        do not call this, return your findings as your final text response
        instead.

        Blocks until the user sends a message; returns it as the tool result.
        This is the phase-end checkpoint -- call it when you need the user to
        pick the next phase or steer the workflow. Call in a loop for
        multi-turn conversation.

        Use koan_yield for phase-boundary decisions; use koan_artifact_write
        to produce or update artifacts (non-blocking).

        Suggestions (optional) render as clickable pills that pre-fill the chat.
        Each dict: id (phase name or "done"), label (short display), command
        (pre-filled text on click).

        Args:
            suggestions: Pills shown above the chat input.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_yield", {"suggestions": suggestions})

        call_id = begin_tool_call(
            agent, "koan_yield", {},
            f"{len(suggestions or [])} suggestion(s)",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        # reply_manifest collects attachment manifests from per-message attachment blocks;
        # steer_manifest collects from steering drain; both flow into end_tool_call.
        reply_manifest: list[dict] = []
        try:
            from ..state import drain_user_messages, drain_steering_messages

            # Emit yield_started -- renders YieldEntry in the conversation stream and
            # sets run.active_yield so the UI pins pills above the chat input.
            from ..events import build_yield_started
            app_state.projection_store.push_event(
                "yield_started",
                build_yield_started(suggestions or []),
                agent_id=agent.agent_id,
            )

            if app_state.server.yolo:
                # Resolve immediately without blocking -- the projection event above
                # already rendered the yield card in the UI; the synthesized response
                # closes it on the next tick.
                directed = app_state.server.directed_phases
                if directed is not None:
                    # Directed mode: steer toward the next phase in the sequence
                    # rather than picking from suggestions.
                    result_blocks = [_text_block(_directed_yolo_response(directed, app_state.run.phase))]
                else:
                    result_blocks = [_text_block(_yolo_yield_response(suggestions))]
            else:
                # Check for already-buffered messages (user typed before we yielded)
                messages = drain_user_messages(app_state) + drain_steering_messages(app_state)

                if not messages:
                    loop = asyncio.get_running_loop()
                    future = loop.create_future()
                    app_state.interactions.yield_future = future

                    await future  # yields to event loop; POST /api/chat resolves it

                    app_state.interactions.yield_future = None
                    messages = drain_user_messages(app_state)

                # Interleave per-message File/Image blocks adjacent to each message text.
                # format_user_messages returns one TextContent per message so the zip works.
                if messages:
                    from .uploads import upload_ids_to_blocks
                    text_blocks = format_user_messages(messages)
                    result_blocks = []
                    for msg, tb in zip(messages, text_blocks):
                        result_blocks.append(tb)
                        if msg.attachments:
                            bs, ms = upload_ids_to_blocks(
                                app_state.uploads,
                                app_state.run.run_dir or "",
                                msg.attachments,
                                agent.runner_type,
                            )
                            result_blocks.extend(bs)
                            reply_manifest.extend(ms)
                else:
                    result_blocks = [_text_block("No message received.")]

            # Log after both yolo and chat paths converge on result_blocks.
            reply_text = _text_of(result_blocks)
            if reply_text:
                log.info(
                    "koan_yield resolved: agent=%s phase=%s mode=%s reply_len=%d",
                    agent.agent_id[:8], app_state.run.phase,
                    "yolo" if app_state.server.yolo else "chat",
                    len(reply_text),
                )
                log.debug("koan_yield reply payload: %s", truncate_payload(reply_text))

            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(reply_manifest + steer_manifest, agent)

            return result_blocks
        finally:
            total_manifest = reply_manifest + steer_manifest
            end_tool_call(agent, call_id, "koan_yield", result_blocks, total_manifest or None)

    async def koan_set_phase(ctx: Context, phase: str) -> list[ContentBlock]:
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
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_set_phase", {"phase": phase})

        call_id = begin_tool_call(agent, "koan_set_phase", {"phase": phase}, phase)
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            current = app_state.run.phase
            workflow = app_state.run.workflow

            # "done" tombstone -- cleanly ends the workflow without a phase transition
            if phase == "done":
                app_state.run.workflow_done = True
                app_state.projection_store.push_event("yield_cleared", {})
                app_state.projection_store.push_event("workflow_completed", {
                    "success": True,
                    "phase": current,
                    "summary": f"Workflow completed from phase '{current}'",
                })
                result_blocks = [_text_block("Workflow complete. Call koan_complete_step to finish.")]
                result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
                _push_tool_attachments(steer_manifest, agent)
                return result_blocks

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

            # Log before mutating phase so the old value is still current.
            log.info(
                "phase transition: agent=%s from=%s to=%s",
                agent.agent_id[:8], app_state.run.phase, phase,
            )

            # Update driver state
            app_state.run.phase = phase
            run_dir = _resolve_run_dir(agent)
            if run_dir:
                run_state = await load_run_state(run_dir)
                await save_run_state(run_dir, {**run_state, "phase": phase})

            # Push artifact diff and phase_started event
            from ..driver import _push_artifact_diff
            _push_artifact_diff(app_state)
            app_state.projection_store.push_event(
                "phase_started",
                {"phase": phase},
                agent_id=agent.agent_id,
            )
            # Clear any active yield now that a phase transition is committed
            app_state.projection_store.push_event("yield_cleared", {})

            # Emit a step-advanced event (step=0) as visual phase-transition marker in the feed
            phase_label = phase.replace("-", " ").title()
            from ..events import build_step_advanced
            app_state.projection_store.push_event(
                "agent_step_advanced",
                build_step_advanced(0, f"-> {phase_label}"),
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
                project_dir=app_state.run.project_dir,
                additional_dirs=app_state.run.additional_dirs,
                task_description=app_state.run.task_description,
                workflow_name=workflow.name if workflow else "",
                phase_instructions=phase_guidance,   # scope framing from workflow
                completed_phase=current,
            )

            result_blocks = [_text_block(f"Phase set to '{phase}'. Call koan_complete_step to begin.")]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_set_phase", result_blocks, steer_manifest or None)

    async def koan_set_workflow(ctx: Context, workflow: str) -> list[ContentBlock]:
        """Switch the active workflow mid-run, preserving the orchestrator
        process and all run-directory context.

        The orchestrator carries its full conversation context across the
        switch. The new workflow's initial_phase becomes the active phase;
        the next koan_complete_step call returns step 1 of that phase. The
        run directory and all artifacts produced under the previous workflow
        remain in place; the new workflow's phase_guidance handles
        cross-workflow context (e.g. an existing brief.md).

        Args:
            workflow: Target workflow name registered in
                      koan/lib/workflows.py:WORKFLOWS. The orchestrator
                      can switch to any registered workflow at any time
                      (any-to-any). The new workflow's initial_phase is
                      entered automatically.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_set_workflow", {"workflow": workflow})

        call_id = begin_tool_call(agent, "koan_set_workflow", {"workflow": workflow}, workflow)
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            current_workflow_obj = app_state.run.workflow
            current_phase = app_state.run.phase

            # Validate target workflow name is registered.
            # get_workflow raises ValueError for unknown names; convert to ToolError
            # with the same invalid_transition shape used by koan_set_phase.
            try:
                new_workflow = get_workflow(workflow)
            except ValueError:
                raise ToolError(json.dumps({
                    "error": "unknown_workflow",
                    "message": (
                        f"'{workflow}' is not a registered workflow. "
                        f"Available workflows: {list(WORKFLOWS.keys())}"
                    ),
                }))

            new_initial_phase = new_workflow.initial_phase
            new_module = new_workflow.get_module(new_initial_phase)
            if new_module is None:
                raise ToolError(json.dumps({
                    "error": "internal_error",
                    "message": (
                        f"Workflow '{workflow}' has no module for its "
                        f"initial_phase '{new_initial_phase}'"
                    ),
                }))

            log.info(
                "workflow transition: agent=%s from=%s to=%s entering_phase=%s",
                agent.agent_id[:8],
                current_workflow_obj.name if current_workflow_obj else "?",
                workflow,
                new_initial_phase,
            )

            # Swap app_state.run.workflow before emitting projection events so
            # any fold consumer reading app_state sees the new value.
            app_state.run.workflow = new_workflow
            app_state.run.phase = new_initial_phase

            # Append to orchestrator task.json's workflow_history using the same
            # atomic write helper as all other task.json writers (brief.md constraint).
            from ..subagent import write_task_json
            import aiofiles
            orchestrator_task_path = Path(agent.subagent_dir) / "task.json"
            async with aiofiles.open(orchestrator_task_path, "r") as f:
                task_dict = json.loads(await f.read())
            history = list(task_dict.get("workflow_history", []))
            history.append(make_workflow_history_entry(workflow, new_initial_phase))
            task_dict["workflow_history"] = history
            await write_task_json(agent.subagent_dir, task_dict)

            # Persist phase to run-state.json (mirrors koan_set_phase).
            run_dir = _resolve_run_dir(agent)
            if run_dir:
                run_state = await load_run_state(run_dir)
                await save_run_state(run_dir, {**run_state, "phase": new_initial_phase})

            # Push artifact diff first so the projection snapshot includes any
            # pending artifact changes before workflow_selected rebuilds availablePhases.
            from ..driver import _push_artifact_diff
            _push_artifact_diff(app_state)

            # Emit projection events in order: workflow_selected rebuilds
            # Run.available_phases; phase_started then updates Run.phase;
            # yield_cleared clears any active yield UI state (mirrors koan_set_phase L992).
            from ..events import build_workflow_selected
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

            # Step-advanced visual marker (mirrors koan_set_phase L995-L1001).
            phase_label = new_initial_phase.replace("-", " ").title()
            from ..events import build_step_advanced
            app_state.projection_store.push_event(
                "agent_step_advanced",
                build_step_advanced(0, f"-> {workflow}: {phase_label}"),
                agent_id=agent.agent_id,
            )

            # Rebuild PhaseContext for the new workflow + initial phase.
            # Same pattern as koan_set_phase L1010-L1018; do not mutate in place.
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

            result_blocks = [_text_block(
                f"Workflow set to '{workflow}'. Now in phase "
                f"'{new_initial_phase}'. Call koan_complete_step to begin."
            )]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_set_workflow", result_blocks, steer_manifest or None)

    async def koan_request_scouts(ctx: Context, questions: list[dict] | None = None) -> list[ContentBlock]:
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_request_scouts", {"questions": questions})

        call_id = begin_tool_call(
            agent, "koan_request_scouts", {"questions": questions or []},
            f"{len(questions or [])} scouts",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            if not questions:
                result_blocks = [_text_block("No scouts requested.")]
                result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
                _push_tool_attachments(steer_manifest, agent)
                return result_blocks

            semaphore = asyncio.Semaphore(app_state.runner_config.config.scout_concurrency)
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
                    "project_dir": app_state.run.project_dir,
                    "additional_dirs": app_state.run.additional_dirs,
                    "question": q.get("prompt", ""),
                    "investigator_role": q.get("role", "investigator"),
                })

            async def run_scout(scout_task: dict) -> str | None:
                async with semaphore:
                    from ..subagent import spawn_subagent
                    result = await spawn_subagent(scout_task, app_state)

                    if result.exit_code != 0:
                        return None

                    return result.final_response or None

            # Clear stale non-primary agents before queuing the new batch
            from ..events import build_agents_cleared, build_scout_queued
            app_state.projection_store.push_event("agents_cleared", build_agents_cleared())
            for st in scout_tasks:
                app_state.projection_store.push_event(
                    "scout_queued",
                    build_scout_queued(
                        scout_id=st.get("label", ""),
                        label=st.get("label", ""),
                    ),
                )

            results = await asyncio.gather(*[run_scout(t) for t in scout_tasks])
            findings = [r for r in results if r is not None]

            if not findings:
                result_blocks = [_text_block("No findings returned.")]
                result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
                _push_tool_attachments(steer_manifest, agent)
                return result_blocks

            result_blocks = [_text_block("\n\n---\n\n".join(findings))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_request_scouts", result_blocks, steer_manifest or None)

    async def koan_ask_question(ctx: Context, questions: list[dict] | None = None) -> list[ContentBlock]:
        """Ask the user one or more clarifying questions.

        The UI renders a split-panel card for each question:
          - LEFT PANEL ("Context"): reference material the user reads while
            deciding. Write markdown here -- code snippets, bullet lists, bold
            terms, file references. This is your chance to show the user what
            you found and why the question matters. Think of it as an
            illustration panel, not a preamble.
          - RIGHT PANEL ("Decision"): the question text and selectable options.
            This is the action side -- keep the question crisp.

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
            or bullets -- the UI adds its own selection controls.
              WRONG:  "(a) Stateless wrapper"  /  "A: Stateless wrapper"
              RIGHT:  "Stateless wrapper -- compile per request, optimize later"
          - Do NOT include an "Other" or "None of the above" option.
            The UI always provides a free-text alternative automatically.
          - Keep labels concise (one line). Put rationale in `context`, not
            in the label.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_ask_question", {"questions": questions})

        call_id = begin_tool_call(
            agent, "koan_ask_question", {"questions": questions or []},
            f"{len(questions or [])} questions",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        answer_manifest: list[dict] = []
        try:
            future = await enqueue_interaction(agent, app_state, "ask", {"questions": questions or []})
            if app_state.server.yolo:
                # Resolve the future synchronously before awaiting so it returns on
                # the next event-loop tick without ever blocking on a POST /api/interact.
                # Safe: no external POST can race this within the same coroutine frame.
                future.set_result(_yolo_ask_answer(questions or []))
            result = await future

            if isinstance(result, dict) and "error" in result:
                raise ToolError(json.dumps(result))

            answers = result.get("answers", [])
            log.info(
                "koan_ask_question answered: agent=%s count=%d",
                agent.agent_id[:8], len(answers),
            )
            for i, a in enumerate(answers):
                body = a.get("answer", "") if isinstance(a, dict) else str(a)
                log.debug("ask_question answer[%d]: %s", i, truncate_payload(body))
            questions_list = questions or []
            # Interleave per-answer File/Image blocks adjacent to each Q/A text block.
            from .uploads import upload_ids_to_blocks
            result_blocks = []
            answer_manifest: list[dict] = []
            for i, a in enumerate(answers):
                q_text = questions_list[i].get("question", f"Q{i+1}") if i < len(questions_list) else f"Q{i+1}"
                a_text = a.get("answer", "") if isinstance(a, dict) else str(a)
                result_blocks.append(_text_block(f"Q: {q_text}\nA: {a_text}"))
                attach_ids = (a.get("attachments") or []) if isinstance(a, dict) else []
                if attach_ids:
                    bs, ms = upload_ids_to_blocks(
                        app_state.uploads,
                        app_state.run.run_dir or "",
                        attach_ids,
                        agent.runner_type,
                    )
                    result_blocks.extend(bs)
                    answer_manifest.extend(ms)
            if not result_blocks:
                result_blocks = [_text_block("No answers provided.")]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(answer_manifest + steer_manifest, agent)
            return result_blocks
        finally:
            total_manifest = answer_manifest + steer_manifest
            end_tool_call(agent, call_id, "koan_ask_question", result_blocks, total_manifest or None)

    async def koan_request_executor(
        ctx: Context,
        artifacts: list[str] | None = None,
        instructions: str = "",
    ) -> list[ContentBlock]:
        """Spawn a coding agent to implement changes.

        The executor reads the listed artifacts from the run directory,
        plans its approach internally, then implements. Blocks until
        the executor exits and returns a result summary.

        Args:
            artifacts: File paths relative to run directory that the
                       executor must read before coding.
                       Example: ["plan.md"]
            instructions: Free-form context for the executor -- key
                          decisions, constraints, or user direction
                          not captured in the artifact files.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_request_executor", {"artifacts": artifacts, "instructions": instructions})

        call_id = begin_tool_call(
            agent, "koan_request_executor",
            {"artifacts": artifacts or [], "instructions": instructions},
            f"{len(artifacts or [])} artifact(s)",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            run_dir = _resolve_run_dir(agent)
            if not run_dir:
                raise ToolError(json.dumps({"error": "no_run_dir", "message": "No run directory available"}))

            from ..events import build_agents_cleared
            app_state.projection_store.push_event("agents_cleared", build_agents_cleared())

            ts_suffix = int(time.time() * 1000)
            subagent_dir = await ensure_subagent_directory(
                run_dir, f"executor-{ts_suffix}"
            )

            task = {
                "role": "executor",
                "run_dir": run_dir,
                "subagent_dir": subagent_dir,
                "project_dir": app_state.run.project_dir,
                "additional_dirs": app_state.run.additional_dirs,
                "artifacts": artifacts or [],
                "instructions": instructions,
            }

            from ..subagent import spawn_subagent
            result = await spawn_subagent(task, app_state)

            if result.exit_code == 0:
                payload = {"status": "succeeded"}
            else:
                payload = {
                    "status": "failed",
                    "exit_code": result.exit_code,
                    "error": result.error or "",
                }
            result_blocks = [_text_block(json.dumps(payload))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_request_executor", result_blocks, steer_manifest or None)

    async def koan_select_story(ctx: Context, story_id: str) -> list[ContentBlock]:
        """Select the next story for execution."""
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_select_story", {"story_id": story_id})

        call_id = begin_tool_call(agent, "koan_select_story", {"story_id": story_id}, story_id)
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            run_dir = _resolve_run_dir(agent)
            if not run_dir:
                raise ToolError(json.dumps({"error": "no_run_dir"}))

            await save_story_state(run_dir, story_id, {
                "storyId": story_id,
                "status": "selected",
                "updatedAt": _now_iso(),
            })
            result_blocks = [_text_block(f"Story '{story_id}' selected for execution.")]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_select_story", result_blocks, steer_manifest or None)

    async def koan_complete_story(ctx: Context, story_id: str) -> list[ContentBlock]:
        """Mark a story as successfully verified and completed."""
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_complete_story", {"story_id": story_id})

        call_id = begin_tool_call(agent, "koan_complete_story", {"story_id": story_id}, story_id)
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            run_dir = _resolve_run_dir(agent)
            if not run_dir:
                raise ToolError(json.dumps({"error": "no_run_dir"}))

            await save_story_state(run_dir, story_id, {
                "storyId": story_id,
                "status": "done",
                "updatedAt": _now_iso(),
            })
            result_blocks = [_text_block(f"Story '{story_id}' marked as done.")]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_complete_story", result_blocks, steer_manifest or None)

    async def koan_retry_story(ctx: Context, story_id: str, failure_summary: str) -> list[ContentBlock]:
        """Send a story back for retry with a detailed failure summary."""
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_retry_story", {"story_id": story_id, "failure_summary": failure_summary})

        call_id = begin_tool_call(agent, "koan_retry_story", {"story_id": story_id}, story_id)
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
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
            result_blocks = [_text_block(f"Story '{story_id}' queued for retry (attempt {retry_count}).")]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_retry_story", result_blocks, steer_manifest or None)

    async def koan_skip_story(ctx: Context, story_id: str, reason: str = "") -> list[ContentBlock]:
        """Skip a story that is superseded or no longer needed."""
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_skip_story", {"story_id": story_id, "reason": reason})

        call_id = begin_tool_call(agent, "koan_skip_story", {"story_id": story_id}, story_id)
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
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
            result_blocks = [_text_block(f"Story '{story_id}' skipped.")]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_skip_story", result_blocks, steer_manifest or None)

    async def koan_memorize(
        ctx: Context,
        type: str,
        title: str,
        body: str,
        related: list[str] | None = None,
        entry_id: int | None = None,
    ) -> list[ContentBlock]:
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
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_memorize", {
            "type": type, "title": title, "entry_id": entry_id,
        })
        call_id = begin_tool_call(
            agent, "koan_memorize",
            {"type": type, "title": title, "entry_id": entry_id},
            f"{type}: {title}",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            store = app_state.memory.memory_store
            result = memory_ops.memorize(store, type, title, body, related, entry_id)

            # Emit memory mutation event so the projection and frontend stay in sync.
            # title and type are already in scope from the tool parameters.
            eid = result.get("entry_id")
            if eid is not None:
                from ..events import build_memory_entry_created, build_memory_entry_updated
                seq = f"{eid:04d}"
                summary = MemoryEntrySummary(
                    seq=seq,
                    type=result.get("type", type),  # type: ignore[arg-type]
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

            result_blocks = [_text_block(json.dumps(result))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        except EntryNotFoundError as e:
            raise ToolError(json.dumps({"error": "entry_not_found", "message": str(e)}))
        except TypeMismatchError as e:
            raise ToolError(json.dumps({"error": "type_mismatch", "message": str(e)}))
        except ValueError as e:
            raise ToolError(json.dumps({"error": "invalid_type", "message": str(e)}))
        finally:
            end_tool_call(agent, call_id, "koan_memorize", result_blocks, steer_manifest or None)

    async def koan_forget(ctx: Context, entry_id: int, type: str | None = None) -> list[ContentBlock]:
        """Remove a memory entry.

        Deletes the entry file from disk. Git preserves history.

        Args:
            entry_id: Sequence number (NNNN prefix from filename)
            type: Memory type (optional). When provided, the found entry's
                  type must match or a type_mismatch error is raised.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_forget", {"type": type, "entry_id": entry_id})
        call_id = begin_tool_call(
            agent, "koan_forget",
            {"type": type, "entry_id": entry_id},
            f"{type or '*'}/{entry_id}",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            store = app_state.memory.memory_store
            result = memory_ops.forget(store, entry_id, type)

            # Emit deletion event so the projection drops the entry immediately.
            from ..events import build_memory_entry_deleted
            seq = f"{result.get('entry_id', entry_id):04d}"
            app_state.projection_store.push_event(
                "memory_entry_deleted",
                build_memory_entry_deleted(seq),
                agent_id=agent.agent_id,
            )

            result_blocks = [_text_block(json.dumps(result))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        except EntryNotFoundError as e:
            raise ToolError(json.dumps({"error": "entry_not_found", "message": str(e)}))
        except TypeMismatchError as e:
            raise ToolError(json.dumps({"error": "type_mismatch", "message": str(e)}))
        except ValueError as e:
            raise ToolError(json.dumps({"error": "invalid_type", "message": str(e)}))
        finally:
            end_tool_call(agent, call_id, "koan_forget", result_blocks, steer_manifest or None)

    async def koan_memory_status(ctx: Context, type: str | None = None) -> list[ContentBlock]:
        """Get an orientation view of project memory.

        Returns the project summary and a flat listing of all entries.
        Checks whether summary.md is stale (older than the most recent
        entry) and regenerates it just-in-time before returning.

        Args:
            type: Filter listing to a specific memory type (optional).
                  The summary is always project-wide regardless of filter.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_memory_status", {"type": type})
        call_id = begin_tool_call(
            agent, "koan_memory_status", {"type": type}, type or "all",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            store = app_state.memory.memory_store
            result = await memory_ops.status(store, type=type)

            # Emit summary update if the just-in-time regeneration ran.
            if result.get("regenerated"):
                from ..events import build_memory_summary_updated
                app_state.projection_store.push_event(
                    "memory_summary_updated",
                    build_memory_summary_updated(result.get("summary", "")),
                    agent_id=agent.agent_id,
                )

            result_blocks = [_text_block(json.dumps(result))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        except ValueError as e:
            raise ToolError(json.dumps({
                "error": "invalid_type",
                "message": str(e),
            }))
        finally:
            end_tool_call(agent, call_id, "koan_memory_status", result_blocks, steer_manifest or None)

    async def koan_search(
        ctx: Context,
        query: str,
        type: str | None = None,
        k: int = 5,
    ) -> list[ContentBlock]:
        """Search memory entries by semantic similarity.

        Runs hybrid dense + BM25 search with cross-encoder reranking.
        Returns the top k entries most relevant to the query.

        Args:
            query: Search query string
            type: Filter results to a specific memory type (optional)
            k: Number of results to return (default: 5)
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_search", {"type": type})
        call_id = begin_tool_call(
            agent, "koan_search",
            {"query": query, "type": type, "k": k},
            f"query={query!r} type={type or 'all'} k={k}",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            if type is not None and type not in MEMORY_TYPES:
                raise ValueError(f"invalid type: {type!r}")
            index = app_state.memory.retrieval_index
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
            result_blocks = [_text_block(json.dumps(out))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        except ValueError as e:
            raise ToolError(json.dumps({"error": "invalid_type", "message": str(e)}))
        except RuntimeError as e:
            raise ToolError(json.dumps({"error": "search_failed", "message": str(e)}))
        finally:
            end_tool_call(agent, call_id, "koan_search", result_blocks, steer_manifest or None)

    async def koan_reflect(
        ctx: Context,
        question: str,
        context: str | None = None,
    ) -> list[ContentBlock]:
        """Synthesize a cited briefing over project memory.

        Runs a single-conversation LLM tool-calling loop that searches memory
        as many times as the model decides is needed, then returns a briefing
        with structured citations. Intended for broad questions that require
        synthesis across multiple entries.

        Args:
            question: The broad question to answer.
            context: Optional caller-provided context (e.g. the subsystem the
                     orchestrator is currently working on). Included in the
                     prompt alongside the question.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_reflect", {})
        call_id = begin_tool_call(
            agent, "koan_reflect",
            {"question": question, "context": context},
            f"question={question!r}",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []

        # _on_trace defined before try so it is in scope for run_reflect_agent.
        # Only kind="text" deltas flow into the agent's conversation feed (M3
        # decision 3). Other kinds (search, done, thinking) stay on the
        # project-scoped reflect projection handled by /api/memory/reflect.
        from ..events import build_reflect_delta

        def _on_trace(ev: ReflectTraceEvent) -> None:
            if ev.kind != "text":
                return
            if not ev.delta:
                return
            app_state.projection_store.push_event(
                "reflect_delta",
                build_reflect_delta(ev.delta),
                agent_id=agent.agent_id,
            )

        try:
            index = app_state.memory.retrieval_index
            result: ReflectResult = await run_reflect_agent(
                index, question, context=context, on_trace=_on_trace,
            )
            out = {
                "answer": result.answer,
                "citations": [
                    {"id": c.id, "title": c.title, "type": c.type, "modifiedMs": c.modified_ms}
                    for c in result.citations
                ],
                "iterations": result.iterations,
            }
            result_blocks = [_text_block(json.dumps(out))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        except IterationCapExceeded as e:
            raise ToolError(json.dumps({
                "error": "iteration_cap_exceeded",
                "message": str(e),
                "iterations": e.iterations,
            }))
        except RuntimeError as e:
            raise ToolError(json.dumps({"error": "reflect_failed", "message": str(e)}))
        finally:
            end_tool_call(agent, call_id, "koan_reflect", result_blocks, steer_manifest or None)

    async def koan_artifact_write(
        ctx: Context,
        filename: str,
        content: str,
        status: str | None = None,
    ) -> list[ContentBlock]:
        """Write or update an artifact file. Non-blocking; full-rewrite semantics.

        Driver-managed YAML frontmatter (status, created, last_modified) is
        composed onto the body. The `status` parameter optionally flips the
        artifact's lifecycle marker (Draft / Approved / In-Progress / Final);
        if omitted, the existing status is preserved or defaulted to In-Progress
        on first write.

        Args:
            filename: Root-only basename, must match [a-z0-9][a-z0-9_-]*.md
            content: Full markdown body (no frontmatter; the driver writes it).
            status: Optional lifecycle marker. Must be one of STATUS_VALUES.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_artifact_write",
                        {"filename": filename, "status": status})

        call_id = begin_tool_call(
            agent, "koan_artifact_write",
            {"filename": filename, "content_len": len(content or ""), "status": status},
            f"write {filename}",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            err = _validate_artifact_filename(filename)
            if err:
                raise ToolError(json.dumps({
                    "error": "invalid_filename", "message": err,
                }))

            run_dir = _resolve_run_dir(agent)
            if not run_dir:
                raise ToolError(json.dumps({
                    "error": "no_run_dir",
                    "message": "No run directory available",
                }))

            from ..artifacts import write_artifact_atomic
            target = Path(run_dir) / filename
            try:
                meta = write_artifact_atomic(target, content or "", status)
            except ValueError as exc:
                raise ToolError(json.dumps({
                    "error": "invalid_status", "message": str(exc),
                }))

            # Emit artifact diff so the sidebar reflects the new/updated file.
            from ..driver import _push_artifact_diff
            _push_artifact_diff(app_state)

            result_blocks = [_text_block(json.dumps({
                "ok": True,
                "filename": filename,
                "status": meta.get("status"),
            }))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_artifact_write", result_blocks, steer_manifest or None)

    async def koan_memory_propose(
        ctx: Context,
        proposals: list[dict],
        context_note: str = "",
    ) -> list[ContentBlock]:
        """Propose one or more memory entries to the user for approval; block until
        they submit decisions.

        Returns a structured JSON payload the orchestrator reads to decide which
        proposals to apply via koan_memorize / koan_forget, which to revise and
        re-propose, and which to drop.

        Args:
            proposals: List of proposal dicts matching the Proposal wire schema.
            context_note: Optional free-form note shown above the proposal list.
        """
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_memory_propose", {})

        call_id = begin_tool_call(
            agent, "koan_memory_propose",
            {"proposal_count": len(proposals or []), "context_note": context_note},
            f"{len(proposals or [])} proposal(s)",
        )
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        curation_manifest: list[dict] = []
        try:
            # Validate proposals list is non-empty and each item matches Proposal schema.
            if not proposals:
                raise ToolError(json.dumps({
                    "error": "invalid_proposal",
                    "message": "proposals must be a non-empty list",
                }))
            validated: list[Proposal] = []
            for p in proposals:
                try:
                    validated.append(Proposal.model_validate(p))
                except Exception as exc:
                    raise ToolError(json.dumps({
                        "error": "invalid_proposal",
                        "message": f"proposal validation failed: {exc}",
                    }))

            # Reentry guard: refuse if a prior propose is still pending.
            existing = app_state.interactions.memory_propose_future
            if existing is not None and not existing.done():
                raise ToolError(json.dumps({
                    "error": "propose_already_pending",
                    "message": (
                        "A prior memory proposal is still awaiting "
                        "review; resolve it before calling "
                        "koan_memory_propose again."
                    ),
                }))

            # Build the batch and emit the started event.
            batch = ActiveCurationBatch(
                proposals=validated,
                batch_id=uuid.uuid4().hex,
                context_note=context_note,
            )
            from ..events import build_memory_curation_started
            app_state.projection_store.push_event(
                "memory_curation_started",
                build_memory_curation_started(batch.to_wire()),
                agent_id=agent.agent_id,
            )

            # api_memory_curation_submit now sets the raw decisions list on the future
            # so this handler can call _render_curation_payload with uploads and runner_type
            # in scope for per-decision attachment interleaving.
            if app_state.server.yolo:
                result_blocks = [_text_block(_yolo_memory_propose_response(batch))]
            else:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                app_state.interactions.memory_propose_future = future
                try:
                    decisions = await future
                finally:
                    app_state.interactions.memory_propose_future = None
                if not isinstance(decisions, list):
                    decisions = []
                run_dir_for_curation = _resolve_run_dir(agent) or ""
                result_blocks, curation_manifest = _render_curation_payload(
                    batch, decisions,
                    app_state.uploads, run_dir_for_curation, agent.runner_type,
                )

            # Emit cleared event after future resolves (tool lifecycle owns it).
            from ..events import build_memory_curation_cleared
            app_state.projection_store.push_event(
                "memory_curation_cleared",
                build_memory_curation_cleared(),
                agent_id=agent.agent_id,
            )

            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(curation_manifest + steer_manifest, agent)
            return result_blocks
        finally:
            total_manifest = curation_manifest + steer_manifest
            end_tool_call(agent, call_id, "koan_memory_propose", result_blocks, total_manifest or None)

    async def koan_artifact_list(ctx: Context) -> list[ContentBlock]:
        """List artifacts in the run directory."""
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_artifact_list", {})
        call_id = begin_tool_call(agent, "koan_artifact_list", {}, "list")
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            run_dir = _resolve_run_dir(agent)
            if not run_dir:
                result_blocks = [_text_block(json.dumps({"artifacts": []}))]
                result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
                _push_tool_attachments(steer_manifest, agent)
                return result_blocks
            from ..artifacts import list_artifacts
            artifacts = list_artifacts(run_dir)
            result_blocks = [_text_block(json.dumps({"artifacts": artifacts}))]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_artifact_list", result_blocks, steer_manifest or None)

    async def koan_artifact_view(ctx: Context, filename: str) -> list[ContentBlock]:
        """Return the full text content of an artifact."""
        agent = await _get_agent(ctx)
        _check_or_raise(agent, app_state, "koan_artifact_view",
                        {"filename": filename})
        call_id = begin_tool_call(agent, "koan_artifact_view",
                                  {"filename": filename}, filename)
        result_blocks: list[ContentBlock] | None = None
        steer_manifest: list[dict] = []
        try:
            run_dir = _resolve_run_dir(agent)
            if not run_dir:
                raise ToolError(json.dumps({
                    "error": "no_run_dir",
                    "message": "No run directory available",
                }))
            # Path-traversal guard: resolve and verify containment.
            run_root = Path(run_dir).resolve()
            target = (run_root / filename).resolve()
            if target != run_root and not str(target).startswith(
                str(run_root) + os.sep
            ):
                raise ToolError(json.dumps({
                    "error": "invalid_path",
                    "message": "filename escapes run_dir",
                }))
            if not target.is_file():
                raise ToolError(json.dumps({
                    "error": "not_found",
                    "message": f"{filename} not found",
                }))
            # Strip driver-managed frontmatter so the LLM sees body only.
            # Frontmatter is an internal concern; exposing it would invite
            # the LLM to parse or reproduce it, breaking the invariant.
            from ..artifacts import split_frontmatter
            raw = target.read_text(encoding="utf-8")
            _, body = split_frontmatter(raw)
            result_blocks = [_text_block(body)]
            result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
            _push_tool_attachments(steer_manifest, agent)
            return result_blocks
        finally:
            end_tool_call(agent, call_id, "koan_artifact_view", result_blocks, steer_manifest or None)

    # -- fastmcp registration (lockstep with Handlers fields) -----------------

    mcp.tool(name="koan_complete_step")(koan_complete_step)
    mcp.tool(name="koan_yield")(koan_yield)
    mcp.tool(name="koan_set_phase")(koan_set_phase)
    mcp.tool(name="koan_set_workflow")(koan_set_workflow)
    mcp.tool(name="koan_request_scouts")(koan_request_scouts)
    mcp.tool(name="koan_ask_question")(koan_ask_question)
    mcp.tool(name="koan_request_executor")(koan_request_executor)
    mcp.tool(name="koan_select_story")(koan_select_story)
    mcp.tool(name="koan_complete_story")(koan_complete_story)
    mcp.tool(name="koan_retry_story")(koan_retry_story)
    mcp.tool(name="koan_skip_story")(koan_skip_story)
    mcp.tool(name="koan_memorize")(koan_memorize)
    mcp.tool(name="koan_forget")(koan_forget)
    mcp.tool(name="koan_memory_status")(koan_memory_status)
    mcp.tool(name="koan_search")(koan_search)
    mcp.tool(name="koan_reflect")(koan_reflect)
    mcp.tool(name="koan_artifact_write")(koan_artifact_write)
    mcp.tool(name="koan_memory_propose")(koan_memory_propose)
    mcp.tool(name="koan_artifact_list")(koan_artifact_list)
    mcp.tool(name="koan_artifact_view")(koan_artifact_view)

    handlers = Handlers(
        koan_complete_step=koan_complete_step,
        koan_yield=koan_yield,
        koan_set_phase=koan_set_phase,
        koan_set_workflow=koan_set_workflow,
        koan_request_scouts=koan_request_scouts,
        koan_ask_question=koan_ask_question,
        koan_request_executor=koan_request_executor,
        koan_select_story=koan_select_story,
        koan_complete_story=koan_complete_story,
        koan_retry_story=koan_retry_story,
        koan_skip_story=koan_skip_story,
        koan_memorize=koan_memorize,
        koan_forget=koan_forget,
        koan_memory_status=koan_memory_status,
        koan_search=koan_search,
        koan_reflect=koan_reflect,
        koan_artifact_write=koan_artifact_write,
        koan_memory_propose=koan_memory_propose,
        koan_artifact_list=koan_artifact_list,
        koan_artifact_view=koan_artifact_view,
    )
    return mcp, handlers


# -- ASGI wrapper -------------------------------------------------------------

def build_mcp_asgi_app(app_state: AppState):
    """Return an ASGI app that validates agent_id then delegates to fastmcp.

    The ASGI wrapper provides a cheap pre-reject (403) for unknown agent IDs
    before the request reaches fastmcp. The actual per-request agent resolution
    happens inside AgentResolutionMiddleware.on_call_tool.
    """
    mcp, _handlers = build_mcp_server(app_state)
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
            await inner(scope, receive, send)
        else:
            await inner(scope, receive, send)

    return asgi_wrapper, inner
