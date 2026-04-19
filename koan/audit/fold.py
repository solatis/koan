# Pure fold function -- reduces (Projection, AuditEvent) -> Projection.
# Python port of src/planner/lib/audit-fold.ts.
# No I/O, no mutation of inputs.

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

from .events import FATAL_DIAGNOSTIC_CODES, Projection

if TYPE_CHECKING:
    from .events import AuditEvent


# -- Helpers -------------------------------------------------------------------

FILE_TOOLS = frozenset({"read", "edit", "write"})


def format_chars(chars: int) -> str:
    if chars < 1000:
        return f"{chars}c"
    k = chars / 1000
    if k >= 10:
        return f"{round(k)}k"
    return f"{k:.1f}k"


def _summarize_call(tool: str, inp: dict) -> str:
    if tool in FILE_TOOLS:
        return f"{tool} {inp.get('path', '')}"
    if tool == "bash":
        cmd = inp.get("command", "")
        first_word = cmd.strip().split()[0] if cmd.strip() else ""
        return f"bash {first_word}"
    return tool


def _summarize_result(tool: str, lines: int | None, chars: int | None) -> str:
    label = tool
    if lines is not None or chars is not None:
        label += f" -- {lines or 0}L/{format_chars(chars or 0)}"
    return label


# -- Fold ----------------------------------------------------------------------

def fold(s: Projection, e: AuditEvent) -> Projection:
    """Pure projection update -- one case per discriminated kind."""
    base = copy(s)
    base.updated_at = e.ts
    base.event_count = s.event_count + 1

    kind = e.kind

    if kind == "phase_start":
        base.role = e.role
        base.phase = e.phase
        base.model = e.model if e.model is not None else s.model
        base.status = "running"
        base.step = 0
        base.total_steps = e.total_steps
        base.step_name = ""
        base.last_action = None
        base.current_tool_call_id = None
        base.error = None
        base.completion_summary = None
        return base

    if kind == "step_transition":
        base.step = e.step
        base.total_steps = e.total_steps
        base.step_name = e.name
        return base

    if kind == "phase_end":
        base.status = e.outcome
        base.error = e.detail if e.detail else None
        base.current_tool_call_id = None
        return base

    if kind == "tool_call":
        base.last_action = _summarize_call(e.tool, e.input)
        base.current_tool_call_id = e.tool_call_id
        if e.tool == "koan_complete_step":
            thoughts = e.input.get("thoughts", "")
            if isinstance(thoughts, str) and thoughts:
                base.completion_summary = thoughts[:500]
        return base

    if kind == "tool_result":
        base.last_action = _summarize_result(e.tool, e.lines, e.chars)
        base.current_tool_call_id = None
        base.last_tool_result_at = e.ts
        return base

    if kind == "usage":
        base.tokens_sent = s.tokens_sent + e.input
        base.tokens_received = s.tokens_received + e.output
        return base

    if kind == "runner_diagnostic":
        base.last_action = e.message
        base.diagnostic = {
            "code": e.code,
            "runner": e.runner,
            "stage": e.stage,
            "message": e.message,
            "details": e.details,
        }
        if e.code in FATAL_DIAGNOSTIC_CODES:
            base.status = "failed"
            base.error = e.message
        return base

    # heartbeat, thinking -- just update timestamp and event_count
    return base
