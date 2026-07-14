# Starlette app factory and route handlers.
# Interaction endpoints resolve PendingInteraction futures from the queue.
# SSE stream pushes JSON payloads for all events (no HTML/Jinja2 rendering).

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from ..logger import get_logger, set_log_dir, truncate_payload

log = get_logger("web.app")

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from ..artifacts import list_artifacts
from ..run_state import atomic_write_json
from ..lib.task_json import current_workflow, make_initial_workflow_history
from ..projections import (
    _primary_agent_id,
    CapsWire,
    ConfiguredModelWire,
    ConnectionWire,
    EmbeddingModelWire,
    IdentityWire,
    OfferingWire,
    PhaseInfo,
    PresetWire,
    Settings,
    SlotAssignmentWire,
    WorkflowInfo,
)
from ..state import ChatMessage
from ..types import ModelSpec, ConnectionStatus, ProviderModel
from .interactions import activate_next_interaction
from ..events import (
    build_questions_answered,
    # build_probe_completed removed in M4: CLI binary probe deleted.
    # build_installation_created/modified/removed removed in M4: installation concept deleted.
    # build_profile_*/build_default_profile_changed removed in M5: profile types deleted.
    # M2: 13 individual settings builders deleted; consolidated into build_settings_listed,
    # itself replaced by producer-side construction of the typed Settings model
    # (see _push_settings_listed).
    build_run_started,
    build_steering_queued,
    build_steering_delivered,
    build_reflect_started,
    build_reflect_trace,
    build_reflect_done,
    build_reflect_cancelled,
    build_reflect_failed,
)
from ..memory.timestamps import iso_to_ms as _iso_to_ms
from ..memory import MEMORY_TYPES
from ..memory.retrieval.backend import search as memory_search

from ..config import KoanConfig
from ..state import AgentState, AppState
NOT_IMPL = Response("Not Implemented", status_code=501)

_STATIC_DIR = Path(__file__).parent / "static"

# Vite build output directory. Populated by `cd frontend && npm run build`.
# Route mounting is conditional on this directory existing so tests pass
# without a build step.
FRONTEND_DIST = Path(__file__).parent / "static" / "app"

# -- Helpers ------------------------------------------------------------------

def _app_state(r: Request) -> AppState:
    return r.app.state.app_state

def _primary_agent(st: AppState) -> AgentState | None:
    """Resolve the live primary orchestrator AgentState for HTTP handlers.

    Returns the first agent in st.agents with is_primary=True, or None when
    no orchestrator is registered (no run active, or orchestrator already
    exited). Used by the mechanical phase/workflow routes to build a
    ToolDeps for delegation to the shared cores.
    """
    return next((a for a in st.agents.values() if a.is_primary), None)


def _runs_dir(st: AppState) -> Path:
    """Derive the per-user runs directory from the AppState's resolved koan home.

    Using st.server.koan_home rather than a module global keeps the web layer
    consistent with --home overrides without reading any environment variable.
    """
    return Path(st.server.koan_home) / "runs"


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


def _log_driver_task_exception(task: "asyncio.Task") -> None:
    """Done-callback for st.run.driver_task: log an escaped exception.

    The driver task is retained on RunState, so asyncio's "exception was
    never retrieved" GC warning never fires for it; without this callback an
    exception that escapes driver_main kills the run with no log output at
    all (the UI just stops progressing).
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("driver task died with unhandled exception", exc_info=exc)


async def api_start_run(r: Request) -> Response:
    """Handle POST /api/start-run.

    Accepts an optional 'overrides' body field ({strong?,standard?,cheap?:
    {connection_id, model_id, thinking}}) which is applied to a deep copy of
    the live config to produce the per-run frozen snapshot.  The frozen config
    + CredentialStore are stored on RunState AND serialized to
    <run_dir>/run-config.yaml as the durable per-run record (Fernet ciphertext
    only; never plaintext).  The spawn path reads the frozen snapshot so
    mid-run settings changes never affect an active run.

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

    # Parse optional per-run overrides; coerce non-dict to empty so the helper
    # treats all slots as "use persisted assignment".
    overrides_raw = body.get("overrides")
    overrides: dict = overrides_raw if isinstance(overrides_raw, dict) else {}

    # Hoist st here so both the 409 guard below and all subsequent handler
    # code share the same binding without a duplicate _app_state(r) call.
    st = _app_state(r)

    # Three-way guard for concurrent starts:
    #   (a) driver_task done or None -> proceed (no active run).
    #   (b) driver_task pending + projection.run is None -> winding down
    #       (run_cleared already emitted at workflow end). Await the teardown
    #       with a shielded timeout so a prompt restart does not 409 while
    #       the loop/subagent/driver stack unwinds.
    #   (c) driver_task pending + projection.run is non-None -> genuinely live
    #       run; reject with 409 run_active.
    driver_task = st.run.driver_task
    if driver_task is not None and not driver_task.done():
        if st.projection_store.projection.run is None:
            # Winding down: await teardown (shield so timeout does not cancel it).
            try:
                await asyncio.wait_for(asyncio.shield(driver_task), timeout=10)
            except asyncio.TimeoutError:
                return JSONResponse(
                    {
                        "error": "run_active",
                        "message": "The previous run is still winding down. Try again in a moment.",
                    },
                    status_code=409,
                )
        else:
            return JSONResponse(
                {
                    "error": "run_active",
                    "message": "A workflow run is already active. Wait for it to complete or clear it first.",
                },
                status_code=409,
            )

    # Block when no connection has a credential available.
    # Check against live provider_status before building the frozen copy so the
    # "no providers configured at all" gate is not bypassed by overrides.
    if not any(cs.available for cs in st.provider_config.provider_status):
        return JSONResponse(
            {"error": "no_providers",
             "message": "No provider credentials found. Add connections and credentials "
                        "in ~/.koan/config.yaml."},
            status_code=422,
        )

    # Build the frozen config (deep copy of live config + overrides applied).
    # Validation runs against the frozen copy so the frozen preset is what gets checked.
    cfg = st.provider_config.config
    frozen_cfg = _build_frozen_run_config(cfg, overrides)

    active_preset_name = frozen_cfg.active
    preset = frozen_cfg.presets.get(active_preset_name)
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
        "start-run received: task_len=%d workflow=%s active_preset=%s attachments=%d overrides=%s",
        len(task), body.get("workflow", "plan"), active_preset_name, len(attachments),
        list(overrides.keys()),
    )
    log.debug("start-run task payload: %s", truncate_payload(task))

    # Build the frozen CredentialStore over the frozen config snapshot.
    from ..credentials import CredentialStore, get_key_backend
    frozen_store = CredentialStore(frozen_cfg, get_key_backend(Path(st.server.koan_home)))

    # Validate each slot's connection has a credential (against the frozen snapshot).
    cm_by_id = {cm.id: cm for cm in frozen_cfg.configured_models}
    conn_by_id = {c.id: c for c in frozen_cfg.connections}
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
            if not frozen_store.has(conn.id):
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
        await save_koan_config(cfg, Path(st.server.koan_home))
        _push_settings_listed(st)

    # Emit run_started to create the Run object in the projection.
    # M5: carries active_preset instead of profile name (plan-milestone-5.md).
    _scout_concurrency = cfg.scout_concurrency
    st.projection_store.push_event(
        "run_started",
        build_run_started(active_preset_name, _scout_concurrency),
    )

    # Store the frozen snapshot on RunState so the spawn path reads it.
    st.run.frozen_config = frozen_cfg
    st.run.frozen_credential_store = frozen_store

    # Eager-flatten: build frozen ModelSpec constructs for all tier slots so
    # capability resolution (thinking clamping, caching settings) runs once at
    # run start, not once per spawn.
    from ..agents.registry import build_resolved_model
    from ..memory.bindings import build_memory_models
    from ..types import ModelSpec as _ModelSpec

    frozen_models: dict[str, _ModelSpec] = {}

    # Tier slots: one ModelSpec per configured slot. api_key is baked in.
    for slot_name, slot in preset.slots.items():
        cm = cm_by_id.get(slot.configured_model_id)
        conn = conn_by_id.get(cm.connection_id) if cm else None
        if cm and conn:
            try:
                api_key = frozen_store.resolve(conn.id) if frozen_store and conn.id else None
                # frozen_models is per-slot/informational; spawn re-resolves per role
                # via resolve_model_spec (which calls cache_tier_for_role).  Here we
                # use the global default tier ('long') because slot is not role-specific.
                frozen_models[slot_name] = build_resolved_model(
                    conn, cm, slot.thinking, slot.caching, cm.embedding_dim, api_key,
                    cache_tier="long",
                )
            except Exception:
                log.warning("failed to build frozen ModelSpec for slot %r; skipping", slot_name)

    st.run.frozen_models = frozen_models

    # Build the per-run memory bundle from the frozen config + store.
    # Each spec carries its baked api_key; no module global is set.
    st.run.memory_models = build_memory_models(frozen_cfg, frozen_store)

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
    run_dir = _runs_dir(st) / run_id
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

    # Serialize the frozen config to disk as the durable per-run record.
    # Carries the same opaque Fernet ciphertext as config.yaml (never plaintext).
    from ..config import write_run_config
    await write_run_config(frozen_cfg, run_dir)

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
    # The task reference is retained on st.run, so an escaped exception is
    # never GC-surfaced by asyncio's never-retrieved warning -- the run just
    # silently stops (observed 2026-07-14: a beartype violation in the spawn
    # path killed the driver with zero log output). Log it explicitly.
    st.run.driver_task.add_done_callback(_log_driver_task_exception)

    return JSONResponse({"ok": True, "run_dir": str(run_dir)})


