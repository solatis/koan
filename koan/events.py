# Event payload builders -- bridges koan domain types into projection event payloads.
# Imports AgentState, RunnerDiagnostic, list_artifacts, etc.
# koan/projections.py does NOT import from here.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runners.base import RunnerDiagnostic
    from .state import AgentState


def build_run_started(
    profile: str,
    installations: dict[str, str],
    scout_concurrency: int,
) -> dict:
    return {
        "profile": profile,
        "installations": installations,
        "scout_concurrency": scout_concurrency,
    }


def build_workflow_selected(workflow: str) -> dict:
    """Build workflow_selected event payload."""
    return {"workflow": workflow}


def build_agent_spawned(agent: AgentState) -> dict:
    return {
        "agent_id": agent.agent_id,
        "role": agent.role,
        "label": agent.label,
        "model": agent.model,
        "is_primary": agent.is_primary,
        "started_at_ms": int(agent.started_at.timestamp() * 1000),
    }


def build_scout_queued(scout_id: str, label: str, model: str | None = None) -> dict:
    return {
        "scout_id": scout_id,
        "label": label,
        "model": model,
    }


def build_agent_exited(
    exit_code: int,
    error: str | None = None,
    usage: dict | None = None,
) -> dict:
    result: dict = {"exit_code": exit_code}
    if error is not None:
        result["error"] = error
    if usage is not None:
        result["usage"] = usage
    return result


def build_agent_spawn_failed(role: str, diagnostic: RunnerDiagnostic) -> dict:
    return {
        "role": role,
        "error_code": diagnostic.code,
        "message": diagnostic.message,
        "details": diagnostic.details,
    }


def build_step_advanced(
    step: int,
    step_name: str,
    usage: dict | None = None,
    total_steps: int | None = None,
) -> dict:
    result: dict = {"step": step, "step_name": step_name}
    if usage is not None:
        result["usage"] = usage
    if total_steps is not None:
        result["total_steps"] = total_steps
    return result


def build_tool_called(
    call_id: str,
    tool: str,
    args: dict | str,
    summary: str = "",
) -> dict:
    return {
        "call_id": call_id,
        "tool": tool,
        "args": args,
        "summary": summary,
    }


def build_tool_started(call_id: str, tool: str) -> dict:
    return {"call_id": call_id, "tool": tool}


def build_tool_stopped(call_id: str, tool: str, summary: str = "") -> dict:
    payload: dict = {"call_id": call_id, "tool": tool}
    if summary:
        payload["summary"] = summary
    return payload


# -- Typed tool event builders (recognized tools with extracted metadata) -----

def build_tool_read(call_id: str, file: str, lines: str = "", ts_ms: int = 0) -> dict:
    return {
        "call_id": call_id, "tool": "read", "file": file, "lines": lines,
        "ts_ms": ts_ms,
    }


def build_tool_write(call_id: str, file: str) -> dict:
    return {"call_id": call_id, "tool": "write", "file": file}


def build_tool_edit(call_id: str, file: str) -> dict:
    return {"call_id": call_id, "tool": "edit", "file": file}


def build_tool_bash(call_id: str, command: str) -> dict:
    return {"call_id": call_id, "tool": "bash", "command": command}


def build_tool_grep(call_id: str, pattern: str, ts_ms: int = 0) -> dict:
    return {
        "call_id": call_id, "tool": "grep", "pattern": pattern,
        "ts_ms": ts_ms,
    }


def build_tool_ls(call_id: str, path: str, ts_ms: int = 0) -> dict:
    return {
        "call_id": call_id, "tool": "ls", "path": path,
        "ts_ms": ts_ms,
    }


def build_tool_completed(
    call_id: str,
    tool: str,
    result: str | None = None,
    ts_ms: int = 0,
) -> dict:
    payload: dict = {"call_id": call_id, "tool": tool, "ts_ms": ts_ms}
    if result is not None:
        payload["result"] = result
    return payload


