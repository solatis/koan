# Starlette app factory and route handlers.
# Interaction endpoints resolve PendingInteraction futures from the queue.
# SSE stream pushes JSON payloads for all events (no HTML/Jinja2 rendering).

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from ..artifacts import list_artifacts
from ..epic_state import atomic_write_json
from ..probe import ProbeResult
from ..types import AgentInstallation, Profile, ProfileTier
from .interactions import activate_next_interaction
from ..events import (
    build_artifact_reviewed,
    build_questions_answered,
    build_workflow_decided,
    build_probe_completed,
    build_installation_created,
    build_installation_modified,
    build_installation_removed,
    build_profile_created,
    build_profile_modified,
    build_profile_removed,
    build_active_profile_changed,
    build_active_installation_changed,
    build_scout_concurrency_changed,
)

if TYPE_CHECKING:
    from ..state import AppState

NOT_IMPL = Response("Not Implemented", status_code=501)

_STATIC_DIR = Path(__file__).parent / "static"

# Vite build output directory. Populated by `cd frontend && npm run build`.
# Route mounting is conditional on this directory existing so tests pass
# without a build step.
FRONTEND_DIST = Path(__file__).parent / "static" / "app"

ALL_PHASES = [
    "intake", "brief-generation", "core-flows", "tech-plan",
    "ticket-breakdown", "cross-artifact-validation",
    "execution", "implementation-validation",
]


# -- Helpers ------------------------------------------------------------------

def _app_state(r: Request) -> AppState:
    return r.app.state.app_state


def _stale_response(msg: str = "Interaction no longer active") -> JSONResponse:
    return JSONResponse({"error": "stale_interaction", "message": msg}, status_code=409)


def _format_size(bytes_val: int) -> str:
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val // 1024} KB"
    return f"{bytes_val / (1024 * 1024):.1f} MB"


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

async def spa_fallback(request: Request) -> Response:
    # Return the built React app entry point for any path not matched above.
    # React reads store state (runStarted) to decide which view to render.
    # Note: Starlette's /{path:path} does match the empty path /, so this
    # correctly handles both / and all sub-paths as the SPA fallback.
    index_html = FRONTEND_DIST / "index.html"
    if index_html.is_file():
        return FileResponse(str(index_html))
    # Return a minimal placeholder when the frontend hasn't been built yet.
    # This keeps tests passing without requiring a prior `npm run build`.
    return Response(
        '<!doctype html><html><body><div id="root"></div></body></html>',
        media_type="text/html",
    )


async def sse_stream(r: Request) -> Response:
    st = _app_state(r)
    store = st.projection_store

    since_str = r.query_params.get("since", "0")
    try:
        since = int(since_str)
    except ValueError:
        since = 0

    async def event_generator():
        # Stale client: send fatal_error and close (not HTTP error -- EventSource
        # cannot read non-200 bodies and would retry with same stale version).
        if since > 0 and since > store.version:
            yield _sse_event("fatal_error", {"reason": "version_not_available"})
            return

        # Subscribe before snapshot -- no await between subscribe and get_snapshot
        # so no events can be missed between the two operations.
        queue = store.subscribe()
        try:
            if since == 0:
                yield _sse_event("snapshot", store.get_snapshot())
            else:
                for event in store.events_since(since):
                    data = {"version": event.version, "agent_id": event.agent_id, **event.payload}
                    yield _sse_event(event.event_type, data)

            while True:
                event = await queue.get()
                data = {"version": event.version, "agent_id": event.agent_id, **event.payload}
                yield _sse_event(event.event_type, data)
        except asyncio.CancelledError:
            pass
        finally:
            store.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse_event(event_type: str, payload: Any) -> str:
    data = json.dumps(payload) if not isinstance(payload, str) else payload
    return f"event: {event_type}\ndata: {data}\n\n"


def _resolve_profile(st: AppState, name: str) -> Profile | None:
    """Look up a profile by name, including the computed balanced profile."""
    if name == "balanced":
        return st.balanced_profile
    for p in st.config.profiles:
        if p.name == name:
            return p
    return None


