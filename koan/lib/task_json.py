# task_json.py -- helpers for reading and writing the workflow_history field
# in orchestrator task.json files.
#
# Schema for the workflow_history field:
#
#   workflow_history: list[WorkflowHistoryEntry]
#
# Each entry records one workflow the run has been in. The most-recent entry
# is the active workflow. The list is append-only: writers push a new entry
# on every workflow switch (M2+). In M1, exactly one entry is written at
# orchestrator spawn time.
#
# started_at uses float epoch seconds to match the existing created_at
# convention at koan/web/app.py (time.time()). ISO 8601 and epoch-ms were
# rejected for inconsistency with the surrounding file.

from __future__ import annotations

import time
from typing import TypedDict


class WorkflowHistoryEntry(TypedDict):
    """One entry in the workflow_history list on an orchestrator task.json.

    name       -- workflow name as registered in koan/lib/workflows.py
    phase      -- the initial_phase entered when this workflow started;
                  records the entered phase, not the phase exited from
    started_at -- epoch seconds (float) when this workflow entry was created
    """
    name: str
    phase: str
    started_at: float


def make_workflow_history_entry(name: str, phase: str) -> WorkflowHistoryEntry:
    """Build a single WorkflowHistoryEntry stamped with the current epoch time.

    phase should be the initial_phase of the workflow -- the phase the
    orchestrator is about to enter, not any prior phase.
    """
    return WorkflowHistoryEntry(name=name, phase=phase, started_at=time.time())


def make_initial_workflow_history(name: str, phase: str) -> list[WorkflowHistoryEntry]:
    """Build the initial workflow_history list for a fresh orchestrator task.json.

    Returns a single-element list. M2's koan_set_workflow tool will append
    subsequent entries to this list on each workflow switch.
    """
    return [make_workflow_history_entry(name, phase)]


def current_workflow(task: dict, *, default: str = "") -> str:
    """Return the active workflow name from a task.json dict.

    Reads the last entry of workflow_history["name"]. Returns default when
    workflow_history is absent or empty -- this covers both old-schema task.json
    files (written before this migration) and subagent task.json files (executor,
    scout) which intentionally do not carry the workflow field.
    """
    history = task.get("workflow_history")
    if not history:
        return default
    return history[-1].get("name", default)
