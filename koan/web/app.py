# Starlette app factory and route handlers.
# Interaction endpoints resolve PendingInteraction futures from the queue.
# SSE stream pushes JSON payloads for all events (no HTML/Jinja2 rendering).

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..logger import get_logger, set_log_dir, truncate_payload

log = get_logger("web.app")

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from ..artifacts import list_artifacts
from ..run_state import atomic_write_json
from ..lib.task_json import current_workflow, make_initial_workflow_history
from ..probe import ProbeResult
from ..projections import _primary_agent_id
from ..state import ChatMessage
from ..types import AgentInstallation, Profile, ProfileTier
from .interactions import activate_next_interaction
from ..events import (
    build_questions_answered,
    build_probe_completed,
    build_run_cleared,
    build_run_started,
    build_steering_queued,
    build_installation_created,
    build_installation_modified,
    build_installation_removed,
    build_profile_created,
    build_profile_modified,
    build_profile_removed,
    build_default_profile_changed,
    build_default_scout_concurrency_changed,
    build_reflect_started,
    build_reflect_trace,
    build_reflect_done,
    build_reflect_cancelled,
    build_reflect_failed,
)
from ..memory.timestamps import iso_to_ms as _iso_to_ms
from ..memory import MEMORY_TYPES
from ..memory.retrieval.backend import search as memory_search

if TYPE_CHECKING:
    from ..state import AppState

NOT_IMPL = Response("Not Implemented", status_code=501)

_STATIC_DIR = Path(__file__).parent / "static"

# Vite build output directory. Populated by `cd frontend && npm run build`.
# Route mounting is conditional on this directory existing so tests pass
# without a build step.
FRONTEND_DIST = Path(__file__).parent / "static" / "app"

RUNS_DIR = Path.home() / ".koan" / "runs"


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


def _render_age(iso_str: str) -> str:
    """Render an ISO 8601 timestamp as a human-readable age string.

    Returns strings like '2h ago', 'yesterday', '3d ago'. Intended for
    memory relation lists where exact timestamps would be distracting.
    """
    ms = _iso_to_ms(iso_str)
    if ms == 0:
        return "unknown"
    diff_s = int(time.time() - ms / 1000)
    if diff_s < 60:
        return "just now"
    if diff_s < 3600:
        return f"{diff_s // 60}m ago"
    if diff_s < 86400:
        return f"{diff_s // 3600}h ago"
    if diff_s < 172800:
        return "yesterday"
    return f"{diff_s // 86400}d ago"


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
    st = _app_state(request)
    index_html = FRONTEND_DIST / "index.html"
    if index_html.is_file():
        if st.server.debug:
            html = index_html.read_text()
            html = html.replace(
                "<head>",
                '<head>\n    <meta name="koan-debug" content="1" />',
                1,
            )
            return Response(html, media_type="text/html")
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
        # Subscribe before snapshot so no events can slip between the two operations.
        queue = store.subscribe()
        try:
            # Version check: send snapshot unless client is exactly current.
            # Handles first connect (since=0), reconnect (since<version), and
            # server restart (since>version) uniformly — a fresh snapshot is always correct.
            if since != store.version:
                yield _sse_event("snapshot", store.get_snapshot())

            while True:
                msg = await queue.get()          # plain dict from push_event
                yield _sse_event(msg["type"], msg)
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
    """Look up a profile by name, including built-in profiles."""
    builtin = st.runner_config.builtin_profiles.get(name)
    if builtin is not None:
        return builtin
    for p in st.runner_config.config.profiles:
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
        for inst in st.runner_config.config.agent_installations:
            if inst.runner_type == rt:
                insts.append({
                    "alias": inst.alias,
                    "binary": inst.binary,
                    "binary_valid": Path(inst.binary).exists(),
                    "extra_args": inst.extra_args,
                })
        installations_by_type[rt] = insts

    return JSONResponse({
        "profile": profile_name,
        "required_runner_types": sorted(required_types),
        "installations": installations_by_type,
    })