async def api_start_run_preflight(r: Request) -> Response:
    """Return required runner types and available installations for a profile."""
    profile_name = r.query_params.get("profile", "")
    if not profile_name:
        return JSONResponse(
            {"error": "validation_error", "message": "profile query parameter is required"},
            status_code=422,
        )

    st = _app_state(r)
    profile = _resolve_profile(st, profile_name)
    if profile is None:
        return JSONResponse(
            {"error": "not_found", "message": f"Profile '{profile_name}' not found"},
            status_code=404,
        )

    # Derive required runner types from profile tiers
    required_types: set[str] = set()
    for tier in profile.tiers.values():
        required_types.add(tier.runner_type)

    # For each type, list available installations with validity status
    installations_by_type: dict[str, list[dict]] = {}
    for rt in sorted(required_types):
        insts = []
        for inst in st.config.agent_installations:
            if inst.runner_type == rt:
                insts.append({
                    "alias": inst.alias,
                    "binary": inst.binary,
                    "binary_valid": Path(inst.binary).exists(),
                    "is_active": st.config.active_installations.get(rt) == inst.alias,
                    "extra_args": inst.extra_args,
                })
        installations_by_type[rt] = insts

    return JSONResponse({
        "profile": profile_name,
        "required_runner_types": sorted(required_types),
        "installations": installations_by_type,
    })


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
    profile_obj = _resolve_profile(st, profile)
    if profile_obj is None:
        return JSONResponse(
            {"error": "validation_error", "message": f"profile '{profile}' not found"},
            status_code=422,
        )

    # Apply installation selections (runner_type -> alias)
    installations = body.get("installations")
    if isinstance(installations, dict):
        for rt, alias in installations.items():
            found = any(
                inst.alias == alias and inst.runner_type == rt
                for inst in st.config.agent_installations
            )
            if not found:
                return JSONResponse(
                    {"error": "validation_error",
                     "message": f"Installation '{alias}' not found for runner type '{rt}'"},
                    status_code=422,
                )
        for rt, alias in installations.items():
            st.config.active_installations[rt] = alias

    # Pre-validate installations for every runner type the profile requires
    from ..runners.registry import RunnerRegistry
    from ..runners.base import RunnerError
    registry = RunnerRegistry()
    checked_types: set[str] = set()
    for tier in profile_obj.tiers.values():
        if tier.runner_type in checked_types:
            continue
        checked_types.add(tier.runner_type)
        try:
            registry.resolve_installation(tier.runner_type, st.config)
        except RunnerError as e:
            return JSONResponse(
                {"error": e.diagnostic.code,
                 "message": e.diagnostic.message,
                 "runner_type": tier.runner_type},
                status_code=422,
            )

    # Persist profile + installation selections
    st.config.active_profile = profile
    from ..config import save_koan_config
    await save_koan_config(st.config)
    st.projection_store.push_event("active_profile_changed", build_active_profile_changed(profile))
    if isinstance(installations, dict):
        for rt, alias in installations.items():
            st.projection_store.push_event(
                "active_installation_changed", build_active_installation_changed(rt, alias),
            )

    # Apply optional overrides
    scout_concurrency = body.get("scout_concurrency")
    if isinstance(scout_concurrency, int) and scout_concurrency > 0:
        st.config.scout_concurrency = scout_concurrency
        await save_koan_config(st.config)
        st.projection_store.push_event("scout_concurrency_changed", build_scout_concurrency_changed(scout_concurrency))

    # Create epic directory
    epic_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    epic_dir = Path.home() / ".koan" / "epics" / epic_id
    epic_dir.mkdir(parents=True, exist_ok=True)

    await atomic_write_json(
        epic_dir / "task.json",
        {"task": task, "created_at": time.time()},
    )

    # Write conversation.jsonl so the intake phase can read it
    import aiofiles as _aiofiles
    conv_line = json.dumps({"type": "message", "role": "user", "content": task})
    conv_path = epic_dir / "conversation.jsonl"
    async with _aiofiles.open(conv_path, "w") as _f:
        await _f.write(conv_line + "\n")

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
    st.projection_store.push_event(
        "questions_answered",
        build_questions_answered(interaction.token, answers, cancelled=False),
        agent_id=interaction.agent_id,
    )
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
    st.projection_store.push_event(
        "artifact_reviewed",
        build_artifact_reviewed(interaction.token, accepted=accepted, response=response, cancelled=False),
        agent_id=interaction.agent_id,
    )
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
    st.projection_store.push_event(
        "workflow_decided",
        build_workflow_decided(interaction.token, decision={"phase": phase, "context": context}, cancelled=False),
        agent_id=interaction.agent_id,
    )
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


