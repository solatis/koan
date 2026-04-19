---
title: Eval solver uses yolo-mode auto-responses and post-hoc projection harvest for
  per-phase scoring
type: decision
created: '2026-04-17T12:06:18Z'
modified: '2026-04-19T09:49:15Z'
---

The koan eval Solver's interactive-gate-handling strategy in `evals/solver.py` was revised on 2026-04-19 during the per-phase eval framework foundation workflow. On 2026-04-17, Leon originally adopted an SSE-driven design in which the Solver subscribed to `/events`, detected `/run/activeYield` and `/run/focus` patch ops, and POSTed a fixed "Please use your best judgment" message to `/api/chat` and `/api/answer` to unblock every gate. That design was retired because it duplicated gate-detection logic the koan server already performs internally and did not extend cleanly to per-phase scoring.

On 2026-04-19, Leon adopted a two-part replacement: (1) the Solver flips `app_state.yolo = True` on its in-process `AppState` handle before calling `create_app()`, so koan's existing yolo-mode auto-response paths (`_yolo_yield_response` and `_yolo_ask_answer` in `koan/web/mcp_endpoint.py`) resolve every `koan_yield` and `koan_ask_question` with the recommended suggestion or option (falling back to "use your best judgement") without any solver involvement; (2) after `projection.run.completion` is non-null, the Solver harvests per-phase data from `ProjectionStore.events` -- phase-bucketed `koan_ask_question` / `koan_yield` / `koan_set_phase` / `koan_request_scouts` / `koan_memorize` / `koan_search` tool_called events plus `artifact_*` events walked against `phase_started` boundaries -- for downstream per-phase scoring. The surrogate-user-LLM alternative remains rejected for the same reason as before (added cost, non-determinism).
