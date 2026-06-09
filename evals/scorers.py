# evals/scorers.py
# DeepEval DAGMetric factories and harvest payload helpers for koan evals.
#
# Public API:
#   JUDGE_MODEL                  -- shared GeminiModel instance
#   build_criterion_metric       -- factory: DAGMetric for one binary criterion
#   build_cross_phase_metric     -- factory: DAGMetric for one cross-phase rubric body
#   DurationMetric               -- programmatic BaseMetric (run duration)
#   TokenCostMetric              -- programmatic BaseMetric (token usage)
#   ToolCallCountMetric          -- programmatic BaseMetric (tool call count)
#   DURATION_METRIC              -- shared singleton
#   TOKEN_COST_METRIC            -- shared singleton
#   TOOL_CALL_COUNT_METRIC       -- shared singleton
#   _payload_questions / _payload_artifacts /
#   _payload_overall / _payload_workflow -- payload selection helpers
#
# Rubric criteria (bullet strings) and cross-phase rubric bodies live in
# evals/rubrics.py. Test cases (fixture/task/case/workflow/directed_phases)
# live in evals/cases.py. Per-row DAGMetrics are constructed at test collection
# time via build_criterion_metric / build_cross_phase_metric and passed to
# assert_test.
#
# INVOKE: deepeval test run tests/evals/test_koan.py
# (Plain pytest works for collection but does not upload to Confident AI.)

from __future__ import annotations

import json

from deepeval.metrics import BaseMetric, DAGMetric
from deepeval.metrics.dag import (
    BinaryJudgementNode,
    DeepAcyclicGraph,
    VerdictNode,
)
from deepeval.models import GeminiModel
from deepeval.test_case import LLMTestCase, LLMTestCaseParams


# -- Judge model ---------------------------------------------------------------

# Model string is pinned per memory entry 77. Do not change speculatively.
JUDGE_MODEL = GeminiModel(model="gemini-3-pro-preview")


# -- DAGMetric factories -------------------------------------------------------

def build_criterion_metric(criterion: str, name: str) -> DAGMetric:
    """Build a DAGMetric that judges ACTUAL_OUTPUT against one binary criterion.

    The DAG is a single BinaryJudgementNode root with two VerdictNode leaves:
    (True, score=10) and (False, score=0). Threshold 1.0 requires pass.
    """
    return DAGMetric(
        name=name,
        dag=DeepAcyclicGraph([
            BinaryJudgementNode(
                criteria=criterion,
                evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
                children=[
                    VerdictNode(verdict=True, score=10),
                    VerdictNode(verdict=False, score=0),
                ],
            ),
        ]),
        model=JUDGE_MODEL,
        threshold=1.0,
    )


def build_cross_phase_metric(body: str, name: str) -> DAGMetric:
    """Build a DAGMetric that judges ACTUAL_OUTPUT against a whole cross-phase
    rubric body as a single holistic criterion."""
    return DAGMetric(
        name=name,
        dag=DeepAcyclicGraph([
            BinaryJudgementNode(
                criteria=body,
                evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
                children=[
                    VerdictNode(verdict=True, score=10),
                    VerdictNode(verdict=False, score=0),
                ],
            ),
        ]),
        model=JUDGE_MODEL,
        threshold=1.0,
    )


# -- Programmatic BaseMetric subclasses ----------------------------------------

class DurationMetric(BaseMetric):
    """Scores run duration against a wall-clock threshold.

    Reads duration_s from test_case.additional_metadata -- no LLM call needed.
    threshold_s defaults to 1800 (30 minutes), enough headroom for plan+intake.
    Raises ValueError when duration_s is absent, signaling a builder bug.
    """

    async_mode = False

    def __init__(self, threshold_s: float = 1800.0) -> None:
        self.threshold = threshold_s
        self.score = 0.0
        self.success = False
        self.reason = ""
        self.error = None
        self.score_breakdown = {}
        self.skipped = False

    @property
    def __name__(self) -> str:
        return "Duration"

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        # Reset skipped defensively for any DeepEval execute path that checks it.
        self.skipped = False
        meta = test_case.additional_metadata or {}
        if "duration_s" not in meta:
            raise ValueError(
                f"DurationMetric requires 'duration_s' in additional_metadata; "
                f"got keys {list(meta)}"
            )
        s = float(meta["duration_s"])
        self.score = s
        self.success = s <= self.threshold
        self.reason = f"duration {s:.1f}s vs threshold {self.threshold:.1f}s"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return self.success


