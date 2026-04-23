# evals/runner.py
# Black-box koan runner: starts koan in-process and returns the harvest dict.
#
# This module replaces evals/solver.py after the DeepEval migration. The
# Inspect AI solver wrapper is gone; the sole public API is run_koan(case),
# which spins up uvicorn, submits the task, waits for completion, harvests
# the projection, and tears the server down. The return value is the same
# harvest dict consumed by scorers.py and test_koan.py.
#
# yolo mode: app_state.server.yolo = True causes koan_yield to auto-respond
# with the recommended progression and koan_ask_question to return the
# recommended answer. This removes all human-in-the-loop gates without
# requiring any SSE-driving loop.

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import socket
import tempfile
from pathlib import Path

import httpx

from evals.cases import Case


DEFAULT_TIMEOUT = 1800

log = logging.getLogger("koan.evals.runner")


def _find_free_port() -> int:
    """Bind to port 0 to get an OS-assigned free port, then release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_server(
    base_url: str,
    poll_interval: float = 0.1,
    max_wait: float = 30.0,
) -> None:
    """Poll /api/probe until the server responds or max_wait is exceeded."""
    deadline = asyncio.get_event_loop().time() + max_wait
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(f"{base_url}/api/probe", timeout=2.0)
                if r.status_code < 500:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(poll_interval)
    raise TimeoutError(f"koan server at {base_url} did not start within {max_wait}s")


async def _wait_for_completion(app_state, timeout: float) -> None:
    """Poll the in-process projection until run.completion is set or timeout.

    Tails projection_store.events and emits log.info for every phase_started
    and koan_* tool_called event. Surfaces live progress in log output
    without requiring Inspect's transcript machinery.
    """
    store = app_state.projection_store
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    start = loop.time()
    last_idx = 0
    while loop.time() < deadline:
        events = store.events
        if len(events) > last_idx:
            for ev in events[last_idx:]:
                line = _progress_line(ev, start)
                if line is not None:
                    log.info(line)
            last_idx = len(events)
        run = store.projection.run
        if run is not None and run.completion is not None:
            elapsed = loop.time() - start
            log.info("t=%6.1fs  workflow completed", elapsed)
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("workflow did not complete within timeout")


def _progress_line(ev, start: float) -> str | None:
    """Turn a projection event into a one-line progress message, or None.

    Surfaces phase_started (state transition) and tool_called for any tool
    whose name starts with koan_ (orchestrator MCP calls). All other event
    types are silently skipped.
    """
    loop = asyncio.get_event_loop()
    elapsed = loop.time() - start
    et = ev.event_type
    if et == "phase_started":
        phase = ev.payload.get("phase", "?")
        return f"t={elapsed:6.1f}s  phase -> {phase}"
    if et == "tool_called":
        tool = ev.payload.get("tool", "")
        if not tool.startswith("koan_"):
            return None
        return f"t={elapsed:6.1f}s  {tool}{_fmt_args(ev.payload.get('args', {}))}"
    return None


def _fmt_args(args: dict) -> str:
    """Compact, length-capped JSON rendering suitable for a log line."""
    if not args:
        return ""
    try:
        s = json.dumps(args, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        s = str(args)
    if len(s) > 200:
        s = s[:197] + "..."
    return f"  {s}"


def _validate_directed_phases(phases: list[str], available: tuple[str, ...]) -> None:
    """Validate a directed phase list before a run starts.

    Raises ValueError when:
    - phases is empty
    - the last entry is not "done"
    - any entry other than "done" is not in the workflow's available phases

    "done" is a tombstone, not a real phase -- it is excluded from the
    existence check so callers do not need to special-case it.
    """
    if not phases:
        raise ValueError("directed_phases must not be empty")
    if phases[-1] != "done":
        raise ValueError(
            f"last entry in directed_phases must be 'done', got '{phases[-1]}'"
        )
    unknown = [p for p in phases if p != "done" and p not in available]
    if unknown:
        raise ValueError(
            f"directed_phases contains unknown phase(s) {unknown};"
            f" available: {list(available)}"
        )


async def run_koan(case: Case, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run koan in-process for a single case and return the harvest dict.

    Starts uvicorn with yolo=True and directed_phases from the case, POSTs
    to /api/start-run, waits for completion, harvests projection events,
    then tears the server down. The returned dict is consumed directly by
    pytest fixtures; no Inspect TaskState intermediary.
    """
    import uvicorn
    from koan.config import load_koan_config
    from koan.state import AppState
    from koan.web.app import create_app

    from evals.harvest import harvest_run

    # repo/ submodule is the snapshot; copy it without .git/ to keep
    # tempdir I/O lean and avoid confusing koan's own git introspection.
    snapshot_path = Path(case.fixture_dir) / "repo"
    directed_phases = list(case.directed_phases)
    workflow = case.workflow
    task_input = (case.task_dir / "task.md").read_text(encoding="utf-8").strip()

    with tempfile.TemporaryDirectory() as project_tmp:
        if snapshot_path.exists():
            shutil.copytree(
                snapshot_path,
                project_tmp,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git"),
            )

        app_state = AppState()
        app_state.runner_config.config = await load_koan_config()
        app_state.run.project_dir = project_tmp
        app_state.server.open_browser = False
        # yolo=True makes koan_yield and koan_ask_question auto-respond,
        # removing all human-in-the-loop gates without needing an SSE loop.
        app_state.server.yolo = True
        # directed_phases steers koan_yield auto-responses toward the next
        # phase in the list instead of picking from suggestions.
        app_state.server.directed_phases = directed_phases
        app_state.init_memory_services()
        app = create_app(app_state)

        port = _find_free_port()
        # AppState.server.port must match the uvicorn bind port because
        # mcp-config.json (which tells the spawned orchestrator CLI how
        # to reach the driver) is built from app_state.server.port at spawn
        # time. A mismatch means the orchestrator cannot register the
        # koan_* tools and spends minutes flailing before discovering the
        # real port on its own.
        app_state.server.port = port
        uv_config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(uv_config)
        server_task = asyncio.create_task(server.serve())

        base_url = f"http://127.0.0.1:{port}"
        await _wait_for_server(base_url)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/api/start-run",
                    json={"task": task_input, "profile": "balanced", "workflow": workflow},
                )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"/api/start-run failed: {resp.status_code} {resp.text}"
                )
            # Validate directed_phases after /api/start-run so app_state.run.workflow
            # is already resolved -- workflow.available_phases is not accessible
            # before the run starts.
            if app_state.run.workflow is not None:
                _validate_directed_phases(
                    directed_phases,
                    app_state.run.workflow.available_phases,
                )
            try:
                await _wait_for_completion(app_state, timeout=timeout)
            except (asyncio.TimeoutError, TimeoutError):
                pass  # harvest whatever exists even on timeout
        finally:
            # Harvest before the server task is awaited so whatever state
            # the projection has at cancel/timeout time is still captured.
            try:
                harvest = harvest_run(app_state)
            except Exception as exc:
                harvest = {
                    "phase_order": [],
                    "phase_summaries": {},
                    "tool_calls_by_phase": {},
                    "artifacts_by_phase": {},
                    "_harvest_error": repr(exc),
                }
            server.should_exit = True
            await server_task

    return harvest