async def api_start_run(r: Request) -> Response:
    """Handle POST /api/start-run.

    Validates the request body, applies installation selections, writes
    task.json to a fresh run directory, and creates a per-run driver task.
    Returns 409 if a driver task for the current run is still alive (concurrent
    starts are rejected; the frontend should not reach this path organically).
    The run-root task.json carries workflow_history (a single-entry list on
    first write) rather than the retired single workflow string field.
    """
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

    attachments_raw = body.get("attachments") or []
    if not isinstance(attachments_raw, list):
        return JSONResponse(
            {"error": "validation_error",
             "message": "attachments must be a list of upload IDs"},
            status_code=422,
        )
    attachments = [a for a in attachments_raw if isinstance(a, str) and a]

    # Hoist st here so both the 409 guard below and all subsequent handler
    # code share the same binding without a duplicate _app_state(r) call.
    st = _app_state(r)

    # Reject concurrent starts. driver_task.done() treats a completed task as
    # absent so the next run is naturally permitted without an explicit reset.
    if (
        st.run.driver_task is not None
        and not st.run.driver_task.done()
    ):
        return JSONResponse(
            {
                "error": "run_active",
                "message": "A workflow run is already active. Wait for it to complete or clear it first.",
            },
            status_code=409,
        )

    # Log before any control-flow branches that can return early so the line
    # always appears when a valid start-run request is received.
    log.info(
        "start-run received: task_len=%d workflow=%s profile=%s attachments=%d",
        len(task), body.get("workflow", "plan"), profile, len(attachments),
    )
    log.debug("start-run task payload: %s", truncate_payload(task))

    # Block when no runners available
    if not any(pr.available for pr in st.runner_config.probe_results):
        return JSONResponse(
            {"error": "no_runners",
             "message": "No available agent installations. Add and configure at least one in Settings."},
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
                for inst in st.runner_config.config.agent_installations
            )
            if not found:
                return JSONResponse(
                    {"error": "validation_error",
                     "message": f"Installation '{alias}' not found for runner type '{rt}'"},
                    status_code=422,
                )
        for rt, alias in installations.items():
            st.run.run_installations[rt] = alias

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
            registry.resolve_installation(tier.runner_type, st.runner_config.config, st.run.run_installations)
        except RunnerError as e:
            return JSONResponse(
                {"error": e.diagnostic.code,
                 "message": e.diagnostic.message,
                 "runner_type": tier.runner_type},
                status_code=422,
            )

    # Persist profile + installation selections
    st.runner_config.config.active_profile = profile
    from ..config import save_koan_config
    await save_koan_config(st.runner_config.config)
    st.projection_store.push_event("default_profile_changed", build_default_profile_changed(profile))

    # Apply optional overrides
    scout_concurrency = body.get("scout_concurrency")
    if isinstance(scout_concurrency, int) and scout_concurrency > 0:
        st.runner_config.config.scout_concurrency = scout_concurrency
        await save_koan_config(st.runner_config.config)
        st.projection_store.push_event("default_scout_concurrency_changed", build_default_scout_concurrency_changed(scout_concurrency))

    # Emit run_started to create the Run object in the projection
    _installations_map = dict(st.run.run_installations)
    _scout_concurrency = st.runner_config.config.scout_concurrency
    st.projection_store.push_event(
        "run_started",
        build_run_started(profile, _installations_map, _scout_concurrency),
    )

    # Reset run-scoped state
    st.interactions.user_message_buffer.clear()
    st.interactions.steering_queue.clear()
    if st.interactions.yield_future is not None and not st.interactions.yield_future.done():
        st.interactions.yield_future.set_result(False)
    st.interactions.yield_future = None
    st.run.workflow_done = False
    # Clear any stale start_attachments from a prior run before assigning new ones.
    st.run.start_attachments = []

    # Create run directory
    run_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    run_dir = Path.home() / ".koan" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # Redirect per-run file sink to this run's koan.log. Must happen here so
    # all subsequent DEBUG/INFO lines (including those from driver_main and
    # subagent spawn) land in the correct file rather than the prior run's.
    set_log_dir(str(run_dir))

    # Commit start-run attachments into the new run dir after set_log_dir so
    # any WARN logs about unknown IDs land in this run's koan.log.
    # Use the committed subset for start_attachments so unknown IDs are filtered.
    from .uploads import commit_to_run
    committed = commit_to_run(st.uploads, attachments, run_dir) if attachments else {}
    st.run.start_attachments = list(committed.keys())

    workflow_name = body.get("workflow", "plan")  # default to "plan"
    try:
        from ..lib.workflows import get_workflow
        workflow_obj = get_workflow(workflow_name)
    except ValueError as e:
        return JSONResponse(
            {"error": "validation_error", "message": str(e)},
            status_code=422,
        )

    await atomic_write_json(
        run_dir / "task.json",
        {
            "task": task,
            # workflow_history replaces the old single "workflow" string field.
            # Most-recent entry is the active workflow; koan_set_workflow appends on switch.
            "workflow_history": make_initial_workflow_history(
                workflow_name, workflow_obj.initial_phase
            ),
            "created_at": time.time(),
            "project_dir": st.run.project_dir,
            # Included for sessions UI future-proofing; the orchestrator reads
            # additional_dirs from app_state.run directly via driver_main, not here.
            "additional_dirs": st.run.additional_dirs,
            # Debug breadcrumb: the IDs passed on start-run. Not the delivery path;
            # delivery uses RunState.start_attachments in koan_complete_step.
            "attachments": attachments,
        },
    )

    st.run.task_description = task
    st.run.run_dir = str(run_dir)
    st.run.workflow = workflow_obj
    st.projection_store.push_event("workflow_selected", {"workflow": workflow_name})

    # Local import so the patch("koan.driver.driver_main") fixture in tests
    # continues to intercept this call from its new spawn site.
    from ..driver import driver_main
    st.run.driver_task = asyncio.create_task(driver_main(st))

    return JSONResponse({"ok": True, "run_dir": str(run_dir)})


async def api_run_clear(r: Request) -> Response:
    """Clear the active run projection, resetting the server to the no-run state.

    This is called by the frontend after a workflow completes (on a 3s timer for
    success; on user action for failure). It is a plain HTTP POST rather than an
    MCP tool because the orchestrator has already exited by the time it is called.

    Idempotent: returns ok=true even when the run is already None. The fold
    case also guards this, but checking here avoids emitting a no-op event.
    """
    st = _app_state(r)

    if st.projection_store.projection.run is None:
        return JSONResponse({"ok": True})

    # Drain any lingering interaction state left over from the completed run.
    # These should be empty post-completion, but guard defensively so a future
    # code path that clears early does not leave dangling futures or buffers.
    st.interactions.user_message_buffer.clear()
    st.interactions.steering_queue.clear()
    if st.interactions.yield_future is not None and not st.interactions.yield_future.done():
        st.interactions.yield_future.set_result(False)
    st.interactions.yield_future = None
    st.run.workflow_done = False
    # Guard: clear start_attachments so a race between run_clear and a stale
    # orchestrator cannot leak boot-time attachments into the next run.
    st.run.start_attachments = []

    st.projection_store.push_event("run_cleared", build_run_cleared())
    return JSONResponse({"ok": True})


