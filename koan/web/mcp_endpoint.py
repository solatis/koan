# MCP endpoint -- fastmcp server with permission-fenced tool handlers.
#
# Exposes build_mcp_asgi_app() which returns an ASGI sub-app that:
#   1. Validates agent_id from query params before reaching fastmcp.
#   2. Runs check_permission() on every tool call.
#   3. Implements koan_complete_step, koan_request_scouts,
#      koan_ask_question, koan_review_artifact, koan_propose_workflow,
#      koan_set_next_phase.

from __future__ import annotations

import asyncio
import json
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

import aiofiles
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..epic_state import atomic_write_json, ensure_subagent_directory
from ..lib.permissions import check_permission
from ..lib.phase_dag import is_valid_transition
from ..logger import get_logger
from ..phases.format_step import format_step
from .interactions import activate_next_interaction, enqueue_interaction

if TYPE_CHECKING:
    from ..state import AgentState, AppState

log = get_logger("mcp")

# Request-scoped agent state, set by the ASGI wrapper before fastmcp runs.
_agent_ctx: ContextVar[AgentState | None] = ContextVar("_agent_ctx", default=None)

# Module-level app_state reference, set by build_mcp_asgi_app().
_app_state: AppState | None = None

# -- fastmcp server -----------------------------------------------------------

mcp = FastMCP(name="koan")


