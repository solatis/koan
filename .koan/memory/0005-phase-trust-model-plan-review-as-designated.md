---
title: Phase trust model -- asymmetric verification by a fresh-context reviewer, not
  cross-phase self-re-verification
type: decision
created: '2026-04-16T07:35:13Z'
modified: '2026-06-20T00:41:15Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
- 0110-review-phase-rewrite-or-loop-back-semantics.md
- 0225-koan-review-and-execution-are-triggered.md
---

The koan phase trust architecture (`docs/phase-trust.md`, `koan/lib/workflows.py`) was designed around an asymmetric verification model. On 2026-02-10, Leon formalized this as part of the initial koan design: phases in the plan pipeline (intake, plan-spec, execute) were built to trust each other outputs without re-verification; only plan-review was designated as the adversarial verifier. Leon documented the rationale in `docs/phase-trust.md`: cross-phase re-verification is the intrinsic self-correction anti-pattern -- the same LLM re-checking its own prior work is more likely to change correct conclusions to incorrect ones than the reverse. Leon gave plan-review the CRITIC role; the original 2026-02-10 framing tasked it with using the actual codebase as an external tool to check every file path, function name, signature, and type claim in `plan.md` against reality.

On 2026-04-23, Leon extended the phase trust model with two additional review phases when implementing the milestones workflow in `koan/lib/workflows.py`. The system gained three adversarial verifiers at different abstraction levels: `milestone-review` verifies `milestones.md` for scope, ordering, and gaps (initiative level); `plan-review` verifies the implementation plan for correctness and feasibility (plan level); `exec-review` verifies the executor output against the plan, classifying outcomes as Clean execution / Minor deviations / Significant deviations / Incomplete (implementation level). All three were designed as advisory-only with severity-classified findings, later shifted to "rewrite-or-loop-back". On 2026-04-27, Leon narrowed the plan-review CRITIC role: mechanical claim-verification (file paths, function names, line numbers, imports, snippet syntax) was dropped because such issues are executor-resolvable, refocusing plan-review on approach soundness, completeness vs `brief.md`, ordering, risks, missing constraints, and docstring discipline.

**Update (feat/epoch refactor):** the paired *-review phases (plan-review, milestone-review, tech-plan-review, exec-review) were collapsed. Artifact review now runs MECHANICALLY in a fresh-context read-only reviewer sub-agent spawned by koan_artifact_write (strong model tier, no scouts), and the execute phase performs inline post-execution conformance review (absorbing exec-review). The asymmetric-verification philosophy -- fresh-context adversarial review, producers trusting upstream without re-verification -- survives, but it is realized by the mechanical reviewer plus inline execute review rather than by separate review phases. Producers reconcile the reviewer findings inline before advancing.