def build_tool_result_captured(
    call_id: str,
    tool: str,
    metrics: dict | None = None,
) -> dict:
    """Build a tool_result_captured event.

    Emitted by the runner layer after it has parsed a tool_result block from
    a user message in the model's stream. `metrics` is a tool-family-specific
    dict that the fold attaches to the matching aggregate child. When the
    runner parser could not interpret the result, metrics is None and the
    fold leaves the child's metric fields unchanged.
    """
    payload: dict = {"call_id": call_id, "tool": tool}
    if metrics is not None:
        payload["metrics"] = metrics
    return payload


def build_artifact_diff(
    old: dict[str, dict],
    new_artifacts: list[dict],
) -> list[tuple[str, dict]]:
    """Compare old artifacts dict (from projection) with new list from list_artifacts().

    Returns list of (event_type, payload) tuples for created/modified/removed entries.
    modified_at is converted from float seconds to int milliseconds.
    """
    events: list[tuple[str, dict]] = []

    # Build new dict keyed by path, converting modified_at to ms
    new_by_path: dict[str, dict] = {}
    for a in new_artifacts:
        path = a["path"]
        new_by_path[path] = {
            "path": path,
            "size": a["size"],
            "modified_at": int(a["modified_at"] * 1000),
        }

    # Created or modified
    for path, new_entry in new_by_path.items():
        if path not in old:
            events.append(("artifact_created", new_entry))
        elif (
            old[path].get("modified_at") != new_entry["modified_at"]
            or old[path].get("size") != new_entry["size"]
        ):
            events.append(("artifact_modified", new_entry))

    # Removed
    for path in old:
        if path not in new_by_path:
            events.append(("artifact_removed", {"path": path}))

    return events


def build_questions_asked(token: str, questions: list) -> dict:
    return {"token": token, "questions": questions}


def build_questions_answered(
    token: str,
    answers: list | None = None,
    cancelled: bool = False,
) -> dict:
    result: dict = {"token": token, "cancelled": cancelled}
    if answers is not None:
        result["answers"] = answers
    return result


def build_yield_started(suggestions: list[dict]) -> dict:
    """Build yield_started event payload.

    Args:
        suggestions: List of {id, label, command} dicts — the structured
                     options the orchestrator presents at a yield point.
    """
    return {"suggestions": suggestions}


def build_phase_summary_captured(phase: str, summary: str) -> dict:
    """Build phase_summary_captured event payload.

    Carries only phase + summary. agent_id is passed separately at push_event
    time for audit; the fold reads only phase and summary (run-scoped state).
    """
    return {"phase": phase, "summary": summary}


# -- Configuration event builders ---------------------------------------------

def build_probe_completed(results: dict[str, bool]) -> dict:
    """Build probe_completed payload.

    Args:
        results: mapping of installation alias → available (bool).
    """
    return {"results": results}


def build_installation_created(
    alias: str, runner_type: str, binary: str, extra_args: list[str],
) -> dict:
    return {
        "alias": alias,
        "runner_type": runner_type,
        "binary": binary,
        "extra_args": extra_args,
    }


def build_installation_modified(
    alias: str, runner_type: str, binary: str, extra_args: list[str],
) -> dict:
    return {
        "alias": alias,
        "runner_type": runner_type,
        "binary": binary,
        "extra_args": extra_args,
    }


def build_installation_removed(alias: str) -> dict:
    return {"alias": alias}


def build_profile_created(name: str, read_only: bool, tiers: dict) -> dict:
    return {"name": name, "read_only": read_only, "tiers": tiers}


def build_profile_modified(name: str, read_only: bool, tiers: dict) -> dict:
    return {"name": name, "read_only": read_only, "tiers": tiers}


def build_profile_removed(name: str) -> dict:
    return {"name": name}


def build_default_profile_changed(name: str) -> dict:
    return {"name": name}


def build_steering_queued(content: str) -> dict:
    return {"content": content}


def build_steering_delivered(count: int) -> dict:
    return {"count": count}


def build_default_scout_concurrency_changed(value: int) -> dict:
    return {"value": value}
