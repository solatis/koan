# evals/scorers.py
# Rubric-driven scorers for koan eval tasks.
#
# Each scorer loads a fixture-level rubric (required) plus an optional
# task-level addendum for a (phase, section) pair, selects the matching
# payload slice from state.metadata["harvest"], and asks a judge model for
# PASS or FAIL. Missing rubric -> scorer returns None -> inspect_ai skips it.
#
# Section enum per phase: summary | questions | artifacts | overall.
# Workflow-level cross-cutter: rubrics/overall.md at the fixture root.

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from inspect_ai.model import get_model
from inspect_ai.scorer import (
    Score, Scorer, accuracy, scorer, stderr, value_to_float,
)
from inspect_ai.solver import TaskState


JUDGE_MODEL = "google/gemini-3.1-pro-preview"

# inspect_ai's default value_to_float only recognises CORRECT/INCORRECT/PARTIAL
# and yes/true/no/false/numeric. Scorers here return "PASS" / "FAIL" as
# Score.value to match rubric authoring conventions and the last-line grade
# pattern, so a custom ValueToFloat is required for accuracy() / stderr().
_PF_TO_FLOAT = value_to_float(correct="PASS", incorrect="FAIL")
_PF_METRICS = [accuracy(to_float=_PF_TO_FLOAT), stderr(to_float=_PF_TO_FLOAT)]


# -- Rubric loading ------------------------------------------------------------

def _load_rubric(state: TaskState, phase: str, section: str) -> str | None:
    fixture_dir = Path(state.metadata["fixture_dir"])
    task_dir = Path(state.metadata["task_dir"])
    fixture_rubric = fixture_dir / "rubrics" / phase / f"{section}.md"
    task_rubric = task_dir / "rubrics" / phase / f"{section}.md"
    parts = []
    if fixture_rubric.exists():
        parts.append(fixture_rubric.read_text(encoding="utf-8"))
    if task_rubric.exists():
        parts.append(
            "\n\n## Task-specific additions\n\n"
            + task_rubric.read_text(encoding="utf-8")
        )
    return "\n\n".join(parts) if parts else None


def _load_workflow_rubric(state: TaskState) -> str | None:
    fixture_dir = Path(state.metadata["fixture_dir"])
    task_dir = Path(state.metadata["task_dir"])
    f_rubric = fixture_dir / "rubrics" / "overall.md"
    t_rubric = task_dir / "rubrics" / "overall.md"
    parts = []
    if f_rubric.exists():
        parts.append(f_rubric.read_text(encoding="utf-8"))
    if t_rubric.exists():
        parts.append(
            "\n\n## Task-specific additions\n\n"
            + t_rubric.read_text(encoding="utf-8")
        )
    return "\n\n".join(parts) if parts else None


# -- Payload selection ---------------------------------------------------------

def _payload_summary(harvest: dict, phase: str) -> str:
    summary = harvest.get("phase_summaries", {}).get(phase)
    if not summary:
        return "(no summary captured for this phase)"
    return summary


def _payload_questions(harvest: dict, phase: str) -> str:
    calls = harvest.get("tool_calls_by_phase", {}).get(phase, [])
    asks = [c for c in calls if c["tool"] == "koan_ask_question"]
    if not asks:
        return "(no koan_ask_question calls during this phase)"
    return json.dumps([c["args"] for c in asks], indent=2)


def _payload_artifacts(harvest: dict, phase: str) -> str:
    art = harvest.get("artifacts_by_phase", {}).get(phase, {
        "created": {}, "modified": {}, "all_present": {},
    })
    blocks = []
    for kind in ("created", "modified", "all_present"):
        items = art.get(kind, {})
        if not items:
            blocks.append(f"### {kind}\n(none)")
        else:
            blocks.append(
                f"### {kind}\n"
                + "\n".join(
                    f"#### {p}\n```\n{c}\n```"
                    for p, c in items.items()
                )
            )
    return "\n\n".join(blocks)