async def _refresh_probe_state(st: AppState, broadcast: bool = True) -> None:
    from ..probe import probe_all_runners
    from ..runners.registry import compute_balanced_profile

    st.probe_results = await probe_all_runners()
    st.balanced_profile = compute_balanced_profile(st.probe_results)

    # Auto-create or update default installations from probe results
    existing_types = {inst.runner_type for inst in st.config.agent_installations}
    changed = False
    new_insts: list[AgentInstallation] = []
    modified_insts: list[AgentInstallation] = []
    for pr in st.probe_results:
        if pr.available and pr.binary_path:
            if pr.runner_type not in existing_types:
                inst = AgentInstallation(
                    alias=f"{pr.runner_type}-default",
                    runner_type=pr.runner_type,
                    binary=pr.binary_path,
                    extra_args=[],
                )
                st.config.agent_installations.append(inst)
                new_insts.append(inst)
                changed = True
            else:
                for inst in st.config.agent_installations:
                    if inst.runner_type == pr.runner_type and inst.alias == f"{pr.runner_type}-default":
                        if inst.binary != pr.binary_path:
                            inst.binary = pr.binary_path
                            modified_insts.append(inst)
                            changed = True
    if changed:
        from ..config import save_koan_config
        await save_koan_config(st.config)

    if broadcast:
        runners = [_serialize_probe_result(pr) for pr in st.probe_results]
        st.projection_store.push_event("probe_completed", build_probe_completed(runners))
        if st.balanced_profile:
            tiers = _serialize_profile(st.balanced_profile, True)["tiers"]
            st.projection_store.push_event(
                "profile_modified",
                build_profile_modified("balanced", True, tiers),
            )
        for inst in new_insts:
            st.projection_store.push_event(
                "installation_created",
                build_installation_created(inst.alias, inst.runner_type, inst.binary, inst.extra_args),
            )
        for inst in modified_insts:
            st.projection_store.push_event(
                "installation_modified",
                build_installation_modified(inst.alias, inst.runner_type, inst.binary, inst.extra_args),
            )


def _push_initial_config_events(st: AppState) -> None:
    """Push full config state into the projection on startup.

    Called after _refresh_probe_state(broadcast=False) so all state is ready.
    Emits one event per config fact so the snapshot captures complete config.
    """
    store = st.projection_store

    # Runners from probe
    runners = [_serialize_probe_result(pr) for pr in st.probe_results]
    store.push_event("probe_completed", build_probe_completed(runners))

    # Profiles (balanced first, then user-defined)
    if st.balanced_profile:
        tiers = _serialize_profile(st.balanced_profile, True)["tiers"]
        store.push_event("profile_created", build_profile_created("balanced", True, tiers))
    for p in st.config.profiles:
        sp = _serialize_profile(p, False)
        store.push_event("profile_created", build_profile_created(p.name, False, sp["tiers"]))

    # Installations
    for inst in st.config.agent_installations:
        store.push_event(
            "installation_created",
            build_installation_created(inst.alias, inst.runner_type, inst.binary, inst.extra_args),
        )

    # Active installation selections
    for rt, alias in st.config.active_installations.items():
        store.push_event("active_installation_changed", build_active_installation_changed(rt, alias))

    # Active profile
    store.push_event("active_profile_changed", build_active_profile_changed(st.config.active_profile))

    # Scout concurrency
    store.push_event("scout_concurrency_changed", build_scout_concurrency_changed(st.config.scout_concurrency))


