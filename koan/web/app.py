# Starlette app factory and route handlers.
# Interaction endpoints resolve PendingInteraction futures from the queue.
# SSE stream pushes pre-rendered HTML fragments for low-frequency events.

from __future__ import annotations

import asyncio
import json
import shutil
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
from ..probe import ProbeResult
from ..types import AgentInstallation, Profile, ProfileTier
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
            "step_name": (
                agent.phase_module.STEP_NAMES.get(agent.step, f"step {agent.step}")
                if agent.phase_module and hasattr(agent.phase_module, "STEP_NAMES")
                else f"step {agent.step}"
            ),
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


# -- Profile validation -------------------------------------------------------

def _validate_profile_tiers(tiers_raw: dict, probe_results: list[ProbeResult]) -> str | None:
    by_runner: dict[str, ProbeResult] = {pr.runner_type: pr for pr in probe_results}
    for tier_name, tier_val in tiers_raw.items():
        if not isinstance(tier_val, dict):
            return f"tier '{tier_name}' must be an object"

        rt = tier_val.get("runner_type", "")
        model = tier_val.get("model", "")
        thinking = tier_val.get("thinking", "disabled")

        if not isinstance(rt, str) or not rt:
            return f"tier '{tier_name}' requires a non-empty 'runner_type'"
        if not isinstance(model, str) or not model:
            return f"tier '{tier_name}' requires a non-empty 'model'"
        if not isinstance(thinking, str) or not thinking:
            return f"tier '{tier_name}' requires a non-empty 'thinking'"

        pr = by_runner.get(rt)
        if pr is None or not pr.available:
            return f"runner_type '{rt}' is not available"

        model_aliases = {m.alias for m in pr.models}
        if model not in model_aliases:
            return f"model '{model}' not found for runner '{rt}'"

        for m in pr.models:
            if m.alias == model:
                if thinking not in m.thinking_modes:
                    return f"thinking mode '{thinking}' not supported by model '{model}'"
                break

    return None


# -- Route handlers -----------------------------------------------------------

async def landing_page(r: Request) -> Response:
    st = _app_state(r)

    # If run already started, render live view
    if st.start_event.is_set():
        return _render_live(st)

    env = _get_jinja()
    tmpl = env.get_template("landing.html")
    html = tmpl.render(
        tiers=None,
        scout_concurrency=st.config.scout_concurrency,
    )
    return Response(html, media_type="text/html")


def _render_live(st: AppState) -> Response:
    env = _get_jinja()
    tmpl = env.get_template("live.html")

    current_phase = st.phase or "intake"

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
        tiers=None,
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

    profile = body.get("profile", "")
    if not isinstance(profile, str) or not profile.strip():
        return JSONResponse(
            {"error": "validation_error", "message": "profile is required"},
            status_code=422,
        )

    st = _app_state(r)

    # Block when no runners available
    if not any(pr.available for pr in st.probe_results):
        return JSONResponse(
            {"error": "no_runners",
             "message": "No available runners. Install and authenticate at least one runner before starting a run."},
            status_code=422,
        )

    # Validate profile exists
    if profile != "balanced" and not any(p.name == profile for p in st.config.profiles):
        return JSONResponse(
            {"error": "validation_error", "message": f"profile '{profile}' not found"},
            status_code=422,
        )

    # Persist profile selection
    st.config.active_profile = profile
    from ..config import save_koan_config
    await save_koan_config(st.config)

    # Apply optional overrides
    scout_concurrency = body.get("scout_concurrency")
    if isinstance(scout_concurrency, int) and scout_concurrency > 0:
        st.config.scout_concurrency = scout_concurrency
        from ..config import save_koan_config
        await save_koan_config(st.config)

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
    accepted = body.get("accepted", False)
    token = body.get("token", "")

    st = _app_state(r)
    active = st.active_interaction
    if active is None or active.type != "artifact-review" or active.token != token:
        return _stale_response()

    interaction = active
    activate_next_interaction(st)
    interaction.future.set_result({"response": response, "accepted": accepted})
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

    # Extract valid phases from the active interaction payload
    valid_phases: set[str] = set()
    for turn in active.payload.get("chat_turns", []):
        for rp in turn.get("recommended_phases", []):
            p = rp.get("phase", "")
            if p:
                valid_phases.add(p)

    if not phase:
        return JSONResponse(
            {"ok": False, "error": "empty_phase", "message": "A phase must be selected"},
            status_code=422,
        )

    if valid_phases and phase not in valid_phases:
        return JSONResponse(
            {"ok": False, "error": "invalid_phase",
             "message": f"Phase '{phase}' is not among the proposed options"},
            status_code=422,
        )

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


