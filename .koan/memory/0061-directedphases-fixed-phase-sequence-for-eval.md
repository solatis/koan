---
title: 'directed_phases: Case-attribute-driven fixed phase sequence for eval runner
  runs'
type: decision
created: '2026-04-19T13:38:19Z'
modified: '2026-04-22T09:24:29Z'
related:
- 0049-eval-solver-answers-all-koan-interactive-gates.md
- 0058-yolo-mode-non-interactive-auto-answer-design-for.md
---

The `directed_phases` feature in the koan eval runner (`evals/runner.py` as of 2026-04-22, originally `evals/solver.py`) was introduced on 2026-04-19 during a development workflow run by Leon. Leon's stated requirement was that eval tests needed to fix the phase sequence a workflow would traverse (e.g. `["intake", "plan-spec", "done"]`) so that specific phase combinations could be isolated and measured. The alternative -- relying on suggestion-based yolo steering (`_yolo_yield_response` in `koan/web/mcp_endpoint.py`) -- was rejected because suggestion-based steering defers phase routing to the orchestrator's interpretation of the recommended suggestion command text, offering no guarantee about which phase would be entered next.

Initially on 2026-04-19, Leon made `directed_phases` a parameter of the `koan_solver()` factory in `evals/solver.py`. Later the same day, during the case-file reorganization, Leon moved `directed_phases` (alongside `workflow`) from factory argument to Inspect Sample metadata: `evals/dataset.py` populated `state.metadata["directed_phases"]` and `state.metadata["workflow"]` from case-file frontmatter, and `solve()` read them per-sample. On 2026-04-22 during the Inspect-to-DeepEval migration, Leon deleted `evals/dataset.py` and moved those values to direct attributes of the `Case` dataclass in `evals/cases.py`; `run_koan(case)` in `evals/runner.py` reads `case.workflow`, `case.directed_phases`, `case.fixture_dir`, and `case.task_dir` directly. When `case.directed_phases` is non-empty, `app_state.yolo` is set to `True` automatically inside `run_koan`. The feature remains internal-only: `directed_phases` is never exposed via the `/api/start-run` request body or any CLI argument.

Mechanically unchanged: a pure function `_directed_yolo_response(directed_phases, current_phase)` in `koan/web/mcp_endpoint.py` above the `koan_yield` handler. When `app_state.yolo` is `True` and `app_state.directed_phases` is not `None`, the `koan_yield` handler calls `_directed_yolo_response` instead of `_yolo_yield_response(suggestions)`. The function returns `"Proceed to the {next_phase} phase."` for normal transitions, and `'The workflow is complete. Call koan_set_phase("done") to end.'` when the next entry is `"done"`. Leon decided that `koan_set_phase` would not be modified to enforce directed phases -- enforcement was explicitly out of scope and eval tests verify instruction-following post-hoc.

Two validation constraints were established by Leon during the original intake session on 2026-04-19 (preserved in `_validate_directed_phases(phases, available)` which moved from `evals/solver.py` to `evals/runner.py` on 2026-04-22): (1) the last entry in `directed_phases` must be `"done"` (the tombstone); (2) every non-`"done"` entry must exist in `workflow.available_phases`. These are called inside `run_koan` after `api_start_run` resolves `app_state.workflow`.
