---
title: Eval rubric and case data migrated from `.md` filesystem to Python module constants
  to support per-row DAGMetric construction
type: decision
created: '2026-04-24T05:48:36Z'
modified: '2026-04-24T05:48:36Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
- 0075-deepeval-test-layout-nine-parametrized-pytest.md
- 0059-eval-rubric-layout-per-phase-rubrics-invariant.md
- 0060-eval-fixture-data-model-fixtures-carry-state.md
---

This entry documents the storage format for koan eval rubric criteria and test-case definitions under `evals/`. On 2026-04-24, Leon migrated rubrics and cases from filesystem `.md` files to code-resident Python module constants alongside a refactor of the DAGMetric judge construction. Criteria previously lived at `evals/fixtures/koan-1/rubrics/<phase_dir>/<section>.md` (8 fixture-level files under `intake/` and `plan_spec/` covering sections `summary`, `questions`, `artifacts`, `overall`) and `evals/fixtures/koan-1/tasks/<task>/rubrics/<phase_dir>/<section>.md` (14 task-level addendum files across tasks `add-logs`, `scout-concurrency-settings-only`, `yolo-flag`), with cross-phase rubric bodies embedded as markdown bodies in `evals/fixtures/koan-1/tasks/<task>/cases/<slug>.md` (3 case files, each also carrying YAML frontmatter with `workflow` and `directed_phases`). `load_rubric_criteria(fixture_dir, task_dir, phase, section)` in `evals/scorers.py` did bullet-extraction at measure time; `discover_cases(FIXTURES_DIR)` in `evals/cases.py` walked the filesystem to build the test-case list.

Post-migration on 2026-04-24, these 25 `.md` files are deleted. Rubric data lives at `evals/rubrics.py` as three module-level dicts: `FIXTURE_RUBRICS: dict[tuple[str, str, str], list[str]]` keyed by `(fixture_id, phase, section)`, `TASK_RUBRIC_ADDENDUMS: dict[tuple[str, str, str, str], list[str]]` keyed by `(fixture_id, task_id, phase, section)`, `CROSS_PHASE_RUBRICS: dict[tuple[str, str, str], str]` keyed by `(fixture_id, task_id, case_id)`. Two pure lookup helpers `get_rubric_criteria(fixture_id, task_id, phase, section) -> list[str] | None` (concatenates fixture + addendum) and `get_cross_phase_rubric(fixture_id, task_id, case_id) -> str | None` replace the filesystem-walking helpers. Case definitions live at `evals/cases.py` as `CASES: list[Case]` module constant; the `Case` dataclass lost the `rubric_body` and `case_path` fields; the `parse_case_file`, `load_case`, `discover_cases` helpers were removed.

Rationale: `DAGMetric` requires criteria at construction time (unlike `BaseMetric` subclasses that could read from `test_case.additional_metadata` at measure time). Combined with the decision to use `pytest.mark.parametrize` + `assert_test` per row, criteria must be available at pytest collection time when the parametrized rows are assembled. The previous lazy-filesystem-read approach was fundamentally incompatible with per-row metric-list construction. Secondary benefit accepted: adding or removing a case or criterion is now a single-line code edit rather than a filesystem operation that requires parsing discipline. Retained as filesystem state: `evals/fixtures/koan-1/tasks/<task>/task.md` (task description, still consumed as `LLMTestCase.input`) and `evals/fixtures/koan-1/repo/` (git submodule with fixture snapshot SHA). Rejected alternative considered during plan-review on 2026-04-24: keep frontmatter-only case `.md` files as a discovery surface, which would have left an odd body-less markdown file per case; Leon chose full code migration over split-brain.
