# Tests for koan.lib.task_json helpers.

from __future__ import annotations

from koan.lib.task_json import (
    current_workflow,
    make_initial_workflow_history,
    make_workflow_history_entry,
)


def test_make_initial_workflow_history_shape():
    """make_initial_workflow_history returns a single-entry list with the expected keys."""
    history = make_initial_workflow_history("plan", "intake")
    assert len(history) == 1
    entry = history[0]
    assert entry["name"] == "plan"
    assert entry["phase"] == "intake"
    assert isinstance(entry["started_at"], float)


def test_current_workflow_returns_latest():
    """current_workflow returns the last entry's name when multiple entries are present."""
    task = {
        "workflow_history": [
            make_workflow_history_entry("a", "intake"),
            make_workflow_history_entry("b", "intake"),
        ]
    }
    assert current_workflow(task) == "b"


def test_current_workflow_returns_default_on_missing():
    """current_workflow returns default when workflow_history key is absent."""
    assert current_workflow({}, default="plan") == "plan"


def test_current_workflow_returns_default_on_empty():
    """current_workflow returns default when workflow_history is an empty list."""
    assert current_workflow({"workflow_history": []}, default="plan") == "plan"