async def api_chat(r: Request) -> Response:
    """Accept a user chat message, buffer it, and unblock any waiting koan_yield.

    Commits any attachment uploads before buffering so koan_yield can find
    the files in the run_dir when it drains the message buffer.
    """
    body = await r.json()
    message = body.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return JSONResponse({"error": "empty_message"}, status_code=422)

    st = _app_state(r)
    if st.run.run_dir is None:
        return JSONResponse({"error": "no_run"}, status_code=409)

    attachments: list[str] = [
        a for a in (body.get("attachments") or [])
        if isinstance(a, str)
    ]
    if attachments:
        from .uploads import commit_to_run
        commit_to_run(st.uploads, attachments, st.run.run_dir)

    ts = int(time.time() * 1000)
    msg = ChatMessage(content=message.strip(), timestamp_ms=ts, attachments=attachments)
    # Route to one buffer based on context to prevent double-delivery.
    # During phase-boundary blocking: message is the transition directive.
    # Otherwise: message is steering feedback delivered on next tool response.
    run = st.projection_store.projection.run
    primary_id = _primary_agent_id(run) if run else None

    # Determine route before branching so the log line reflects actual routing.
    route = "yield" if (
        st.interactions.yield_future is not None
        and not st.interactions.yield_future.done()
    ) else "steering"
    log.info("chat message received: route=%s len=%d", route, len(message))
    log.debug("chat message payload: %s", truncate_payload(message))

    if st.interactions.yield_future is not None and not st.interactions.yield_future.done():
        st.interactions.user_message_buffer.append(msg)
        # Show inline in the activity feed -- this is a direct conversation message
        st.projection_store.push_event(
            "user_message",
            {"content": msg.content, "timestamp_ms": msg.timestamp_ms},
            agent_id=primary_id,
        )
        st.interactions.yield_future.set_result(True)
    else:
        st.interactions.steering_queue.append(msg)
        # Show in the steering indicator above chat -- not inline
        st.projection_store.push_event(
            "steering_queued", build_steering_queued(msg.content),
        )

    return JSONResponse({"ok": True})


async def api_artifact_comment(r: Request) -> Response:
    """Accept an artifact-anchored comment; route as steering input.

    Body schema: {path: str, comment: str, attachments: list[str]}

    The comment is delivered to the orchestrator as a steering message tagged
    with the artifact path. If a yield is currently active for the orchestrator,
    the comment resolves the yield future (surfacing as the user's reply).
    Otherwise it is enqueued to the steering queue; the next step boundary
    drains it and includes [artifact: {path}] in the steering envelope.

    Mirrors api_chat routing logic; the only differences are the required path
    field and the artifact_path tag on the ChatMessage.
    """
    body = await r.json()
    path = body.get("path", "")
    comment = body.get("comment", "")
    attachments = body.get("attachments") or []

    if not isinstance(path, str) or not path:
        return JSONResponse({"error": "missing_path"}, status_code=422)
    if not isinstance(comment, str) or not comment.strip():
        return JSONResponse({"error": "missing_comment"}, status_code=422)

    st = _app_state(r)

    if attachments:
        if st.run.run_dir is None:
            return JSONResponse({"error": "no_run"}, status_code=409)
        from .uploads import commit_to_run
        commit_to_run(st.uploads, attachments, st.run.run_dir)

    ts = int(time.time() * 1000)
    msg = ChatMessage(
        content=comment,
        timestamp_ms=ts,
        attachments=attachments,
        artifact_path=path,
    )

    run = st.projection_store.projection.run
    primary_id = _primary_agent_id(run) if run else None

    if (
        st.interactions.yield_future is not None
        and not st.interactions.yield_future.done()
    ):
        # Resolve the yield with the artifact comment so the orchestrator
        # receives it as its yield reply rather than queued steering input.
        st.projection_store.push_event(
            "user_message",
            {
                "content": msg.content,
                "timestamp_ms": msg.timestamp_ms,
                "artifact_path": msg.artifact_path,
            },
            agent_id=primary_id,
        )
        st.interactions.user_message_buffer.append(msg)
        st.interactions.yield_future.set_result(True)
    else:
        st.interactions.steering_queue.append(msg)
        st.projection_store.push_event(
            "steering_queued", build_steering_queued(msg.content),
        )

    return JSONResponse({"ok": True})


# -- Upload endpoint -----------------------------------------------------------

async def api_upload(r: Request) -> Response:
    """Accept a single multipart file upload, store it in the server-lifetime
    tempdir, return id + metadata.

    Returns 422 for non-multipart bodies or missing 'file' field so the client
    gets a structured error instead of an unhandled framework 500.
    """
    st = _app_state(r)

    # Starlette's r.form() does not raise on non-multipart bodies -- it silently
    # returns an empty FormData.  Check the Content-Type header first so the
    # client receives the more specific "invalid_multipart" error.
    content_type = r.headers.get("content-type", "")
    if not (
        content_type.startswith("multipart/form-data")
        or content_type.startswith("application/x-www-form-urlencoded")
    ):
        return JSONResponse(
            {"error": "invalid_multipart",
             "message": "request body must be multipart/form-data"},
            status_code=422,
        )

    try:
        form = await r.form()
    except Exception:
        return JSONResponse(
            {"error": "invalid_multipart",
             "message": "request body must be multipart/form-data"},
            status_code=422,
        )

    upload_file = form.get("file")
    if upload_file is None or isinstance(upload_file, str):
        return JSONResponse(
            {"error": "missing_file",
             "message": "form field 'file' is required and must be a file"},
            status_code=422,
        )

    from .uploads import register_upload
    try:
        record = await register_upload(st.uploads, upload_file)
    except ValueError as e:
        return JSONResponse(
            {"error": "invalid_filename", "message": str(e)},
            status_code=422,
        )

    log.info(
        "upload received: id=%s filename=%s size=%d content_type=%s",
        record.id, record.filename, record.size, record.content_type,
    )

    return JSONResponse({
        "id": record.id,
        "filename": record.filename,
        "size": record.size,
        "content_type": record.content_type,
    })


# -- Memory read endpoints -----------------------------------------------------

