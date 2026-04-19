# evals/tasks.py
# Inspect AI Task definitions for koan evals.

from inspect_ai import Task, task

from evals.dataset import load_dataset
from evals.scorers import (
    intake_summary,
    intake_questions,
    intake_artifacts,
    intake_overall,
    plan_spec_summary,
    plan_spec_questions,
    plan_spec_artifacts,
    plan_spec_overall,
    workflow_overall,
)
from evals.solver import koan_solver


@task
def koan_plan_eval() -> Task:
    """Full-run koan plan workflow eval with per-phase rubric scoring."""
    return Task(
        dataset=load_dataset(),
        solver=koan_solver(),
        scorer=[
            intake_summary(),
            intake_questions(),
            intake_artifacts(),
            intake_overall(),
            plan_spec_summary(),
            plan_spec_questions(),
            plan_spec_artifacts(),
            plan_spec_overall(),
            workflow_overall(),
        ],
    )
