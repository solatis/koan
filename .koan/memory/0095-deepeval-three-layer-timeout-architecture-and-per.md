---
title: DeepEval three-layer timeout architecture and per-task override for criteria-sequential
  metrics
type: context
created: '2026-04-23T16:54:44Z'
modified: '2026-04-23T16:54:44Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
---

This entry documents DeepEval's timeout architecture and the environment-variable override that Leon adopted for koan's criteria-sequential judge metrics. Leon distilled the three-layer model and its override hook on 2026-04-23 during DeepEval-migration debugging after the suite's judge metrics repeatedly tripped DeepEval's per-task timeout.

DeepEval (version 3.9.7 as of 2026-04-23) has three distinct timeout layers that interact during `evaluate()` execution:

1. Per-attempt timeout -- 88.5 seconds default. Bounds a single judge LLM call attempt inside a metric's `a_measure()`. Exceeding it raises a retryable timeout.
2. Per-task timeout -- 180 seconds default. Bounds the full `(test_case, metric)` evaluation task, including all retries and any `asyncio.gather` the metric performs internally.
3. Gather-buffer timeout -- 27 seconds. Additional slack DeepEval adds on top of the per-task timeout when wrapping tasks in `asyncio.gather` at the evaluate() level.

Koan's RubricComplianceMetric iterates over each rubric criterion sequentially (to avoid the thundering-herd failure documented in the companion lesson entry). For rubrics with 6+ criteria at ~15-20 seconds per criterion call, total metric duration can exceed the 180-second per-task default before reaching the final criterion. Leon's override adopted on 2026-04-23: set `DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE=600` in the eval environment. Koan sets this in `tests/evals/conftest.py` module-level environment setup before importing deepeval. The 600-second value accommodates an 8-criterion rubric at 60s per criterion plus retry headroom; revise if rubric sizes grow.

The per-attempt timeout is separately overridable via `DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE` but koan has not needed to raise it (Gemini calls return well under 88 seconds in practice). The gather-buffer is not user-configurable; it is a library constant.
