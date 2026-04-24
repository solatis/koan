---
title: Phase trust model -- three adversarial review phases at different abstraction
  levels
type: decision
created: '2026-04-16T07:35:13Z'
modified: '2026-04-23T13:25:01Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The koan phase trust architecture (`docs/phase-trust.md`, `koan/lib/workflows.py`) was designed around an asymmetric verification model. On 2026-02-10, Leon formalized this as part of the initial koan design: phases in the plan pipeline (intake, plan-spec, execute) were built to trust each other outputs without re-verification; only plan-review was designated as the adversarial verifier. Leon documented the rationale in `docs/phase-trust.md`: cross-phase re-verification is the intrinsic self-correction anti-pattern -- the same LLM re-checking its own prior work is more likely to change correct conclusions to incorrect ones than the reverse. Leon gave plan-review the CRITIC role: it uses the actual codebase as an external tool to check every file path, function name, signature, and type claim in `plan.md` against reality. plan-review is advisory only -- it reports findings with severity classification and may suggest looping back to plan-spec, but does not modify `plan.md`.

On 2026-04-23, Leon extended the phase trust model with two additional review phases when implementing the milestones workflow in `koan/lib/workflows.py`. The system now has three adversarial verifiers at different abstraction levels: `milestone-review` (`koan/phases/milestone_review.py`) verifies `milestones.md` for scope, ordering, and gaps (initiative level); `plan-review` (`koan/phases/plan_review.py`) verifies the implementation plan for correctness and feasibility (plan level); `exec-review` (`koan/phases/exec_review.py`) verifies the executor output against the plan, classifying outcomes as Clean execution / Minor deviations / Significant deviations / Incomplete (implementation level). All three share the CRITIC design: advisory-only, severity-classified findings, external verification via codebase reads or bash commands. `exec-review` is `SCOPE="general"` and is wired into both the `plan` and `milestones` workflows.
