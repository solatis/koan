---
title: Rewrite-or-loop-back replaces advisory-only review doctrine; reconciliation
  now lives in producer phases
type: decision
created: '2026-04-26T09:32:48Z'
modified: '2026-06-20T01:00:23Z'
related:
- 0005-phase-trust-model-plan-review-as-designated.md
- 0225-koan-review-and-execution-are-triggered.md
---

On 2026-04-26, Leon shifted the koan review-phase doctrine (`koan/phases/{plan_review,milestone_review,exec_review}.py`, `docs/phase-trust.md`) from "advisory only" to "rewrite-or-loop-back". The change: review phases (`plan-review`, `milestone-review`, `exec-review`) classify each finding in their step 2 as either INTERNAL (the producer could have caught it given files it already loaded -- producer artifact body + `brief.md`) or NEW-FILES-NEEDED (catching it would have required loading additional files). For internal findings, the review phase issues `koan_artifact_write` against the producer's artifact in step 2, fixing the issue in place; for new-files findings, the review phase yields with the producer phase recommended in the `koan_yield` suggestions list (loop-back). Mixed findings produce both behaviours. The classification is LLM judgement, not a heuristic -- alternatives rejected at intake: heuristic-from-references, explicit-manifest, always-rewrite-unless-new-file-cited.

**Update (feat/epoch refactor):** the *-review phases that hosted this doctrine were removed. The INTERNAL-vs-NEW-FILES-NEEDED finding classification and the rewrite-in-place / loop-back behavior now live in the PRODUCER phases (which reconcile the mechanical reviewer findings inline) and in the execute phase inline post-execution review. The reviewer sub-agent spawned by koan_artifact_write returns freeform findings; the producer judges and incorporates them in place before advancing, or writes an immutable remediation successor (e.g. plan-milestone-N-remediation-K.md) when a frozen artifact must change.