async def api_probe(r: Request) -> Response:
    st = _app_state(r)
    if r.query_params.get("refresh", "") in ("1", "true"):
        await _refresh_probe_state(st)
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

    new_profile = Profile(name=name, tiers=tiers)
    st.config.profiles.append(new_profile)
    from ..config import save_koan_config
    await save_koan_config(st.config)
    sp = _serialize_profile(new_profile, False)
    st.projection_store.push_event("profile_created", build_profile_created(name, False, sp["tiers"]))
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
    sp = _serialize_profile(target, False)
    st.projection_store.push_event("profile_modified", build_profile_modified(name, False, sp["tiers"]))
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
    reset_active = st.config.active_profile == name
    if reset_active:
        st.config.active_profile = "balanced"

    from ..config import save_koan_config
    await save_koan_config(st.config)
    st.projection_store.push_event("profile_removed", build_profile_removed(name))
    if reset_active:
        st.projection_store.push_event("active_profile_changed", build_active_profile_changed("balanced"))
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

    clean_args = [str(a) for a in extra_args]
    st.config.agent_installations.append(AgentInstallation(
        alias=alias, runner_type=runner_type, binary=binary,
        extra_args=clean_args,
    ))
    from ..config import save_koan_config
    await save_koan_config(st.config)
    st.projection_store.push_event(
        "installation_created",
        build_installation_created(alias, runner_type, binary, clean_args),
    )
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
    st.projection_store.push_event(
        "installation_modified",
        build_installation_modified(target.alias, target.runner_type, target.binary, target.extra_args),
    )
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

    st.config.agent_installations.pop(idx)
    # Clean up active_installations if this alias was active
    for rt, active_alias in list(st.config.active_installations.items()):
        if active_alias == alias:
            del st.config.active_installations[rt]

    from ..config import save_koan_config
    await save_koan_config(st.config)
    st.projection_store.push_event("installation_removed", build_installation_removed(alias))
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
    st.projection_store.push_event(
        "active_installation_changed", build_active_installation_changed(runner_type, alias),
    )
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


# -- Settings JSON endpoints --------------------------------------------------

async def api_settings_body(r: Request) -> Response:
    st = _app_state(r)

    profiles = []
    if st.balanced_profile:
        profiles.append(_serialize_profile(st.balanced_profile, True))
    for p in st.config.profiles:
        profiles.append(_serialize_profile(p, False))

    installations = []
    for inst in st.config.agent_installations:
        is_active = (st.config.active_installations or {}).get(inst.runner_type) == inst.alias
        installations.append({
            "alias": inst.alias,
            "runner_type": inst.runner_type,
            "binary": inst.binary,
            "extra_args": inst.extra_args,
            "is_active": is_active,
        })

    return JSONResponse({
        "profiles": profiles,
        "installations": installations,
        "activeInstallations": st.config.active_installations or {},
        "scoutConcurrency": st.config.scout_concurrency,
    })


async def api_settings_profile_form(r: Request) -> Response:
    st = _app_state(r)

    name = r.query_params.get("name", "")
    is_edit = r.query_params.get("edit", "0") == "1"

    available_runners = [
        _serialize_probe_result(pr) for pr in st.probe_results if pr.available
    ]

    tiers: dict = {}
    if is_edit and name:
        for p in st.config.profiles:
            if p.name == name:
                sp = _serialize_profile(p, False)
                tiers = sp.get("tiers", {})
                break

    return JSONResponse({
        "name": name,
        "tiers": tiers,
        "availableRunners": available_runners,
        "isEdit": is_edit,
    })


async def api_settings_installation_form(r: Request) -> Response:
    st = _app_state(r)

    alias = r.query_params.get("alias", "")
    is_edit = r.query_params.get("edit", "0") == "1"

    # Use ALL runners, not just available ones
    all_runners = [_serialize_probe_result(pr) for pr in st.probe_results]

    runner_type = ""
    binary = ""
    extra_args: list = []
    if is_edit and alias:
        for inst in st.config.agent_installations:
            if inst.alias == alias:
                runner_type = inst.runner_type
                binary = inst.binary
                extra_args = inst.extra_args
                break

    return JSONResponse({
        "alias": alias,
        "runnerType": runner_type,
        "binary": binary,
        "extraArgs": extra_args,
        "allRunners": all_runners,
        "isEdit": is_edit,
    })


