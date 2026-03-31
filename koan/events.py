# Event payload builders -- bridges koan domain types into projection event payloads.
# Imports AgentState, RunnerDiagnostic, list_artifacts, etc.
# koan/projections.py does NOT import from here.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runners.base import RunnerDiagnostic
    from .state import AgentState


def build_agent_spawned(agent: AgentState) -> dict:
    return {
        "agent_id": agent.agent_id,
        "role": agent.role,
        "model": agent.model,
        "is_primary": agent.is_primary,
        "started_at_ms": int(agent.started_at.timestamp() * 1000),
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
) -> dict:
    result: dict = {"step": step, "step_name": step_name}
    if usage is not None:
        result["usage"] = usage
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


def build_tool_completed(
    call_id: str,
    tool: str,
    result: str | None = None,
) -> dict:
    payload: dict = {"call_id": call_id, "tool": tool}
    if result is not None:
        payload["result"] = result
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


def build_artifact_review_requested(
    token: str,
    path: str,
    description: str,
    content: str,
) -> dict:
    return {
        "token": token,
        "path": path,
        "description": description,
        "content": content,
    }


def build_artifact_reviewed(
    token: str,
    accepted: bool | None = None,
    response: str | None = None,
    cancelled: bool = False,
) -> dict:
    result: dict = {"token": token, "cancelled": cancelled}
    if accepted is not None:
        result["accepted"] = accepted
    if response is not None:
        result["response"] = response
    return result


def build_workflow_decision_requested(token: str, chat_turns: list) -> dict:
    return {"token": token, "chat_turns": chat_turns}


def build_workflow_decided(
    token: str,
    decision: dict | None = None,
    cancelled: bool = False,
) -> dict:
    result: dict = {"token": token, "cancelled": cancelled}
    if decision is not None:
        result["decision"] = decision
    return result


# -- Configuration event builders ---------------------------------------------

def build_probe_completed(runners: list[dict]) -> dict:
    return {"runners": runners}


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


def build_active_profile_changed(name: str) -> dict:
    return {"name": name}



def build_scout_concurrency_changed(value: int) -> dict:
    return {"value": value}
