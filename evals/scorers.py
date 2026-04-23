# evals/scorers.py
# DeepEval metric factories and harvest payload helpers for koan evals.
#
# Public API:
#   JUDGE_MODEL          -- shared GeminiModel instance (gemini-3-pro)
#   make_rubric_metric   -- GEval for a (phase, section) pair
#   make_workflow_metric -- GEval for the cross-cutting workflow rubric
#   build_test_case      -- LLMTestCase from a harvest dict + payload str
#   _payload_summary     -- extract phase summary text from harvest
#   _payload_questions   -- extract koan_ask_question calls from harvest
#   _payload_artifacts   -- extract artifact content from harvest
#   _payload_overall     -- combined phase payload
#   _payload_workflow    -- combined cross-phase payload
#
# The payload helpers are framework-agnostic; they were present under the
# Inspect harness and are unchanged in body here.

from __future__ import annotations

import json
from pathlib import Path

from deepeval.metrics import GEval
from deepeval.models import GeminiModel
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from evals.cases import Case


# Instantiated once at module load and shared across all GEval instances in a
# session. gemini-3-pro is the post-plan-review corrected target; the original
# task description referenced google/gemini-3.1-pro-preview which does not
# exist in either DeepEval's GEMINI_MODELS_DATA catalog or Google's lineup.
JUDGE_MODEL = GeminiModel(model="gemini-3-pro")


# -- Rubric loading ------------------------------------------------------------

def _load_rubric(fixture_dir: Path, task_dir: Path, phase: str, section: str) -> str | None:
    """Load and concatenate rubric text for a (phase, section) pair.

    Returns fixture-level rubric text, optionally with a task-level addendum
    appended. Returns None when no rubric files exist for this combination,
    which causes callers to skip the test rather than fail.

    Rubric directories use underscores regardless of how koan names the phase
    internally (e.g. phase "plan-spec" -> dir "plan_spec").
    """
    phase_dir = phase.replace("-", "_")
    fixture_rubric = fixture_dir / "rubrics" / phase_dir / f"{section}.md"
    task_rubric = task_dir / "rubrics" / phase_dir / f"{section}.md"
    parts = []
    if fixture_rubric.exists():
        parts.append(fixture_rubric.read_text(encoding="utf-8"))
    if task_rubric.exists():
        parts.append(
            "\n\n## Task-specific additions\n\n"
            + task_rubric.read_text(encoding="utf-8")
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
    # Use the chronological phase_order captured by harvest_run so the
    # workflow-level payload reads in the order phases actually ran
    # (intake -> plan-spec -> ...) rather than alphabetically.
    order = harvest.get("phase_order") or sorted(summaries.keys())
    # Append any phases that appear in data but not in phase_order (shouldn't
    # happen, but keeps the payload lossless if harvest is incomplete).
    tail = [p for p in summaries.keys() if p not in order]
    blocks = []
    for phase in list(order) + tail:
        blocks.append(
            f"# phase: {phase}\n\n"
            f"## summary\n{summaries.get(phase, '')}\n\n"
            f"## tool_calls\n{json.dumps(tools.get(phase, []), indent=2)}\n\n"
            f"## artifacts\n{_payload_artifacts(harvest, phase)}"
        )
    return "\n\n---\n\n".join(blocks)


# -- DeepEval metric factories -------------------------------------------------

def make_rubric_metric(case: Case, phase: str, section: str) -> GEval | None:
    """Build a GEval metric for a (phase, section) rubric pair.

    Returns None when no rubric file exists for this (phase, section) on
    disk; the test function skips rather than fails in that case.

    strict_mode=True ensures the judge returns a binary PASS/FAIL verdict
    rather than a partial score, matching the rubric contract
    ("Respond with PASS or FAIL on the last line.").
    async_mode=True lets DeepEval parallelize judgment calls within a session.
    """
    rubric = _load_rubric(case.fixture_dir, case.task_dir, phase, section)
    if rubric is None:
        return None
    return GEval(
        name=f"{phase}/{section}",
        criteria=rubric,
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        strict_mode=True,
        model=JUDGE_MODEL,
        async_mode=True,
    )


def make_workflow_metric(case: Case) -> GEval | None:
    """Build a GEval metric for the cross-cutting workflow rubric.

    Returns None when the case has no rubric body (empty or whitespace-only),
    which causes the test to skip rather than fail.
    """
    if not case.rubric_body.strip():
        return None
    return GEval(
        name="workflow/overall",
        criteria=case.rubric_body,
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        strict_mode=True,
        model=JUDGE_MODEL,
        async_mode=True,
    )


def build_test_case(harvest: dict, payload: str) -> LLMTestCase:
    """Wrap a harvest payload in an LLMTestCase for DeepEval assertion.

    The `input` field is required by LLMTestCase but not included in
    evaluation_params, so a terse placeholder suffices -- the judge never
    sees it as a grading criterion.
    """
    return LLMTestCase(
        input="(koan eval harvest)",
        actual_output=payload,
        additional_metadata={"harvest": harvest},
    )