async def api_memory_entries(r: Request) -> Response:
    """Return a summary of all memory entries for the project.

    Optional query params:
      q     -- non-empty string routes through the hybrid search pipeline
               (reranked, up to 20 results); absent or empty returns full listing.
      type  -- filter to a specific memory type; invalid value returns 422.
    """
    st = _app_state(r)
    q = r.query_params.get("q", "").strip()
    type_str = r.query_params.get("type", "").strip()

    # Validate type before touching the store so the client gets a clean 422.
    if type_str and type_str not in MEMORY_TYPES:
        return JSONResponse({"error": "invalid_type"}, status_code=422)

    store = st.memory.memory_store
    if store is None:
        return JSONResponse({"entries": []})

    def _wire(e) -> dict | None:
        if e.file_path is None:
            return None
        return {
            "seq": e.file_path.name[:4],
            "type": e.type,
            "title": e.title,
            "createdMs": _iso_to_ms(e.created),
            "modifiedMs": _iso_to_ms(e.modified),
        }

    if not q:
        # No query: full listing with optional server-side type filter.
        entries = [
            w for e in store.list_entries(type=type_str or None)
            if (w := _wire(e)) is not None
        ]
        return JSONResponse({"entries": entries})

    # Non-empty query: route through the hybrid search + rerank pipeline.
    index = st.memory.retrieval_index
    if index is None:
        # Memory search not initialised (retrieval index not built yet).
        return JSONResponse({"entries": []})

    try:
        results = await memory_search(index, q, k=20, type_filter=type_str or None)
    except RuntimeError as exc:
        log.warning("memory search failed: %s", exc)
        return JSONResponse({"entries": []})

    # Preserve reranked order -- do not re-sort.
    entries = [
        w for r in results
        if (w := _wire(r.entry)) is not None
    ]
    return JSONResponse({"entries": entries})


async def api_memory_entry(r: Request) -> Response:
    """Return body and relations for a single memory entry."""
    st = _app_state(r)
    seq = r.path_params.get("seq", "")
    try:
        num = int(seq)
    except ValueError:
        return JSONResponse({"error": "invalid_seq"}, status_code=422)

    store = st.memory.memory_store
    if store is None:
        return JSONResponse({"error": "not_found"}, status_code=404)

    e = store.get_entry(num)
    if e is None:
        return JSONResponse({"error": "not_found"}, status_code=404)

    seq_str = f"{num:04d}"
    filename = e.file_path.name if e.file_path else f"{seq_str}.md"

    # Build relation lists: outgoing from entry.related, incoming by scanning
    # all entries for back-references to this file's filename.
    def make_relation(other) -> dict:
        other_seq = other.file_path.name[:4] if other.file_path else "????"
        return {
            "seq": other_seq,
            "type": other.type,
            "title": other.title,
            "age": _render_age(other.modified),
        }

    outgoing = []
    for rel_filename in (e.related or []):
        # related stores filenames like "0042-some-slug.md"
        try:
            rel_num = int(rel_filename[:4])
        except (ValueError, IndexError):
            continue
        other = store.get_entry(rel_num)
        if other:
            outgoing.append(make_relation(other))

    incoming = []
    for other in store.list_entries():
        if other.file_path is None:
            continue
        if filename in (other.related or []):
            incoming.append(make_relation(other))

    return JSONResponse({
        "entry": {
            "seq": seq_str,
            "type": e.type,
            "title": e.title,
            "body": e.body,
            "createdMs": _iso_to_ms(e.created),
            "modifiedMs": _iso_to_ms(e.modified),
            "filename": filename,
            "related": list(e.related or []),
        },
        "relations": {"outgoing": outgoing, "incoming": incoming},
    })


async def api_memory_summary(r: Request) -> Response:
    """Return the project memory summary."""
    st = _app_state(r)
    store = st.memory.memory_store
    if store is None:
        return JSONResponse({"summary": ""})
    return JSONResponse({"summary": store.get_summary() or ""})


# -- Memory curation submit ---------------------------------------------------

async def api_memory_curation_submit(r: Request) -> Response:
    """Resolve the koan_memory_propose future with the user's curation decisions.

    Commits per-decision attachment uploads before resolving so the tool handler
    can find files in run_dir when it calls _render_curation_payload.
    Sets the raw decisions list on the future (rendering happens inside
    koan_memory_propose where agent.runner_type and app_state.uploads are in scope).
    """
    body = await r.json()
    batch_id = body.get("batch_id", "")
    decisions = body.get("decisions", [])

    st = _app_state(r)

    # Validate active batch exists and batch_id matches.
    active_run = st.projection_store.projection.run
    active_batch = active_run.active_curation_batch if active_run else None
    if active_batch is None or active_batch.batch_id != batch_id:
        return JSONResponse({"error": "no_active_curation"}, status_code=409)

    future = st.interactions.memory_propose_future
    if future is None or future.done():
        return JSONResponse({"error": "no_active_propose"}, status_code=409)

    # Collect all attachment IDs from all decisions and commit them upfront.
    all_ids: list[str] = []
    for d in decisions:
        if isinstance(d, dict):
            all_ids.extend(d.get("attachments") or [])

    if all_ids:
        if st.run.run_dir is None:
            return JSONResponse({"error": "no_run"}, status_code=409)
        from .uploads import commit_to_run
        commit_to_run(st.uploads, all_ids, st.run.run_dir)

    log.info(
        "memory curation submitted: batch_id=%s decisions=%d",
        batch_id, len(decisions),
    )
    # Pass raw decisions list; koan_memory_propose renders with uploads context.
    future.set_result(decisions)
    return JSONResponse({"ok": True})


# -- Reflect endpoints --------------------------------------------------------

