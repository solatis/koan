# EventLog -- append-only audit trail with asyncio queue serialization.
# Python port of src/planner/lib/event-log.ts.
# Writes events.jsonl and state.json atomically to a subagent directory.

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles

from .events import Projection, RunnerDiagnosticEvent
from .fold import fold

if TYPE_CHECKING:
    from ..runners.base import RunnerDiagnostic


# -- Helpers -------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SENTINEL = object()

HEARTBEAT_INTERVAL = 10.0


# -- EventLog ------------------------------------------------------------------

class EventLog:
    def __init__(self, subagent_dir: str, role: str, phase: str, model: str | None = None):
        self._dir = subagent_dir
        self._events_path = str(Path(subagent_dir) / "events.jsonl")
        self._state_path = str(Path(subagent_dir) / "state.json")
        self._state_tmp_path = str(Path(subagent_dir) / "state.tmp.json")
        self._seq = 0
        self._projection = Projection(
            role=role,
            phase=phase,
            model=model,
            status="running",
            updated_at=_now(),
        )
        self._queue: asyncio.Queue = asyncio.Queue()
        self._consumer_task: asyncio.Task | None = None
        self._fd: Any = None
        self._heartbeat_task: asyncio.Task | None = None

    async def open(self) -> None:
        Path(self._dir).mkdir(parents=True, exist_ok=True)
        self._fd = await aiofiles.open(self._events_path, "a")
        await self._write_state()
        self._consumer_task = asyncio.create_task(self._consume())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.append({"kind": "heartbeat"})
        except asyncio.CancelledError:
            pass

    async def _consume(self) -> None:
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                self._queue.task_done()
                break
            try:
                await self._do_append(item)
            finally:
                self._queue.task_done()

    async def _do_append(self, partial: dict) -> None:
        if self._fd is None:
            raise RuntimeError("EventLog.append called before open()")

        partial["ts"] = _now()
        partial["seq"] = self._seq
        self._seq += 1

        line = json.dumps(partial, default=str) + "\n"
        await self._fd.write(line)
        await self._fd.flush()

        # Reconstruct as a typed event for fold.
        # fold() dispatches on kind and reads attributes directly.
        from . import events as ev
        kind = partial.get("kind", "")
        event_cls = _KIND_MAP.get(kind)
        if event_cls is not None:
            event = event_cls(**{k: v for k, v in partial.items() if k in event_cls.__dataclass_fields__})
        else:
            return

        self._projection = fold(self._projection, event)
        await self._write_state()

    async def append(self, partial: dict) -> None:
        await self._queue.put(partial)

    async def emit_phase_start(self, total_steps: int) -> None:
        await self.append({
            "kind": "phase_start",
            "phase": self._projection.phase,
            "role": self._projection.role,
            "model": self._projection.model,
            "total_steps": total_steps,
        })

    async def emit_step_transition(self, step: int, name: str, total_steps: int) -> None:
        await self.append({
            "kind": "step_transition",
            "step": step,
            "name": name,
            "total_steps": total_steps,
        })

    async def emit_phase_end(self, outcome: str, detail: str | None = None) -> None:
        await self.append({
            "kind": "phase_end",
            "outcome": outcome,
            "detail": detail,
        })

    async def emit_runner_diagnostic(self, diag: RunnerDiagnostic) -> None:
        await self.append({
            "kind": "runner_diagnostic",
            "code": diag.code,
            "runner": diag.runner,
            "stage": diag.stage,
            "message": diag.message,
            "details": diag.details,
        })

    async def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._consumer_task is not None:
            await self._queue.put(_SENTINEL)
            await self._consumer_task
            self._consumer_task = None

        if self._fd is not None:
            await self._fd.close()
            self._fd = None

    @property
    def state(self) -> Projection:
        return self._projection

    async def _write_state(self) -> None:
        data = asdict(self._projection)
        content = json.dumps(data, indent=2) + "\n"
        async with aiofiles.open(self._state_tmp_path, "w") as f:
            await f.write(content)
        os.rename(self._state_tmp_path, self._state_path)


# -- Kind -> event class map ---------------------------------------------------

from .events import (
    HeartbeatEvent,
    PhaseEndEvent,
    PhaseStartEvent,
    RunnerDiagnosticEvent,
    StepTransitionEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
)

_KIND_MAP: dict[str, type] = {
    "phase_start": PhaseStartEvent,
    "step_transition": StepTransitionEvent,
    "phase_end": PhaseEndEvent,
    "heartbeat": HeartbeatEvent,
    "usage": UsageEvent,
    "thinking": ThinkingEvent,
    "tool_call": ToolCallEvent,
    "tool_result": ToolResultEvent,
    "runner_diagnostic": RunnerDiagnosticEvent,
}
