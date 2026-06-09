---
title: Per-phase eval scoring via post-hoc harvest of a full workflow run; mid-run
  stop and freeze/resume remain out of scope
type: decision
created: '2026-04-17T12:14:31Z'
modified: '2026-04-22T09:23:57Z'
---

The koan eval dataset granularity decision was extended on 2026-04-19 and reframed on 2026-04-22. On 2026-04-17, Leon had made the initial choice: each full run covers a workflow end-to-end from task description to final artifact set, with per-phase and per-step checkpointing deferred because mid-run resume required a fragile orchestrator `--resume` flag.

On 2026-04-19, Leon extended that decision to cover per-phase scoring specifically: rather than adding a `stop_after_phase` mechanism to `/api/start-run`, each `(fixture, task)` sample still runs the full workflow and the solver harvests per-phase data post hoc from `ProjectionStore.events` (bucketed by `phase_started` boundaries). Leon's stated rationale: scoring any later phase requires running the earlier phases anyway, so full-run is strictly cheaper than mid-run stop once you are scoring multiple phases. A server-side `stop_after_phase` was considered (would have triggered a `koan_set_phase("done")` redirect inside yolo mode at the target phase boundary) and explicitly rejected on this cost argument.

On 2026-04-22 during the Inspect-to-DeepEval migration, the "Inspect AI Sample" framing was dropped in favor of parametrized pytest cases. A session-scoped `harvest(case)` fixture in `tests/evals/conftest.py` calls `asyncio.run(run_koan(case))` once per unique case, and pytest's parameter-keyed fixture caching lets all nine per-section tests for a given case read the same harvest without re-running koan. The harvest contract (phase-bucketed tool-call events + `artifact_*` events walked against `phase_started` boundaries) is unchanged; only the framework-level plumbing around it changed. Per-phase checkpoint freeze/resume remains deferred for the same 2026-04-17 reason (fragile resume path in the orchestrator CLI).
