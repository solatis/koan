---
title: Review-phase rewrite-or-loop-back semantics replace advisory-only doctrine
type: decision
created: '2026-04-26T09:32:48Z'
modified: '2026-04-26T09:32:48Z'
related:
- 0005-phase-trust-model.md
---

On 2026-04-26, Leon shifted the koan review-phase doctrine (`koan/phases/{plan_review,milestone_review,exec_review}.py`, `docs/phase-trust.md`) from "advisory only" to "rewrite-or-loop-back". The change: review phases (`plan-review`, `milestone-review`, `exec-review`) classify each finding in their step 2 as either INTERNAL (the producer could have caught it given files it already loaded -- producer artifact body + `brief.md`) or NEW-FILES-NEEDED (catching it would have required loading additional files). For internal findings, the review phase issues `koan_artifact_write` against the producer's artifact in step 2, fixing the issue in place; for new-files findings, the review phase yields with the producer phase recommended in the `koan_yield` suggestions list (loop-back). Mixed findings produce both behaviours -- the rewrite is applied AND the yield recommends loop-back. The classification is LLM judgement, not a heuristic or explicit producer-loaded manifest -- alternatives rejected at intake: heuristic-from-references, explicit-manifest, always-rewrite-unless-new-file-cited. Permission-fence design: a role-level `koan_artifact_write` grant on the orchestrator role suffices, plus prompt discipline; per-filename allowlist scoping was rejected as over-engineering and remains a future enhancement noted in `docs/phase-trust.md`. Step 2 prompts grew substantially across the three review modules -- worth monitoring for prompt-attention dilution. Rewrite + loop-back logic sits BEFORE the `terminal_invoke` directive in step 2; the yield directive renders unchanged. The doctrine supersedes the earlier "advisory only" framing recorded in `0005-phase-trust-model-plan-review-as-designated.md`.
