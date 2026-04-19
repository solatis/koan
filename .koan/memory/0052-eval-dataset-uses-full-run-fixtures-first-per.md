---
title: Per-phase eval scoring via post-hoc harvest of a full workflow run; mid-run
  stop and freeze/resume remain out of scope
type: decision
created: '2026-04-17T12:14:31Z'
modified: '2026-04-19T09:49:29Z'
---

The koan eval dataset granularity decision in `evals/` was extended on 2026-04-19 during the per-phase eval framework foundation workflow. On 2026-04-17, Leon had made the initial choice: each Inspect AI Sample runs a complete workflow from task description to final artifact set, with per-phase and per-step checkpointing deferred because mid-run resume required a fragile orchestrator `--resume` flag.

On 2026-04-19, Leon extended that decision to cover per-phase scoring specifically: rather than adding a `stop_after_phase` mechanism to `/api/start-run`, each `(fixture, task)` Sample still runs the full workflow and the Solver harvests per-phase data post hoc from `ProjectionStore.events` (bucketed by `phase_started` boundaries). Leon's stated rationale: scoring any later phase requires running the earlier phases anyway, so full-run is strictly cheaper than mid-run stop once you are scoring multiple phases. A server-side `stop_after_phase` was considered (would have triggered a `koan_set_phase("done")` redirect inside yolo mode at the target phase boundary) and explicitly rejected on this cost argument. Per-phase checkpoint freeze/resume remains deferred for the same 2026-04-17 reason (fragile resume path in the orchestrator CLI).
