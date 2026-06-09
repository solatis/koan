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
from ..projections import _primary_agent_id
from ..state import ChatMessage
from ..types import ModelSpec, ConnectionStatus, ModelRegistryEntry, ProviderModel
from .interactions import activate_next_interaction
from ..events import (
    build_questions_answered,
    # build_probe_completed removed in M4: CLI binary probe deleted.
    # build_installation_created/modified/removed removed in M4: installation concept deleted.
    # build_profile_*/build_default_profile_changed removed in M5: profile types deleted.
    build_provider_status_listed,
    build_model_registry_listed,
    build_provider_models_listed,
    build_run_cleared,
    build_run_started,
    build_steering_queued,
    build_connections_listed,
    build_configured_models_listed,
    build_presets_listed,
    build_active_changed,
    build_memory_bindings_listed,
    build_model_capabilities_listed,
    build_default_scout_concurrency_changed,
    build_workflows_listed,
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


# _validate_profile_tiers removed in M5: profile CRUD endpoints deleted.
# _serialize_profile and _resolve_profile removed in M5: profile types deleted.


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


async def api_start_run_preflight(r: Request) -> Response:
    """Return required connections and availability for the active preset.

    M5: 'profile' query param removed; uses the active preset from config.
    Returns which connections the active preset's slots reference and whether
    each has a credential stored.  Returns 422 when no preset is configured.
    """
    st = _app_state(r)
    cfg = st.provider_config.config
    active_preset_name = cfg.active
    preset = cfg.presets.get(active_preset_name)
    if preset is None:
        return JSONResponse(
            {"error": "unconfigured",
             "message": f"No active preset found (active='{active_preset_name}'). "
                        "Configure a preset in ~/.koan/config.yaml."},
            status_code=422,
        )

    # Resolve required connection ids from the preset's slot assignments.
    cm_by_id = {cm.id: cm for cm in cfg.configured_models}
    conn_by_id = {c.id: c for c in cfg.connections}
    store = st.provider_config.credential_store
    required_conns: dict[str, dict] = {}
    for slot_name, slot in preset.slots.items():
        cm = cm_by_id.get(slot.configured_model_id)
        if cm is None:
            continue
        conn = conn_by_id.get(cm.connection_id)
        if conn is None:
            continue
        from ..types import KEYLESS_PROVIDER_TYPES
        if conn.type in KEYLESS_PROVIDER_TYPES:
            available = bool(conn.base_url)
        else:
            available = bool(store and store.has(conn.id))
        required_conns[conn.id] = {
            "connection_id": conn.id,
            "connection_type": conn.type,
            "available": available,
        }
    return JSONResponse({
        "active_preset": active_preset_name,
        "connections": list(required_conns.values()),
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

    # M5: resolve active preset from config (no 'profile' body param required).
    cfg = st.provider_config.config
    active_preset_name = cfg.active
    preset = cfg.presets.get(active_preset_name)
    if preset is None:
        return JSONResponse(
            {"error": "unconfigured",
             "message": f"No active preset found (active='{active_preset_name}'). "
                        "Configure a preset in ~/.koan/config.yaml."},
            status_code=422,
        )

    # Log before any control-flow branches that can return early so the line
    # always appears when a valid start-run request is received.
    log.info(
        "start-run received: task_len=%d workflow=%s active_preset=%s attachments=%d",
        len(task), body.get("workflow", "plan"), active_preset_name, len(attachments),
    )
    log.debug("start-run task payload: %s", truncate_payload(task))

    # Block when no connection has a credential available.
    # provider_status is now list[ConnectionStatus]; available means credential stored.
    if not any(cs.available for cs in st.provider_config.provider_status):
        return JSONResponse(
            {"error": "no_providers",
             "message": "No provider credentials found. Add connections and credentials "
                        "in ~/.koan/config.yaml."},
            status_code=422,
        )

    # Validate each slot's connection has a credential.
    cm_by_id = {cm.id: cm for cm in cfg.configured_models}
    conn_by_id = {c.id: c for c in cfg.connections}
    store = st.provider_config.credential_store
    from ..types import KEYLESS_PROVIDER_TYPES
    for slot_name, slot in preset.slots.items():
        cm = cm_by_id.get(slot.configured_model_id)
        if cm is None:
            return JSONResponse(
                {"error": "unconfigured",
                 "message": f"Slot '{slot_name}': configured model "
                            f"'{slot.configured_model_id}' not found."},
                status_code=422,
            )
        conn = conn_by_id.get(cm.connection_id)
        if conn is None:
            return JSONResponse(
                {"error": "unconfigured",
                 "message": f"Slot '{slot_name}': connection '{cm.connection_id}' not found."},
                status_code=422,
            )
        if conn.type in KEYLESS_PROVIDER_TYPES:
            if not conn.base_url:
                return JSONResponse(
                    {"error": "missing_credentials",
                     "message": f"Connection '{conn.id}' (type '{conn.type}') "
                                f"requires a base_url (keyless provider)."},
                    status_code=422,
                )
        else:
            if not (store and store.has(conn.id)):
                return JSONResponse(
                    {"error": "missing_credentials",
                     "message": f"Connection '{conn.id}' (type '{conn.type}') "
                                f"has no stored credential.",
                     "connection_id": conn.id},
                    status_code=422,
                )

    # Apply optional scout_concurrency override.
    scout_concurrency = body.get("scout_concurrency")
    if isinstance(scout_concurrency, int) and scout_concurrency > 0:
        cfg.scout_concurrency = scout_concurrency
        from ..config import save_koan_config
        await save_koan_config(cfg)
        st.projection_store.push_event(
            "default_scout_concurrency_changed",
            build_default_scout_concurrency_changed(scout_concurrency),
        )

    # Emit run_started to create the Run object in the projection.
    # M5: carries active_preset instead of profile name (plan-milestone-5.md).
    _scout_concurrency = cfg.scout_concurrency
    st.projection_store.push_event(
        "run_started",
        build_run_started(active_preset_name, _scout_concurrency),
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
            # the in-process loop no longer consumes start_attachments (the MCP
            # handler that did was removed in M1).
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
            "steering_queued", build_steering_queued(msg.content, msg.timestamp_ms),
        )
        log.debug(
            "steering enqueued | ts=%d agent=%s artifact=%s len=%d",
            msg.timestamp_ms, primary_id or "-", msg.artifact_path or "-", len(msg.content),
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
            "steering_queued", build_steering_queued(msg.content, msg.timestamp_ms),
        )
        log.debug(
            "steering enqueued | ts=%d agent=%s artifact=%s len=%d",
            msg.timestamp_ms, primary_id or "-", msg.artifact_path or "-", len(msg.content),
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

    # M5: resolve model name from reflect_llm memory binding (replaces env var).
    # Graceful fallback to a safe default when binding is not configured.
    try:
        from ..memory.bindings import resolve_memory_binding as _rmb
        _reflect_rmm = _rmb("reflect_llm")
        model = _reflect_rmm.model_id
    except Exception:
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


def _serialize_connection_status(cs: ConnectionStatus) -> dict:
    """Serialize ConnectionStatus to a wire dict for the provider_status_listed event.

    M5: replaces _serialize_provider_status (per-type) with per-connection status.
    connection_id and connection_type are non-secret; available is credential-derived.
    """
    return {
        "connection_id": cs.connection_id,
        "connection_type": cs.connection_type,
        "available": cs.available,
    }


def _serialize_model_registry_entry(e: ModelRegistryEntry) -> dict:
    """Serialize ModelRegistryEntry to a wire dict for the model_registry_listed event."""
    return {
        "provider": e.provider,
        "model": e.model,
        "display_name": e.display_name,
        "context_window": e.context_window,
        "thinking_modes": e.thinking_modes,
        "tier_hint": e.tier_hint,
    }


def _serialize_provider_model(pm: ProviderModel) -> dict:
    """Serialize ProviderModel to a wire dict for the provider_models_listed event."""
    return {
        "provider": pm.provider,
        "model": pm.model,
        "display_name": pm.display_name,
        "context_window": pm.context_window,
    }


def _push_provider_models(st: "AppState") -> None:
    """Push the current provider_models overlay as a provider_models_listed event.

    Flattens st.provider_config.provider_models (dict provider -> list) into a
    single cross-provider list and pushes a replace-all provider_models_listed
    event to the projection store. Called on save, Test, and eager-refresh.
    """
    flat = [
        _serialize_provider_model(pm)
        for models in st.provider_config.provider_models.values()
        for pm in models
    ]
    st.projection_store.push_event(
        "provider_models_listed",
        build_provider_models_listed(flat),
    )


def _provider_probe_results(st: AppState) -> list[ConnectionStatus]:
    """Build per-connection availability from the connections-based config (M5).

    M5: replaces the old per-type ProviderStatus synthesis with per-connection
    ConnectionStatus.  One ConnectionStatus per Connection in config.connections.
    For keyless types (KEYLESS_PROVIDER_TYPES, e.g. lmstudio), available is True
    when the connection has a non-empty base_url.  For keyed types, available is
    True when a credential is stored for the connection id.
    """
    from ..types import KEYLESS_PROVIDER_TYPES
    store = st.provider_config.credential_store
    cfg = st.provider_config.config
    connections = cfg.connections if cfg else []

    result: list[ConnectionStatus] = []
    for conn in connections:
        if conn.type in KEYLESS_PROVIDER_TYPES:
            available = bool(conn.base_url)
        else:
            available = bool(store and store.has(conn.id))
        result.append(ConnectionStatus(
            connection_id=conn.id,
            connection_type=conn.type,
            available=available,
        ))
    return result


async def _refresh_probe_state(st: AppState, broadcast: bool = True) -> None:
    """Refresh per-connection availability and model registry.

    M5: builtin_profiles removed; provider_status is now per-connection
    ConnectionStatus.  model_registry is built from MODEL_CAPABILITIES +
    genai-prices bundled snapshot.  No config mutation.
    """
    from ..agents.model_catalog import build_model_registry

    st.provider_config.provider_status = _provider_probe_results(st)
    st.provider_config.model_registry = build_model_registry()

    if broadcast:
        # Push per-connection availability and model registry.
        st.projection_store.push_event(
            "provider_status_listed",
            build_provider_status_listed([_serialize_connection_status(cs) for cs in st.provider_config.provider_status]),
        )
        st.projection_store.push_event(
            "model_registry_listed",
            build_model_registry_listed([_serialize_model_registry_entry(e) for e in st.provider_config.model_registry]),
        )


def _serialize_connection(conn) -> dict:
    """Serialize a Connection to a wire dict for connections_listed."""
    return {
        "id": conn.id,
        "connection_type": conn.type,
        "base_url": conn.base_url,
        "region": conn.region,
    }


def _serialize_configured_model(cm) -> dict:
    """Serialize a ConfiguredModel to a wire dict for configured_models_listed."""
    return {
        "id": cm.id,
        "connection_id": cm.connection_id,
        "model_id": cm.model_id,
        "resolved_from": getattr(cm, "resolved_from", None),
    }


def _serialize_preset(preset) -> dict:
    """Serialize a Preset to a wire dict for presets_listed."""
    slots = {}
    for slot_name, slot in preset.slots.items():
        slots[slot_name] = {
            "configured_model_id": slot.configured_model_id,
            "thinking": slot.thinking if hasattr(slot, "thinking") else "disabled",
        }
    return {"slots": slots}


def _serialize_memory_bindings(bindings) -> dict | None:
    """Serialize MemoryBindings to a wire dict for memory_bindings_listed."""
    if bindings is None:
        return None
    result = {}
    for key in ("embedding", "memory_llm", "reflect_llm"):
        mb = getattr(bindings, key, None)
        if mb is not None:
            result[key] = {
                "configured_model_id": mb.configured_model_id,
                "thinking": getattr(mb, "thinking", "disabled"),
            }
    return result or None


def _serialize_model_capabilities(st: "AppState") -> list[dict]:
    """Build a ResolvedCapabilitiesWire-shaped dict for each configured model (M6).

    Calls resolve_capabilities(conn.type, cm.model_id) for each entry in
    cfg.configured_models.  A missing connection (misconfigured config) logs a
    warning and skips the entry rather than crashing -- callers must tolerate
    partial results.  Secrets are never read here; only the connection type is
    needed for capability resolution.
    """
    from ..agents.capability_resolver import resolve_capabilities

    cfg = st.provider_config.config
    if not cfg:
        return []

    conn_by_id = {c.id: c for c in cfg.connections}
    result: list[dict] = []
    for cm in cfg.configured_models:
        conn = conn_by_id.get(cm.connection_id)
        if conn is None:
            log.warning(
                "_serialize_model_capabilities: configured_model %r references unknown connection %r; skipping",
                cm.id,
                cm.connection_id,
            )
            continue
        caps = resolve_capabilities(conn.type, cm.model_id)
        result.append({
            "configured_model_id": cm.id,
            "thinking_supported": caps.thinking_supported,
            "thinking_modes": [str(m) for m in caps.thinking_modes],
            "thinking_shape": caps.thinking_shape,
            "supports_web_search": caps.supports_web_search,
            "supports_tools": caps.supports_tools,
            "context_window": caps.context_window,
            "context_window_variants": list(caps.context_window_variants),
            "supports_prompt_caching": caps.supports_prompt_caching,
            "tier_hint": caps.tier_hint,
            "recognized": caps.recognized,
        })
    return result


def _push_model_capabilities(st: "AppState") -> None:
    """Push model_capabilities_listed for all configured models (M6).

    Called on startup and on any mutation that touches connections or
    configured_models -- a connection's type determines the resolved capabilities
    of all models attached to it (brief D4).
    """
    caps = _serialize_model_capabilities(st)
    st.projection_store.push_event(
        "model_capabilities_listed",
        build_model_capabilities_listed(caps),
    )


def _push_initial_config_events(st: AppState) -> None:
    """Push full config state into the projection on startup.

    M5: replaces profile/active_profile events with connections/configured_models/
    presets/active/memory_bindings events.  Called after _refresh_probe_state
    (broadcast=False) so all state is ready.
    M6: also pushes model_capabilities_listed.
    """
    store = st.projection_store
    cfg = st.provider_config.config

    # M5: connections, configured_models, presets, active, memory_bindings.
    store.push_event(
        "connections_listed",
        build_connections_listed([_serialize_connection(c) for c in cfg.connections]),
    )
    store.push_event(
        "configured_models_listed",
        build_configured_models_listed([_serialize_configured_model(cm) for cm in cfg.configured_models]),
    )
    store.push_event(
        "presets_listed",
        build_presets_listed({
            name: _serialize_preset(p)
            for name, p in cfg.presets.items()
        }),
    )
    store.push_event("active_changed", build_active_changed(cfg.active))
    store.push_event(
        "memory_bindings_listed",
        build_memory_bindings_listed(_serialize_memory_bindings(cfg.memory)),
    )

    # Per-connection availability (replaces per-type ProviderStatus).
    store.push_event(
        "provider_status_listed",
        build_provider_status_listed([_serialize_connection_status(cs) for cs in st.provider_config.provider_status]),
    )

    # Model registry and dynamic overlay (overlay empty at boot; eager task fills it).
    store.push_event(
        "model_registry_listed",
        build_model_registry_listed([_serialize_model_registry_entry(e) for e in st.provider_config.model_registry]),
    )
    _push_provider_models(st)

    # Scout concurrency.
    store.push_event(
        "default_scout_concurrency_changed",
        build_default_scout_concurrency_changed(cfg.scout_concurrency),
    )

    # Workflows registry: static for the process lifetime.
    from ..lib.workflows import WORKFLOWS as _WORKFLOWS
    workflows_payload: list[dict] = []
    for wf in _WORKFLOWS.values():
        workflows_payload.append({
            "id": wf.name,
            "description": wf.description,
            "phases": [
                {"id": p, "description": wf.phase_descriptions.get(p, "")}
                for p in wf.available_phases
            ],
            "initial_phase": wf.initial_phase,
        })
    store.push_event("workflows_listed", build_workflows_listed(workflows_payload))

    # M6: per-configured-model read-only capabilities snapshot.
    _push_model_capabilities(st)


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
    """Return per-connection availability; refresh on request.

    M5: response is {connections: [{connection_id, connection_type, available}]}.
    Callers that previously consumed the 'runners' and 'balanced_profile' fields
    should migrate to the new shape.
    """
    st = _app_state(r)
    if r.query_params.get("refresh", "") in ("1", "true"):
        await _refresh_probe_state(st)
    return JSONResponse({
        "connections": [_serialize_connection_status(cs) for cs in st.provider_config.provider_status],
    })


# api_profiles_list/create/update/delete removed in M5: profile CRUD endpoints
# deleted.  Profiles replaced by connections/configured_models/presets (plan-milestone-5.md).


# -- Provider model-listing helpers -------------------------------------------
# These helpers are called by the Test endpoint, the post-save refresh, and the
# eager startup background task. They never raise to the caller.

async def _refresh_one_provider_models(
    st: "AppState",
    provider: str,
    *,
    api_key: str | None,
    base_url: str | None,
    region: str | None,
) -> tuple[bool, str]:
    """List models for one provider and update the overlay on success.

    On success: updates st.provider_config.provider_models[provider], calls
    _push_provider_models(st), and returns (True, ""). On ModelListingError:
    returns (False, message) without touching the overlay. Each provider is
    isolated so a single failure cannot abort the others.
    """
    from ..agents.model_listing import list_provider_models, ModelListingError
    try:
        models = await list_provider_models(
            provider,
            api_key=api_key,
            base_url=base_url,
            region=region,
        )
        st.provider_config.provider_models[provider] = models
        _push_provider_models(st)
        return (True, "")
    except ModelListingError as exc:
        return (False, str(exc))
    except Exception as exc:
        return (False, str(exc))


async def _refresh_provider_models_eager(st: "AppState") -> None:
    """Populate the provider model overlay at startup for all configured connections.

    M5: iterates config.connections instead of config.provider_auth.  For keyed
    providers a credential must exist in the store; for keyless types (lmstudio)
    a non-empty base_url is required.  Each connection is wrapped in its own
    try/except so one failure cannot abort others.  Runs as a non-blocking asyncio
    background task -- never called from within _refresh_probe_state.
    """
    from ..types import KEYLESS_PROVIDER_TYPES

    LISTING_CAPABLE = {"openai", "anthropic", "google", "lmstudio"}
    cfg = st.provider_config.config
    if not cfg:
        return
    store = st.provider_config.credential_store

    for conn in cfg.connections:
        if conn.type not in LISTING_CAPABLE:
            continue
        if conn.type in KEYLESS_PROVIDER_TYPES:
            if not conn.base_url:
                continue
            api_key = None
            base_url = conn.base_url
            region = None
        else:
            if not (store and store.has(conn.id)):
                continue  # no credential -- skip silently
            api_key = store.resolve(conn.id)
            base_url = conn.base_url
            region = conn.region
        try:
            await _refresh_one_provider_models(
                st, conn.type,
                api_key=api_key,
                base_url=base_url,
                region=region,
            )
        except Exception:
            pass  # per-connection isolation


# api_settings_provider/api_settings_provider_delete/api_settings_provider_test
# removed in M5: provider settings mutation endpoints deleted; mutation is M6 scope.
# See plan-milestone-5.md, brief D9.

# /api/agents (GET) removed in M4: api_agents_list deleted; installation concept
# fully removed. All prior installation endpoints were removed in M3.


# -- Settings JSON endpoints --------------------------------------------------

async def api_settings_body(r: Request) -> Response:
    """Return the settings page payload.

    M5: response is {connections, configured_models, presets, active, scoutConcurrency}.
    Profile fields removed (plan-milestone-5.md).
    """
    st = _app_state(r)
    cfg = st.provider_config.config

    return JSONResponse({
        "connections": [_serialize_connection(c) for c in cfg.connections],
        "configured_models": [_serialize_configured_model(cm) for cm in cfg.configured_models],
        "presets": {name: _serialize_preset(p) for name, p in cfg.presets.items()},
        "active": cfg.active,
        "scoutConcurrency": cfg.scout_concurrency,
    })


# api_settings_profile_form removed in M5: profile form endpoints deleted;
# presets replace profiles (plan-milestone-5.md).





async def api_settings_scout_concurrency(r: Request) -> Response:
    body = await r.json()
    value = body.get("scout_concurrency")
    if not isinstance(value, int) or value < 1 or value > 32:
        return JSONResponse(
            {"error": "validation_error", "message": "scout_concurrency must be an integer between 1 and 32"},
            status_code=422,
        )
    st = _app_state(r)
    st.provider_config.config.scout_concurrency = value
    from ..config import save_koan_config
    await save_koan_config(st.provider_config.config)
    st.projection_store.push_event("default_scout_concurrency_changed", build_default_scout_concurrency_changed(value))
    return JSONResponse({"ok": True})


# api_settings_provider_test removed in M5: provider test endpoint deleted;
# mutation/test is M6 scope (plan-milestone-5.md).


# -- Config mutation endpoints (M6) ------------------------------------------
# Each endpoint follows the template established by api_settings_scout_concurrency:
#   parse + validate body -> mutate st.provider_config.config ->
#   await save_koan_config(...) -> push matching projection event(s) ->
#   return JSONResponse({"ok": True}), 422 on validation error.
# Secrets are never echoed in responses or the projection (brief D3).

_VALID_CONNECTION_TYPES = {"google", "anthropic", "openai", "bedrock", "lmstudio", "voyage"}
_VALID_SLOT_NAMES = {"strong", "standard", "cheap"}
_VALID_MEMORY_KINDS = {"embedding", "memory_llm", "reflect_llm"}


def _push_connection_events(st: "AppState") -> None:
    """Push connections_listed + provider_status_listed + model_capabilities (M6).

    Called after any connection mutation so the projection stays consistent with
    the mutated config.  Provider availability is recomputed from the credential
    store rather than the old cached st.provider_config.provider_status so that
    a newly-credentialed connection becomes available immediately.
    """
    cfg = st.provider_config.config
    st.provider_config.provider_status = _provider_probe_results(st)
    st.projection_store.push_event(
        "connections_listed",
        build_connections_listed([_serialize_connection(c) for c in cfg.connections]),
    )
    st.projection_store.push_event(
        "provider_status_listed",
        build_provider_status_listed([_serialize_connection_status(cs) for cs in st.provider_config.provider_status]),
    )
    _push_model_capabilities(st)


async def api_config_connection_set(r: Request) -> Response:
    """Upsert a connection (POST/PUT /api/config/connections[/{id}]).

    Body: {id, type, base_url?, region?, azure_deployment?, api_version?,
           timeout?, secret?}.  The id may be provided in the body or the path.
    If a 'secret' field is present it is stored encrypted in the credential store
    and never echoed back.  Pushes connections_listed + provider_status_listed +
    model_capabilities_listed after saving.

    Returns 422 on validation error.
    """
    from ..config import save_koan_config
    from ..types import Connection

    body = await r.json()

    # id comes from the path param (PUT /api/config/connections/{id}) or from
    # the body (POST /api/config/connections).
    conn_id = r.path_params.get("id") or body.get("id", "")
    conn_type = body.get("type", "")

    if not conn_id or not isinstance(conn_id, str):
        return JSONResponse({"error": "validation_error", "message": "connection id is required"}, status_code=422)
    if conn_type not in _VALID_CONNECTION_TYPES:
        return JSONResponse(
            {"error": "validation_error", "message": f"type must be one of {sorted(_VALID_CONNECTION_TYPES)}"},
            status_code=422,
        )

    st = _app_state(r)
    cfg = st.provider_config.config

    # Build the Connection object from the body.  Endpoint settings only; the
    # secret lives in the credential store, never on the Connection.
    timeout_raw = body.get("timeout")
    conn = Connection(
        id=conn_id,
        type=conn_type,
        base_url=body.get("base_url") or None,
        region=body.get("region") or None,
        azure_deployment=body.get("azure_deployment") or None,
        api_version=body.get("api_version") or None,
        timeout=float(timeout_raw) if timeout_raw is not None else None,
    )

    # Upsert: replace an existing connection by id or append a new one.
    existing_idx = next((i for i, c in enumerate(cfg.connections) if c.id == conn_id), None)
    if existing_idx is not None:
        cfg.connections[existing_idx] = conn
    else:
        cfg.connections.append(conn)

    # Store the secret if provided; never echo it back.
    # credential_store.set() updates both the in-memory cache and the config
    # credentials envelope so save_koan_config writes the encrypted envelope.
    secret = body.get("secret")
    if secret and isinstance(secret, str):
        st.provider_config.credential_store.set(conn_id, secret)

    await save_koan_config(cfg)
    _push_connection_events(st)
    return JSONResponse({"ok": True})


async def api_config_connection_delete(r: Request) -> Response:
    """Delete a connection (DELETE /api/config/connections/{id}).

    Removes the connection from cfg.connections and its credential from the
    store.  Pushes connections_listed + provider_status_listed +
    model_capabilities_listed after saving.

    Returns 404 when the connection id is not found.
    """
    from ..config import save_koan_config

    conn_id = r.path_params.get("id", "")
    st = _app_state(r)
    cfg = st.provider_config.config

    existing = next((c for c in cfg.connections if c.id == conn_id), None)
    if existing is None:
        return JSONResponse({"error": "not_found", "message": f"connection '{conn_id}' not found"}, status_code=404)

    cfg.connections = [c for c in cfg.connections if c.id != conn_id]
    st.provider_config.credential_store.remove(conn_id)

    await save_koan_config(cfg)
    _push_connection_events(st)
    return JSONResponse({"ok": True})


async def api_config_model_set(r: Request) -> Response:
    """Upsert a configured model (POST/PUT /api/config/models[/{id}]).

    Body: {id, connection_id, model_id, resolved_from?}.  id may be in the path
    (PUT) or the body (POST).  Pushes configured_models_listed +
    model_capabilities_listed after saving.

    Returns 422 on validation error.
    """
    from ..config import save_koan_config
    from ..types import ConfiguredModel

    body = await r.json()
    cm_id = r.path_params.get("id") or body.get("id", "")
    connection_id = body.get("connection_id", "")
    model_id = body.get("model_id", "")

    if not cm_id or not isinstance(cm_id, str):
        return JSONResponse({"error": "validation_error", "message": "configured model id is required"}, status_code=422)
    if not connection_id or not isinstance(connection_id, str):
        return JSONResponse({"error": "validation_error", "message": "connection_id is required"}, status_code=422)
    if not model_id or not isinstance(model_id, str):
        return JSONResponse({"error": "validation_error", "message": "model_id is required"}, status_code=422)

    st = _app_state(r)
    cfg = st.provider_config.config

    # Validate that the referenced connection exists.
    if not any(c.id == connection_id for c in cfg.connections):
        return JSONResponse(
            {"error": "validation_error", "message": f"connection '{connection_id}' not found"},
            status_code=422,
        )

    cm = ConfiguredModel(
        id=cm_id,
        connection_id=connection_id,
        model_id=model_id,
        resolved_from=body.get("resolved_from") or None,
    )

    existing_idx = next((i for i, m in enumerate(cfg.configured_models) if m.id == cm_id), None)
    if existing_idx is not None:
        cfg.configured_models[existing_idx] = cm
    else:
        cfg.configured_models.append(cm)

    await save_koan_config(cfg)
    st.projection_store.push_event(
        "configured_models_listed",
        build_configured_models_listed([_serialize_configured_model(m) for m in cfg.configured_models]),
    )
    _push_model_capabilities(st)
    return JSONResponse({"ok": True})


async def api_config_model_delete(r: Request) -> Response:
    """Delete a configured model (DELETE /api/config/models/{id}).

    Returns 404 when the model id is not found.  Pushes configured_models_listed +
    model_capabilities_listed after saving.
    """
    from ..config import save_koan_config

    cm_id = r.path_params.get("id", "")
    st = _app_state(r)
    cfg = st.provider_config.config

    if not any(m.id == cm_id for m in cfg.configured_models):
        return JSONResponse({"error": "not_found", "message": f"configured_model '{cm_id}' not found"}, status_code=404)

    cfg.configured_models = [m for m in cfg.configured_models if m.id != cm_id]

    await save_koan_config(cfg)
    st.projection_store.push_event(
        "configured_models_listed",
        build_configured_models_listed([_serialize_configured_model(m) for m in cfg.configured_models]),
    )
    _push_model_capabilities(st)
    return JSONResponse({"ok": True})


async def api_config_slot_set(r: Request) -> Response:
    """Assign a configured model to a slot in the $last preset (PUT /api/config/slots/{slot}).

    Body: {configured_model_id, thinking?}.  Validates that:
      - slot is one of strong/standard/cheap
      - configured_model_id exists
      - the chosen thinking mode is in resolve_capabilities(...).thinking_modes (422 otherwise)
    Only mutates the reserved $last preset (brief D7 / Out-of-scope: named presets).
    Pushes presets_listed after saving.

    Returns 422 on validation error.
    """
    from ..config import save_koan_config
    from ..types import SlotAssignment, Preset
    from ..agents.capability_resolver import resolve_capabilities

    slot = r.path_params.get("slot", "")
    if slot not in _VALID_SLOT_NAMES:
        return JSONResponse(
            {"error": "validation_error", "message": f"slot must be one of {sorted(_VALID_SLOT_NAMES)}"},
            status_code=422,
        )

    body = await r.json()
    cm_id = body.get("configured_model_id", "")
    thinking = body.get("thinking", "disabled")

    if not cm_id or not isinstance(cm_id, str):
        return JSONResponse({"error": "validation_error", "message": "configured_model_id is required"}, status_code=422)

    st = _app_state(r)
    cfg = st.provider_config.config

    # Validate that the configured model exists and resolve its connection.
    cm = next((m for m in cfg.configured_models if m.id == cm_id), None)
    if cm is None:
        return JSONResponse(
            {"error": "validation_error", "message": f"configured_model '{cm_id}' not found"},
            status_code=422,
        )

    conn = next((c for c in cfg.connections if c.id == cm.connection_id), None)
    if conn is None:
        return JSONResponse(
            {"error": "validation_error", "message": f"connection '{cm.connection_id}' for model '{cm_id}' not found"},
            status_code=422,
        )

    # Validate that the chosen thinking mode is supported by the model.
    # resolve_capabilities is a pure function; 422 is deterministic and observable
    # (brief D4 -- capabilities are resolved, never asked).
    caps = resolve_capabilities(conn.type, cm.model_id)
    supported_modes = ["disabled", *[str(m) for m in caps.thinking_modes]]
    if thinking not in supported_modes:
        return JSONResponse(
            {
                "error": "validation_error",
                "message": (
                    f"thinking mode '{thinking}' is not supported for model '{cm.model_id}' "
                    f"on connection '{conn.type}'; supported: {supported_modes}"
                ),
            },
            status_code=422,
        )

    # Ensure $last preset exists before writing.
    if "$last" not in cfg.presets:
        cfg.presets["$last"] = Preset()

    cfg.presets["$last"].slots[slot] = SlotAssignment(
        configured_model_id=cm_id,
        thinking=thinking,
    )

    await save_koan_config(cfg)
    st.projection_store.push_event(
        "presets_listed",
        build_presets_listed({name: _serialize_preset(p) for name, p in cfg.presets.items()}),
    )
    return JSONResponse({"ok": True})


async def api_config_memory_set(r: Request) -> Response:
    """Set a memory binding (PUT /api/config/memory/{kind}).

    kind is one of embedding, memory_llm, reflect_llm.
    Body: {configured_model_id, thinking?}.  Validates that configured_model_id
    exists.  Pushes memory_bindings_listed after saving.

    Returns 422 on validation error.
    """
    from ..config import save_koan_config
    from ..types import MemoryBinding, MemoryBindings

    kind = r.path_params.get("kind", "")
    if kind not in _VALID_MEMORY_KINDS:
        return JSONResponse(
            {"error": "validation_error", "message": f"kind must be one of {sorted(_VALID_MEMORY_KINDS)}"},
            status_code=422,
        )

    body = await r.json()
    cm_id = body.get("configured_model_id", "")
    thinking = body.get("thinking", "disabled")

    if not cm_id or not isinstance(cm_id, str):
        return JSONResponse({"error": "validation_error", "message": "configured_model_id is required"}, status_code=422)

    st = _app_state(r)
    cfg = st.provider_config.config

    if not any(m.id == cm_id for m in cfg.configured_models):
        return JSONResponse(
            {"error": "validation_error", "message": f"configured_model '{cm_id}' not found"},
            status_code=422,
        )

    if cfg.memory is None:
        cfg.memory = MemoryBindings()

    setattr(cfg.memory, kind, MemoryBinding(configured_model_id=cm_id, thinking=thinking))

    await save_koan_config(cfg)
    st.projection_store.push_event(
        "memory_bindings_listed",
        build_memory_bindings_listed(_serialize_memory_bindings(cfg.memory)),
    )
    return JSONResponse({"ok": True})


async def api_config_connection_list_models(r: Request) -> Response:
    """Trigger a live model listing for a connection (POST /api/config/connections/{id}/list-models).

    Resolves the connection, obtains its credential (or base_url for keyless
    types), calls _refresh_one_provider_models, and pushes provider_models_listed
    on success.  Returns {ok: True} on success, {ok: False, message: ...} on
    ModelListingError or for non-listing types so the caller can offer a free-text
    fallback (brief D7).  Never raises to the client.
    """
    from ..types import KEYLESS_PROVIDER_TYPES

    conn_id = r.path_params.get("id", "")
    st = _app_state(r)
    cfg = st.provider_config.config

    conn = next((c for c in cfg.connections if c.id == conn_id), None)
    if conn is None:
        return JSONResponse({"error": "not_found", "message": f"connection '{conn_id}' not found"}, status_code=404)

    store = st.provider_config.credential_store
    if conn.type in KEYLESS_PROVIDER_TYPES:
        if not conn.base_url:
            return JSONResponse({"ok": False, "message": f"connection '{conn_id}' has no base_url configured"})
        api_key = None
        base_url = conn.base_url
        region = None
    else:
        if not (store and store.has(conn_id)):
            return JSONResponse({"ok": False, "message": f"no credential available for connection '{conn_id}'"})
        api_key = store.resolve(conn_id)
        base_url = conn.base_url
        region = conn.region

    ok, msg = await _refresh_one_provider_models(
        st,
        conn.type,
        api_key=api_key,
        base_url=base_url,
        region=region,
    )
    if ok:
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "message": msg})


async def api_config_model_newest(r: Request) -> Response:
    """Resolve and pin the newest model in a family (POST /api/config/models/newest).

    Body: {connection_id, family, id?}.  Resolves the connection, calls
    resolve_newest_in_family, upserts a ConfiguredModel with the pinned model_id +
    resolved_from provenance, saves, and pushes configured_models_listed +
    model_capabilities_listed.

    On ModelListingError (non-listing connection type or fetch failure) returns 409
    with message "unavailable for this connection type" so the caller knows to
    require an explicit pin.  On NewestInFamilyUnavailable returns 422 "no models
    in that family" so the caller can suggest a different family or explicit pin
    (M3 pattern: two distinct unavailability signals, brief D11).
    """
    from ..config import save_koan_config
    from ..agents.model_listing import ModelListingError
    from ..agents.newest_in_family import (
        NewestInFamilyUnavailable,
        resolve_newest_in_family,
    )
    from ..types import ConfiguredModel

    body = await r.json()
    conn_id = body.get("connection_id", "")
    family = body.get("family", "")
    cm_id = body.get("id") or None  # caller may supply an id; otherwise auto-generate

    if not conn_id or not isinstance(conn_id, str):
        return JSONResponse({"error": "validation_error", "message": "connection_id is required"}, status_code=422)
    if not family or not isinstance(family, str):
        return JSONResponse({"error": "validation_error", "message": "family is required"}, status_code=422)

    st = _app_state(r)
    cfg = st.provider_config.config

    conn = next((c for c in cfg.connections if c.id == conn_id), None)
    if conn is None:
        return JSONResponse({"error": "not_found", "message": f"connection '{conn_id}' not found"}, status_code=404)

    try:
        resolution = await resolve_newest_in_family(conn, family, st.provider_config.credential_store)
    except ModelListingError as exc:
        return JSONResponse(
            {"error": "unavailable", "message": f"model listing unavailable for this connection type: {exc}"},
            status_code=409,
        )
    except NewestInFamilyUnavailable as exc:
        return JSONResponse(
            {"error": "not_found", "message": f"no models in family '{family}': {exc}"},
            status_code=422,
        )

    # Auto-generate an id when the caller does not supply one.  Use a
    # deterministic slug so repeated calls for the same (connection, family)
    # upsert rather than accumulate duplicates.
    if not cm_id:
        import uuid as _uuid
        cm_id = str(_uuid.uuid4())

    cm = ConfiguredModel(
        id=cm_id,
        connection_id=conn_id,
        model_id=resolution.model_id,
        resolved_from=resolution.resolved_from,
    )

    existing_idx = next((i for i, m in enumerate(cfg.configured_models) if m.id == cm_id), None)
    if existing_idx is not None:
        cfg.configured_models[existing_idx] = cm
    else:
        cfg.configured_models.append(cm)

    await save_koan_config(cfg)
    st.projection_store.push_event(
        "configured_models_listed",
        build_configured_models_listed([_serialize_configured_model(m) for m in cfg.configured_models]),
    )
    _push_model_capabilities(st)
    return JSONResponse({"ok": True, "model_id": resolution.model_id, "resolved_from": resolution.resolved_from})


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

def create_app(app_state: AppState) -> Starlette:
    # /mcp removed in M1: tools run in-process via the koan FunctionToolset.
    # No MCP sub-app to build or wire a lifespan for.

    @asynccontextmanager
    async def lifespan(app):
        """Manage server-lifetime resources for the Starlette application.

        Startup: initialise upload state, refresh probes, push initial config
        events, optionally open the browser.
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

        # Eagerly populate the provider model overlay in the background.
        # Non-blocking: an unreachable provider yields an empty overlay entry,
        # never delays or crashes boot. The eager task must not be awaited here.
        asyncio.create_task(_refresh_provider_models_eager(app_state))

        # Open browser once after server is listening
        if app_state.server.open_browser:
            app_state.server.open_browser = False  # one-shot guard

            async def _open_browser():
                await asyncio.sleep(0.3)  # let uvicorn bind the socket
                import webbrowser
                await asyncio.to_thread(webbrowser.open, app_state.server.connect_back_url())

            asyncio.create_task(_open_browser())

        yield

        # -- Shutdown: cancel in-process subagent tasks ------------------------
        # In-process executor/scout tasks (M6) are cancelled first so their
        # spawn_subagent loops unwind before the (legacy) subprocess teardown.
        tasks = dict(app_state._active_tasks)
        if tasks:
            log.info("shutdown: cancelling %d in-process subagent task(s)…", len(tasks))
            for t in tasks.values():
                t.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            log.info("shutdown: in-process subagent tasks cancelled")

        # M4: _active_processes shutdown block removed -- the legacy CLI subprocess
        # registration path is deleted; in-process agents have no subprocess to kill.

        # Clean up the upload tempdir after all agents have stopped so any
        # in-flight request that still holds a record path has time to finish.
        shutdown_upload_state(app_state.uploads)

    routes = [
        # /mcp removed: tools run in-process via the koan FunctionToolset.
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
        # /api/profiles routes removed in M5: profile CRUD deleted.
        # /api/agents removed in M4: installation concept fully deleted.
        Route("/api/settings/body", api_settings_body, methods=["GET"]),
        Route("/api/settings/scout-concurrency", api_settings_scout_concurrency, methods=["PUT"]),
        # /api/settings/profile-form removed in M5: profile form endpoints deleted.
        # /api/settings/provider routes removed in M5: provider mutation is M6 scope.
        # -- M6: config mutation routes --
        Route("/api/config/connections", api_config_connection_set, methods=["POST"]),
        Route("/api/config/connections/{id}", api_config_connection_set, methods=["PUT"]),
        Route("/api/config/connections/{id}", api_config_connection_delete, methods=["DELETE"]),
        Route("/api/config/connections/{id}/list-models", api_config_connection_list_models, methods=["POST"]),
        Route("/api/config/models", api_config_model_set, methods=["POST"]),
        Route("/api/config/models/newest", api_config_model_newest, methods=["POST"]),
        Route("/api/config/models/{id}", api_config_model_set, methods=["PUT"]),
        Route("/api/config/models/{id}", api_config_model_delete, methods=["DELETE"]),
        Route("/api/config/slots/{slot}", api_config_slot_set, methods=["PUT"]),
        Route("/api/config/memory/{kind}", api_config_memory_set, methods=["PUT"]),
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
