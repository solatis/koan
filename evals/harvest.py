# evals/harvest.py
# Post-hoc extraction of per-phase data from a completed koan run.
#
# harvest_run walks ProjectionStore.events chronologically, using phase_started
# events as phase boundaries and bucketing all tool_called events (both koan MCP
# tools and built-in tools like Read, Grep, Bash) by the active phase. Content
# is read from disk at workflow completion -- see README for the known limitation
# on files modified in later phases.

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from koan.state import AppState


log = logging.getLogger("koan.evals.harvest")


def harvest_run(app_state: AppState) -> dict[str, Any]:
    """Extract per-phase data from app_state after the workflow completes."""
    store = app_state.projection_store
    run_dir = Path(app_state.run.run_dir) if app_state.run.run_dir else None
    phase_order = _phase_order(store.events)
    tool_calls_by_phase = _bucket_tool_calls(store.events)
    artifacts_by_phase = _bucket_artifacts(store.events, run_dir)
    duration_s = _compute_duration_s(store.events)
    token_cost = _compute_token_cost(store.projection.run)
    tool_call_count = _compute_tool_call_count(tool_calls_by_phase)
    result = {
        "phase_order": phase_order,
        "tool_calls_by_phase": tool_calls_by_phase,
        "artifacts_by_phase": artifacts_by_phase,
        "duration_s": duration_s,
        "token_cost": token_cost,
        "tool_call_count": tool_call_count,
    }
    _log_harvest(result)
    return result


def _log_harvest(h: dict[str, Any]) -> None:
    """Emit diagnostic logging.info lines describing harvested data.

    One block per phase: a one-line summary of counts, followed by the
    phase summary text (truncated), each koan_ask_question, and each
    artifact path + size. Useful for debugging without a frontend.
    """
    phase_order = h["phase_order"]
    log.info("harvest complete: phases=%s", phase_order or "(none)")
    tc = h.get("token_cost", {})
    log.info(
        "harvest programmatic: duration=%.1fs tokens=%d+%d tool_calls=%d",
        h.get("duration_s", 0.0),
        tc.get("input_tokens", 0),
        tc.get("output_tokens", 0),
        sum(h.get("tool_call_count", {}).values()),
    )
    for phase in phase_order:
        tools = h["tool_calls_by_phase"].get(phase, [])
        arts = h["artifacts_by_phase"].get(phase, {})
        created = arts.get("created", {})
        modified = arts.get("modified", {})
        questions = [t for t in tools if t["tool"] == "koan_ask_question"]
        log.info(
            "phase=%s tool_calls=%d questions=%d "
            "artifacts_created=%d artifacts_modified=%d",
            phase, len(tools), len(questions),
            len(created), len(modified),
        )
        for t in tools:
            args = _truncate(json.dumps(t.get("args", {}), default=str), 300)
            log.info("phase=%s tool=%s args=%s", phase, t.get("tool"), args)
        for path, content in sorted(created.items()):
            log.info("phase=%s created=%s (%d chars)", phase, path, len(content))
        for path, content in sorted(modified.items()):
            log.info("phase=%s modified=%s (%d chars)", phase, path, len(content))


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def _compute_duration_s(events: list) -> float:
    """Compute elapsed seconds between run_started and workflow_completed events.

    Returns 0.0 when either event is absent -- common during partial harvests
    or when the workflow has not yet completed.
    """
    start_ts: str | None = None
    end_ts: str | None = None
    for ev in events:
        if ev.event_type == "run_started" and start_ts is None:
            start_ts = ev.timestamp
        elif ev.event_type == "workflow_completed":
            end_ts = ev.timestamp
    if start_ts is None or end_ts is None:
        return 0.0
    try:
        t0 = datetime.fromisoformat(start_ts).timestamp()
        t1 = datetime.fromisoformat(end_ts).timestamp()
        return max(0.0, t1 - t0)
    except (ValueError, TypeError):
        return 0.0


def _compute_token_cost(run) -> dict[str, int]:
    """Sum input/output tokens across all orchestrator agents.

    Scouts and executors are excluded; only the primary orchestrator agent
    contributes. If the projection has no run (early harvest), returns zeros.
    """
    if run is None:
        return {"input_tokens": 0, "output_tokens": 0}
    total_in = 0
    total_out = 0
    for agent in run.agents.values():
        if agent.role != "orchestrator":
            continue
        conv = agent.conversation
        total_in += conv.input_tokens
        total_out += conv.output_tokens
    return {"input_tokens": total_in, "output_tokens": total_out}


def _compute_tool_call_count(tool_calls_by_phase: dict) -> dict[str, int]:
    """Aggregate per-phase tool call entries into a flat {tool: count} dict.

    Each entry in tool_calls_by_phase is already one call (not a batch),
    so this is a simple per-tool counter across all phases.
    """
    counts: dict[str, int] = {}
    for entries in tool_calls_by_phase.values():
        for entry in entries:
            tool = entry.get("tool", "")
            if tool:
                counts[tool] = counts.get(tool, 0) + 1
    return counts