async def _run_reflect_background(
    st: Any,
    session_id: str,
    question: str,
    context: str | None,
    started_at_ms: int,
) -> None:
    """Background task: run the reflect agent and emit projection events.

    CancelledError is re-raised so the DELETE handler can await the task and
    emit reflect_cancelled exactly once. All other exceptions emit reflect_failed.
    """
    from ..memory.retrieval.reflect import (
        run_reflect_agent, IterationCapExceeded,
    )

    def on_trace(ev) -> None:
        # Dispatch every kind (search, done, thinking, text) so the frontend
        # receives a unified arrival-ordered trace without separate event types.
        trace = {
            "iteration": ev.iteration,
            "kind": ev.kind,
            "query": ev.query,
            "type_filter": ev.type_filter,
            "result_count": ev.result_count,
            "delta": ev.delta,
        }
        st.projection_store.push_event(
            "reflect_trace",
            build_reflect_trace(session_id, trace),
        )

    try:
        result = await run_reflect_agent(
            index=st.memory.retrieval_index,
            question=question,
            context=context,
            on_trace=on_trace,
        )
        completed_ms = int(time.time() * 1000)
        st.projection_store.push_event(
            "reflect_done",
            build_reflect_done(
                session_id,
                result.answer,
                [
                    {"id": c.id, "title": c.title, "type": c.type,
                     "modifiedMs": c.modified_ms}
                    for c in result.citations
                ],
                completed_ms,
                result.iterations,
            ),
        )
    except IterationCapExceeded as e:
        completed_ms = int(time.time() * 1000)
        st.projection_store.push_event(
            "reflect_failed",
            build_reflect_failed(session_id, str(e), completed_ms),
        )
    except asyncio.CancelledError:
        # DELETE handler emits reflect_cancelled after awaiting the task;
        # re-raise so the handler sees CancelledError and can proceed.
        raise
    except Exception as e:
        completed_ms = int(time.time() * 1000)
        st.projection_store.push_event(
            "reflect_failed",
            build_reflect_failed(session_id, repr(e), completed_ms),
        )
    finally:
        # Clear handles only when terminated through a normal (non-cancelled) path.
        # CancelledError leaves them for the DELETE handler to clear.
        if (
            st.interactions.reflect_session_id == session_id
            and st.interactions.reflect_task is not None
            and st.interactions.reflect_task.done()
            and not st.interactions.reflect_task.cancelled()
        ):
            st.interactions.reflect_task = None
            st.interactions.reflect_session_id = None


async def api_memory_reflect_start(r: Request) -> Response:
    """Start a background reflect session."""
    body = await r.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "empty_question"}, status_code=422)

    st = _app_state(r)
    existing_task = st.interactions.reflect_task
    if existing_task is not None and not existing_task.done():
        return JSONResponse(
            {
                "error": "reflect_already_active",
                "session_id": st.interactions.reflect_session_id,
            },
            status_code=409,
        )

    model = os.environ.get("KOAN_REFLECT_MODEL") or "gemini-flash-latest"
    session_id = uuid.uuid4().hex
    started_at_ms = int(time.time() * 1000)
    max_iterations = 10  # matches reflect.MAX_ITERATIONS

    st.projection_store.push_event(
        "reflect_started",
        build_reflect_started(session_id, question, model, started_at_ms, max_iterations),
    )

    task = asyncio.create_task(
        _run_reflect_background(st, session_id, question, body.get("context"), started_at_ms)
    )
    st.interactions.reflect_task = task
    st.interactions.reflect_session_id = session_id

    return JSONResponse({"ok": True, "session_id": session_id})


async def api_memory_reflect_cancel(r: Request) -> Response:
    """Cancel the active reflect session."""
    st = _app_state(r)
    task = st.interactions.reflect_task
    if task is None or task.done():
        return JSONResponse({"error": "no_active_reflect"}, status_code=409)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    completed_ms = int(time.time() * 1000)
    st.projection_store.push_event(
        "reflect_cancelled",
        build_reflect_cancelled(st.interactions.reflect_session_id or "", completed_ms),
    )
    st.interactions.reflect_task = None
    st.interactions.reflect_session_id = None
    return JSONResponse({"ok": True})


async def api_answer(r: Request) -> Response:
    """Resolve an active koan_ask_question interaction with user answers.

    Commits per-answer attachment uploads before resolving so the tool handler
    can find files in run_dir when it interleaves File/Image blocks.
    """
    body = await r.json()
    answers = body.get("answers", [])
    token = body.get("token", "")

    st = _app_state(r)
    active = st.interactions.active_interaction
    if active is None or active.type != "ask" or active.token != token:
        return _stale_response()

    interaction = active

    # Collect all attachment IDs across all answers and commit them upfront.
    all_ids: list[str] = []
    for a in answers:
        if isinstance(a, dict):
            all_ids.extend(a.get("attachments") or [])

    if all_ids:
        if st.run.run_dir is None:
            return JSONResponse({"error": "no_run"}, status_code=409)
        from .uploads import commit_to_run
        commit_to_run(st.uploads, all_ids, st.run.run_dir)

    log.info("answer received: token=%s answer_count=%d", token, len(answers))
    for i, a in enumerate(answers):
        body_text = a.get("answer", "") if isinstance(a, dict) else str(a)
        log.debug("answer[%d] payload: %s", i, truncate_payload(body_text))
    st.projection_store.push_event(
        "questions_answered",
        build_questions_answered(interaction.token, answers, cancelled=False),
        agent_id=interaction.agent_id,
    )
    activate_next_interaction(st)
    interaction.future.set_result({"answers": answers})
    return JSONResponse({"ok": True})


