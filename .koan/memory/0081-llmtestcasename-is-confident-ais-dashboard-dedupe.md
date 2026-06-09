---
title: LLMTestCase.name is Confident AI's dashboard dedupe axis; identical input strings
  collapse rows into one logical test
type: lesson
created: '2026-04-23T11:05:29Z'
modified: '2026-04-23T11:05:29Z'
related:
- 0075-deepeval-test-layout-nine-parametrized-pytest.md
---

This entry records the root cause of the dashboard-collapse symptom Leon observed against the koan DeepEval suite on 2026-04-23 afternoon. After two redesign iterations aimed at metric-name dimensionality, the Confident AI dashboard still showed one logical test per test-run for each task -- despite pytest having run ~21 parametrized rows per task. Leon's exact framing: "each test run only has a single test -- even though many different rubrics exist, I don't see them."

Root cause: every `LLMTestCase` built by `tests/evals/test_koan.py` used `input="(koan eval harvest)"` as a placeholder and did not set the `name=` field. `LLMTestCase.name` is a first-class Pydantic field in deepeval 3.9.7 (verified via `LLMTestCase.model_fields`) that the Confident AI dashboard uses as the primary test-case identity key. When `name` is absent, the dashboard falls back to grouping by `input`, which was identical across all ~21 rows -- collapsing them into a single logical test per test run. The earlier diagnosis that metric-names were the dimensional axis was correct but secondary: even with correctly dimensional metric names, identical test-case inputs still collapse rows in the dashboard's row axis.

Fix applied on 2026-04-23 afternoon: set `LLMTestCase(name=f"{fixture_id}/{task_id}/{case_id}/{phase}/{section}", ...)` for rubric rows and `name=f"{fixture_id}/{task_id}/{case_id}/workflow"` for run rows. Added a runtime assertion inside `test_workflow_suite`: `names = [tc.name for tc in test_cases]; assert len(set(names)) == len(names), "duplicate LLMTestCase.name values"`. Also moved `token_cost` and `completion_time` from `additional_metadata` onto the first-class `LLMTestCase.token_cost` and `LLMTestCase.completion_time` fields, which the dashboard visualizes natively. Lesson for future DeepEval work in this repo: whenever many test cases will be passed to the same evaluation, audit that every case has a distinct, dashboard-meaningful `name` before assuming a metric-name or input issue is the cause of a collapse.
