# Starlette app factory and route handlers.
# Interaction endpoints resolve PendingInteraction futures from the queue.
# SSE stream pushes pre-rendered HTML fragments for low-frequency events.

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from ..artifacts import list_artifacts
from ..epic_state import atomic_write_json
from .interactions import activate_next_interaction

if TYPE_CHECKING:
    from ..state import AppState

NOT_IMPL = Response("Not Implemented", status_code=501)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

ALL_PHASES = [
    "intake", "brief-generation", "core-flows", "tech-plan",
    "ticket-breakdown", "cross-artifact-validation",
    "execution", "implementation-validation",
]


# -- Jinja2 environment (module-level singleton) ----------------------------

_jinja_env: Environment | None = None


def _get_jinja() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
    return _jinja_env


# -- Helpers ------------------------------------------------------------------

def _app_state(r: Request) -> AppState:
    return r.app.state.app_state


def _stale_response(msg: str = "Interaction no longer active") -> JSONResponse:
    return JSONResponse({"error": "stale_interaction", "message": msg}, status_code=409)


def _done_phases(current: str) -> list[str]:
    """Return list of phases that are done (before current in the ordered list)."""
    result = []
    for p in ALL_PHASES:
        if p == current:
            break
        result.append(p)
    return result


def _format_size(bytes_val: int) -> str:
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val // 1024} KB"
    return f"{bytes_val / (1024 * 1024):.1f} MB"


def _format_elapsed_ms(ms: int) -> str:
    s = ms // 1000
    m = s // 60
    s = s % 60
    return f"{m}m {s:02d}s"


def _format_tokens(sent: int, recv: int) -> str:
    def _fmt(n: int) -> str:
        if not n:
            return "--"
        if n < 1000:
            return str(n)
        return f"{n // 1000}k"
    return f"{_fmt(sent)} / {_fmt(recv)}"


def _build_artifact_tree(artifacts: list[dict]) -> dict:
    """Group artifacts by their directory for tree rendering."""
    tree: dict[str, list] = {}
    for a in artifacts:
        p = Path(a["path"])
        folder = str(p.parent) if str(p.parent) != "." else "epic-root"
        name = p.name
        if folder not in tree:
            tree[folder] = []
        tree[folder].append({
            "path": a["path"],
            "name": name,
            "formatted_size": _format_size(a["size"]),
            "modified_display": time.strftime(
                "%H:%M:%S", time.localtime(a["modified_at"])
            ),
        })
    return tree


def _build_subagent_display(st: AppState) -> dict | None:
    """Build subagent display dict from the first active agent."""
    for agent in st.agents.values():
        elapsed_ms = int((time.time() - agent.started_at.timestamp()) * 1000)
        return {
            "role": agent.role,
            "model": agent.model or "--",
            "step": agent.step,
            "step_name": f"step {agent.step}",
            "tokens_display": _format_tokens(
                agent.token_count.get("sent", 0),
                agent.token_count.get("received", 0),
            ),
            "elapsed": _format_elapsed_ms(elapsed_ms),
            "started_at_ms": int(agent.started_at.timestamp() * 1000),
        }
    return None


def _build_agents_list(st: AppState) -> list[dict]:
    """Build agent list for the monitor table."""
    result = []
    for agent in st.agents.values():
        elapsed_ms = int((time.time() - agent.started_at.timestamp()) * 1000)
        result.append({
            "role": agent.role,
            "model": agent.model or "--",
            "status": "running",
            "tokens_display": _format_tokens(
                agent.token_count.get("sent", 0),
                agent.token_count.get("received", 0),
            ),
            "elapsed": _format_elapsed_ms(elapsed_ms),
            "doing": f"step {agent.step}",
        })
    return result


# -- Route handlers -----------------------------------------------------------

async def landing_page(r: Request) -> Response:
    st = _app_state(r)

    # If run already started, render live view
    if st.start_event.is_set():
        return _render_live(st)

    env = _get_jinja()
    tmpl = env.get_template("landing.html")
    tiers = None
    if st.config.model_tiers:
        tiers = {
            "strong": st.config.model_tiers.strong,
            "standard": st.config.model_tiers.standard,
            "cheap": st.config.model_tiers.cheap,
        }
    html = tmpl.render(
        tiers=tiers,
        scout_concurrency=st.config.scout_concurrency,
    )
    return Response(html, media_type="text/html")