# -- Probe & profile endpoints ------------------------------------------------

def _serialize_model_info(m) -> dict:
    return {
        "alias": m.alias,
        "display_name": m.display_name,
        "thinking_modes": sorted(m.thinking_modes),
        "tier_hint": m.tier_hint,
    }


def _serialize_probe_result(pr: ProbeResult) -> dict:
    return {
        "runner_type": pr.runner_type,
        "available": pr.available,
        "binary_path": pr.binary_path,
        "version": pr.version,
        "models": [_serialize_model_info(m) for m in pr.models],
    }


def _serialize_profile(p: Profile, read_only: bool) -> dict:
    return {
        "name": p.name,
        "read_only": read_only,
        "tiers": {
            tier_name: {
                "runner_type": pt.runner_type,
                "model": pt.model,
                "thinking": pt.thinking,
            }
            for tier_name, pt in p.tiers.items()
        },
    }


async def api_probe(r: Request) -> Response:
    st = _app_state(r)
    runners = [_serialize_probe_result(pr) for pr in st.probe_results]
    balanced = _serialize_profile(st.balanced_profile, True) if st.balanced_profile else None
    return JSONResponse({"runners": runners, "balanced_profile": balanced})


async def api_profiles_list(r: Request) -> Response:
    st = _app_state(r)
    profiles = []
    if st.balanced_profile:
        profiles.append(_serialize_profile(st.balanced_profile, True))
    for p in st.config.profiles:
        profiles.append(_serialize_profile(p, False))
    return JSONResponse({"profiles": profiles})


async def api_profiles_create(r: Request) -> Response:
    body = await r.json()
    name = body.get("name", "")
    tiers_raw = body.get("tiers", {})

    if not isinstance(name, str) or not name.strip():
        return JSONResponse(
            {"error": "validation_error", "message": "name is required"},
            status_code=422,
        )
    if name == "balanced":
        return JSONResponse(
            {"error": "validation_error", "message": "cannot use reserved name 'balanced'"},
            status_code=422,
        )
    if any(p.name == name for p in _app_state(r).config.profiles):
        return JSONResponse(
            {"error": "validation_error", "message": f"profile '{name}' already exists"},
            status_code=422,
        )

    st = _app_state(r)
    if not isinstance(tiers_raw, dict):
        return JSONResponse(
            {"error": "validation_error", "message": "tiers must be an object"},
            status_code=422,
        )
    err = _validate_profile_tiers(tiers_raw, st.probe_results)
    if err is not None:
        return JSONResponse(
            {"error": "validation_error", "message": err},
            status_code=422,
        )

    tiers = {}
    for tier_name, tier_val in tiers_raw.items():
        tiers[tier_name] = ProfileTier(
                runner_type=tier_val.get("runner_type", ""),
                model=tier_val.get("model", ""),
                thinking=tier_val.get("thinking", "disabled"),
            )

    st.config.profiles.append(Profile(name=name, tiers=tiers))
    from ..config import save_koan_config
    await save_koan_config(st.config)
    return JSONResponse({"ok": True})


