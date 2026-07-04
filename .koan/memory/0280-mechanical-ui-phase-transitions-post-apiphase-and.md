---
title: 'Mechanical UI phase transitions: POST /api/phase and /api/workflow share apply_set_phase/apply_set_workflow
  with the tool handlers, accepted only while parked at a yield, no model turn on
  resume'
type: decision
created: '2026-07-04T01:31:46Z'
modified: '2026-07-04T01:31:46Z'
related:
- 0084-run-clearing-is-frontend-initiated-via-post.md
- 0243-koan-execution-unbundled-into-koanrequestexecutor.md
---

UI-initiated phase transitions in koan -- Leon decided that clicking any phase-transition suggestion (including "done") is mechanical: the frontend POSTs to `/api/phase` (body `{"phase": ...}`), which builds a `ToolDeps` from `app_state` plus the primary orchestrator `AgentState` and delegates to the same shared core `apply_set_phase` the `koan_set_phase` tool handler uses. `POST /api/workflow` mirrors this over `apply_set_workflow` for backend consistency (no UI trigger exists for it). The routes pre-validate with the same shared validators (`is_valid_transition`, `get_workflow`) and additionally inspect the core's return for the recoverable `{"ok": false}` envelope, treating it as route/core validator drift (422, no resume) rather than resolving into an unchanged phase. Mechanical transitions are accepted only while the agent loop is parked at a yield (`yield_future` pending); otherwise the route rejects with 409 -- they are never queued. On resume the loop skips prompt assembly and the LLM turn entirely: it terminates on `done`, or runs the step-0 handshake that injects the new phase's step-1 guidance, so no model turn occurs in the old phase. Free-text suggestions and typed slash commands remain LLM-interpreted via `POST /api/chat`. Alternatives rejected: a parallel HTTP-only implementation of the transition (duplicated validation/state/event logic drifts from the tool path); mechanizing only `/done` and `/execute` (arbitrary inconsistency across phase suggestions); queueing a mid-turn transition for the next end-of-turn (steering-like deferral muddies "mechanical") or applying it immediately mid-turn (yanks `phase_module`/`phase_ctx` out from under a running model turn); resuming with a synthetic prompt so the model gets one turn in the old phase (wasted turn, non-mechanical semantics).
