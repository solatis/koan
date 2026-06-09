---
title: Run clearing is frontend-initiated via POST /api/run/clear; backend emits authoritative
  `run_cleared` projection event
type: decision
created: '2026-04-23T11:51:46Z'
modified: '2026-04-23T11:51:46Z'
related:
- 0003-server-authoritative-projection-via-json-patch-over-symmetric-dual-fold.md
- 0019-projection-events-record-facts-derived-state-belongs-in-the-fold-function.md
---

This entry documents the run-clearing lifecycle added to the koan workflow engine in `koan/projections.py`, `koan/events.py`, `koan/web/app.py`, and `frontend/src/App.tsx`. On 2026-04-23, Leon decided that after a workflow run completes (the orchestrator exits and the driver emits `workflow_completed`), the frontend -- not the backend -- is responsible for triggering a subsequent `run_cleared` projection event that resets `projection.run = None` and returns the user to the landing page. The mechanism: the frontend starts a 3000 ms timer on `run.completion.success === true`, then calls `POST /api/run/clear`; on failure (`completion.success === false`) the frontend does not auto-navigate, instead exposing an explicit "Back to overview" button in `CompletionView` and switching the `HeaderBar` to navigation mode so nav-link clicks call `api.clearRun()` before `navigate(...)`. Rationale Leon stated during intake: UI timing (banner display duration) is a frontend concern, and the clear is authoritative because a forthcoming multi-run parallel feature needs a projection-level reset rather than a frontend-only store mutation. Alternatives rejected: (1) backend auto-emits `run_cleared` on a server-side delay after `workflow_completed` -- rejected because it couples UI timing to the backend and is un-cancellable; (2) frontend-only zustand clear without a projection event -- rejected because it does not survive SSE reconnect and would break once multiple concurrent runs are tracked server-side. The new `POST /api/run/clear` endpoint is idempotent (returns `{ok: true}` when `projection.run` is already None) and also drains `user_message_buffer`, `steering_queue`, and any outstanding `yield_future` defensively.
