# Starlette app factory and route handlers.
# Interaction endpoints resolve PendingInteraction futures from the queue.

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from ..epic_state import atomic_write_json
from .interactions import activate_next_interaction

if TYPE_CHECKING:
    from ..state import AppState

NOT_IMPL = Response("Not Implemented", status_code=501)


# -- Helpers ------------------------------------------------------------------

def _app_state(r: Request) -> AppState:
    return r.app.state.app_state


def _stale_response(msg: str = "Interaction no longer active") -> JSONResponse:
    return JSONResponse({"error": "stale_interaction", "message": msg}, status_code=409)


# -- Route handlers -----------------------------------------------------------

async def landing_page(r: Request) -> Response:
    return NOT_IMPL


async def sse_stream(r: Request) -> Response:
    return NOT_IMPL


async def api_start_run(r: Request) -> Response:
    body = await r.json()
    task = body.get("task", "")
    if not isinstance(task, str) or not task.strip():
        return JSONResponse(
            {"error": "validation_error", "message": "task is required"},
            status_code=422,
        )

    st = _app_state(r)

    # Apply optional overrides
    model_tiers = body.get("model_tiers")
    if model_tiers is not None:
        from ..config import ModelTierConfig
        st.config.model_tiers = ModelTierConfig(**model_tiers)

    scout_concurrency = body.get("scout_concurrency")
    if isinstance(scout_concurrency, int) and scout_concurrency > 0:
        st.config.scout_concurrency = scout_concurrency

    # Create epic directory
    epic_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    epic_dir = Path.home() / ".koan" / "epics" / epic_id
    epic_dir.mkdir(parents=True, exist_ok=True)

    await atomic_write_json(
        epic_dir / "task.json",
        {"task": task, "created_at": time.time()},
    )

    st.epic_dir = str(epic_dir)
    st.start_event.set()

    return JSONResponse({"ok": True, "epic_dir": str(epic_dir)})


async def api_answer(r: Request) -> Response:
    body = await r.json()
    answers = body.get("answers", [])
    token = body.get("token", "")

    st = _app_state(r)
    active = st.active_interaction
    if active is None or active.type != "ask" or active.token != token:
        return _stale_response()

    interaction = active
    activate_next_interaction(st)
    interaction.future.set_result({"answers": answers})
    return JSONResponse({"ok": True})


async def api_artifact_review(r: Request) -> Response:
    body = await r.json()
    response = body.get("response", "")
    token = body.get("token", "")

    st = _app_state(r)
    active = st.active_interaction
    if active is None or active.type != "artifact-review" or active.token != token:
        return _stale_response()

    interaction = active
    activate_next_interaction(st)
    interaction.future.set_result({"response": response})
    return JSONResponse({"ok": True})


async def api_workflow_decision(r: Request) -> Response:
    body = await r.json()
    phase = body.get("phase", "")
    context = body.get("context", "")
    token = body.get("token", "")

    st = _app_state(r)
    active = st.active_interaction
    if active is None or active.type != "workflow-decision" or active.token != token:
        return _stale_response()

    interaction = active
    activate_next_interaction(st)
    interaction.future.set_result({"phase": phase, "context": context})
    return JSONResponse({"ok": True})


async def api_artifacts(r: Request) -> Response:
    return NOT_IMPL


async def static_files(r: Request) -> Response:
    return NOT_IMPL


# -- App factory --------------------------------------------------------------

def _build_mcp(app_state: AppState):
    from .mcp_endpoint import build_mcp_asgi_app
    return build_mcp_asgi_app(app_state)


def create_app(app_state: AppState) -> Starlette:
    @asynccontextmanager
    async def lifespan(app):
        from ..driver import driver_main
        asyncio.create_task(driver_main(app_state))
        yield

    routes = [
        Route("/", landing_page),
        Route("/events", sse_stream),
        Mount("/mcp", app=_build_mcp(app_state)),
        Route("/api/start-run", api_start_run, methods=["POST"]),
        Route("/api/answer", api_answer, methods=["POST"]),
        Route("/api/artifact-review", api_artifact_review, methods=["POST"]),
        Route("/api/workflow-decision", api_workflow_decision, methods=["POST"]),
        Route("/api/artifacts/{path:path}", api_artifacts),
        Route("/static/{path:path}", static_files),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.app_state = app_state
    return app