async def api_settings_scout_concurrency(r: Request) -> Response:
    body = await r.json()
    value = body.get("scout_concurrency")
    if not isinstance(value, int) or value < 1 or value > 32:
        return JSONResponse(
            {"error": "validation_error", "message": "scout_concurrency must be an integer between 1 and 32"},
            status_code=422,
        )
    st = _app_state(r)
    st.config.scout_concurrency = value
    from ..config import save_koan_config
    await save_koan_config(st.config)
    st.projection_store.push_event("scout_concurrency_changed", build_scout_concurrency_changed(value))
    return JSONResponse({"ok": True})


# -- Initial prompt endpoint --------------------------------------------------

async def api_initial_prompt(r: Request) -> Response:
    st = _app_state(r)
    return JSONResponse({"prompt": st.initial_prompt})


# -- App factory --------------------------------------------------------------

def _build_mcp(app_state: AppState):
    from .mcp_endpoint import build_mcp_asgi_app
    wrapper, inner = build_mcp_asgi_app(app_state)
    # Stash the inner StarletteWithLifespan so the parent lifespan can
    # enter it (StreamableHTTPSessionManager needs its task-group running).
    wrapper._mcp_inner = inner  # type: ignore[attr-defined]
    return wrapper


def create_app(app_state: AppState) -> Starlette:
    # Build the MCP sub-app early so we can wire its lifespan.
    mcp_app = _build_mcp(app_state)

    @asynccontextmanager
    async def lifespan(app):
        from ..driver import driver_main
        await _refresh_probe_state(app_state, broadcast=False)
        _push_initial_config_events(app_state)

        asyncio.create_task(driver_main(app_state))

        # Open browser once after server is listening
        if app_state.open_browser:
            app_state.open_browser = False  # one-shot guard

            async def _open_browser():
                await asyncio.sleep(0.3)  # let uvicorn bind the socket
                import webbrowser
                await asyncio.to_thread(webbrowser.open, f"http://127.0.0.1:{app_state.port}")

            asyncio.create_task(_open_browser())

        # Enter the fastmcp app's lifespan so the
        # StreamableHTTPSessionManager task-group is running.
        async with mcp_app._mcp_inner.lifespan(app):  # type: ignore[attr-defined]
            yield

    routes = [
        Mount("/mcp", app=mcp_app),
        Route("/api/start-run", api_start_run, methods=["POST"]),
        Route("/api/start-run/preflight", api_start_run_preflight, methods=["GET"]),
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
        Route("/api/settings/body", api_settings_body, methods=["GET"]),
        Route("/api/settings/scout-concurrency", api_settings_scout_concurrency, methods=["PUT"]),
        Route("/api/settings/profile-form", api_settings_profile_form, methods=["GET"]),
        Route("/api/settings/installation-form", api_settings_installation_form, methods=["GET"]),
        Route("/api/initial-prompt", api_initial_prompt, methods=["GET"]),
        Route("/events", sse_stream),
    ]

    # Mount the built React app if available. Conditional to allow tests to
    # run without a prior `npm run build`.
    if FRONTEND_DIST.exists() and FRONTEND_DIST.is_dir():
        routes.append(
            Mount("/static/app", app=StaticFiles(directory=str(FRONTEND_DIST), html=False))
        )

    # Legacy static files (remaining assets in koan/web/static/ outside app/)
    if _STATIC_DIR.exists():
        routes.append(Mount("/static", app=StaticFiles(directory=str(_STATIC_DIR))))

    # SPA fallback must be LAST — catches all paths not matched above.
    # Starlette's /{path:path} matches the empty path / as well, so both
    # the root URL and any deep link resolve to the React app's index.html.
    routes.append(Route("/{path:path}", spa_fallback))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.app_state = app_state
    return app
