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
import socket
import tarfile
import tempfile
from pathlib import Path

import httpx
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Solver, TaskState, solver


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
    """Poll the in-process projection until run.completion is set or timeout."""
    # Direct projection polling is acceptable here because the solver runs
    # in-process and shares the same AppState / ProjectionStore as uvicorn.
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        run = app_state.projection_store.projection.run
        if run is not None and run.completion is not None:
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("workflow did not complete within timeout")


@solver
def koan_solver(timeout: int = DEFAULT_TIMEOUT) -> Solver:
    """Black-box koan eval solver.

    Starts koan's HTTP server in-process with yolo=True, submits the task
    description, waits for the workflow to complete, then harvests per-phase
    data from the event log as the task output.
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

            app_state = AppState()
            app_state.config = await load_koan_config()
            app_state.project_dir = project_tmp
            app_state.open_browser = False
            # yolo=True makes koan_yield and koan_ask_question auto-respond,
            # removing all human-in-the-loop gates without needing an SSE loop.
            app_state.yolo = True
            app = create_app(app_state)

            port = _find_free_port()
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
                    await client.post(
                        f"{base_url}/api/start-run",
                        json={"task": state.input, "profile": "balanced"},
                    )
                try:
                    await _wait_for_completion(app_state, timeout=timeout)
                except (asyncio.TimeoutError, TimeoutError):
                    pass  # harvest whatever exists even if we timed out
            finally:
                server.should_exit = True
                await server_task

            harvest = harvest_run(app_state)
            state.metadata["harvest"] = harvest
            state.metadata["artifacts"] = harvest["artifacts_by_phase"]
            # Populate state.output for backward compatibility with tooling that
            # reads concatenated artifact content from the solver output.
            content = "\n\n---\n\n".join(
                f"# {path}\n\n{c}"
                for phase_artifacts in harvest["artifacts_by_phase"].values()
                for path, c in phase_artifacts["all_present"].items()
            )
            state.output = ModelOutput.from_content("koan-solver", content)
            return state

    return solve
