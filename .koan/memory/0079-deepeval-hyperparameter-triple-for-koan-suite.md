---
title: DeepEval hyperparameter triple for koan suite -- {orchestrator_model, judge_model,
  koan_git_sha}
type: decision
created: '2026-04-23T06:53:51Z'
modified: '2026-04-23T06:53:51Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
- 0075-deepeval-test-layout-nine-parametrized-pytest.md
---

This entry documents the hyperparameter-logging decision for the koan DeepEval suite at `tests/evals/` and `evals/`. On 2026-04-23, during an intake phase restructuring the eval integration, Leon adopted the three-value hyperparameter triple `{orchestrator_model, judge_model, koan_git_sha}`, tagged once per pytest invocation via `@deepeval.log_hyperparameters`.

Rationale grounded in DeepEval docs at `deepeval.com/guides/guides-optimizing-hyperparameters` and Confident AI's dashboard docs at `confident-ai.com/docs/llm-evaluation/dashboards/model-and-prompt-insights`: hyperparameters are the slicing axis of the "Compare Test Results" page. Test runs with identical hyperparameters are treated as repeat observations; test runs with different values are compared side-by-side. Leon's framing: every pytest invocation is one tagged test run, and the dashboard comparison axis is the hyperparameter values.

`orchestrator_model` captures which LLM drives the orchestrator subagent. `judge_model` captures the grading LLM separately (currently `gemini-3-pro-preview`, fixed; logged so future judge-model changes are traceable). `koan_git_sha` (`git rev-parse HEAD`) captures all code and prompt changes since koan's prompts live in source.

Rejected as hyperparameters on 2026-04-23: `profile` (redundant with `orchestrator_model`, which already captures the runner/model/thinking triple chosen by the profile); `prompt_bundle_sha` (redundant with `koan_git_sha` since koan's prompts are tracked in the same git repo). Rejected as hyperparameters but retained as per-test-case metadata on `LLMTestCase.additional_metadata`: `workflow` (e.g. `'plan'` or `'milestones'`), `directed_phases`, `task_id`, and harvested programmatic measurements (`duration_s`, `token_cost`, `tool_call_count`). These vary per test case within a single pytest invocation, so they belong to the case, not to the run.
