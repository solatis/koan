---
title: DeepEval assert_test wraps its test case in a singleton list; evaluate() is
  the real batch parallelism primitive
type: lesson
created: '2026-04-23T11:05:45Z'
modified: '2026-04-23T11:05:45Z'
related:
- 0075-deepeval-test-layout-nine-parametrized-pytest.md
---

This entry records the parallelism contract of DeepEval's `assert_test` vs `evaluate()` primitives, discovered on 2026-04-23 afternoon while Leon observed live output from `deepeval test run tests/evals/`. The progress-bar header read "Evaluating 1 test case(s) in parallel" for every one of the ~21 pytest parametrized tests in the suite, which triggered the investigation into whether DeepEval was actually batching work.

Reading `deepeval/evaluate/evaluate.py:137` and `:150` showed that `assert_test(test_case, metrics)` always wraps its input in a singleton list: `a_execute_test_cases([test_case], metrics, ...)`. The "1" in the progress-bar header is literal. DeepEval's batch parallelism machinery exists -- `a_execute_test_cases` will run N cases concurrently under `async_config = AsyncConfig(max_concurrent=100)` -- but it only does so when called with a list of more than one test case. Under the pytest-parametrize + assert_test shape, each pytest test hands DeepEval one case at a time, and pytest runs parametrized tests serially by default. Within-case parallelism (N metrics concurrent) and within-metric parallelism (asyncio.gather over per-criterion judge calls inside RubricComplianceMetric) work, but across-case batching does not.

The idiomatic batch primitive is `evaluate(test_cases: List, metrics: List, hyperparameters: Optional[Dict], async_config: Optional[AsyncConfig])`. Called with a list of N test cases, DeepEval's engine runs up to `async_config.max_concurrent` concurrent `(case, metric)` evaluations simultaneously. Lesson applied on 2026-04-23: the koan suite collapsed two parametrized pytest functions (`test_rubric`, `test_run`, totaling ~21 rows) into a single `test_workflow_suite()` that builds all ~21 `LLMTestCase` objects up front and calls `evaluate()` exactly once. Cost: pytest-level `-k` filtering collapses to the function level (there is only one function), so selective re-run of one row requires editing the test. Benefit: DeepEval gets the full batch; the progress bar reads "Evaluating N test case(s) in parallel" with N=21; wall-clock drops substantially for a judge-bound suite. Alternative considered and deferred: keep pytest parametrize and add `pytest-xdist -n N` for process-level parallelism; rejected for this iteration because it does not simultaneously fix the LLMTestCase.name dedupe bug or the hyperparameter-decorator wiring issue (recorded separately).