def _phase_order(events: list) -> list[str]:
    """Return phase names in the order they first appeared as phase_started."""
    seen: list[str] = []
    for ev in events:
        if ev.event_type != "phase_started":
            continue
        phase = ev.payload.get("phase", "")
        if phase and phase not in seen:
            seen.append(phase)
    return seen


def _bucket_tool_calls(events: list) -> dict[str, list[dict]]:
    """Walk events; group all tool calls (koan MCP + built-in) by active phase.

    Uses a stateful walk over tool_request / tool_input_delta / tool_result
    events (M1 vocabulary). Phase is recorded at tool_request time so that
    long-blocking tools (e.g. koan_yield spanning a phase boundary) bucket
    into the phase that initiated them, not the phase when they returned.
    """
    buckets: dict[str, list[dict]] = {}
    current_phase = ""
    # call_id -> {tool, args, phase, ts}: accumulates until tool_result
    in_flight: dict[str, dict] = {}
    for ev in events:
        if ev.event_type == "phase_started":
            current_phase = ev.payload.get("phase", current_phase)
            buckets.setdefault(current_phase, [])
            continue
        cid = ev.payload.get("call_id", "")
        if not cid:
            continue
        if ev.event_type == "tool_request":
            tool = ev.payload.get("tool", "")
            if tool:
                in_flight[cid] = {
                    "tool": tool,
                    "args": {},
                    "phase": current_phase,
                    "ts": ev.timestamp,
                }
        elif ev.event_type == "tool_input_delta":
            if cid in in_flight:
                ti = ev.payload.get("tool_input")
                if isinstance(ti, dict):
                    in_flight[cid]["args"] = ti
        elif ev.event_type == "tool_result":
            rec = in_flight.pop(cid, None)
            if rec is not None:
                phase = rec.pop("phase", current_phase)
                buckets.setdefault(phase, []).append(rec)
    return buckets


def _bucket_artifacts(events: list, run_dir: Path | None) -> dict[str, dict]:
    """
    Returns {phase: {created: {path: content}, modified: {...}, all_present: {...}}}.

    Content is read from disk at workflow completion. Known limitation: files
    modified in later phases show final content, not per-phase content. This is
    acceptable for intake + plan-spec evaluation because intake produces no
    artifacts and plan-spec produces plan.md which the execute phase may later
    modify -- but execute is not in the initial eval scope.
    """
    # Track which paths were created/modified per phase and what is present
    # at each phase boundary, so we can materialize content at the end.
    buckets: dict[str, dict[str, set[str]]] = {}
    current_phase = ""
    all_present: set[str] = set()
    # Snapshot all_present at the end of each phase so per-phase all_present
    # reflects what existed when that phase concluded (not at workflow end).
    phase_end_snapshot: dict[str, set[str]] = {}

    for ev in events:
        if ev.event_type == "phase_started":
            if current_phase:
                phase_end_snapshot[current_phase] = set(all_present)
            current_phase = ev.payload.get("phase", current_phase)
            buckets.setdefault(current_phase, {
                "created": set(), "modified": set(),
            })
        elif ev.event_type == "artifact_created":
            path = ev.payload.get("path", "")
            if path:
                all_present.add(path)
                buckets.setdefault(current_phase, {"created": set(), "modified": set()})
                buckets[current_phase]["created"].add(path)
        elif ev.event_type == "artifact_modified":
            path = ev.payload.get("path", "")
            if path:
                all_present.add(path)
                buckets.setdefault(current_phase, {"created": set(), "modified": set()})
                buckets[current_phase]["modified"].add(path)
        elif ev.event_type == "artifact_removed":
            path = ev.payload.get("path", "")
            all_present.discard(path)

    # Snapshot the final phase boundary
    if current_phase:
        phase_end_snapshot[current_phase] = set(all_present)

    # Materialize content from disk (at workflow-completion time)
    result: dict[str, dict] = {}
    for phase, sets in buckets.items():
        result[phase] = {
            "created": _read_paths(sets["created"], run_dir),
            "modified": _read_paths(sets["modified"], run_dir),
            "all_present": _read_paths(
                phase_end_snapshot.get(phase, set()), run_dir,
            ),
        }
    return result


def _read_paths(paths: set[str], run_dir: Path | None) -> dict[str, str]:
    """Read file contents from run_dir; skip missing files silently."""
    if run_dir is None:
        return {}
    out: dict[str, str] = {}
    for p in sorted(paths):
        fp = run_dir / p
        try:
            out[p] = fp.read_text(encoding="utf-8")
        except OSError:
            pass
    return out
