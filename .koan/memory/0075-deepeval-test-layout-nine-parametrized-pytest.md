---
title: DeepEval test layout -- parametrize + assert_test under `deepeval test run`
  CLI after four reversals
type: decision
created: '2026-04-22T09:16:47Z'
modified: '2026-04-24T05:47:44Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
- 0083-deepevalloghyperparameters-fires-at-module-import.md
- 0082-deepeval-asserttest-wraps-its-test-case-in-a.md
- 0097-evaluate-maxconcurrent-combined-with.md
---

This entry documents the test-module layout of `tests/evals/test_koan.py` and `tests/evals/conftest.py`. Four dated decisions shape the current state.

On 2026-04-22, Leon decided the nine-function shape: one pytest function per `(phase, section)` combination, each parametrized via a session-scoped `case` fixture over `discover_cases(FIXTURES_DIR)`. A session-scoped `harvest(case)` fixture ran `run_koan(case)` once per unique case. Rationale: preserving per-(case, section) granularity in pytest output required distinct function definitions.

On 2026-04-23 morning, during an intake investigating harvest dumps for the three `koan-1` tasks, Leon reversed the nine-function decision. The shape became two parametrized functions: `test_rubric` over `(case, phase, section)` rows and `test_run` over `(case)` rows, both reading from a session-scoped `harvest_cache: dict[tuple, dict]` keyed on `(fixture_id, task_id, case_id)`.

On 2026-04-23 afternoon, Leon reversed the two-function decision. Triggers: `assert_test(tc, metrics)` wraps its case in a singleton `[test_case]` list (memory 82), so DeepEval never parallelized across rows; every `LLMTestCase` used `input="(koan eval harvest)"` without setting `name=""`, collapsing rows on the dashboard (memory 81); `@deepeval.log_hyperparameters` emitted "No hyperparameters logged" warnings under plain pytest (memory 83). The replacement was a single pytest function `test_workflow_suite(harvest_cache)` building ~21 test cases and calling `evaluate(test_cases, metrics, hyperparameters=HYPERPARAMETERS, async_config=AsyncConfig(max_concurrent=10))` exactly once. Metrics were construction-parameterless singletons with `self.skipped = True` for rows where required metadata was absent.

On 2026-04-24, Leon reversed the single-evaluate() decision because DAGMetric requires criteria at construction time and one DAGMetric per criterion is incompatible with `evaluate()`'s single shared metrics list. The shape returned to parametrize + `assert_test` per row: `test_rubric` over `_RUBRIC_ROWS = _build_rubric_rows()` and `test_run` over `_RUN_ROWS = _build_run_rows()`, each calling `assert_test(tc, metrics_for_row)` with a per-row DAGMetric list. Critical companion decision: tests are invoked via `deepeval test run tests/evals/test_koan.py` rather than plain `pytest`. Under the CLI, `pytest_sessionstart` in `deepeval/plugins/plugin.py:20-28` calls `global_test_run_manager.create_test_run(...)` because `get_is_running_deepeval()` returns True (gated on the `DEEPEVAL` env var set exclusively by the CLI at `deepeval/cli/test.py:174`). The shared test_run lets module-level `@deepeval.log_hyperparameters` attach hyperparameters correctly, every per-row `assert_test` accumulate cases into the same run rather than resetting, and `wrap_up_test_run()` upload to Confident AI at session end. Under plain pytest none of these mechanisms fire. Cross-row parallelism was sacrificed: pytest runs parametrized rows sequentially and `assert_test` wraps each case in a singleton, so peak concurrency is now in-row N-metrics instead of across-row N-cases. Metric-eval wall-clock increased ~4x (~100s to ~420s); total suite wall-clock increased ~2x (~7min to ~13min). Leon accepted the regression because within-row parallelism suffices for the Gemini concurrency budget. The `self.skipped` plumbing on judge metrics was removed; programmatic metrics (`DurationMetric`, `TokenCostMetric`, `ToolCallCountMetric`) now raise `ValueError` on missing metadata rather than silently skipping. `DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE=600` is set at the top of `test_koan.py` before any deepeval import.
