# Async probe for installed coding-agent runners.
# Checks binary availability, auth status, and version for each runner.
# All probes run concurrently via asyncio.gather; failures never propagate.

import asyncio
import json
import shutil
from dataclasses import dataclass, field

from .types import ModelInfo

PROBE_TIMEOUT_SECONDS: int = 15


@dataclass
class ProbeResult:
    runner_type: str
    available: bool
    binary_path: str | None = None
    version: str | None = None
    models: list[ModelInfo] = field(default_factory=list)


async def _run_cmd(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT_SECONDS)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except OSError:
            pass
        return (-1, "", "")
    except OSError:
        return (-1, "", "")


async def _probe_claude() -> ProbeResult:
    binary = shutil.which("claude")
    if binary is None:
        return ProbeResult(runner_type="claude", available=False)

    rc, out, _ = await _run_cmd(["claude", "auth", "status"])
    if rc != 0:
        return ProbeResult(runner_type="claude", available=False, binary_path=binary)
    try:
        data = json.loads(out)
        if not data.get("loggedIn"):
            return ProbeResult(runner_type="claude", available=False, binary_path=binary)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return ProbeResult(runner_type="claude", available=False, binary_path=binary)

    rc_v, out_v, _ = await _run_cmd(["claude", "--version"])
    if rc_v != 0:
        return ProbeResult(runner_type="claude", available=False, binary_path=binary)

    models: list[ModelInfo] = []
    try:
        from .runners.claude import ClaudeRunner
        models = ClaudeRunner(subagent_dir="").list_models(binary)
    except Exception:
        pass

    return ProbeResult(runner_type="claude", available=True, binary_path=binary, version=out_v.strip(), models=models)


async def _probe_codex() -> ProbeResult:
    binary = shutil.which("codex")
    if binary is None:
        return ProbeResult(runner_type="codex", available=False)

    rc, out, err = await _run_cmd(["codex", "login", "status"])
    combined = out + err
    if rc != 0 or "Logged in" not in combined:
        return ProbeResult(runner_type="codex", available=False, binary_path=binary)

    rc_v, out_v, _ = await _run_cmd(["codex", "--version"])
    if rc_v != 0:
        return ProbeResult(runner_type="codex", available=False, binary_path=binary)

    models: list[ModelInfo] = []
    try:
        from .runners.codex import CodexRunner
        models = CodexRunner().list_models(binary)
    except Exception:
        pass

    return ProbeResult(runner_type="codex", available=True, binary_path=binary, version=out_v.strip(), models=models)


async def _probe_gemini() -> ProbeResult:
    binary = shutil.which("gemini")
    if binary is None:
        return ProbeResult(runner_type="gemini", available=False)

    rc, out, _ = await _run_cmd(["gemini", "--version"])
    version = out.strip() if rc == 0 else None

    # NOTE: gemini CLI has no lightweight auth-status command (unlike claude
    # and codex).  We can only verify the binary exists and runs.  If the
    # user has no Gemini subscription the balanced profile will still list
    # gemini, but the run will fail at spawn time with a clear error.
    available = rc == 0
    models: list[ModelInfo] = []
    if available:
        try:
            from .runners.gemini import GeminiRunner
            models = GeminiRunner(subagent_dir="").list_models(binary)
        except Exception:
            pass

    return ProbeResult(
        runner_type="gemini",
        available=available,
        binary_path=binary,
        version=version,
        models=models,
    )


async def probe_all_runners() -> list[ProbeResult]:
    try:
        results = await asyncio.gather(
            _probe_claude(),
            _probe_codex(),
            _probe_gemini(),
        )
        return list(results)
    except Exception:
        return [
            ProbeResult(runner_type="claude", available=False),
            ProbeResult(runner_type="codex", available=False),
            ProbeResult(runner_type="gemini", available=False),
        ]
