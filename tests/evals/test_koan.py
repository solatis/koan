# tests/evals/test_koan.py
# Parametrized pytest tests per rubric row and per run row.
# INVOKE VIA: deepeval test run tests/evals/test_koan.py
# (Plain `pytest` works for collection but does NOT upload to Confident AI
# and does NOT attach hyperparameters; see plan.md / memory 75 for rationale.)

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

# Per-task timeout for criteria-sequential DAG eval must be set before deepeval
# runtime reads it. 600s accommodates rubrics with many criteria at ~15s/call.
os.environ.setdefault("DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE", "600")

import deepeval
import pytest
from deepeval import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from evals.cases import Case
from evals.rubrics import (
    FIXTURE_RUBRICS,
    TASK_RUBRIC_ADDENDUMS,
    get_cross_phase_rubric,
    get_rubric_criteria,
)
from evals.scorers import (
    DURATION_METRIC,
    TOKEN_COST_METRIC,
    TOOL_CALL_COUNT_METRIC,
    _payload_artifacts,
    _payload_overall,
    _payload_questions,
    _payload_workflow,
    build_criterion_metric,
    build_cross_phase_metric,
)
from tests.evals.conftest import CASES, HYPERPARAMETERS, _get_harvest


log = logging.getLogger("koan.evals.test_koan")

SECTIONS = ("questions", "artifacts", "overall")
_PAYLOAD_FNS = {
    "questions": _payload_questions,
    "artifacts": _payload_artifacts,
    "overall":   _payload_overall,
}


# -- Hyperparameters -----------------------------------------------------------

# Fires at module import. Under `deepeval test run`, pytest_sessionstart has
# already created the shared test_run, so this attaches correctly. Under plain
# pytest this still runs but attaches to an ephemeral test_run (see memory 75).
@deepeval.log_hyperparameters
def _hyperparameters() -> dict[str, str]:
    return HYPERPARAMETERS


# -- Row builders --------------------------------------------------------------

@dataclass(frozen=True)
class RubricRow:
    case: Case
    phase: str
    section: str
    name: str  # LLMTestCase.name


@dataclass(frozen=True)
class RunRow:
    case: Case
    name: str


def _active_phases(case: Case) -> list[str]:
    return [p for p in case.directed_phases if p != "done"]


def _build_rubric_rows() -> list[RubricRow]:
    rows: list[RubricRow] = []
    for case in CASES:
        for phase in _active_phases(case):
            for section in SECTIONS:
                if get_rubric_criteria(
                    case.fixture_id, case.task_id, phase, section,
                ) is None:
                    continue
                rows.append(RubricRow(
                    case=case, phase=phase, section=section,
                    name=(
                        f"{case.fixture_id}/{case.task_id}/{case.case_id}"
                        f"/{phase}/{section}"
                    ),
                ))
    return rows


def _build_run_rows() -> list[RunRow]:
    return [
        RunRow(
            case=case,
            name=f"{case.fixture_id}/{case.task_id}/{case.case_id}/workflow",
        )
        for case in CASES
    ]


# -- Metric name helpers -------------------------------------------------------

def _norm(s: str) -> str:
    return s.replace("-", "_")


def _fixture_criterion_name(phase: str, section: str, idx: int) -> str:
    return f"Fixture_{_norm(phase)}_{section}_{idx:02d}"


def _task_criterion_name(task_id: str, phase: str, section: str, idx: int) -> str:
    return f"Task_{_norm(task_id)}_{_norm(phase)}_{section}_{idx:02d}"


def _cross_phase_name(task_id: str, case_id: str) -> str:
    return f"CrossPhaseCoherence_{_norm(task_id)}_{_norm(case_id)}"


# -- LLMTestCase + metric list builders ----------------------------------------

def _rubric_test_case(row: RubricRow, harvest: dict) -> LLMTestCase:
    task_md = (row.case.task_dir / "task.md").read_text(encoding="utf-8").strip()
    payload = _PAYLOAD_FNS[row.section](harvest, row.phase)
    return LLMTestCase(
        name=row.name,
        input=task_md,
        actual_output=payload,
        additional_metadata={
            "fixture_id": row.case.fixture_id,
            "task_id":    row.case.task_id,
            "case_id":    row.case.case_id,
            "phase":      row.phase,
            "section":    row.section,
        },
    )


def _run_test_case(row: RunRow, harvest: dict) -> LLMTestCase:
    task_md = (row.case.task_dir / "task.md").read_text(encoding="utf-8").strip()
    tok = harvest.get("token_cost", {}) or {}
    total_tokens = int(tok.get("input_tokens", 0)) + int(tok.get("output_tokens", 0))
    return LLMTestCase(
        name=row.name,
        input=task_md,
        actual_output=_payload_workflow(harvest),
        token_cost=float(total_tokens),
        completion_time=float(harvest.get("duration_s", 0.0)),
        additional_metadata={
            "fixture_id":      row.case.fixture_id,
            "task_id":         row.case.task_id,
            "case_id":         row.case.case_id,
            "workflow":        row.case.workflow,
            "directed_phases": row.case.directed_phases,
            "duration_s":      harvest.get("duration_s", 0.0),
            "token_cost":      tok,
            "tool_call_count": harvest.get("tool_call_count", {}),
        },
    )


def _rubric_metrics(row: RubricRow) -> list[BaseMetric]:
    fixture_crits = FIXTURE_RUBRICS.get(
        (row.case.fixture_id, row.phase, row.section), [],
    )
    task_crits = TASK_RUBRIC_ADDENDUMS.get(
        (row.case.fixture_id, row.case.task_id, row.phase, row.section), [],
    )
    metrics: list[BaseMetric] = []
    for i, c in enumerate(fixture_crits, start=1):
        metrics.append(build_criterion_metric(
            c, _fixture_criterion_name(row.phase, row.section, i),
        ))
    for i, c in enumerate(task_crits, start=1):
        metrics.append(build_criterion_metric(
            c, _task_criterion_name(row.case.task_id, row.phase, row.section, i),
        ))
    return metrics


def _run_metrics(row: RunRow) -> list[BaseMetric]:
    # Programmatic metrics apply to every run row; raise ValueError on
    # missing metadata so builder bugs surface immediately rather than silently.
    metrics: list[BaseMetric] = [
        DURATION_METRIC, TOKEN_COST_METRIC, TOOL_CALL_COUNT_METRIC,
    ]
    cross_phase_body = get_cross_phase_rubric(
        row.case.fixture_id, row.case.task_id, row.case.case_id,
    )
    if cross_phase_body is not None:
        metrics.append(build_cross_phase_metric(
            cross_phase_body,
            name=_cross_phase_name(row.case.task_id, row.case.case_id),
        ))
    return metrics


# -- Parametrized tests --------------------------------------------------------

_RUBRIC_ROWS = _build_rubric_rows()
_RUN_ROWS = _build_run_rows()


@pytest.mark.parametrize(
    "row", _RUBRIC_ROWS, ids=[r.name for r in _RUBRIC_ROWS],
)
def test_rubric(row: RubricRow, harvest_cache):
    harvest = _get_harvest(row.case, harvest_cache)
    assert_test(_rubric_test_case(row, harvest), _rubric_metrics(row))


@pytest.mark.parametrize(
    "row", _RUN_ROWS, ids=[r.name for r in _RUN_ROWS],
)
def test_run(row: RunRow, harvest_cache):
    harvest = _get_harvest(row.case, harvest_cache)
    assert_test(_run_test_case(row, harvest), _run_metrics(row))
