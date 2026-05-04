# Event payload builders -- bridges koan domain types into projection event payloads.
# Imports AgentState, AgentDiagnostic, list_artifacts, etc.
# koan/projections.py does NOT import from here.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agents.base import AgentDiagnostic
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


def build_run_cleared() -> dict:
    # Empty payload: run_cleared carries no fields. Follows the same convention
    # as build_agents_cleared, build_memory_curation_cleared, build_reflect_cleared.
    return {}


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


def build_agents_cleared() -> dict:
    return {}


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


def build_agent_spawn_failed(role: str, diagnostic: AgentDiagnostic) -> dict:
    """Build the agent_spawn_failed projection event payload.

    Carries the role of the agent that failed to spawn, the diagnostic code,
    message, and any details. Used by koan.subagent.spawn_subagent and
    koan.agents.registry on resolution failure.
    """
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


# Legacy tool event builders removed in M1: the streaming stdout path is
# the single source of truth for tool lifecycle events. All callers were
# switched to build_tool_request / build_tool_input_delta / build_tool_result
# before these builders were deleted.


def build_tool_request(call_id: str, tool: str, tool_use_id: str = "") -> dict:
    """Build a tool_request event payload.

    Emitted when the streaming path first sees a tool invocation. tool_use_id is
    the LLM-assigned identifier used later to correlate with tool_result events.
    """
    payload: dict = {"call_id": call_id, "tool": tool}
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


def build_tool_input_delta(
    call_id: str,
    tool: str,
    tool_input: dict | None,
    delta: dict | str | None,
) -> dict:
    """Build a tool_input_delta event payload.

    tool_input is the latest aggregate of all received deltas (server-side
    running parse). delta is the just-arrived chunk; both are kept so consumers
    can choose between the complete-so-far view and the incremental view.
    """
    payload: dict = {"call_id": call_id, "tool": tool}
    if tool_input is not None:
        payload["tool_input"] = tool_input
    if delta is not None:
        payload["delta"] = delta
    return payload


def build_tool_result(
    call_id: str,
    tool: str,
    result: str | None = None,
    attachments: list[dict] | None = None,
    metrics: dict | None = None,
    ts_ms: int = 0,
) -> dict:
    """Build a tool_result event payload.

    The result event closes the lifecycle for one tool invocation. It carries the
    text result (for koan tools), an optional attachment manifest (extracted from
    stream content blocks), and optional metrics (for exploration tools).
    """
    payload: dict = {"call_id": call_id, "tool": tool, "ts_ms": ts_ms}
    if result is not None:
        payload["result"] = result
    if attachments:
        payload["attachments"] = attachments
    if metrics is not None:
        payload["metrics"] = metrics
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


def build_steering_queued(content: str, timestamp_ms: int) -> dict:
    """Build steering_queued event payload.

    timestamp_ms is the enqueue wall-clock time (milliseconds since epoch).
    Stored on the projection's SteeringMessage so downstream consumers can
    derive enqueue-to-delivery latency once the matching steering_delivered
    event arrives.
    """
    return {"content": content, "timestamp_ms": timestamp_ms}


def build_steering_delivered(
    count: int,
    enqueue_ts_ms_list: list[int],
    delivery_ts_ms: int,
) -> dict:
    """Build steering_delivered event payload.

    enqueue_ts_ms_list contains one entry per drained message, in FIFO drain
    order (parallel to the messages list returned by drain_for_primary). This
    preserves per-message latency derivation when N > 1 messages drain together.

    delivery_ts_ms is the wall-clock time the batch was delivered (ms since
    epoch). Latency for message i: delivery_ts_ms - enqueue_ts_ms_list[i].

    These fields live only on the wire event for log/replay analysis; they are
    not folded into the live projection state.
    """
    return {
        "count": count,
        "enqueue_ts_ms_list": enqueue_ts_ms_list,
        "delivery_ts_ms": delivery_ts_ms,
    }


def build_default_scout_concurrency_changed(value: int) -> dict:
    return {"value": value}


def build_workflows_listed(workflows: list[dict]) -> dict:
    """Build workflows_listed event payload.

    Each entry in workflows is a dict shaped as the WorkflowInfo wire model
    with snake_case keys: {id, description, phases, initial_phase}. The fold
    reconstructs WorkflowInfo via WorkflowInfo(**entry).

    Snake_case is used here (not camelCase) because the payload consumer is
    the Python fold, not the wire -- matching the same convention used by
    build_profile_created passing read_only straight to Profile(read_only=...).
    """
    return {"workflows": workflows}


# -- Memory curation event builders -------------------------------------------

def build_memory_curation_started(batch: dict) -> dict:
    """Payload for memory_curation_started. batch is ActiveCurationBatch.to_wire()."""
    return {"batch": batch}


def build_memory_curation_cleared() -> dict:
    return {}


# -- Memory mutation event builders -------------------------------------------

def build_memory_entry_created(entry: dict) -> dict:
    """Payload for memory_entry_created. entry is MemoryEntrySummary.to_wire()."""
    return entry


def build_memory_entry_updated(entry: dict) -> dict:
    """Payload for memory_entry_updated. entry is MemoryEntrySummary.to_wire()."""
    return entry


def build_memory_entry_deleted(seq: str) -> dict:
    return {"seq": seq}


def build_memory_summary_updated(summary: str) -> dict:
    return {"summary": summary}


# -- Reflect event builders ---------------------------------------------------

def build_reflect_started(
    session_id: str,
    question: str,
    model: str,
    started_at_ms: int,
    max_iterations: int,
) -> dict:
    return {
        "session_id": session_id,
        "question": question,
        "model": model,
        "started_at_ms": started_at_ms,
        "max_iterations": max_iterations,
    }


def build_reflect_trace(session_id: str, trace: dict) -> dict:
    return {"session_id": session_id, "trace": trace}


def build_reflect_done(
    session_id: str,
    answer: str,
    citations: list[dict],
    completed_at_ms: int,
    iterations: int,
) -> dict:
    """Build reflect_done event payload.

    Each citation dict carries id, title, type, and modifiedMs (camelCase on wire).
    """
    return {
        "session_id": session_id,
        "answer": answer,
        "citations": citations,
        "completed_at_ms": completed_at_ms,
        "iterations": iterations,
    }


def build_reflect_cancelled(session_id: str, completed_at_ms: int) -> dict:
    return {"session_id": session_id, "completed_at_ms": completed_at_ms}


def build_reflect_failed(session_id: str, error: str, completed_at_ms: int) -> dict:
    return {"session_id": session_id, "error": error, "completed_at_ms": completed_at_ms}


def build_reflect_cleared() -> dict:
    return {}


# -- Domain event builders (agent-conversation channel) -----------------------

def build_reflect_delta(delta: str) -> dict:
    """Build reflect_delta event payload.

    Carries a single text fragment from the pydantic-ai reflection loop's
    text-output stream. The fold appends it to the in-flight ToolKoanEntry's
    result.answer for the agent. Correlated by agent_id only -- koan MCP tools
    block, so at most one in-flight koan entry per agent.
    """
    return {"delta": delta}


def build_tool_attachments(manifest: list[dict]) -> dict:
    """Build tool_attachments event payload.

    Carries a koan-side attachment manifest (upload_id, filename, size,
    content_type, path per AttachmentEntry) emitted by an MCP handler when
    uploads are committed for the active agent. The fold overwrites the
    in-flight tool entry's attachments field. Richer than the runner-extracted
    partial manifest on tool_result content blocks, which lacks koan-side fields.
    """
    return {"attachments": manifest}