def _render_live(st: AppState) -> Response:
    env = _get_jinja()
    tmpl = env.get_template("live.html")

    current_phase = st.phase or "intake"
    tiers = None
    if st.config.model_tiers:
        tiers = {
            "strong": st.config.model_tiers.strong,
            "standard": st.config.model_tiers.standard,
            "cheap": st.config.model_tiers.cheap,
        }

    artifacts = []
    if st.epic_dir:
        try:
            artifacts = list_artifacts(st.epic_dir)
        except Exception:
            pass

    html = tmpl.render(
        phases=ALL_PHASES,
        current_phase=current_phase,
        done_phases=_done_phases(current_phase),
        subagent=_build_subagent_display(st),
        phase_status={"phase": current_phase},
        agents=_build_agents_list(st),
        artifacts=artifacts,
        artifact_tree=_build_artifact_tree(artifacts),
        tiers=tiers,
        scout_concurrency=st.config.scout_concurrency,
    )
    return Response(html, media_type="text/html")


async def sse_stream(r: Request) -> Response:
    st = _app_state(r)

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        st.sse_clients.append(queue)
        try:
            # Replay last known state
            for event_type, payload in st.last_sse_values.items():
                yield _sse_event(event_type, payload)

            # Stream live events
            while True:
                event_type, payload = await queue.get()
                yield _sse_event(event_type, payload)
        except asyncio.CancelledError:
            pass
        finally:
            st.sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse_event(event_type: str, payload: Any) -> str:
    data = json.dumps(payload) if not isinstance(payload, str) else payload
    return f"event: {event_type}\ndata: {data}\n\n"


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


async def api_artifacts_list(r: Request) -> Response:
    st = _app_state(r)
    if not st.epic_dir:
        return JSONResponse({"error": "no_run", "message": "No run started"}, status_code=404)

    artifacts = list_artifacts(st.epic_dir)
    files = []
    for a in artifacts:
        files.append({
            "path": a["path"],
            "size": a["size"],
            "formattedSize": _format_size(a["size"]),
            "modifiedAt": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(a["modified_at"])
            ),
        })
    return JSONResponse({"files": files})


async def api_artifact_content(r: Request) -> Response:
    st = _app_state(r)
    if not st.epic_dir:
        return JSONResponse({"error": "no_run"}, status_code=404)

    req_path = r.path_params.get("path", "")

    # Path traversal guard
    epic = Path(st.epic_dir).resolve()
    target = (epic / req_path).resolve()
    if not str(target).startswith(str(epic)):
        return JSONResponse(
            {"error": "invalid_path", "message": "Path traversal not allowed"},
            status_code=400,
        )

    if not target.is_file():
        return JSONResponse({"error": "not_found"}, status_code=404)

    try:
        content = target.read_text("utf-8")
    except Exception:
        content = "(binary or unreadable file)"

    return JSONResponse({
        "content": content,
        "displayPath": str(target.relative_to(epic)),
    })


async def api_model_config_get(r: Request) -> Response:
    st = _app_state(r)
    tiers = {"strong": "", "standard": "", "cheap": ""}
    if st.config.model_tiers:
        tiers = {
            "strong": st.config.model_tiers.strong,
            "standard": st.config.model_tiers.standard,
            "cheap": st.config.model_tiers.cheap,
        }
    return JSONResponse({
        "tiers": tiers,
        "scoutConcurrency": st.config.scout_concurrency,
    })


async def api_model_config_put(r: Request) -> Response:
    body = await r.json()

    st = _app_state(r)
    mt = body.get("model_tiers")
    if mt and isinstance(mt, dict):
        from ..config import ModelTierConfig
        st.config.model_tiers = ModelTierConfig(
            strong=mt.get("strong", ""),
            standard=mt.get("standard", ""),
            cheap=mt.get("cheap", ""),
        )

    sc = body.get("scout_concurrency")
    if isinstance(sc, int) and sc > 0:
        st.config.scout_concurrency = sc

    from ..config import save_koan_config
    await save_koan_config(st.config)

    return JSONResponse({"ok": True})


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
        Route("/api/artifacts", api_artifacts_list),
        Route("/api/artifacts/{path:path}", api_artifact_content),
        Route("/api/model-config", api_model_config_get, methods=["GET"]),
        Route("/api/model-config", api_model_config_put, methods=["PUT"]),
        Mount("/static", app=StaticFiles(directory=str(_STATIC_DIR))),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.app_state = app_state
    return app
