---
title: evaluate max_concurrent combined with asyncio.gather inside metrics creates
  a thundering-herd API flood
type: lesson
created: '2026-04-23T16:55:13Z'
modified: '2026-04-23T16:55:13Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
- 0075-deepeval-test-layout-nine-parametrized-pytest.md
---

This lesson was distilled on 2026-04-23 by Leon during DeepEval migration debugging after he observed 136+ simultaneous Gemini API calls from a single eval run, overwhelming rate limits and producing a cascade of retry failures.

Failure calculus. DeepEval's `evaluate(test_cases, metrics, async_config=AsyncConfig(max_concurrent=N))` runs up to N `(case, metric)` pairs concurrently. Koan's eval suite has ~21 test cases and several judge metrics; with `max_concurrent=100` DeepEval was willing to run all rows in parallel. Inside each metric, the earlier judge contract used `await asyncio.gather(*[judge_criterion(c) for c in criteria])` to parallelize per-criterion judge calls. For a 6-criterion rubric across 21 cases that compounds to 126 simultaneous Gemini API calls, plus CrossPhaseCoherence and any other metric layered on top. Gemini's concurrent-request budget is far below that, so the harness spent most of its wall-clock in exponential-backoff retries that eventually tripped the per-task timeout.

Fix adopted on 2026-04-23. Two coordinated changes:

1. Per-criterion calls inside metrics are sequential: `RubricComplianceMetric.a_measure` now iterates `for criterion in criteria: verdict = await JUDGE_MODEL.a_generate_with_schema(...)`, not asyncio.gather. This caps per-metric concurrency at 1.
2. `AsyncConfig(max_concurrent=10)` on the `evaluate()` call (down from the earlier 100). This caps cross-case concurrency at 10.

The resulting peak concurrency is ~10 Gemini API calls, which fits the rate budget. Total wall-clock is comparable to the broken design because the old design spent its time in backoff, not in forward progress.

Lesson for future koan metric work: within-metric parallelism and evaluate()-level parallelism multiply. Budget the peak as (max_concurrent x per-metric-gather-width). If the judge model has a concurrency ceiling, pick one axis to parallelize and keep the other sequential. Koan picks cross-case parallelism as the single axis.
