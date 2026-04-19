# evals/solver.py
# Inspect AI Solver: runs koan as an in-process black-box.
#
# The solver starts koan's HTTP server via uvicorn, POSTs a start-run
# request, then monitors the /events SSE stream to detect interactive
# gates and respond with a fixed "use your best judgment" message.
#
# SSE protocol note: koan's SSE stream emits only "snapshot" and "patch"
# event types (RFC 6902 JSON Patch on the camelCase projection). The
# event names yield_started / questions_asked / workflow_completed are
# internal projection events that change projection state, not SSE event
# types. Gates are detected by inspecting patch operations on:
#   /run/activeYield  -> orchestrator blocked in koan_yield
#   /run/focus        -> orchestrator waiting for koan_ask_question answers
#   /run/completion   -> workflow finished
#
# Per-phase and per-step resume via --resume are explicitly deferred.
# Design direction: each phase boundary could be treated as a fixture
# checkpoint, using the projection version + run-state.json as the resume
# anchor. Not implemented until the full-run eval is proven stable.

from __future__ import annotations

import asyncio
import json
import socket
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import httpx
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Solver, TaskState, solver


GATE_RESPONSE = (
    "Please use your best judgment and pick whichever option you think is best."
)
DEFAULT_TIMEOUT = 1800


def _find_free_port() -> int:
    """Bind to port 0 to get an OS-assigned free port, then release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_server(base_url: str, poll_interval: float = 0.1, max_wait: float = 30.0) -> None:
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


def _active_yield_from_patch(ops: list[dict]) -> bool:
    """Return True if any patch op sets /run/activeYield to a non-null value."""
    for op in ops:
        path = op.get("path", "")
        if path == "/run/activeYield" or path.startswith("/run/activeYield/"):
            if op.get("op") in ("add", "replace") and op.get("value") is not None:
                return True
    return False


def _question_focus_from_patch(ops: list[dict]) -> dict | None:
    """Return the QuestionFocus value if a patch op sets /run/focus to type=question."""
    for op in ops:
        path = op.get("path", "")
        if path == "/run/focus" and op.get("op") in ("add", "replace"):
            value = op.get("value")
            if isinstance(value, dict) and value.get("type") == "question":
                return value
    return None


def _completion_from_patch(ops: list[dict]) -> bool:
    """Return True if any patch op sets /run/completion to a non-null value."""
    for op in ops:
        path = op.get("path", "")
        if path == "/run/completion" or path.startswith("/run/completion/"):
            if op.get("op") in ("add", "replace") and op.get("value") is not None:
                return True
    return False


def _active_yield_from_snapshot(state: dict) -> bool:
    run = state.get("run") or {}
    return run.get("activeYield") is not None


def _question_focus_from_snapshot(state: dict) -> dict | None:
    run = state.get("run") or {}
    focus = run.get("focus")
    if isinstance(focus, dict) and focus.get("type") == "question":
        return focus
    return None


def _completion_from_snapshot(state: dict) -> bool:
    run = state.get("run") or {}
    return run.get("completion") is not None


async def _post_chat(base_url: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(f"{base_url}/api/chat", json={"message": GATE_RESPONSE})


async def _post_answer(base_url: str, token: str, questions: list) -> None:
    answers = [
        {
            "question_index": i,
            "value": "other",
            "free_text": GATE_RESPONSE,
        }
        for i in range(len(questions))
    ]
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"{base_url}/api/answer",
            json={"token": token, "answers": answers},
        )


async def _sse_drive_loop(base_url: str) -> None:
    """Subscribe to the SSE stream and respond to interactive gates until workflow completes."""
    # httpx stream() keeps the connection open; we parse SSE lines manually.
    # Timeout=None on the outer client since the run may take 30+ minutes.
    async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
        async with client.stream("GET", f"{base_url}/events") as resp:
            current_event: str | None = None
            async for raw_line in resp.aiter_lines():
                line = raw_line.rstrip("\r")
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:") and current_event is not None:
                    try:
                        data: Any = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue

                    if current_event == "snapshot":
                        state = data.get("state", {})
                        if _completion_from_snapshot(state):
                            return
                        if _active_yield_from_snapshot(state):
                            await _post_chat(base_url)
                        else:
                            focus = _question_focus_from_snapshot(state)
                            if focus is not None:
                                await _post_answer(
                                    base_url,
                                    focus.get("token", ""),
                                    focus.get("questions", []),
                                )

                    elif current_event == "patch":
                        ops: list[dict] = data.get("patch", [])
                        if _completion_from_patch(ops):
                            return
                        if _active_yield_from_patch(ops):
                            await _post_chat(base_url)
                        else:
                            focus = _question_focus_from_patch(ops)
                            if focus is not None:
                                await _post_answer(
                                    base_url,
                                    focus.get("token", ""),
                                    focus.get("questions", []),
                                )
                elif line == "":
                    current_event = None


def _collect_artifacts(run_dir: Path) -> dict[str, str]:
    """Read all .md files from the run directory, keyed by filename."""
    result = {}
    for p in sorted(run_dir.glob("*.md")):
        try:
            result[p.name] = p.read_text(encoding="utf-8")
        except OSError:
            pass
    return result


@solver
def koan_solver(timeout: int = DEFAULT_TIMEOUT) -> Solver:
    """Black-box koan eval solver.

    Starts koan's HTTP server in-process, submits the task description,
    responds to all interactive gates with a fixed "use your best judgment"
    message, and harvests the final run artifacts as the task output.
    """

    async def solve(state: TaskState, generate) -> TaskState:
        import uvicorn
        from koan.config import load_koan_config
        from koan.state import AppState
        from koan.web.app import create_app

        snapshot_path = Path(state.metadata["snapshot_path"])

        with tempfile.TemporaryDirectory() as project_tmp:
            # Extract the project snapshot so the orchestrator sees it as the
            # project root. If no snapshot exists yet (no fixtures committed),
            # leave project_tmp empty and koan will operate on an empty dir.
            if snapshot_path.exists():
                with tarfile.open(snapshot_path, "r:gz") as tar:
                    tar.extractall(project_tmp)

            app_state = AppState()
            # Load the user's real config so probe_results finds installed
            # agents. Without this, /api/start-run fails with no_runners.
            app_state.config = await load_koan_config()
            # Point koan at the extracted snapshot rather than the solver's
            # CWD. AppState.project_dir flows through task.json to every
            # spawned subagent as its spawn cwd.
            app_state.project_dir = project_tmp
            # Don't try to open a browser during headless evals.
            app_state.open_browser = False
            app = create_app(app_state)

            port = _find_free_port()
            uv_config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
            )
            server = uvicorn.Server(uv_config)
            # Run uvicorn in a background asyncio task so we can drive it
            # concurrently with the SSE loop.
            server_task = asyncio.create_task(server.serve())

            base_url = f"http://127.0.0.1:{port}"
            await _wait_for_server(base_url)

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await client.post(
                        f"{base_url}/api/start-run",
                        json={"task": state.input, "profile": "balanced"},
                    )

                await asyncio.wait_for(_sse_drive_loop(base_url), timeout=timeout)

            except asyncio.TimeoutError:
                pass  # harvest whatever artifacts exist after timeout
            finally:
                server.should_exit = True
                await server_task

            run_dir = app_state.run_dir
            artifacts = _collect_artifacts(Path(run_dir)) if run_dir else {}

        content = "\n\n---\n\n".join(artifacts.values()) if artifacts else ""
        # Use ModelOutput (TaskOutput does not exist in inspect_ai 0.3+).
        state.output = ModelOutput.from_content("koan-solver", content)
        state.metadata["artifacts"] = artifacts
        return state

    return solve
