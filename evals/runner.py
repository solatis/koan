# evals/runner.py
# Black-box koan runner: spawns koan as a subprocess and returns a harvest dict.
#
# run_koan(case) starts `uv run koan run` as an external process against the
# live codebase, submits the task via HTTP, polls /api/run-status for
# completion, then fetches the harvest dict from /api/eval-harvest (which runs
# harvest_run() in-process against the live ProjectionStore.events).
#
# The previous SSE-reconstruction approach was deleted because ProjectionStore
# .events is memory-only (not persisted to disk), so the harvest must execute
# inside the server process. Fetching via HTTP is the only correct path.

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from pathlib import Path

import httpx

from evals.cases import Case

logging.getLogger("httpx").setLevel(logging.WARNING)


DEFAULT_TIMEOUT = 1800
PROJECT_DIR = str(Path(__file__).resolve().parents[1])

log = logging.getLogger("koan.evals.runner")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_server(base_url: str, max_wait: float = 60.0) -> None:
    deadline = asyncio.get_event_loop().time() + max_wait
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(f"{base_url}/api/probe", timeout=2.0)
                if r.status_code < 500:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)
    raise TimeoutError(f"koan server did not start within {max_wait}s")


async def _poll_for_completion(base_url: str, timeout: float) -> None:
    """Poll /api/run-status every 5 seconds until workflow completes or timeout.

    Replaced the old SSE snapshot approach: the snapshot only carries the
    projection wire format which lacks phase attribution for artifacts and
    has empty tool_calls. The /api/run-status endpoint is a lightweight
    alternative that drives the poll loop without doing any harvest work.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    last_phase = None
    start = loop.time()
    async with httpx.AsyncClient(timeout=15.0) as client:
        while loop.time() < deadline:
            try:
                r = await client.get(f"{base_url}/api/run-status")
                r.raise_for_status()
                data = r.json()
            except httpx.TransportError:
                await asyncio.sleep(5.0)
                continue
            phase = data.get("phase") or ""
            if phase != last_phase:
                log.info("t=%6.1fs  phase -> %s", loop.time() - start, phase)
                last_phase = phase
            if data.get("completion") is not None:
                log.info("t=%6.1fs  workflow completed", loop.time() - start)
                return
            await asyncio.sleep(5.0)
    log.info("workflow timed out after %ds", int(timeout))


async def _fetch_harvest(client: httpx.AsyncClient, base_url: str) -> dict:
    """Fetch the harvest dict from the in-process /api/eval-harvest endpoint.

    raise_for_status() is intentional: a 500 from the harvest endpoint means
    harvest_run() threw, which is a setup error that must surface rather than
    silently producing an empty harvest dict.
    """
    r = await client.get(f"{base_url}/api/eval-harvest", timeout=30.0)
    r.raise_for_status()
    return r.json()


async def run_koan(case: Case, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Spawn koan as a subprocess and return the harvest dict."""
    case_id = f"{case.fixture_id}/{case.task_id}/{case.case_id}"
    log.info("[%s] starting run_koan  workflow=%s directed=%s",
             case_id, case.workflow, case.directed_phases)

    directed_phases = list(case.directed_phases)
    workflow = case.workflow
    task_input = (case.task_dir / "task.md").read_text(encoding="utf-8").strip()
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    cmd = [
        sys.executable, "-m", "koan",
        "run",
        "--yolo",
        "--no-open",
        "--skip-build",
        "--port", str(port),
        "--log-level", "INFO",
        "--directed-phases", *directed_phases,
    ]
    log.info("[%s] spawning: %s", case_id, " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,
        cwd=PROJECT_DIR,
    )

    try:
        log.info("[%s] waiting for server on port %d (pid=%d)",
                 case_id, port, proc.pid)
        await _wait_for_server(base_url)
        log.info("[%s] server ready, posting /api/start-run", case_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/api/start-run",
                json={
                    "task": task_input,
                    "profile": "balanced",
                    "workflow": workflow,
                },
            )
        if resp.status_code >= 400:
            log.info("[%s] /api/start-run FAILED: %d %s",
                     case_id, resp.status_code, resp.text)
            raise RuntimeError(
                f"/api/start-run failed: {resp.status_code} {resp.text}"
            )
        log.info("[%s] /api/start-run OK, polling for completion (timeout=%ds)",
                 case_id, timeout)

        await _poll_for_completion(base_url, timeout)
        async with httpx.AsyncClient(timeout=30.0) as client:
            harvest = await _fetch_harvest(client, base_url)
        log.info(
            "[%s] harvest: phases=%s duration=%.1fs",
            case_id,
            harvest.get("phase_order", []),
            harvest.get("duration_s", 0.0),
        )
        return harvest

    finally:
        log.info("[%s] terminating koan server (pid=%d)", case_id, proc.pid)
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        log.info("[%s] server stopped", case_id)