async def api_profiles_update(r: Request) -> Response:
    name = r.path_params["name"]
    if name == "balanced":
        return JSONResponse(
            {"error": "read_only", "message": "balanced profile cannot be edited"},
            status_code=422,
        )

    st = _app_state(r)
    target = None
    for p in st.config.profiles:
        if p.name == name:
            target = p
            break
    if target is None:
        return JSONResponse({"error": "not_found", "message": f"profile '{name}' not found"}, status_code=404)

    body = await r.json()
    tiers_raw = body.get("tiers", {})
    if not isinstance(tiers_raw, dict):
        return JSONResponse(
            {"error": "validation_error", "message": "tiers must be an object"},
            status_code=422,
        )
    err = _validate_profile_tiers(tiers_raw, st.probe_results)
    if err is not None:
        return JSONResponse({"error": "validation_error", "message": err}, status_code=422)

    new_tiers = {}
    for tier_name, tier_val in tiers_raw.items():
        new_tiers[tier_name] = ProfileTier(
            runner_type=tier_val.get("runner_type", ""),
            model=tier_val.get("model", ""),
            thinking=tier_val.get("thinking", "disabled"),
        )
    target.tiers = new_tiers

    from ..config import save_koan_config
    await save_koan_config(st.config)
    return JSONResponse({"ok": True})


async def api_profiles_delete(r: Request) -> Response:
    name = r.path_params["name"]
    if name == "balanced":
        return JSONResponse(
            {"error": "read_only", "message": "balanced profile cannot be deleted"},
            status_code=400,
        )

    st = _app_state(r)
    idx = None
    for i, p in enumerate(st.config.profiles):
        if p.name == name:
            idx = i
            break
    if idx is None:
        return JSONResponse({"error": "not_found", "message": f"profile '{name}' not found"}, status_code=404)

    st.config.profiles.pop(idx)
    if st.config.active_profile == name:
        st.config.active_profile = "balanced"

    from ..config import save_koan_config
    await save_koan_config(st.config)
    return JSONResponse({"ok": True})


# -- Agent installation endpoints ---------------------------------------------

async def api_agents_list(r: Request) -> Response:
    st = _app_state(r)
    installations = [
        {
            "alias": inst.alias,
            "runner_type": inst.runner_type,
            "binary": inst.binary,
            "extra_args": inst.extra_args,
        }
        for inst in st.config.agent_installations
    ]
    return JSONResponse({
        "installations": installations,
        "active_installations": st.config.active_installations,
    })


async def api_agents_create(r: Request) -> Response:
    body = await r.json()
    alias = body.get("alias", "")
    runner_type = body.get("runner_type", "")
    binary = body.get("binary", "")
    extra_args = body.get("extra_args", [])

    if not isinstance(alias, str) or not alias.strip():
        return JSONResponse(
            {"error": "validation_error", "message": "alias is required"},
            status_code=422,
        )
    if not isinstance(runner_type, str) or not runner_type.strip():
        return JSONResponse(
            {"error": "validation_error", "message": "runner_type is required"},
            status_code=422,
        )
    if not isinstance(binary, str) or not binary.strip():
        return JSONResponse(
            {"error": "validation_error", "message": "binary is required"},
            status_code=422,
        )

    st = _app_state(r)
    if any(inst.alias == alias for inst in st.config.agent_installations):
        return JSONResponse(
            {"error": "validation_error", "message": f"alias '{alias}' already exists"},
            status_code=422,
        )

    if not isinstance(extra_args, list):
        extra_args = []

    st.config.agent_installations.append(AgentInstallation(
        alias=alias, runner_type=runner_type, binary=binary,
        extra_args=[str(a) for a in extra_args],
    ))
    from ..config import save_koan_config
    await save_koan_config(st.config)
    return JSONResponse({"ok": True})


