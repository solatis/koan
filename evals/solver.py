# evals/solver.py
# Inspect AI Solver: runs koan as an in-process black-box.
#
# The solver starts koan's HTTP server via uvicorn, sets yolo=True so all
# user-interaction gates are auto-answered, POSTs a start-run request, then
# polls the in-process projection until the workflow completes. Per-phase data
# is harvested from ProjectionStore.events after completion.
#
# yolo mode: app_state.yolo = True causes koan_yield to auto-respond with
# the recommended progression and koan_ask_question to return the recommended
# answer (or "use your best judgement" if none is configured). This removes
# all human-in-the-loop gates without requiring any SSE-driving loop.

from __future__ import annotations

import asyncio
import json
import socket
import tarfile
import tempfile
from pathlib import Path

import httpx
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Solver, TaskState, solver
from inspect_ai.log import transcript


DEFAULT_TIMEOUT = 1800


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

    Tails projection_store.events and emits an InfoEvent via inspect_ai's
    transcript for every phase_started and every koan_* tool_called event.
    Renders live in Inspect's Running Samples TUI and persists in the .eval
    log. Without this the sample appears frozen during a 20-minute run.
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
                    transcript().info(line, source="koan-eval")
            last_idx = len(events)
        run = store.projection.run
        if run is not None and run.completion is not None:
            elapsed = loop.time() - start
            transcript().info(
                f"t={elapsed:6.1f}s  workflow completed",
                source="koan-eval",
            )
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
    """Compact, length-capped JSON rendering suitable for a transcript line."""
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


@solver
def koan_solver(
    timeout: int = DEFAULT_TIMEOUT,
) -> Solver:
    """Black-box koan eval solver.

    Starts koan's HTTP server in-process with yolo=True, submits the task
    description, waits for the workflow to complete, then harvests per-phase
    data from the event log as the task output.

    Workflow and directed_phases are read from Sample metadata populated by
    load_dataset. This keeps the solver agnostic of case files while honoring
    the data-driven model -- case files are the source of truth.
    """

    async def solve(state: TaskState, generate) -> TaskState:
        import uvicorn
        from koan.config import load_koan_config
        from koan.state import AppState
        from koan.web.app import create_app

        from evals.harvest import harvest_run

        snapshot_path = Path(state.metadata["snapshot_path"])

        with tempfile.TemporaryDirectory() as project_tmp:
            if snapshot_path.exists():
                with tarfile.open(snapshot_path, "r:gz") as tar:
                    tar.extractall(project_tmp)

            # Read workflow and directed_phases from Sample metadata so the
            # solver stays agnostic of case files -- they are injected by
            # load_dataset and are the single source of truth for a run.
            workflow = state.metadata.get("workflow", "plan")
            directed_phases = state.metadata.get("directed_phases") or None

            app_state = AppState()
            app_state.config = await load_koan_config()
            app_state.project_dir = project_tmp
            app_state.open_browser = False
            # yolo=True makes koan_yield and koan_ask_question auto-respond,
            # removing all human-in-the-loop gates without needing an SSE loop.
            app_state.yolo = True
            # directed_phases steers koan_yield auto-responses toward the next
            # phase in the list instead of picking from suggestions.
            app_state.directed_phases = directed_phases
            app = create_app(app_state)

            port = _find_free_port()
            # AppState.port must match the uvicorn bind port because
            # mcp-config.json (which tells the spawned orchestrator CLI how
            # to reach the driver) is built from app_state.port at spawn
            # time. A mismatch means the orchestrator cannot register the
            # koan_* tools and spends minutes flailing with curl/lsof before
            # finally discovering the real port on its own.
            app_state.port = port
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
                        json={"task": state.input, "profile": "balanced", "workflow": workflow},
                    )
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"/api/start-run failed: {resp.status_code} {resp.text}"
                    )
                # Validate directed_phases after api_start_run so app_state.workflow
                # is already resolved -- workflow.available_phases is not accessible
                # at solver construction time.
                if directed_phases is not None and app_state.workflow is not None:
                    _validate_directed_phases(
                        directed_phases,
                        app_state.workflow.available_phases,
                    )
                try:
                    await _wait_for_completion(app_state, timeout=timeout)
                except (asyncio.TimeoutError, TimeoutError):
                    pass  # harvest whatever exists even if we timed out
            finally:
                # Harvest before the server task is awaited to cleanup, so
                # whatever state the projection has at cancel/timeout time is
                # still captured. app_state is live regardless of server state.
                try:
                    harvest = harvest_run(app_state)
                except Exception as exc:
                    harvest = {
                        "phase_order": [],
                        "phase_summaries": {},
                        "tool_calls_by_phase": {},
                        "artifacts_by_phase": {},
                        "final_projection": {},
                        "_harvest_error": repr(exc),
                    }
                state.metadata["harvest"] = harvest
                state.metadata["artifacts"] = harvest.get("artifacts_by_phase", {})
                content = "\n\n---\n\n".join(
                    f"# {path}\n\n{c}"
                    for phase_artifacts in harvest.get("artifacts_by_phase", {}).values()
                    for path, c in phase_artifacts.get("all_present", {}).items()
                )
                state.output = ModelOutput.from_content("koan-solver", content)
                server.should_exit = True
                await server_task
            return state

    return solve