def _check_or_raise(agent: AgentState, tool_name: str, tool_args: dict | None = None) -> None:
    phase_ctx = agent.phase_ctx
    resolved_epic_dir = (
        phase_ctx.epic_dir if phase_ctx is not None and phase_ctx.epic_dir
        else agent.epic_dir or None
    )
    result = check_permission(
        role=agent.role,
        tool_name=tool_name,
        epic_dir=resolved_epic_dir,
        tool_args=tool_args,
        current_step=agent.step,
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


def begin_tool_call(
    agent: AgentState,
    tool: str,
    args: dict | str,
    summary: str = "",
) -> str:
    """Emit tool_called event and return call_id. No-op if app_state is not set."""
    call_id = str(uuid.uuid4())
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


# -- Tool implementations -----------------------------------------------------

@mcp.tool(name="koan_complete_step")
async def koan_complete_step(thoughts: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_complete_step", {"thoughts": thoughts})

    call_id = begin_tool_call(agent, "koan_complete_step", {"thoughts": thoughts}, f"step {agent.step} → next")
    result_str: str | None = None
    try:
        # Mark handshake observed (decoupled from stream parsing)
        agent.handshake_observed = True

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

        # Loop-back handling
        if next_step is not None and next_step <= current_step:
            await phase_module.on_loop_back(current_step, next_step, ctx)

        # Advance step
        agent.step = next_step if next_step is not None else current_step

        # Determine step name
        step_names = getattr(phase_module, "STEP_NAMES", {})
        step_num = next_step if next_step is not None else current_step
        step_name = step_names.get(step_num, "")

        # Emit audit event
        if agent.event_log is not None:
            await agent.event_log.emit_step_transition(
                step_num,
                step_name,
                phase_module.TOTAL_STEPS,
            )

        # Emit agent_step_advanced to projection
        if _app_state is not None:
            from ..events import build_step_advanced
            _app_state.projection_store.push_event(
                "agent_step_advanced",
                build_step_advanced(step_num, step_name, total_steps=phase_module.TOTAL_STEPS),
                agent_id=agent.agent_id,
            )

        # Return guidance or completion signal
        if next_step is None:
            result_str = "Phase complete."
            return result_str

        guidance = phase_module.step_guidance(next_step, ctx)
        result_str = format_step(guidance)

        # In debug mode, surface the step guidance in the UI
        if _app_state is not None and _app_state.debug:
            _app_state.projection_store.push_event(
                "debug_step_guidance",
                {"content": result_str},
                agent_id=agent.agent_id,
            )

        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_complete_step", result_str)


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
            return result_str

        assert _app_state is not None, "app_state not initialized"

        semaphore = asyncio.Semaphore(_app_state.config.scout_concurrency)
        epic_dir = agent.phase_ctx.epic_dir

        scout_tasks = []
        for q in questions:
            scout_id = q.get("id", str(uuid.uuid4())[:8])
            subagent_dir = await ensure_subagent_directory(
                epic_dir, f"scout-{scout_id}-{uuid.uuid4().hex[:8]}"
            )
            scout_tasks.append({
                "role": "scout",
                "label": scout_id,
                "epic_dir": epic_dir,
                "subagent_dir": subagent_dir,
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
            return result_str

        result_str = "\n\n---\n\n".join(findings)
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_request_scouts", result_str)


@mcp.tool(name="koan_ask_question")
async def koan_ask_question(questions: list[dict] | None = None) -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_ask_question", {"questions": questions})

    call_id = begin_tool_call(
        agent, "koan_ask_question", {"questions": questions or []},
        f"{len(questions or [])} questions",
    )
    result_str: str | None = None
    try:
        assert _app_state is not None, "app_state not initialized"

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
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_ask_question", result_str)


@mcp.tool(name="koan_review_artifact")
async def koan_review_artifact(path: str = "", description: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_review_artifact", {"path": path, "description": description})

    call_id = begin_tool_call(
        agent, "koan_review_artifact", {"path": path, "description": description},
        description or path,
    )
    result_str: str | None = None
    try:
        assert _app_state is not None, "app_state not initialized"

        try:
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
        except FileNotFoundError:
            raise ToolError(
                json.dumps({"error": "file_not_found", "message": f"Artifact not found: {path}"})
            )

        future = await enqueue_interaction(
            agent, _app_state, "artifact-review",
            {"path": path, "description": description, "content": content},
        )
        result = await future

        if isinstance(result, dict) and "error" in result:
            raise ToolError(json.dumps(result))

        response = result.get("response", "")
        accepted = result.get("accepted", response == "" or response.strip().lower() in ("", "ok", "approved", "lgtm", "accept"))
        agent.phase_ctx.last_review_accepted = accepted

        result_str = "ACCEPTED" if accepted else f"REVISION REQUESTED: {response}"
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_review_artifact", result_str)


@mcp.tool(name="koan_propose_workflow")
async def koan_propose_workflow(status: str = "", phases: list | None = None) -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_propose_workflow", {"status": status, "phases": phases})

    call_id = begin_tool_call(
        agent, "koan_propose_workflow", {"status": status, "phases": phases or []},
        "proposing phases",
    )
    result_str: str | None = None
    try:
        assert _app_state is not None, "app_state not initialized"

        # Normalise phases: accept both list[str] and list[dict].
        normalised: list[dict] = []
        for p in (phases or []):
            if isinstance(p, str):
                normalised.append({"phase": p, "context": "", "recommended": False})
            elif isinstance(p, dict):
                normalised.append(p)

        chat_turns = [{
            "role": "orchestrator",
            "status_report": status,
            "recommended_phases": [
                {
                    "phase": p.get("phase", p.get("name", "")),
                    "context": p.get("context", p.get("description", "")),
                    "recommended": p.get("recommended", False),
                }
                for p in normalised
            ],
        }]
        future = await enqueue_interaction(
            agent, _app_state, "workflow-decision",
            {"chat_turns": chat_turns},
        )
        result = await future

        if isinstance(result, dict) and "error" in result:
            raise ToolError(json.dumps(result))

        agent.phase_ctx.proposal_made = True

        phase = result.get("phase", "")
        context = result.get("context", "")
        result_str = f"Selected: {phase}\n{context}".strip()
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_propose_workflow", result_str)


@mcp.tool(name="koan_set_next_phase")
async def koan_set_next_phase(phase: str = "", instructions: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_set_next_phase", {"phase": phase, "instructions": instructions})

    call_id = begin_tool_call(
        agent, "koan_set_next_phase", {"phase": phase, "instructions": instructions}, phase,
    )
    result_str: str | None = None
    try:
        from_phase = getattr(agent.phase_ctx, "completed_phase", None)
        if not is_valid_transition(from_phase, phase):
            raise ToolError(
                json.dumps({
                    "error": "invalid_transition",
                    "message": f"Transition {from_phase} -> {phase} is not valid",
                })
            )

        out_path = Path(agent.phase_ctx.subagent_dir) / "workflow-decision.json"
        await atomic_write_json(out_path, {"next_phase": phase, "instructions": instructions})
        agent.phase_ctx.next_phase_set = True
        result_str = f"Phase set to {phase}."
        return result_str
    finally:
        end_tool_call(agent, call_id, "koan_set_next_phase", result_str)


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
