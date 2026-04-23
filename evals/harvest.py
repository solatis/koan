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
from pathlib import Path
from typing import Any

from koan.state import AppState


log = logging.getLogger("koan.evals.harvest")


def harvest_run(app_state: AppState) -> dict[str, Any]:
    """Extract per-phase data from app_state after the workflow completes."""
    store = app_state.projection_store
    run_dir = Path(app_state.run.run_dir) if app_state.run.run_dir else None
    summaries = (
        store.projection.run.phase_summaries
        if store.projection.run else {}
    )
    phase_order = _phase_order(store.events)
    tool_calls_by_phase = _bucket_tool_calls(store.events)
    artifacts_by_phase = _bucket_artifacts(store.events, run_dir)
    result = {
        "phase_order": phase_order,
        "phase_summaries": dict(summaries),
        "tool_calls_by_phase": tool_calls_by_phase,
        "artifacts_by_phase": artifacts_by_phase,
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
    for phase in phase_order:
        summary = h["phase_summaries"].get(phase, "")
        tools = h["tool_calls_by_phase"].get(phase, [])
        arts = h["artifacts_by_phase"].get(phase, {})
        created = arts.get("created", {})
        modified = arts.get("modified", {})
        questions = [t for t in tools if t["tool"] == "koan_ask_question"]
        log.info(
            "phase=%s summary_chars=%d tool_calls=%d questions=%d "
            "artifacts_created=%d artifacts_modified=%d",
            phase, len(summary), len(tools), len(questions),
            len(created), len(modified),
        )
        if summary:
            log.info("phase=%s summary: %s", phase, _truncate(summary, 800))
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


def _normalize_tool_event(ev) -> dict | None:
    """Normalize any tool event into {tool, args, ts}. Returns None if not a tool event."""
    p = ev.payload
    et = ev.event_type
    if et == "tool_called":
        tool = p.get("tool", "")
        return {"tool": tool, "args": p.get("args", {}), "ts": ev.timestamp} if tool else None
    if et == "tool_read":
        return {"tool": "read", "args": {"file": p.get("file", ""), "lines": p.get("lines", "")}, "ts": ev.timestamp}
    if et == "tool_bash":
        return {"tool": "bash", "args": {"command": p.get("command", "")}, "ts": ev.timestamp}
    if et == "tool_grep":
        return {"tool": "grep", "args": {"pattern": p.get("pattern", "")}, "ts": ev.timestamp}
    if et == "tool_ls":
        return {"tool": "ls", "args": {"path": p.get("path", "")}, "ts": ev.timestamp}
    if et == "tool_write":
        return {"tool": "write", "args": {"file": p.get("file", "")}, "ts": ev.timestamp}
    if et == "tool_edit":
        return {"tool": "edit", "args": {"file": p.get("file", "")}, "ts": ev.timestamp}
    return None


def _bucket_tool_calls(events: list) -> dict[str, list[dict]]:
    """Walk events; group all tool calls (koan MCP + built-in) by active phase."""
    buckets: dict[str, list[dict]] = {}
    current_phase = ""
    for ev in events:
        if ev.event_type == "phase_started":
            current_phase = ev.payload.get("phase", current_phase)
            buckets.setdefault(current_phase, [])
            continue
        entry = _normalize_tool_event(ev)
        if entry is not None:
            buckets.setdefault(current_phase, []).append(entry)
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
