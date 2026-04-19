---
title: Eval dataset uses full-run fixtures first; per-phase checkpoint freeze deferred
type: decision
created: '2026-04-17T12:14:31Z'
modified: '2026-04-17T12:14:31Z'
---

The koan eval dataset granularity decision was made on 2026-04-17 during the test suite overhaul planning session. Leon decided that the first iteration of the `evals/` framework would use full-run fixtures only: each `Sample` in the Inspect AI Dataset corresponds to one complete koan workflow run from task description to final artifact set. Leon explicitly deferred per-phase and per-step fixture checkpointing. Leon's stated reason: mid-run resume requires the `--resume` flag on the orchestrator CLI, which Leon described as fragile and not ready to instrument. The design direction (per-phase and per-step freeze points) was documented in the plan at `plan.md` for a future iteration but excluded from the initial implementation scope.
