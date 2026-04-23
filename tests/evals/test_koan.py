# tests/evals/test_koan.py
# Nine parametrized pytest test functions -- one per (phase, section) pair.
#
# Each function is named explicitly (not generated via a factory loop) to
# preserve pytest's per-function test IDs and enable -k filtering:
#
#   pytest tests/evals/ -k "intake_summary"
#   pytest tests/evals/ -k "plan_spec and yolo_flag"
#
# The `case` and `harvest` fixtures are session-scoped and defined in
# conftest.py. pytest expands each function into one invocation per
# parametrized case; the harvest for that case is reused across all nine
# functions that share it.
#
# Per-task rubric addenda are picked up transparently via case.task_dir
# inside make_rubric_metric -- no per-task test variation needed.

import pytest

from deepeval import assert_test

from evals.cases import Case
from evals.scorers import (
    _payload_artifacts,
    _payload_overall,
    _payload_questions,
    _payload_summary,
    _payload_workflow,
    build_test_case,
    make_rubric_metric,
    make_workflow_metric,
)


def _check_phase_gate(case: Case, phase: str) -> None:
    """Skip this test when the phase was not in the case's directed sequence."""
    active = [p for p in case.directed_phases if p != "done"]
    if phase not in active:
        pytest.skip(f"phase {phase!r} not in directed_phases")


# -- intake --------------------------------------------------------------------

def test_intake_summary(case, harvest):
    _check_phase_gate(case, "intake")
    metric = make_rubric_metric(case, "intake", "summary")
    if metric is None:
        pytest.skip("no rubric for intake/summary")
    assert_test(build_test_case(harvest, _payload_summary(harvest, "intake")), [metric])


def test_intake_questions(case, harvest):
    _check_phase_gate(case, "intake")
    metric = make_rubric_metric(case, "intake", "questions")
    if metric is None:
        pytest.skip("no rubric for intake/questions")
    assert_test(build_test_case(harvest, _payload_questions(harvest, "intake")), [metric])


def test_intake_artifacts(case, harvest):
    _check_phase_gate(case, "intake")
    metric = make_rubric_metric(case, "intake", "artifacts")
    if metric is None:
        pytest.skip("no rubric for intake/artifacts")
    assert_test(build_test_case(harvest, _payload_artifacts(harvest, "intake")), [metric])


def test_intake_overall(case, harvest):
    _check_phase_gate(case, "intake")
    metric = make_rubric_metric(case, "intake", "overall")
    if metric is None:
        pytest.skip("no rubric for intake/overall")
    assert_test(build_test_case(harvest, _payload_overall(harvest, "intake")), [metric])


# -- plan-spec -----------------------------------------------------------------

def test_plan_spec_summary(case, harvest):
    _check_phase_gate(case, "plan-spec")
    metric = make_rubric_metric(case, "plan-spec", "summary")
    if metric is None:
        pytest.skip("no rubric for plan-spec/summary")
    assert_test(build_test_case(harvest, _payload_summary(harvest, "plan-spec")), [metric])


def test_plan_spec_questions(case, harvest):
    _check_phase_gate(case, "plan-spec")
    metric = make_rubric_metric(case, "plan-spec", "questions")
    if metric is None:
        pytest.skip("no rubric for plan-spec/questions")
    assert_test(build_test_case(harvest, _payload_questions(harvest, "plan-spec")), [metric])


def test_plan_spec_artifacts(case, harvest):
    _check_phase_gate(case, "plan-spec")
    metric = make_rubric_metric(case, "plan-spec", "artifacts")
    if metric is None:
        pytest.skip("no rubric for plan-spec/artifacts")
    assert_test(build_test_case(harvest, _payload_artifacts(harvest, "plan-spec")), [metric])


def test_plan_spec_overall(case, harvest):
    _check_phase_gate(case, "plan-spec")
    metric = make_rubric_metric(case, "plan-spec", "overall")
    if metric is None:
        pytest.skip("no rubric for plan-spec/overall")
    assert_test(build_test_case(harvest, _payload_overall(harvest, "plan-spec")), [metric])


# -- workflow (cross-cutting) --------------------------------------------------

def test_workflow_overall(case, harvest):
    # No phase gate: the workflow rubric spans all phases that ran.
    metric = make_workflow_metric(case)
    if metric is None:
        pytest.skip("no case rubric body")
    assert_test(build_test_case(harvest, _payload_workflow(harvest)), [metric])
