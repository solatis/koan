# Event payload builders -- bridges koan domain types into projection event payloads.
# Imports AgentState, AgentDiagnostic, list_artifacts, etc.
# koan/projections.py does NOT import from here.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agents.base import AgentDiagnostic
    from .state import AgentState


def build_run_started(
    active_preset: str,
    scout_concurrency: int,
) -> dict:
    """Build run_started event payload.

    active_preset is the name of the preset active at run start (e.g. '$last').
    M5: 'profile' renamed to 'active_preset'; 'installations' dropped (removed M4).
    """
    return {
        "active_preset": active_preset,
        "scout_concurrency": scout_concurrency,
    }


def build_run_cleared() -> dict:
    # Empty payload: run_cleared carries no fields. Follows the same convention
    # as build_agents_cleared and build_reflect_cleared.
    return {}


def build_workflow_selected(workflow: str) -> dict:
    """Build workflow_selected event payload."""
    return {"workflow": workflow}


def build_agent_spawned(agent: AgentState) -> dict:
    """Build agent_spawned event payload.

    Carries provider alongside identity so the projection fold can derive cost
    without live lookups.
    """
    return {
        "agent_id": agent.agent_id,
        "role": agent.role,
        "label": agent.label,
        "model": agent.model,
        "is_primary": agent.is_primary,
        "started_at_ms": int(agent.started_at.timestamp() * 1000),
        "provider": agent.provider,
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


def build_tool_request(call_id: str, tool: str, tool_use_id: str = "", ts_ms: int = 0, tool_args: dict | None = None) -> dict:
    """Build a tool_request event payload.

    Emitted when the streaming path first sees a tool invocation. tool_use_id is
    the LLM-assigned identifier used later to correlate with tool_result events.
    ts_ms is the epoch-millisecond timestamp stamped at tool_start time.
    tool_args is the complete args dict when the provider sends it at part
    start (e.g. Anthropic); the fold uses it to populate command fields early.
    """
    payload: dict = {"call_id": call_id, "tool": tool}
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    if ts_ms:
        payload["ts_ms"] = ts_ms
    if tool_args is not None:
        payload["args"] = tool_args
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


def build_tool_failed(call_id: str, tool: str, error: str = "", ts_ms: int = 0) -> dict:
    """Build a tool_failed event payload (argument validation rejected the call).

    The failed event closes the lifecycle for a tool invocation whose arguments
    never passed validation -- the tool body did not run. The fold replaces the
    in-flight entry with a ToolFailedEntry; the malformed model-authored input
    survives only as an opaque JSON string on that entry.
    """
    return {"call_id": call_id, "tool": tool, "error": error, "ts_ms": ts_ms}


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
        suggestions: List of {id, label, command?, phase?, recommended?} dicts — the structured
                     options the orchestrator presents at a yield point.
    """
    return {"suggestions": suggestions}


# -- Configuration event builders ---------------------------------------------

# build_probe_completed removed in M4: CLI binary probe and installation concept
# deleted; provider credential availability uses build_provider_status_listed.

def build_settings_listed(
    connections: list[dict],
    configured_models: list[dict],
    offerings_by_connection: dict[str, list[dict]],
    presets: dict,
    active: str,
    memory_bindings: dict | None,
    default_scout_concurrency: int,
    max_retry_attempts: int,
    max_retry_wait_seconds: float,
    workflows: list[dict],
    embedding_models: list[dict],
) -> dict:
    """Assemble the full settings_listed snapshot payload.

    Carries the entire Settings state. Pushed at startup and after every config
    mutation with replace-all semantics (the fold constructs a complete Settings
    object from this payload). Replaces the 13 former individual settings events
    deleted in M2.
    """
    return {
        "connections": connections,
        "configured_models": configured_models,
        "offerings_by_connection": offerings_by_connection,
        "presets": presets,
        "active": active,
        "memory_bindings": memory_bindings,
        "default_scout_concurrency": default_scout_concurrency,
        "max_retry_attempts": max_retry_attempts,
        "max_retry_wait_seconds": max_retry_wait_seconds,
        "workflows": workflows,
        "embedding_models": embedding_models,
    }

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


# Memory curation event builders (build_memory_curation_started /
# build_memory_curation_cleared) removed in M7: the koan_memory_propose
# approval gate is retired; no blocking curation events are emitted.

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

def build_reflect_inline_trace(trace: dict) -> dict:
    """Build reflect_inline_trace event payload.

    Carries a single trace event from the reflect subagent's internal
    tool-calling loop. The fold appends it to the in-flight ToolKoanEntry's
    result.traces array. Correlated by agent_id only -- koan MCP tools block,
    so at most one in-flight koan entry per agent.
    """
    return {"trace": trace}


def build_tool_attachments(manifest: list[dict]) -> dict:
    """Build tool_attachments event payload.

    Carries a koan-side attachment manifest (upload_id, filename, size,
    content_type, path per AttachmentEntry) emitted by an MCP handler when
    uploads are committed for the active agent. The fold overwrites the
    in-flight tool entry's attachments field. Richer than the runner-extracted
    partial manifest on tool_result content blocks, which lacks koan-side fields.
    """
    return {"attachments": manifest}


def build_token_telemetry(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    context_size: int,
) -> dict:
    """Build token_telemetry event payload.

    Carries per-turn usage facts from the just-completed turn plus the
    measured context size. The projection fold accumulates these into
    running totals on Conversation and computes per-turn deltas on
    Conversation.telemetry.

    Args:
        input_tokens: Input tokens from this turn's RunUsage.
        output_tokens: Output tokens from this turn's RunUsage.
        cache_read_tokens: Cache read tokens from this turn's RunUsage.
        cache_write_tokens: Cache write tokens from this turn's RunUsage.
        context_size: Total context size in tokens from Model.count_tokens().
    """
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "context_size": context_size,
    }
