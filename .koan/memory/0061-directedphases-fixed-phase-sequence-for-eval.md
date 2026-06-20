---
title: 'directed_phases: Case-attribute-driven fixed phase sequence for eval runner
  runs'
type: decision
created: '2026-04-19T13:38:19Z'
modified: '2026-06-20T03:59:20Z'
related:
- 0049-eval-solver-answers-all-koan-interactive-gates.md
- 0058-yolo-mode-non-interactive-auto-answer-design-for.md
---

The `directed_phases` feature in koan's eval runner (`evals/runner.py`) lets an eval case fix the exact phase sequence a workflow traverses (e.g. `["intake", "plan", "done"]`) so specific phase combinations can be isolated and measured. Leon's requirement was deterministic phase routing under eval. Rejected alternative: relying on suggestion-based yolo steering (`_yolo_yield_response`), because that defers routing to the orchestrator's interpretation of the recommended suggestion text and gives no guarantee which phase is entered next. Mechanism: a pure function `_directed_yolo_response(directed_phases, current_phase)` in `koan/agents/loop.py`. In yolo mode, when `app_state.server.directed_phases` is set, the loop's phase-boundary hand-back calls `_directed_yolo_response` instead of `_yolo_yield_response(suggestions)`; it returns a 'proceed to the next phase' instruction for normal transitions, and a 'workflow is complete -- set the phase to done' instruction when the next entry is the terminal sentinel. Leon decided `koan_set_phase` would NOT be modified to enforce directed phases -- enforcement was out of scope, and eval tests verify instruction-following post-hoc.