async def api_artifacts_list(r: Request) -> Response:
    st = _app_state(r)
    if not st.run.run_dir:
        return JSONResponse({"error": "no_run", "message": "No run started"}, status_code=404)

    artifacts = list_artifacts(st.run.run_dir)
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
    if not st.run.run_dir:
        return JSONResponse({"error": "no_run"}, status_code=404)

    req_path = r.path_params.get("path", "")

    # Path traversal guard
    run = Path(st.run.run_dir).resolve()
    target = (run / req_path).resolve()
    if not str(target).startswith(str(run)):
        return JSONResponse(
            {"error": "invalid_path", "message": "Path traversal not allowed"},
            status_code=400,
        )

    if not target.is_file():
        return JSONResponse({"error": "not_found"}, status_code=404)

    try:
        run_content = target.read_text("utf-8")
    except Exception:
        run_content = "(binary or unreadable file)"

    return JSONResponse({
        "content": run_content,
        "displayPath": str(target.relative_to(run)),
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
    from ..runners.registry import compute_builtin_profiles

    st.runner_config.probe_results = await probe_all_runners()
    st.runner_config.builtin_profiles = compute_builtin_profiles(st.runner_config.probe_results)

    # --yolo: per-runner permission-skipping flags for default installations.
    # Claude is excluded: new default installations receive --permission-mode
    # acceptEdits unconditionally via _claude_post_build_args at spawn time.
    _YOLO_ARGS: dict[str, list[str]] = {
        "codex": ["--dangerously-bypass-approvals-and-sandbox"],
        "gemini": ["--yolo"],
    }

    # Auto-create or update default installations from probe results
    existing_types = {inst.runner_type for inst in st.runner_config.config.agent_installations}
    changed = False
    new_insts: list[AgentInstallation] = []
    modified_insts: list[AgentInstallation] = []
    for pr in st.runner_config.probe_results:
        if pr.available and pr.binary_path:
            if pr.runner_type not in existing_types:
                extra = _YOLO_ARGS.get(pr.runner_type, []) if st.server.yolo else []
                inst = AgentInstallation(
                    alias=f"{pr.runner_type}-default",
                    runner_type=pr.runner_type,
                    binary=pr.binary_path,
                    extra_args=extra,
                )
                st.runner_config.config.agent_installations.append(inst)
                new_insts.append(inst)
                changed = True
            else:
                for inst in st.runner_config.config.agent_installations:
                    if inst.runner_type == pr.runner_type and inst.alias == f"{pr.runner_type}-default":
                        need_update = False
                        if inst.binary != pr.binary_path:
                            inst.binary = pr.binary_path
                            need_update = True
                        # Sync yolo flags on default installations
                        yolo_args = _YOLO_ARGS.get(pr.runner_type, []) if st.server.yolo else []
                        if yolo_args and not all(a in inst.extra_args for a in yolo_args):
                            inst.extra_args = list({*inst.extra_args, *yolo_args})
                            need_update = True
                        if need_update:
                            modified_insts.append(inst)
                            changed = True
    if changed:
        from ..config import save_koan_config
        await save_koan_config(st.runner_config.config)

    if broadcast:
        # New installations must exist in the projection BEFORE probe_completed
        # sets their `available` flag.
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
        # Now set available on all installations (including the ones just created)
        _probe_results_dict = {
            inst.alias: any(pr.runner_type == inst.runner_type and pr.available
                           for pr in st.runner_config.probe_results)
            for inst in st.runner_config.config.agent_installations
        }
        st.projection_store.push_event("probe_completed", build_probe_completed(_probe_results_dict))
        for bp in st.runner_config.builtin_profiles.values():
            tiers = _serialize_profile(bp, True)["tiers"]
            st.projection_store.push_event(
                "profile_modified",
                build_profile_modified(bp.name, True, tiers),
            )


def _push_initial_config_events(st: AppState) -> None:
    """Push full config state into the projection on startup.

    Called after _refresh_probe_state(broadcast=False) so all state is ready.
    Emits one event per config fact so the snapshot captures complete config.
    """
    store = st.projection_store

    # Installations FIRST -- probe_completed needs them to exist so it can set
    # the `available` flag on each one.
    for inst in st.runner_config.config.agent_installations:
        store.push_event(
            "installation_created",
            build_installation_created(inst.alias, inst.runner_type, inst.binary, inst.extra_args),
        )

    # probe_completed: set available flag on each installation (now they exist)
    _probe_avail = {
        inst.alias: any(pr.runner_type == inst.runner_type and pr.available
                       for pr in st.runner_config.probe_results)
        for inst in st.runner_config.config.agent_installations
    }
    store.push_event("probe_completed", build_probe_completed(_probe_avail))

    # Profiles (built-in first, then user-defined)
    for bp in st.runner_config.builtin_profiles.values():
        tiers = _serialize_profile(bp, True)["tiers"]
        store.push_event("profile_created", build_profile_created(bp.name, True, tiers))
    for p in st.runner_config.config.profiles:
        sp = _serialize_profile(p, False)
        store.push_event("profile_created", build_profile_created(p.name, False, sp["tiers"]))

    # Active profile
    store.push_event("default_profile_changed", build_default_profile_changed(st.runner_config.config.active_profile))

    # Scout concurrency
    store.push_event("default_scout_concurrency_changed", build_default_scout_concurrency_changed(st.runner_config.config.scout_concurrency))


async def api_eval_harvest(r: Request) -> Response:
    # Import deferred to keep the eval harness out of the main import chain.
    # harvest_run() reads from in-process ProjectionStore.events, so it must
    # run inside the server process -- the HTTP endpoint is the only safe path.
    from evals.harvest import harvest_run
    return JSONResponse(harvest_run(_app_state(r)))


async def api_run_status(r: Request) -> Response:
    # Lightweight status endpoint for the eval runner's polling loop.
    # Returns completion and current phase so the runner can detect workflow
    # end without streaming SSE or parsing snapshot JSON.
    st = _app_state(r)
    run = st.projection_store.projection.run
    if run is None:
        return JSONResponse({"completion": None, "phase": ""})
    return JSONResponse({
        "completion": run.completion.model_dump() if run.completion else None,
        "phase": run.phase,
    })


async def api_probe(r: Request) -> Response:
    st = _app_state(r)
    if r.query_params.get("refresh", "") in ("1", "true"):
        await _refresh_probe_state(st)
    runners = [_serialize_probe_result(pr) for pr in st.runner_config.probe_results]
    balanced = st.runner_config.builtin_profiles.get("balanced")
    balanced_json = _serialize_profile(balanced, True) if balanced else None
    return JSONResponse({"runners": runners, "balanced_profile": balanced_json})


async def api_profiles_list(r: Request) -> Response:
    st = _app_state(r)
    profiles = [_serialize_profile(bp, True) for bp in st.runner_config.builtin_profiles.values()]
    for p in st.runner_config.config.profiles:
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
    if name in _app_state(r).runner_config.builtin_profiles:
        return JSONResponse(
            {"error": "validation_error", "message": f"cannot use reserved name '{name}'"},
            status_code=422,
        )
    if any(p.name == name for p in _app_state(r).runner_config.config.profiles):
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
    err = _validate_profile_tiers(tiers_raw, st.runner_config.probe_results)
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
    st.runner_config.config.profiles.append(new_profile)
    from ..config import save_koan_config
    await save_koan_config(st.runner_config.config)
    sp = _serialize_profile(new_profile, False)
    st.projection_store.push_event("profile_created", build_profile_created(name, False, sp["tiers"]))
    return JSONResponse({"ok": True})


async def api_profiles_update(r: Request) -> Response:
    name = r.path_params["name"]
    if name in _app_state(r).runner_config.builtin_profiles:
        return JSONResponse(
            {"error": "read_only", "message": f"built-in profile '{name}' cannot be edited"},
            status_code=422,
        )

    st = _app_state(r)
    target = None
    for p in st.runner_config.config.profiles:
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
    err = _validate_profile_tiers(tiers_raw, st.runner_config.probe_results)
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
    await save_koan_config(st.runner_config.config)
    sp = _serialize_profile(target, False)
    st.projection_store.push_event("profile_modified", build_profile_modified(name, False, sp["tiers"]))
    return JSONResponse({"ok": True})


async def api_profiles_delete(r: Request) -> Response:
    name = r.path_params["name"]
    if name in _app_state(r).runner_config.builtin_profiles:
        return JSONResponse(
            {"error": "read_only", "message": f"built-in profile '{name}' cannot be deleted"},
            status_code=400,
        )

    st = _app_state(r)
    idx = None
    for i, p in enumerate(st.runner_config.config.profiles):
        if p.name == name:
            idx = i
            break
    if idx is None:
        return JSONResponse({"error": "not_found", "message": f"profile '{name}' not found"}, status_code=404)

    st.runner_config.config.profiles.pop(idx)
    reset_active = st.runner_config.config.active_profile == name
    if reset_active:
        st.runner_config.config.active_profile = "balanced"

    from ..config import save_koan_config
    await save_koan_config(st.runner_config.config)
    st.projection_store.push_event("profile_removed", build_profile_removed(name))
    if reset_active:
        st.projection_store.push_event("default_profile_changed", build_default_profile_changed("balanced"))
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
        for inst in st.runner_config.config.agent_installations
    ]
    return JSONResponse({"installations": installations})


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
    if any(inst.alias == alias for inst in st.runner_config.config.agent_installations):
        return JSONResponse(
            {"error": "validation_error", "message": f"alias '{alias}' already exists"},
            status_code=422,
        )

    if not isinstance(extra_args, list):
        extra_args = []

    clean_args = [str(a) for a in extra_args]
    st.runner_config.config.agent_installations.append(AgentInstallation(
        alias=alias, runner_type=runner_type, binary=binary,
        extra_args=clean_args,
    ))
    from ..config import save_koan_config
    await save_koan_config(st.runner_config.config)
    st.projection_store.push_event(
        "installation_created",
        build_installation_created(alias, runner_type, binary, clean_args),
    )
    return JSONResponse({"ok": True})


async def api_agents_update(r: Request) -> Response:
    alias = r.path_params["alias"]
    st = _app_state(r)
    target = None
    for inst in st.runner_config.config.agent_installations:
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
    await save_koan_config(st.runner_config.config)
    st.projection_store.push_event(
        "installation_modified",
        build_installation_modified(target.alias, target.runner_type, target.binary, target.extra_args),
    )
    return JSONResponse({"ok": True})


async def api_agents_delete(r: Request) -> Response:
    alias = r.path_params["alias"]
    st = _app_state(r)
    idx = None
    for i, inst in enumerate(st.runner_config.config.agent_installations):
        if inst.alias == alias:
            idx = i
            break
    if idx is None:
        return JSONResponse({"error": "not_found", "message": f"installation '{alias}' not found"}, status_code=404)

    st.runner_config.config.agent_installations.pop(idx)

    from ..config import save_koan_config
    await save_koan_config(st.runner_config.config)
    st.projection_store.push_event("installation_removed", build_installation_removed(alias))
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

    profiles = [_serialize_profile(bp, True) for bp in st.runner_config.builtin_profiles.values()]
    for p in st.runner_config.config.profiles:
        profiles.append(_serialize_profile(p, False))

    installations = []
    for inst in st.runner_config.config.agent_installations:
        installations.append({
            "alias": inst.alias,
            "runner_type": inst.runner_type,
            "binary": inst.binary,
            "extra_args": inst.extra_args,
        })

    return JSONResponse({
        "profiles": profiles,
        "installations": installations,
        "scoutConcurrency": st.runner_config.config.scout_concurrency,
    })


async def api_settings_profile_form(r: Request) -> Response:
    st = _app_state(r)

    name = r.query_params.get("name", "")
    is_edit = r.query_params.get("edit", "0") == "1"

    available_runners = [
        _serialize_probe_result(pr) for pr in st.runner_config.probe_results if pr.available
    ]

    tiers: dict = {}
    if is_edit and name:
        for p in st.runner_config.config.profiles:
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
    all_runners = [_serialize_probe_result(pr) for pr in st.runner_config.probe_results]

    runner_type = ""
    binary = ""
    extra_args: list = []
    if is_edit and alias:
        for inst in st.runner_config.config.agent_installations:
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
    st.runner_config.config.scout_concurrency = value
    from ..config import save_koan_config
    await save_koan_config(st.runner_config.config)
    st.projection_store.push_event("default_scout_concurrency_changed", build_default_scout_concurrency_changed(value))
    return JSONResponse({"ok": True})


# -- Initial prompt endpoint --------------------------------------------------

async def api_initial_prompt(r: Request) -> Response:
    st = _app_state(r)
    return JSONResponse({"prompt": st.server.initial_prompt, "project_dir": st.run.project_dir})


# -- Sessions endpoints -------------------------------------------------------

async def api_sessions_list(r: Request) -> Response:
    """Return the list of past runs for the sessions UI.

    The workflow field in each session dict is derived from
    workflow_history[-1]["name"] via current_workflow(). The API response
    shape is unchanged: the frontend still receives {run_id, task, workflow,
    created_at, project_dir}; only the on-disk source for workflow has changed.
    """
    sessions = []
    if RUNS_DIR.is_dir():
        entries = sorted(RUNS_DIR.iterdir(), reverse=True)
        for run_path in entries:
            if not run_path.is_dir():
                continue
            task_file = run_path / "task.json"
            try:
                data = json.loads(task_file.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            sessions.append({
                "run_id": run_path.name,
                "task": data.get("task", ""),
                # workflow is derived from workflow_history to keep the response
                # shape identical to the old schema while supporting history.
                "workflow": current_workflow(data, default=""),
                "created_at": data.get("created_at", 0),
                "project_dir": data.get("project_dir", ""),
            })
    return JSONResponse({"sessions": sessions})


async def api_sessions_delete(r: Request) -> Response:
    run_id = r.path_params["run_id"]
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        return JSONResponse(
            {"error": "invalid", "message": "invalid run_id"},
            status_code=400,
        )
    run_path = RUNS_DIR / run_id
    if not run_path.is_dir():
        return JSONResponse(
            {"error": "not_found", "message": f"session '{run_id}' not found"},
            status_code=404,
        )
    st = _app_state(r)
    if st.run.run_dir and Path(st.run.run_dir).resolve() == run_path.resolve():
        return JSONResponse(
            {"error": "active_run", "message": "cannot delete the currently active run"},
            status_code=409,
        )
    shutil.rmtree(run_path)
    return JSONResponse({"ok": True})


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
        """Manage server-lifetime resources for the Starlette application.

        Startup: initialise upload state, refresh probes, push initial config
        events, optionally open the browser, then enter the MCP sub-app
        lifespan so the StreamableHTTPSessionManager task-group is running.
        Shutdown: terminate active agent processes and release the upload
        tempdir.  Driver tasks are NOT created here; they are spawned
        per-run by api_start_run.
        """
        from .uploads import init_upload_state, shutdown_upload_state
        # init_upload_state creates the server-lifetime tempdir before any
        # request can arrive, so register_upload never sees a None tempdir.
        init_upload_state(app_state.uploads)
        await _refresh_probe_state(app_state, broadcast=False)
        _push_initial_config_events(app_state)

        # Open browser once after server is listening
        if app_state.server.open_browser:
            app_state.server.open_browser = False  # one-shot guard

            async def _open_browser():
                await asyncio.sleep(0.3)  # let uvicorn bind the socket
                import webbrowser
                await asyncio.to_thread(webbrowser.open, app_state.server.connect_back_url())

            asyncio.create_task(_open_browser())

        # Enter the fastmcp app's lifespan so the
        # StreamableHTTPSessionManager task-group is running.
        async with mcp_app._mcp_inner.lifespan(app):  # type: ignore[attr-defined]
            yield

        # -- Shutdown: kill all active agent processes -------------------------
        procs = dict(app_state._active_processes)
        if procs:
            log.info("shutdown: terminating %d active agent(s)…", len(procs))
            for aid, proc in procs.items():
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass  # already dead

            # Give agents a few seconds to exit cleanly
            async def _wait_proc(aid: str, proc: asyncio.subprocess.Process) -> None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    log.warning("shutdown: agent %s did not exit in time, killing", aid)
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass

            await asyncio.gather(*[_wait_proc(a, p) for a, p in procs.items()])
            log.info("shutdown: all agents stopped")

        # Clean up the upload tempdir after all agents have stopped so any
        # in-flight request that still holds a record path has time to finish.
        shutdown_upload_state(app_state.uploads)

    routes = [
        Mount("/mcp", app=mcp_app),
        Route("/api/start-run", api_start_run, methods=["POST"]),
        Route("/api/run/clear", api_run_clear, methods=["POST"]),
        Route("/api/start-run/preflight", api_start_run_preflight, methods=["GET"]),
        Route("/api/answer", api_answer, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/artifact-comment", api_artifact_comment, methods=["POST"]),
        Route("/api/upload", api_upload, methods=["POST"]),
        Route("/api/memory/entries", api_memory_entries, methods=["GET"]),
        Route("/api/memory/entries/{seq}", api_memory_entry, methods=["GET"]),
        Route("/api/memory/summary", api_memory_summary, methods=["GET"]),
        Route("/api/memory/reflect", api_memory_reflect_start, methods=["POST"]),
        Route("/api/memory/reflect", api_memory_reflect_cancel, methods=["DELETE"]),
        Route("/api/memory/curation", api_memory_curation_submit, methods=["POST"]),
        Route("/api/artifacts", api_artifacts_list),
        Route("/api/artifacts/{path:path}", api_artifact_content),
        Route("/api/eval-harvest", api_eval_harvest, methods=["GET"]),
        Route("/api/run-status", api_run_status, methods=["GET"]),
        Route("/api/probe", api_probe),
        Route("/api/profiles", api_profiles_list, methods=["GET"]),
        Route("/api/profiles", api_profiles_create, methods=["POST"]),
        Route("/api/profiles/{name}", api_profiles_update, methods=["PUT"]),
        Route("/api/profiles/{name}", api_profiles_delete, methods=["DELETE"]),
        Route("/api/agents", api_agents_list, methods=["GET"]),
        Route("/api/agents", api_agents_create, methods=["POST"]),
        Route("/api/agents/detect", api_agents_detect, methods=["GET"]),
        Route("/api/agents/{alias}", api_agents_update, methods=["PUT"]),
        Route("/api/agents/{alias}", api_agents_delete, methods=["DELETE"]),
        Route("/api/settings/body", api_settings_body, methods=["GET"]),
        Route("/api/settings/scout-concurrency", api_settings_scout_concurrency, methods=["PUT"]),
        Route("/api/settings/profile-form", api_settings_profile_form, methods=["GET"]),
        Route("/api/settings/installation-form", api_settings_installation_form, methods=["GET"]),
        Route("/api/initial-prompt", api_initial_prompt, methods=["GET"]),
        Route("/api/sessions", api_sessions_list, methods=["GET"]),
        Route("/api/sessions/{run_id}", api_sessions_delete, methods=["DELETE"]),
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
