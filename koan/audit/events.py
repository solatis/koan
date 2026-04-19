# Audit event type definitions -- discriminated union of all event kinds.
# Python port of src/planner/lib/audit-events.ts.
# No I/O, no side effects -- pure type definitions.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


# -- Event types --------------------------------------------------------------

@dataclass(kw_only=True)
class PhaseStartEvent:
    kind: Literal["phase_start"] = "phase_start"
    ts: str = ""
    seq: int = 0
    phase: str = ""
    role: str = ""
    model: str | None = None
    total_steps: int = 0


@dataclass(kw_only=True)
class StepTransitionEvent:
    kind: Literal["step_transition"] = "step_transition"
    ts: str = ""
    seq: int = 0
    step: int = 0
    name: str = ""
    total_steps: int = 0


@dataclass(kw_only=True)
class PhaseEndEvent:
    kind: Literal["phase_end"] = "phase_end"
    ts: str = ""
    seq: int = 0
    outcome: str = ""
    detail: str | None = None


@dataclass(kw_only=True)
class HeartbeatEvent:
    kind: Literal["heartbeat"] = "heartbeat"
    ts: str = ""
    seq: int = 0


@dataclass(kw_only=True)
class UsageEvent:
    kind: Literal["usage"] = "usage"
    ts: str = ""
    seq: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass(kw_only=True)
class ThinkingEvent:
    kind: Literal["thinking"] = "thinking"
    ts: str = ""
    seq: int = 0
    text: str = ""
    chars: int = 0


@dataclass(kw_only=True)
class ToolCallEvent:
    kind: Literal["tool_call"] = "tool_call"
    ts: str = ""
    seq: int = 0
    tool_call_id: str = ""
    tool: str = ""
    input: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class ToolResultEvent:
    kind: Literal["tool_result"] = "tool_result"
    ts: str = ""
    seq: int = 0
    tool_call_id: str = ""
    tool: str = ""
    error: bool = False
    lines: int | None = None
    chars: int | None = None
    koan_response: list[str] | None = None


@dataclass(kw_only=True)
class RunnerDiagnosticEvent:
    kind: Literal["runner_diagnostic"] = "runner_diagnostic"
    ts: str = ""
    seq: int = 0
    code: str = ""
    runner: str = ""
    stage: str = ""
    message: str = ""
    details: dict | None = None


AuditEvent = Union[
    PhaseStartEvent,
    StepTransitionEvent,
    PhaseEndEvent,
    HeartbeatEvent,
    UsageEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
    RunnerDiagnosticEvent,
]

# Fatal diagnostic codes that force status to "failed".
FATAL_DIAGNOSTIC_CODES = frozenset({
    "mcp_inject_failed",
    "bootstrap_failure",
})


# -- Projection ---------------------------------------------------------------

@dataclass
class Projection:
    role: str = ""
    phase: str = ""
    model: str | None = None
    status: str = "running"
    step: int = 0
    total_steps: int = 0
    step_name: str = ""
    last_action: str | None = None
    current_tool_call_id: str | None = None
    updated_at: str = ""
    event_count: int = 0
    error: str | None = None
    diagnostic: dict | None = None
    completion_summary: str | None = None
    tokens_sent: int = 0
    tokens_received: int = 0
    last_tool_result_at: str | None = None