async def api_agents_update(r: Request) -> Response:
    alias = r.path_params["alias"]
    st = _app_state(r)
    target = None
    for inst in st.config.agent_installations:
        if inst.alias == alias:
            target = inst
            break
    if target is None:
        return JSONResponse({"error": "not_found", "message": f"installation '{alias}' not found"}, status_code=404)

    body = await r.json()
    if "binary" in body:
        target.binary = body["binary"]
    if "runner_type" in body:
        target.runner_type = body["runner_type"]
    if "extra_args" in body:
        ea = body["extra_args"]
        target.extra_args = [str(a) for a in ea] if isinstance(ea, list) else []

    from ..config import save_koan_config
    await save_koan_config(st.config)
    return JSONResponse({"ok": True})


async def api_agents_delete(r: Request) -> Response:
    alias = r.path_params["alias"]
    st = _app_state(r)
    idx = None
    for i, inst in enumerate(st.config.agent_installations):
        if inst.alias == alias:
            idx = i
            break
    if idx is None:
        return JSONResponse({"error": "not_found", "message": f"installation '{alias}' not found"}, status_code=404)

    removed = st.config.agent_installations.pop(idx)
    # Clean up active_installations if this alias was active
    for rt, active_alias in list(st.config.active_installations.items()):
        if active_alias == alias:
            del st.config.active_installations[rt]

    from ..config import save_koan_config
    await save_koan_config(st.config)
    return JSONResponse({"ok": True})


async def api_agents_set_active(r: Request) -> Response:
    runner_type = r.path_params["runner_type"]
    body = await r.json()
    alias = body.get("alias", "")

    if not isinstance(alias, str) or not alias.strip():
        return JSONResponse(
            {"error": "validation_error", "message": "alias is required"},
            status_code=422,
        )

    st = _app_state(r)
    found = any(
        inst.alias == alias and inst.runner_type == runner_type
        for inst in st.config.agent_installations
    )
    if not found:
        return JSONResponse(
            {"error": "validation_error",
             "message": f"no installation with alias '{alias}' and runner_type '{runner_type}'"},
            status_code=422,
        )

    st.config.active_installations[runner_type] = alias
    from ..config import save_koan_config
    await save_koan_config(st.config)
    return JSONResponse({"ok": True})


async def api_agents_detect(r: Request) -> Response:
    runner_type = r.query_params.get("runner_type", "")
    if not runner_type:
        return JSONResponse(
            {"error": "validation_error", "message": "runner_type query parameter is required"},
            status_code=422,
        )
    result = shutil.which(runner_type)
    return JSONResponse({"path": result})


# -- App factory --------------------------------------------------------------

def _build_mcp(app_state: AppState):
    from .mcp_endpoint import build_mcp_asgi_app
    return build_mcp_asgi_app(app_state)


def create_app(app_state: AppState) -> Starlette:
    @asynccontextmanager
    async def lifespan(app):
        from ..driver import driver_main
        from ..probe import probe_all_runners
        from ..runners.registry import compute_balanced_profile

        app_state.probe_results = await probe_all_runners()
        app_state.balanced_profile = compute_balanced_profile(app_state.probe_results)

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
        Route("/api/probe", api_probe),
        Route("/api/profiles", api_profiles_list, methods=["GET"]),
        Route("/api/profiles", api_profiles_create, methods=["POST"]),
        Route("/api/profiles/{name}", api_profiles_update, methods=["PUT"]),
        Route("/api/profiles/{name}", api_profiles_delete, methods=["DELETE"]),
        Route("/api/agents", api_agents_list, methods=["GET"]),
        Route("/api/agents", api_agents_create, methods=["POST"]),
        Route("/api/agents/detect", api_agents_detect, methods=["GET"]),
        Route("/api/agents/{runner_type}/active", api_agents_set_active, methods=["PUT"]),
        Route("/api/agents/{alias}", api_agents_update, methods=["PUT"]),
        Route("/api/agents/{alias}", api_agents_delete, methods=["DELETE"]),
        Mount("/static", app=StaticFiles(directory=str(_STATIC_DIR))),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.app_state = app_state
    return app