def _payload_overall(harvest: dict, phase: str) -> str:
    return (
        f"## summary\n{_payload_summary(harvest, phase)}\n\n"
        f"## questions\n{_payload_questions(harvest, phase)}\n\n"
        f"## artifacts\n{_payload_artifacts(harvest, phase)}\n\n"
        f"## all_tool_calls\n"
        + json.dumps(
            harvest.get("tool_calls_by_phase", {}).get(phase, []),
            indent=2,
        )
    )


def _payload_workflow(harvest: dict) -> str:
    summaries = harvest.get("phase_summaries", {})
    tools = harvest.get("tool_calls_by_phase", {})
    blocks = []
    for phase in sorted(summaries.keys()):
        blocks.append(
            f"# phase: {phase}\n\n"
            f"## summary\n{summaries.get(phase, '')}\n\n"
            f"## tool_calls\n{json.dumps(tools.get(phase, []), indent=2)}\n\n"
            f"## artifacts\n{_payload_artifacts(harvest, phase)}"
        )
    return "\n\n---\n\n".join(blocks)


# -- Judge invocation ----------------------------------------------------------

_JUDGE_PROMPT = """You are grading an AI orchestrator against a rubric.

## Rubric

{rubric}

## Data

{payload}

Respond with a brief rationale, then on the last line exactly one of:
PASS
FAIL
"""


async def _grade(rubric: str, payload: str) -> Score:
    model = get_model(JUDGE_MODEL)
    out = await model.generate(_JUDGE_PROMPT.format(rubric=rubric, payload=payload))
    text = out.completion.strip()
    last_line = text.splitlines()[-1].strip().upper() if text else "FAIL"
    value = "PASS" if last_line == "PASS" else "FAIL"
    return Score(value=value, explanation=text)


# -- Scorer factories ----------------------------------------------------------

def _scorer_name(phase: str, section: str) -> str:
    # Normalize phase names like "plan-spec" to underscores so log columns
    # render cleanly and match the Python factory variable names.
    return f"{phase.replace('-', '_')}_{section}"


def _rubric_scorer(phase: str, section: str, payload_fn: Callable):
    # Returns a scorer factory (call with () to get a Scorer). The inner
    # _build function is decorated with @scorer so inspect_ai picks it up;
    # name= is set explicitly so the registry key matches the factory variable.
    @scorer(metrics=_PF_METRICS, name=_scorer_name(phase, section))
    def _build() -> Scorer:
        async def score(state: TaskState, target) -> Score | None:
            rubric = _load_rubric(state, phase, section)
            if rubric is None:
                # No rubric for this (phase, section) -> skip gracefully.
                return None
            harvest = state.metadata.get("harvest", {})
            payload = payload_fn(harvest, phase)
            return await _grade(rubric, payload)
        return score
    return _build


intake_summary    = _rubric_scorer("intake",    "summary",   _payload_summary)
intake_questions  = _rubric_scorer("intake",    "questions", _payload_questions)
intake_artifacts  = _rubric_scorer("intake",    "artifacts", _payload_artifacts)
intake_overall    = _rubric_scorer("intake",    "overall",   _payload_overall)

plan_spec_summary   = _rubric_scorer("plan-spec", "summary",   _payload_summary)
plan_spec_questions = _rubric_scorer("plan-spec", "questions", _payload_questions)
plan_spec_artifacts = _rubric_scorer("plan-spec", "artifacts", _payload_artifacts)
plan_spec_overall   = _rubric_scorer("plan-spec", "overall",   _payload_overall)


@scorer(metrics=_PF_METRICS, name="workflow_overall")
def workflow_overall() -> Scorer:
    async def score(state: TaskState, target) -> Score | None:
        rubric = _load_workflow_rubric(state)
        if rubric is None:
            return None
        harvest = state.metadata.get("harvest", {})
        return await _grade(rubric, _payload_workflow(harvest))
    return score
