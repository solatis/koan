# evals/cases.py
# Case definitions as code. Each Case references a fixture snapshot and
# a task directory on disk; cross-phase rubric bodies live in evals/rubrics.py.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


FIXTURES_DIR: Path = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class Case:
    fixture_id: str            # e.g. "koan-1"
    task_id: str               # e.g. "yolo-flag"
    case_id: str               # e.g. "intake-plan-spec"
    fixture_dir: Path
    task_dir: Path
    workflow: str              # e.g. "plan"
    directed_phases: list[str] # must end with "done"


def _make_case(
    fixture_id: str,
    task_id: str,
    case_id: str,
    workflow: str,
    directed_phases: list[str],
) -> Case:
    return Case(
        fixture_id=fixture_id,
        task_id=task_id,
        case_id=case_id,
        fixture_dir=FIXTURES_DIR / fixture_id,
        task_dir=FIXTURES_DIR / fixture_id / "tasks" / task_id,
        workflow=workflow,
        directed_phases=directed_phases,
    )


# Ordered list of test cases. Adding a case = appending here + adding rubric
# data to evals/rubrics.py (if rubrics apply).
CASES: list[Case] = [
    _make_case(
        fixture_id="koan-1",
        task_id="add-logs",
        case_id="intake-plan-spec",
        workflow="plan",
        directed_phases=["intake", "plan-spec", "done"],
    ),
    _make_case(
        fixture_id="koan-1",
        task_id="scout-concurrency-settings-only",
        case_id="intake-plan-spec",
        workflow="plan",
        directed_phases=["intake", "plan-spec", "done"],
    ),
    _make_case(
        fixture_id="koan-1",
        task_id="yolo-flag",
        case_id="intake-plan-spec",
        workflow="plan",
        directed_phases=["intake", "plan-spec", "done"],
    ),
]