# api_run_clear deleted: run clearing is now server-authoritative at workflow
# end (finalize_workflow_end, called from apply_set_phase's done branch and
# driver_main's failure exit). Mid-run abandonment is deliberately unhandled
# (out of scope).


async def api_chat(r: Request) -> Response:
    """Accept a user chat message, buffer it, and resolve the yield_future hand-back.

    Commits any attachment uploads before buffering so the loop can find
    the files in the run_dir when it drains the message buffer. When
    mechanical_resume is set (a mechanical transition is mid-apply), the
    message is deferred to the steering queue instead of resolving the
    yield_future.

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
    # Determine route before branching so the log line reflects actual routing.
    # mechanical_resume claim: when a mechanical transition is mid-apply, defer
    # chat to steering so the route does not resolve yield_future out from
    # under the mechanical route handler.
    route = "yield" if (
        st.interactions.yield_future is not None
        and not st.interactions.yield_future.done()
        and not st.interactions.mechanical_resume
    ) else "steering"
    log.info("chat message received: route=%s len=%d", route, len(message))
    log.debug("chat message payload: %s", truncate_payload(message))

    # mechanical_resume deferral: a mechanical transition is mid-apply; route
    # to steering so the message is delivered in the new phase, not stranded.
    if (
        st.interactions.yield_future is not None
        and not st.interactions.yield_future.done()
        and not st.interactions.mechanical_resume
    ):
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


async def api_set_phase(r: Request) -> Response:
    """Mechanical phase transition sharing apply_set_phase with the koan_set_phase tool.

    Accepts {"phase": "<name>"} (including "done"). Only valid while the workflow
    is parked at a yield (yield_future pending); rejected with 409 otherwise. The
    route sets mechanical_resume (the claim) synchronously before the first await
    so concurrent api_chat / api_artifact_comment messages reroute to steering
    during the apply. On "done", the shared core performs the server-authoritative
    workflow end (emits workflow_completed + run_cleared).

    Error codes: 422 invalid_phase / invalid_transition; 409 no_run / not_at_yield /
    transition_pending / no_agent.
    """
    body = await r.json()
    phase = body.get("phase")
    if not isinstance(phase, str) or not phase.strip():
        return JSONResponse(
            {"error": "invalid_phase", "message": "Missing or empty 'phase' field."},
            status_code=422,
        )
    phase = phase.strip()

    st = _app_state(r)
    if st.run.run_dir is None:
        return JSONResponse(
            {"error": "no_run", "message": "No active run."},
            status_code=409,
        )

    # Yield-park guard: mechanical transitions only while parked at a yield.
    fut = st.interactions.yield_future
    if fut is None or fut.done():
        return JSONResponse(
            {"error": "not_at_yield",
             "message": "The agent is not awaiting input; mechanical transitions "
                        "are only accepted while the workflow is parked at a phase boundary."},
            status_code=409,
        )
    if st.interactions.mechanical_resume:
        return JSONResponse(
            {"error": "transition_pending",
             "message": "A mechanical transition is already being applied."},
            status_code=409,
        )

    agent = _primary_agent(st)
    if agent is None:
        return JSONResponse(
            {"error": "no_agent",
             "message": "No primary orchestrator agent is registered."},
            status_code=409,
        )

    # Pre-validate: reuse the same validator the shared core uses (not a
    # parallel implementation). "done" bypasses the transition check.
    if phase != "done":
        if st.run.workflow is None:
            return JSONResponse(
                {"error": "invalid_transition",
                 "message": f"No active workflow; cannot transition to '{phase}'."},
                status_code=422,
            )
        from ..lib.workflows import is_valid_transition
        if not is_valid_transition(st.run.workflow, st.run.phase, phase):
            phases = list(st.run.workflow.available_phases)
            return JSONResponse(
                {"error": "invalid_transition",
                 "message": f"'{phase}' is not available from '{st.run.phase}'. "
                            f"Available phases: {phases} (plus 'done')."},
                status_code=422,
            )

    # Claim: set BEFORE the first await of the apply so concurrent chat /
    # artifact-comment messages reroute to steering during the apply.
    st.interactions.mechanical_resume = True

    try:
        from ..tools.koan_tools import ToolDeps, apply_set_phase
        result = await apply_set_phase(ToolDeps(app_state=st, agent=agent), phase)
    except Exception:
        st.interactions.mechanical_resume = False
        raise

    # Envelope check: the core RETURNS agent-correctable failures as a
    # {"ok": false, ...} JSON string rather than raising. If pre-validation
    # and the core's validator have drifted, treat the envelope as failure:
    # reset the claim, do NOT resolve the future, return 422.
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            st.interactions.mechanical_resume = False
            err = parsed.get("error", {})
            return JSONResponse(
                {"error": err.get("reason", "invalid_transition"),
                 "message": err.get("message", "Phase transition rejected.")},
                status_code=422,
            )
    except (ValueError, TypeError):
        pass  # Not a JSON envelope -- success return is a plain sentence.

    # Resolve: the value is ignored; mechanical_resume is the sentinel.
    fut2 = st.interactions.yield_future
    if fut2 is not None and not fut2.done():
        fut2.set_result(True)
    else:
        # Defensive: the claim makes this unreachable in normal operation.
        log.warning("api_set_phase: yield_future no longer pending after apply")
        st.interactions.mechanical_resume = False

    return JSONResponse({"ok": True, "phase": phase})


async def api_set_workflow(r: Request) -> Response:
    """Mechanical workflow switch sharing apply_set_workflow with the koan_set_workflow tool.

    Accepts {"workflow": "<name>"}. Same parked-at-yield precondition, claim-flag
    race protection, and error-path discipline as api_set_phase. No frontend
    trigger exists for this route (backend consistency only).

    Error codes: 422 invalid_workflow / unknown_workflow; 409 no_run / not_at_yield /
    transition_pending / no_agent.
    """
    body = await r.json()
    workflow = body.get("workflow")
    if not isinstance(workflow, str) or not workflow.strip():
        return JSONResponse(
            {"error": "invalid_workflow", "message": "Missing or empty 'workflow' field."},
            status_code=422,
        )
    workflow = workflow.strip()

    st = _app_state(r)
    if st.run.run_dir is None:
        return JSONResponse(
            {"error": "no_run", "message": "No active run."},
            status_code=409,
        )

    fut = st.interactions.yield_future
    if fut is None or fut.done():
        return JSONResponse(
            {"error": "not_at_yield",
             "message": "The agent is not awaiting input; mechanical transitions "
                        "are only accepted while the workflow is parked at a phase boundary."},
            status_code=409,
        )
    if st.interactions.mechanical_resume:
        return JSONResponse(
            {"error": "transition_pending",
             "message": "A mechanical transition is already being applied."},
            status_code=409,
        )

    agent = _primary_agent(st)
    if agent is None:
        return JSONResponse(
            {"error": "no_agent",
             "message": "No primary orchestrator agent is registered."},
            status_code=409,
        )

    # Pre-validate: reuse get_workflow (the same validator the core uses).
    from ..lib.workflows import get_workflow
    try:
        get_workflow(workflow)
    except ValueError as e:
        return JSONResponse(
            {"error": "unknown_workflow", "message": str(e)},
            status_code=422,
        )

    st.interactions.mechanical_resume = True

    try:
        from ..tools.koan_tools import ToolDeps, apply_set_workflow
        result = await apply_set_workflow(ToolDeps(app_state=st, agent=agent), workflow)
    except Exception:
        st.interactions.mechanical_resume = False
        raise

    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            st.interactions.mechanical_resume = False
            err = parsed.get("error", {})
            return JSONResponse(
                {"error": err.get("reason", "unknown_workflow"),
                 "message": err.get("message", "Workflow switch rejected.")},
                status_code=422,
            )
    except (ValueError, TypeError):
        pass

    fut2 = st.interactions.yield_future
    if fut2 is not None and not fut2.done():
        fut2.set_result(True)
    else:
        log.warning("api_set_workflow: yield_future no longer pending after apply")
        st.interactions.mechanical_resume = False

    return JSONResponse({"ok": True, "workflow": workflow})


async def api_artifact_comment(r: Request) -> Response:
    """Accept an artifact-anchored comment; route as steering input.

    Body schema: {path: str, comment: str, attachments: list[str]}

    The comment is delivered to the orchestrator as a steering message tagged
    with the artifact path. If a yield is currently active for the orchestrator,
    the comment resolves the yield future (surfacing as the user's reply).
    Otherwise it is enqueued to the steering queue; the next step boundary
    drains it and includes [artifact: {path}] in the steering envelope.

    Mirrors api_chat routing logic (including the mechanical_resume deferral);
    the only differences are the required path field and the artifact_path
    tag on the ChatMessage.
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

    # mechanical_resume deferral: mirrors api_chat -- when a mechanical
    # transition is mid-apply, route the comment to steering so it is
    # delivered in the new phase rather than resolving the future (which
    # would skip the drain and strand the comment for stale delivery).
    if (
        st.interactions.yield_future is not None
        and not st.interactions.yield_future.done()
        and not st.interactions.mechanical_resume
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
        from ..memory.bindings import build_memory_models, require_memory_model
        _models = build_memory_models(st.provider_config.config, st.provider_config.credential_store)
        results = await memory_search(
            index, q, require_memory_model(_models.embedding, "embedding"),
            k=20, type_filter=type_str or None,
        )
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


# api_memory_curation_submit removed in M7: the koan_memory_propose approval
# gate is retired; curation writes memory directly via koan_memorize/koan_forget.
# The /api/memory/curation route is removed accordingly.

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
        # Skip internal lifecycle events that the standalone page doesn't
        # need: search_start (the search event with result_count is
        # sufficient) and thinking_delta (thinking content is only surfaced
        # in the inline KoanToolCard path, not the standalone page).
        if ev.kind in ("search_start", "thinking_delta"):
            return
        # Forward final-form events (search, text) to the frontend as a
        # unified arrival-ordered trace.
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
        from ..memory.bindings import build_memory_models, require_memory_model
        from ..agents.registry import build_resolved_model

        _cfg = st.provider_config.config
        _cred_store = st.provider_config.credential_store

        # Resolve embedding from the memory bindings.
        _mem_models = build_memory_models(_cfg, _cred_store)
        embed = require_memory_model(_mem_models.embedding, "embedding")

        # Resolve the standard model spec from the active preset's standard slot.
        _active_preset = _cfg.presets.get(_cfg.active)
        _std_slot = _active_preset.slots.get("standard") if _active_preset else None
        if _std_slot is None:
            raise RuntimeError(
                f"Standard model slot is not configured in preset '{_cfg.active}'. "
                "Assign a model to the 'standard' tier to use memory reflection."
            )
        _std_cm = next(
            (m for m in _cfg.configured_models if m.id == _std_slot.configured_model_id), None
        )
        _std_conn = (
            next((c for c in _cfg.connections if c.id == _std_cm.connection_id), None)
            if _std_cm else None
        )
        if _std_cm is None or _std_conn is None:
            raise RuntimeError(
                "Standard model slot references a missing configured model or connection."
            )
        _std_api_key = _cred_store.resolve(_std_conn.id) if _cred_store and _std_conn.id else None
        standard_spec = build_resolved_model(
            _std_conn, _std_cm, _std_slot.thinking, _std_slot.caching,
            _std_cm.embedding_dim, _std_api_key, cache_tier="short",
        )

        result = await run_reflect_agent(
            index=st.memory.retrieval_index,
            model=standard_spec,
            embed=embed,
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

    # Resolve display model name from the active preset's standard slot for the projection event.
    try:
        _cfg = st.provider_config.config
        _active_preset = _cfg.presets.get(_cfg.active)
        _std_slot = _active_preset.slots.get("standard") if _active_preset else None
        _std_cm = (
            next((m for m in _cfg.configured_models if m.id == _std_slot.configured_model_id), None)
            if _std_slot else None
        )
        model = _std_cm.model_id if _std_cm else "standard"
    except Exception:
        model = "standard"
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
    if active is None or active.type not in ("ask", "retry_escalation") or active.token != token:
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
    }


def _provider_probe_results(st: AppState) -> list[ConnectionStatus]:
    """Build per-connection availability from the connections-based config (M5).

    M5: replaces the old per-type ProviderStatus synthesis with per-connection
    ConnectionStatus.  One ConnectionStatus per Connection in config.connections.
    For keyless types (KEYLESS_PROVIDER_TYPES), available is True when the
    connection has a non-empty base_url.  For keyed types, available is True
    when a credential is stored for the connection id.
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
    """Refresh per-connection availability.

    M2: model_registry build deleted (the model_registry_listed event was
    absorbed into settings_listed; offerings_by_connection is computed from
    the curated catalog, not from a registry). No config mutation. When
    broadcast is True, push a settings_listed snapshot so availability stays
    consistent with the projection (the only startup caller passes
    broadcast=False, so the broadcast path is effectively dead but kept for
    robustness).
    """
    st.provider_config.provider_status = _provider_probe_results(st)
    if broadcast:
        _push_settings_listed(st)


def _serialize_connection(conn, available: bool) -> ConnectionWire:
    """Serialize a Connection to its settings_listed wire model.

    `route` replaces the old `connection_type` (same value -- conn.type IS the
    route id). `base_url` is dropped (adapter-internal). `available` is
    credential-derived from ProviderConfigState.provider_status.
    """
    return ConnectionWire(
        id=conn.id,
        route=conn.type,
        locality=conn.locality,
        available=available,
    )


def _serialize_identity(ident) -> IdentityWire:
    """Map a ModelIdentity to its wire model.

    The kind comes from the identity (chat/embedding); snapshot is None when
    absent.
    """
    return IdentityWire(
        vendor=ident.vendor,
        family=ident.family,
        version=ident.version,
        snapshot=ident.snapshot,
        kind=ident.kind,
    )


def _serialize_caps(caps) -> CapsWire:
    """Map a Capabilities dataclass to its wire model.

    kind is "embedding" when caps.embedding_dims is non-empty, else "chat".
    thinking_levels mirrors caps.thinking.modes. native_tools is a sorted list.
    supports_tools is always True (matching the prior _serialize_model_capabilities
    behavior -- the projection does not yet model a false-tools capability).
    provenance is flattened per-field to {source, date, detail} entries.
    """
    kind = "embedding" if caps.embedding_dims else "chat"
    prov = {}
    for k, p in caps.provenance.items():
        prov[k] = {"source": p.source, "date": p.date, "detail": p.detail}
    return CapsWire(
        kind=kind,
        thinking_levels=[str(m) for m in caps.thinking.modes],
        prompt_caching=caps.prompt_caching,
        native_tools=sorted(caps.native_tools),
        supports_tools=True,
        embedding_dims=list(caps.embedding_dims) if caps.embedding_dims else None,
        resolved=caps.resolved,
        provenance=prov,
    )


def _compute_offerings_by_connection(st: AppState) -> dict[str, list[OfferingWire]]:
    """Compute offerings for each available connection.

    For each available connection, iterate _BASE_CATALOG entries, build a
    ModelIdentity, call codec.render(ident, conn.locality). Entries where render
    returns None are excluded (the codec is the vendor filter). For each rendered
    wire_id, call resolve_offering(conn.type, wire_id) to get route-aware caps
    (base -> overlay -> profile merge). Kind filtering: the voyage route only
    gets embedding entries; chat routes only get chat entries. Kind is determined
    from caps.embedding_dims (non-empty tuple -> embedding). Only connections with
    a stored credential get entries; unavailable connections are absent from the
    result dict (per Decision 2).

    Offerings are resolved-by-construction: entries whose route codec cannot
    parse back its own render output are skipped, never emitted with a null
    identity. Opaque-naming routes (ollama-cloud) therefore contribute no
    catalog offerings -- their models must come from live listing, not from
    rendering the curated catalog through a codec that cannot recognize it.
    """
    from koan.models.capabilities import _BASE_CATALOG
    from koan.models.codecs import CODECS
    from koan.models.identity import ModelIdentity, canonical
    from koan.models.offering import resolve_offering
    from koan.models.routes import get_route

    cfg = st.provider_config.config
    if not cfg:
        return {}
    available_by_conn = {cs.connection_id: cs.available for cs in st.provider_config.provider_status}
    result: dict[str, list[OfferingWire]] = {}
    for conn in cfg.connections:
        if not available_by_conn.get(conn.id, False):
            continue
        route = get_route(conn.type)
        codec = CODECS.get(route.naming)
        if codec is None:
            continue
        is_embedding_route = route.naming == "voyage"
        offerings: list[OfferingWire] = []
        for (vendor, family, version), caps in _BASE_CATALOG.items():
            kind = "embedding" if caps.embedding_dims else "chat"
            # Kind filter: embedding route gets only embedding entries; chat
            # routes get only chat entries.
            if is_embedding_route != (kind == "embedding"):
                continue
            ident = ModelIdentity(vendor=vendor, family=family, version=version, kind=kind)
            wire_id = codec.render(ident, conn.locality)
            if wire_id is None:
                continue
            # resolve_offering round-trips the wire_id through codec.parse then
            # applies the route overlay + profile merge, yielding route-aware caps
            # (e.g. anthropic -> prompt_caching="explicit" with web tools).
            offering = resolve_offering(conn.type, wire_id)
            if not isinstance(offering.ref, ModelIdentity):
                # render/parse round-trip failed: not a real catalog offering
                # for this route (see docstring).
                continue
            offerings.append(OfferingWire(
                wire_id=wire_id,
                identity=_serialize_identity(offering.ref),
                display_name=canonical(offering.ref),
                caps=_serialize_caps(offering.caps),
            ))
        if offerings:
            result[conn.id] = offerings
    return result


def _serialize_configured_model(cm, conn) -> ConfiguredModelWire:
    """Serialize a ConfiguredModel with resolved identity and caps.

    Resolves the offering via resolve_offering(conn.type, cm.model_id) so the
    wire entry carries identity (or None when unresolved), resolved (bool), and
    route-aware caps. A missing connection should be filtered by the caller
    (the assembler skips configured_models whose connection_id is not in config).
    """
    from koan.models.offering import resolve_offering
    from koan.models.identity import ModelIdentity

    offering = resolve_offering(conn.type, cm.model_id)
    ref_ident = offering.ref if isinstance(offering.ref, ModelIdentity) else None
    return ConfiguredModelWire(
        id=cm.id,
        connection_id=cm.connection_id,
        model_id=cm.model_id,
        resolved_from=getattr(cm, "resolved_from", None),
        embedding_dim=getattr(cm, "embedding_dim", None),
        identity=_serialize_identity(ref_ident) if ref_ident is not None else None,
        resolved=ref_ident is not None,
        caps=_serialize_caps(offering.caps),
    )


def _serialize_workflows() -> list[WorkflowInfo]:
    """Serialize the static workflow registry into settings_listed wire models.

    Returns one WorkflowInfo per workflow. Static for the process lifetime;
    populated once at startup.
    """
    from ..lib.workflows import WORKFLOWS as _WORKFLOWS
    out: list[WorkflowInfo] = []
    for wf in _WORKFLOWS.values():
        out.append(WorkflowInfo(
            id=wf.name,
            description=wf.description,
            phases=[
                PhaseInfo(id=p, description=wf.phase_descriptions.get(p, ""))
                for p in wf.available_phases
            ],
            initial_phase=wf.initial_phase,
        ))
    return out


def _push_settings_listed(st: AppState) -> None:
    """Push a full settings_listed snapshot to the projection store.

    Assembles the complete Settings state: connections (with available),
    configured_models (with identity + caps), offerings_by_connection (rendered
    from the curated catalog with route-aware caps), presets, active,
    memory_bindings, scout/retry settings, workflows, embedding_models. Called
    at startup and after every config mutation. Replace-all semantics: the fold
    replaces the entire Settings object.

    The payload is the typed projections.Settings model constructed here at
    the producer -- the same model the fold validates back. An invalid value
    (e.g. a null offering identity) raises HERE, in the request handler that
    caused it, not later in the fold. model_dump(mode="json") keeps the stored
    event payload snake_case and JSON-safe, identical in shape to the old
    dict-built payloads.
    """
    cfg = st.provider_config.config
    if not cfg:
        return
    avail_by_conn = {cs.connection_id: cs.available for cs in st.provider_config.provider_status}
    conn_by_id = {c.id: c for c in cfg.connections}
    settings = Settings(
        connections=[_serialize_connection(c, avail_by_conn.get(c.id, False)) for c in cfg.connections],
        configured_models=[
            _serialize_configured_model(cm, conn_by_id[cm.connection_id])
            for cm in cfg.configured_models
            if cm.connection_id in conn_by_id
        ],
        offerings_by_connection=_compute_offerings_by_connection(st),
        presets={name: _serialize_preset(p) for name, p in cfg.presets.items()},
        active=cfg.active,
        memory_bindings=_serialize_memory_bindings(cfg.memory),
        default_scout_concurrency=cfg.scout_concurrency,
        max_retry_attempts=cfg.max_retry_attempts,
        max_retry_wait_seconds=cfg.max_retry_wait_seconds,
        workflows=_serialize_workflows(),
        embedding_models=_serialize_embedding_models(),
    )
    st.projection_store.push_event("settings_listed", settings.model_dump(mode="json"))


def _serialize_preset(preset) -> PresetWire:
    """Serialize a Preset to its settings_listed wire model."""
    slots = {}
    for slot_name, slot in preset.slots.items():
        slots[slot_name] = SlotAssignmentWire(
            configured_model_id=slot.configured_model_id,
            thinking=slot.thinking if hasattr(slot, "thinking") else "disabled",
        )
    return PresetWire(slots=slots)


def _serialize_memory_bindings(bindings) -> dict | None:
    """Serialize MemoryBindings to a wire dict for the settings_listed snapshot.

    Only the embedding binding is serialized; memory_llm and reflect_llm were
    removed. Each entry carries only 'configured_model_id'. Returns None when
    bindings is None or has no binding configured.
    """
    """Serialize MemoryBindings to a wire dict for the settings_listed snapshot.

    Only the embedding binding is serialized; memory_llm and reflect_llm were
    removed. Each entry carries only 'configured_model_id'. Returns None when
    bindings is None or has no binding configured.
    """
    if bindings is None:
        return None
    result = {}
    for key in ("embedding",):
        mb = getattr(bindings, key, None)
        if mb is not None:
            result[key] = {
                "configured_model_id": mb.configured_model_id,
            }
    return result or None


def _serialize_embedding_models() -> list[EmbeddingModelWire]:
    """Build the embedding_models entries for the settings_listed snapshot.

    Returns one EmbeddingModelWire per recognized Voyage embedding model.  The
    list is static for the process lifetime and is pushed once at startup
    inside the settings_listed snapshot.
    """
    from ..memory.bindings import voyage_embedding_models
    return [
        EmbeddingModelWire(
            model_id=m.model_id,
            dimensions=list(m.dimensions),
            default_dimension=m.default_dimension,
        )
        for m in voyage_embedding_models()
    ]


def _effective_embedding_identity(cfg) -> tuple[str, int] | None:
    """Return (model_id, resolved_dim) for the active embedding binding, or None.

    Pure, non-raising: returns None when no embedding binding is configured,
    when the bound configured model or its connection is missing, when the
    connection type is not voyage, or when the model is not in the recognized
    catalog.  Guards with is_recognized_voyage_model before calling
    resolve_voyage_embedding_dim so a stale or hand-edited model id cannot
    500 an unrelated config save.
    """
    from ..memory.bindings import is_recognized_voyage_model, resolve_voyage_embedding_dim

    if cfg.memory is None or cfg.memory.embedding is None:
        return None
    cm_id = cfg.memory.embedding.configured_model_id
    cm = next((m for m in cfg.configured_models if m.id == cm_id), None)
    if cm is None:
        return None
    conn = next((c for c in cfg.connections if c.id == cm.connection_id), None)
    if conn is None or conn.type != "voyage":
        return None
    if not is_recognized_voyage_model(cm.model_id):
        return None
    try:
        dim = resolve_voyage_embedding_dim(cm.model_id, cm.embedding_dim)
    except Exception:
        return None
    return (cm.model_id, dim)


async def _rebuild_embedding_index(st: AppState) -> dict:
    """Trigger a force rebuild of the LanceDB vector index.

    Fully defensive: never raises into the caller.  Returns {"ok": True} on
    success or {"ok": False, "message": ...} when the rebuild fails.  A failed
    rebuild leaves an empty table that the next ensure_synced() re-embeds,
    self-healing.  Returns {"ok": True} immediately when no retrieval_index
    is configured (memory subsystem not initialized for this process).
    """
    if st.memory.retrieval_index is None:
        return {"ok": True}
    try:
        from ..memory.bindings import build_memory_models, require_memory_model
        _models = build_memory_models(st.provider_config.config, st.provider_config.credential_store)
        embed = require_memory_model(_models.embedding, "embedding")
        await st.memory.retrieval_index.rebuild(embed)
        return {"ok": True}
    except Exception as exc:
        log.error("_rebuild_embedding_index: rebuild failed: %s", exc)
        return {"ok": False, "message": str(exc)}


def _push_initial_config_events(st: AppState) -> None:
    """Push the full settings_listed snapshot into the projection on startup.

    M2: replaces the 13 individual settings events with one consolidated
    settings_listed full snapshot (replace-all semantics). Called after
    _refresh_probe_state (broadcast=False) so provider_status (availability) is
    ready for the connections' `available` flag and offerings_by_connection.
    """
    _push_settings_listed(st)


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


# api_probe removed in M2: per-connection availability now lives on the
# connections in the settings_listed snapshot. The eval runner health-checks
# via /api/run-status instead.


# api_profiles_list/create/update/delete removed in M5: profile CRUD endpoints
# deleted.  Profiles replaced by connections/configured_models/presets (plan-milestone-5.md).


# -- Provider model-listing helpers -------------------------------------------
# These helpers are called by the Test endpoint, the post-save refresh, and the
# eager startup background task. They never raise to the caller.

# Connection types that expose a live list-models endpoint.
# Hoisted here (not inside the eager task) so the save handler and eager task
# share the same authoritative set without duplicating a literal.
# M2: derived from the route registry -- routes with a non-None listing strategy.
from koan.models.routes import ROUTES as _ROUTES_FOR_LISTING
LISTING_CAPABLE: frozenset[str] = frozenset(r.id for r in _ROUTES_FOR_LISTING if r.listing is not None)

async def _refresh_one_provider_models(
    st: AppState,
    connection_id: str,
    provider: str,
    *,
    api_key: str | None,
    base_url: str | None,
    region: str | None,
) -> tuple[bool, str, int]:
    """List models for one connection and update the overlay on success.

    On success: updates st.provider_config.provider_models[connection_id] and
    returns (True, "", count). M2: no longer pushes a projection event -- the
    overlay is Test-endpoint storage only, not projected (offerings come from
    the curated catalog). On ModelListingError or any exception: returns
    (False, message, 0) without touching the overlay. Each connection is
    isolated so a single failure cannot abort the others. The overlay is keyed
    by connection_id, not provider type, so two connections of the same type
    keep independent model lists.
    """
    from ..agents.model_listing import list_provider_models, ModelListingError
    try:
        models = await list_provider_models(
            provider,
            api_key=api_key,
            base_url=base_url,
            region=region,
        )
        st.provider_config.provider_models[connection_id] = models
        log.info(
            "listed %d models for connection %s (type %s)",
            len(models), connection_id, provider,
        )
        return (True, "", len(models))
    except ModelListingError as exc:
        return (False, str(exc), 0)
    except Exception as exc:
        return (False, str(exc), 0)


# _refresh_provider_models_eager removed in M2: the eager startup task fed the
# now-deleted provider_models Settings event. Offerings are computed from the
# curated catalog in settings_listed, so there is no Settings need for a
# boot-time live listing. model_listing survives as the Test endpoint helper.

# api_settings_provider/api_settings_provider_delete/api_settings_provider_test
# removed in M5: provider settings mutation endpoints deleted; mutation is M6 scope.
# See plan-milestone-5.md, brief D9.

# /api/agents (GET) removed in M4: api_agents_list deleted; installation concept
# fully removed. All prior installation endpoints were removed in M3.


# -- Settings JSON endpoints --------------------------------------------------

# api_settings_body removed in M2: the frontend consumes the settings_listed
# SSE snapshot, not this HTTP endpoint. No non-frontend callers remained.


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
    await save_koan_config(st.provider_config.config, Path(st.server.koan_home))
    _push_settings_listed(st)
    return JSONResponse({"ok": True})


async def api_settings_retry(r: Request) -> Response:
    body = await r.json()
    max_retry_attempts = body.get("max_retry_attempts")
    max_retry_wait_seconds = body.get("max_retry_wait_seconds")
    if not isinstance(max_retry_attempts, int) or max_retry_attempts < 1 or max_retry_attempts > 100:
        return JSONResponse(
            {"error": "validation_error", "message": "max_retry_attempts must be an integer between 1 and 100"},
            status_code=422,
        )
    if not isinstance(max_retry_wait_seconds, (int, float)) or isinstance(max_retry_wait_seconds, bool) or max_retry_wait_seconds < 1 or max_retry_wait_seconds > 600:
        return JSONResponse(
            {"error": "validation_error", "message": "max_retry_wait_seconds must be a number between 1 and 600"},
            status_code=422,
        )
    st = _app_state(r)
    st.provider_config.config.max_retry_attempts = int(max_retry_attempts)
    st.provider_config.config.max_retry_wait_seconds = float(max_retry_wait_seconds)
    from ..config import save_koan_config
    await save_koan_config(st.provider_config.config, Path(st.server.koan_home))
    _push_settings_listed(st)
    return JSONResponse({"ok": True})


# api_settings_provider_test removed in M5: provider test endpoint deleted;
# mutation/test is M6 scope (plan-milestone-5.md).


# -- Config mutation endpoints (M6) ------------------------------------------
# Each endpoint follows the template established by api_settings_scout_concurrency:
#   parse + validate body -> mutate st.provider_config.config ->
#   await save_koan_config(...) -> push matching projection event(s) ->
#   return JSONResponse({"ok": True}), 422 on validation error.
# Secrets are never echoed in responses or the projection (brief D3).

# M2: route ids are canonical; the registry is the sole validation source.
from koan.models.routes import route_ids as _route_ids_fn
_VALID_CONNECTION_TYPES = set(_route_ids_fn())
_VALID_SLOT_NAMES = {"strong", "standard", "cheap"}
# memory_llm and reflect_llm removed — LLM tiers now derive from preset cheap/standard slots.
_VALID_MEMORY_KINDS = {"embedding"}


def _build_frozen_run_config(cfg: KoanConfig, overrides: dict) -> KoanConfig:
    """Return a deep-copied KoanConfig with per-run slot overrides applied.

    Overrides are baked into the frozen copy's $last preset via ephemeral
    ConfiguredModel entries (id='override:<slot>').  The live cfg and the
    persisted config.yaml are never mutated.  An override entry missing
    connection_id or model_id is skipped, leaving the persisted slot in place.
    """
    from ..types import ConfiguredModel, Preset, SlotAssignment
    frozen = copy.deepcopy(cfg)
    if "$last" not in frozen.presets:
        frozen.presets["$last"] = Preset()
    last = frozen.presets["$last"]
    for slot in ("strong", "standard", "cheap"):
        ov = overrides.get(slot)
        if not isinstance(ov, dict):
            continue
        conn_id = ov.get("connection_id", "")
        model_id = ov.get("model_id", "")
        if not conn_id or not model_id:
            # Incomplete override -- fall back to the persisted slot.
            continue
        override_cm_id = f"override:{slot}"
        # Remove any stale override configured-model from a previous call.
        frozen.configured_models = [
            cm for cm in frozen.configured_models if cm.id != override_cm_id
        ]
        frozen.configured_models.append(ConfiguredModel(
            id=override_cm_id,
            connection_id=conn_id,
            model_id=model_id,
        ))
        last.slots[slot] = SlotAssignment(
            configured_model_id=override_cm_id,
            thinking=ov.get("thinking", "disabled"),
        )
    return frozen


def _push_connection_events(st: AppState) -> None:
    """Push a settings_listed snapshot after a connection mutation.

    Recomputes provider availability from the credential store so a
    newly-credentialed connection becomes available immediately, then pushes one
    settings_listed snapshot (replace-all semantics) carrying the reshaped
    connections, offerings_by_connection, and configured-model caps.
    """
    st.provider_config.provider_status = _provider_probe_results(st)
    _push_settings_listed(st)


async def api_config_connection_set(r: Request) -> Response:
    """Upsert a connection (POST/PUT /api/config/connections[/{id}]).

    Body: {id, type, base_url?, locality?, secret?}.  The id may be provided
           in the body or the path.
    If a 'secret' field is present it is stored encrypted in the credential store
    and never echoed back.  Pushes settings_listed after saving.  When the
    body omits base_url on edit, the existing connection's base_url is
    preserved (the Settings wire dropped it in M2, so the frontend cannot
    round-trip it).

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
    # M2: dead fields (azure_deployment, api_version, timeout) removed; locality replaces region.
    # Preserve base_url from the existing connection when the body omits it.
    # base_url was dropped from the Settings wire (M2); the frontend cannot
    # round-trip it, so the save handler must not wipe it on edit.
    existing_conn = next((c for c in cfg.connections if c.id == conn_id), None)
    base_url = body.get("base_url") or None
    if base_url is None and existing_conn is not None:
        base_url = existing_conn.base_url
    conn = Connection(
        id=conn_id,
        type=conn_type,
        base_url=base_url,
        locality=body.get("locality") or None,
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
    store = st.provider_config.credential_store
    if secret and isinstance(secret, str) and store is not None:
        store.set(conn_id, secret)

    await save_koan_config(cfg, Path(st.server.koan_home))
    _push_connection_events(st)

    # M2: post-save background model-list refresh deleted. Offerings are now
    # computed from the curated catalog (not live listings) in settings_listed,
    # so there is no Settings need for a background refresh on save.
    return JSONResponse({"ok": True})


async def api_config_connection_delete(r: Request) -> Response:
    """Delete a connection (DELETE /api/config/connections/{id}).

    Removes the connection from cfg.connections and its credential from the
    store.  Pushes settings_listed after saving.

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
    store = st.provider_config.credential_store
    if store is not None:
        store.remove(conn_id)

    await save_koan_config(cfg, Path(st.server.koan_home))
    _push_connection_events(st)
    return JSONResponse({"ok": True})


async def api_config_model_set(r: Request) -> Response:
    """Upsert a configured model (POST/PUT /api/config/models[/{id}]).

    Body: {id, connection_id, model_id, resolved_from?, embedding_dim?}.
    id may be in the path (PUT) or the body (POST).  Pushes
    settings_listed after saving.

    embedding_dim: integer from the model's recognized dimension options, or
    absent/null to use the catalog default.  For voyage connections only; 422
    when the model_id is not in the recognized catalog or the dimension is not
    in the model's option set.

    When the embedding binding's effective identity (model_id, resolved_dim)
    changes after saving, the LanceDB vector index is rebuilt automatically.
    A rebuild failure does not roll back the save; the response carries a
    "rebuild_error" field and HTTP stays 200.

    Returns 422 on validation error.
    """
    from ..config import save_koan_config
    from ..types import ConfiguredModel
    from ..memory.bindings import (
        is_recognized_voyage_model,
        voyage_dimension_options,
    )

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
    conn = next((c for c in cfg.connections if c.id == connection_id), None)
    if conn is None:
        return JSONResponse(
            {"error": "validation_error", "message": f"connection '{connection_id}' not found"},
            status_code=422,
        )

    # Voyage-specific validation: whitelist model_id and embedding_dim.
    embedding_dim: int | None = None
    if conn.type == "voyage":
        if not is_recognized_voyage_model(model_id):
            from ..memory.bindings import VOYAGE_EMBEDDING_MODELS
            return JSONResponse(
                {
                    "error": "validation_error",
                    "message": (
                        f"model '{model_id}' is not a recognized Voyage embedding model; "
                        f"recognized: {sorted(VOYAGE_EMBEDDING_MODELS)}"
                    ),
                },
                status_code=422,
            )
        raw_dim = body.get("embedding_dim")
        if raw_dim is not None:
            parsed_dim = int(raw_dim) if isinstance(raw_dim, (int, float)) else None
            if parsed_dim is None or parsed_dim not in voyage_dimension_options(model_id):
                return JSONResponse(
                    {
                        "error": "validation_error",
                        "message": (
                            f"embedding_dim {raw_dim!r} is not valid for model '{model_id}'; "
                            f"valid options: {list(voyage_dimension_options(model_id))}"
                        ),
                    },
                    status_code=422,
                )
            embedding_dim = parsed_dim

    # Capture the embedding identity before mutation for the rebuild trigger.
    old_identity = _effective_embedding_identity(cfg)

    cm = ConfiguredModel(
        id=cm_id,
        connection_id=connection_id,
        model_id=model_id,
        resolved_from=body.get("resolved_from") or None,
        embedding_dim=embedding_dim,
    )

    existing_idx = next((i for i, m in enumerate(cfg.configured_models) if m.id == cm_id), None)
    if existing_idx is not None:
        cfg.configured_models[existing_idx] = cm
    else:
        cfg.configured_models.append(cm)

    await save_koan_config(cfg, Path(st.server.koan_home))
    _push_settings_listed(st)

    # Rebuild the vector index when the embedding identity changed.
    response_body: dict = {"ok": True}
    new_identity = _effective_embedding_identity(cfg)
    if new_identity is not None and new_identity != old_identity:
        result = await _rebuild_embedding_index(st)
        if not result.get("ok"):
            response_body["rebuild_error"] = result.get("message", "rebuild failed")

    return JSONResponse(response_body)


async def api_config_model_delete(r: Request) -> Response:
    """Delete a configured model (DELETE /api/config/models/{id}).

    Returns 404 when the model id is not found.  Pushes
    settings_listed after saving.
    """
    from ..config import save_koan_config

    cm_id = r.path_params.get("id", "")
    st = _app_state(r)
    cfg = st.provider_config.config

    if not any(m.id == cm_id for m in cfg.configured_models):
        return JSONResponse({"error": "not_found", "message": f"configured_model '{cm_id}' not found"}, status_code=404)

    cfg.configured_models = [m for m in cfg.configured_models if m.id != cm_id]

    await save_koan_config(cfg, Path(st.server.koan_home))
    _push_settings_listed(st)
    return JSONResponse({"ok": True})


async def api_config_slot_set(r: Request) -> Response:
    """Assign a configured model to a slot in the $last preset (PUT /api/config/slots/{slot}).

    Body: {configured_model_id, thinking?}.  Validates that:
      - slot is one of strong/standard/cheap
      - configured_model_id exists
      - the chosen thinking mode is in resolve_capabilities(...).thinking_modes (422 otherwise)
    Only mutates the reserved $last preset (brief D7 / Out-of-scope: named presets).
    Pushes settings_listed after saving.

    Returns 422 on validation error.
    """
    from ..config import save_koan_config
    from ..types import SlotAssignment, Preset
    from koan.models.offering import resolve_offering

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
    offering = resolve_offering(conn.type, cm.model_id)
    caps = offering.caps
    supported_modes = ["disabled", *[str(m) for m in caps.thinking.modes]]
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

    await save_koan_config(cfg, Path(st.server.koan_home))
    _push_settings_listed(st)
    return JSONResponse({"ok": True})


async def api_config_memory_set(r: Request) -> Response:
    """Set a memory binding (PUT /api/config/memory/{kind}).

    kind must be 'embedding'.
    Body: {configured_model_id}.  Validates that configured_model_id
    exists.  Pushes settings_listed after saving.

    For kind == 'embedding': validates that the referenced configured model's
    connection is of type 'voyage' and that its model_id is in the recognized
    Voyage embedding model catalog.  Returns 422 otherwise.

    When the embedding binding's effective identity (model_id, resolved_dim)
    changes after saving, the LanceDB vector index is rebuilt automatically.
    A rebuild failure does not roll back the save; the response carries a
    "rebuild_error" field and HTTP stays 200.

    Returns 422 on validation error.
    """
    from ..config import save_koan_config
    from ..types import MemoryBinding, MemoryBindings
    from ..memory.bindings import is_recognized_voyage_model

    kind = r.path_params.get("kind", "")
    if kind not in _VALID_MEMORY_KINDS:
        return JSONResponse(
            {"error": "validation_error", "message": f"kind must be one of {sorted(_VALID_MEMORY_KINDS)}"},
            status_code=422,
        )

    body = await r.json()
    cm_id = body.get("configured_model_id", "")

    if not cm_id or not isinstance(cm_id, str):
        return JSONResponse({"error": "validation_error", "message": "configured_model_id is required"}, status_code=422)

    st = _app_state(r)
    cfg = st.provider_config.config

    cm = next((m for m in cfg.configured_models if m.id == cm_id), None)
    if cm is None:
        return JSONResponse(
            {"error": "validation_error", "message": f"configured_model '{cm_id}' not found"},
            status_code=422,
        )

    # Voyage whitelist: the embedding binding must point at a recognized Voyage model.
    if kind == "embedding":
        conn = next((c for c in cfg.connections if c.id == cm.connection_id), None)
        if conn is None or conn.type != "voyage":
            return JSONResponse(
                {
                    "error": "validation_error",
                    "message": (
                        f"configured_model '{cm_id}' must use a voyage connection for the embedding role"
                    ),
                },
                status_code=422,
            )
        if not is_recognized_voyage_model(cm.model_id):
            from ..memory.bindings import VOYAGE_EMBEDDING_MODELS
            return JSONResponse(
                {
                    "error": "validation_error",
                    "message": (
                        f"model '{cm.model_id}' is not a recognized Voyage embedding model; "
                        f"recognized: {sorted(VOYAGE_EMBEDDING_MODELS)}"
                    ),
                },
                status_code=422,
            )

    if cfg.memory is None:
        cfg.memory = MemoryBindings()

    # Capture the embedding identity before mutation for the rebuild trigger.
    old_identity = _effective_embedding_identity(cfg)

    setattr(cfg.memory, kind, MemoryBinding(configured_model_id=cm_id))

    await save_koan_config(cfg, Path(st.server.koan_home))
    _push_settings_listed(st)

    # Rebuild the vector index when the embedding identity changed.
    response_body: dict = {"ok": True}
    if kind == "embedding":
        new_identity = _effective_embedding_identity(cfg)
        if new_identity is not None and new_identity != old_identity:
            result = await _rebuild_embedding_index(st)
            if not result.get("ok"):
                response_body["rebuild_error"] = result.get("message", "rebuild failed")

    return JSONResponse(response_body)


async def api_config_connection_list_models(r: Request) -> Response:
    """Trigger a live model listing for a connection (POST /api/config/connections/{id}/list-models).

    Resolves the connection, obtains its credential (or base_url for keyless
    types), calls _refresh_one_provider_models, and returns {ok: true, count: N}
    on success so the Test badge can
    display the real model count.  Returns {ok: false, message: ...} on
    ModelListingError or for non-listing types so the caller can offer a
    free-text fallback (brief D7).  Never raises to the client.
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
        region = conn.locality

    ok, msg, count = await _refresh_one_provider_models(
        st,
        conn_id,
        conn.type,
        api_key=api_key,
        base_url=base_url,
        region=region,
    )
    if ok:
        return JSONResponse({"ok": True, "count": count})
    return JSONResponse({"ok": False, "message": msg})


# api_config_model_newest removed in M2: the newest-in-family endpoint and
# async resolver are deleted. Family grouping data now lives in
# offerings_by_connection identity fields (the frontend derives pins from
# there). resolve_families survives as a pure catalog function for tests.


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
    st = _app_state(r)
    runs_dir = _runs_dir(st)
    sessions = []
    if runs_dir.is_dir():
        entries = sorted(runs_dir.iterdir(), reverse=True)
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
    # Bind st before run_path so _runs_dir(st) can derive the correct home.
    st = _app_state(r)
    run_path = _runs_dir(st) / run_id
    if not run_path.is_dir():
        return JSONResponse(
            {"error": "not_found", "message": f"session '{run_id}' not found"},
            status_code=404,
        )
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

        # M2: eager provider-model overlay task deleted. Offerings are computed
        # from the curated catalog in settings_listed, so there is no boot-time
        # live listing need.

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

    routes: list[BaseRoute] = [
        # /mcp removed: tools run in-process via the koan FunctionToolset.
        Route("/api/start-run", api_start_run, methods=["POST"]),
        # /api/run/clear removed: run clearing is server-authoritative at
        # workflow end (finalize_workflow_end). Mid-run abandonment unhandled.
        Route("/api/phase", api_set_phase, methods=["POST"]),
        Route("/api/workflow", api_set_workflow, methods=["POST"]),
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
        # /api/memory/curation removed in M7: koan_memory_propose gate retired.
        Route("/api/artifacts", api_artifacts_list),
        Route("/api/artifacts/{path:path}", api_artifact_content),
        Route("/api/eval-harvest", api_eval_harvest, methods=["GET"]),
        Route("/api/run-status", api_run_status, methods=["GET"]),
        # /api/probe removed in M2: availability lives in settings_listed.
        # /api/profiles routes removed in M5: profile CRUD deleted.
        # /api/agents removed in M4: installation concept fully deleted.
        # /api/settings/body removed in M2: frontend consumes the SSE snapshot.
        Route("/api/settings/scout-concurrency", api_settings_scout_concurrency, methods=["PUT"]),
        Route("/api/settings/retry", api_settings_retry, methods=["PUT"]),
        # /api/settings/profile-form removed in M5: profile form endpoints deleted.
        # /api/settings/provider routes removed in M5: provider mutation is M6 scope.
        # -- M6: config mutation routes --
        Route("/api/config/connections", api_config_connection_set, methods=["POST"]),
        Route("/api/config/connections/{id}", api_config_connection_set, methods=["PUT"]),
        Route("/api/config/connections/{id}", api_config_connection_delete, methods=["DELETE"]),
        Route("/api/config/connections/{id}/list-models", api_config_connection_list_models, methods=["POST"]),
        Route("/api/config/models", api_config_model_set, methods=["POST"]),
        # /api/config/models/newest removed in M2: endpoint + resolver deleted.
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
