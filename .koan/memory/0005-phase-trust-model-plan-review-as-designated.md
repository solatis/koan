---
title: Phase trust model -- three adversarial review phases at different abstraction
  levels
type: decision
created: '2026-04-16T07:35:13Z'
modified: '2026-04-26T09:37:55Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The koan phase trust architecture (`docs/phase-trust.md`, `koan/lib/workflows.py`) was designed around an asymmetric verification model. On 2026-02-10, Leon formalized this as part of the initial koan design: phases in the plan pipeline (intake, plan-spec, execute) were built to trust each other outputs without re-verification; only plan-review was designated as the adversarial verifier. Leon documented the rationale in `docs/phase-trust.md`: cross-phase re-verification is the intrinsic self-correction anti-pattern -- the same LLM re-checking its own prior work is more likely to change correct conclusions to incorrect ones than the reverse. Leon gave plan-review the CRITIC role: it uses the actual codebase as an external tool to check every file path, function name, signature, and type claim in `plan.md` against reality.

On 2026-04-23, Leon extended the phase trust model with two additional review phases when implementing the milestones workflow in `koan/lib/workflows.py`. The system gained three adversarial verifiers at different abstraction levels: `milestone-review` (`koan/phases/milestone_review.py`) verifies `milestones.md` for scope, ordering, and gaps (initiative level); `plan-review` (`koan/phases/plan_review.py`) verifies the implementation plan for correctness and feasibility (plan level); `exec-review` (`koan/phases/exec_review.py`) verifies the executor output against the plan, classifying outcomes as Clean execution / Minor deviations / Significant deviations / Incomplete (implementation level). All three shared the CRITIC design as advisory-only with severity-classified findings.

On 2026-04-26, during M4 of the unified-artifact-flow initiative, Leon shifted the doctrine from "advisory only" to "rewrite-or-loop-back" (memory entry on review-phase rewrite-or-loop-back semantics). Review phases now classify each finding as INTERNAL (producer could have caught it from files already loaded -- producer artifact body + `brief.md`) or NEW-FILES-NEEDED (would have required loading additional files). For internal findings, the review phase issues `koan_artifact_write` against the producer's artifact in step 2; for new-files findings, the review phase yields with the producer phase recommended in `koan_yield` suggestions. `docs/phase-trust.md` was rewritten to 221 lines documenting the new doctrine. Permission-fence design: role-level grant + prompt discipline; per-filename allowlist scoping rejected as over-engineering.