class TokenCostMetric(BaseMetric):
    """Scores total orchestrator token usage against a threshold.

    Reads token_cost from test_case.additional_metadata. threshold_tokens
    defaults to 500k -- a generous budget for a two-phase plan run.
    Raises ValueError when token_cost is absent, signaling a builder bug.
    """

    async_mode = False

    def __init__(self, threshold_tokens: int = 500_000) -> None:
        self.threshold = float(threshold_tokens)
        self.score = 0.0
        self.success = False
        self.reason = ""
        self.error = None
        self.score_breakdown = {}
        self.skipped = False

    @property
    def __name__(self) -> str:
        return "TokenCost"

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        # Reset skipped defensively for any DeepEval execute path that checks it.
        self.skipped = False
        meta = test_case.additional_metadata or {}
        if "token_cost" not in meta:
            raise ValueError(
                f"TokenCostMetric requires 'token_cost' in additional_metadata; "
                f"got keys {list(meta)}"
            )
        tc = meta["token_cost"] or {}
        total = int(tc.get("input_tokens", 0)) + int(tc.get("output_tokens", 0))
        self.score = float(total)
        self.success = total <= self.threshold
        self.reason = (
            f"tokens {total} (in={tc.get('input_tokens', 0)} "
            f"out={tc.get('output_tokens', 0)}) vs threshold {int(self.threshold)}"
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return self.success


class ToolCallCountMetric(BaseMetric):
    """Scores total tool call count across all phases against a threshold.

    Reads tool_call_count from test_case.additional_metadata. threshold_calls
    defaults to 500 -- a rough ceiling for non-pathological runs.
    Raises ValueError when tool_call_count is absent, signaling a builder bug.
    """

    async_mode = False

    def __init__(self, threshold_calls: int = 500) -> None:
        self.threshold = float(threshold_calls)
        self.score = 0.0
        self.success = False
        self.reason = ""
        self.error = None
        self.score_breakdown = {}
        self.skipped = False

    @property
    def __name__(self) -> str:
        return "ToolCallCount"

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        # Reset skipped defensively for any DeepEval execute path that checks it.
        self.skipped = False
        meta = test_case.additional_metadata or {}
        if "tool_call_count" not in meta:
            raise ValueError(
                f"ToolCallCountMetric requires 'tool_call_count' in additional_metadata; "
                f"got keys {list(meta)}"
            )
        counts = meta["tool_call_count"] or {}
        total = sum(int(v) for v in counts.values())
        self.score = float(total)
        self.success = total <= self.threshold
        self.score_breakdown = dict(counts)
        self.reason = f"tool calls total={total} vs threshold {int(self.threshold)}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return self.success


# Module-level shared singletons for programmatic metrics.
DURATION_METRIC = DurationMetric()
TOKEN_COST_METRIC = TokenCostMetric()
TOOL_CALL_COUNT_METRIC = ToolCallCountMetric()


# -- Payload selection ---------------------------------------------------------

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
        f"## questions\n{_payload_questions(harvest, phase)}\n\n"
        f"## artifacts\n{_payload_artifacts(harvest, phase)}\n\n"
        f"## all_tool_calls\n"
        + json.dumps(
            harvest.get("tool_calls_by_phase", {}).get(phase, []),
            indent=2,
        )
    )


def _payload_workflow(harvest: dict) -> str:
    tools = harvest.get("tool_calls_by_phase", {})
    # Fall back to artifacts_by_phase.keys() when phase_order is absent --
    # a phase that produced artifacts is the best available ordering signal.
    artifacts_by_phase = harvest.get("artifacts_by_phase", {})
    order = harvest.get("phase_order") or sorted(artifacts_by_phase.keys())
    tail = [p for p in artifacts_by_phase.keys() if p not in order]
    blocks = []
    for phase in list(order) + tail:
        blocks.append(
            f"# phase: {phase}\n\n"
            f"## tool_calls\n{json.dumps(tools.get(phase, []), indent=2)}\n\n"
            f"## artifacts\n{_payload_artifacts(harvest, phase)}"
        )
    return "\n\n---\n\n".join(blocks)
