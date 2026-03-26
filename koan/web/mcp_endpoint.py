# MCP endpoint -- fastmcp server with permission-fenced tool stubs.
#
# Exposes build_mcp_asgi_app() which returns an ASGI sub-app that:
#   1. Validates agent_id from query params before reaching fastmcp.
#   2. Runs check_permission() on every tool call.
#   3. Delegates to stub handlers that will be replaced in T6/T7.

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..lib.permissions import check_permission
from ..logger import get_logger

if TYPE_CHECKING:
    from ..state import AgentState, AppState

log = get_logger("mcp")

# Request-scoped agent state, set by the ASGI wrapper before fastmcp runs.
_agent_ctx: ContextVar[AgentState | None] = ContextVar("_agent_ctx", default=None)

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


# -- Tool stubs ---------------------------------------------------------------

@mcp.tool(name="koan_complete_step")
def koan_complete_step(thoughts: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_complete_step", {"thoughts": thoughts})
    return "[stub] koan_complete_step: not yet implemented"


@mcp.tool(name="koan_set_confidence")
def koan_set_confidence(level: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_set_confidence", {"level": level})
    return "[stub] koan_set_confidence: not yet implemented"


@mcp.tool(name="koan_request_scouts")
def koan_request_scouts(questions: list[str] | None = None) -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_request_scouts", {"questions": questions})
    return "[stub] koan_request_scouts: not yet implemented"


@mcp.tool(name="koan_ask_question")
def koan_ask_question(question: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_ask_question", {"question": question})
    return "[stub] koan_ask_question: not yet implemented"


@mcp.tool(name="koan_review_artifact")
def koan_review_artifact(artifact: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_review_artifact", {"artifact": artifact})
    return "[stub] koan_review_artifact: not yet implemented"


@mcp.tool(name="koan_propose_workflow")
def koan_propose_workflow(workflow: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_propose_workflow", {"workflow": workflow})
    return "[stub] koan_propose_workflow: not yet implemented"


@mcp.tool(name="koan_set_next_phase")
def koan_set_next_phase(phase: str = "") -> str:
    agent = _get_agent()
    _check_or_raise(agent, "koan_set_next_phase", {"phase": phase})
    return "[stub] koan_set_next_phase: not yet implemented"


# -- ASGI wrapper --------------------------------------------------------------

def build_mcp_asgi_app(app_state: AppState):
    """Return an ASGI app that validates agent_id then delegates to fastmcp."""
    inner = mcp.http_app()

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

    return asgi_wrapper
