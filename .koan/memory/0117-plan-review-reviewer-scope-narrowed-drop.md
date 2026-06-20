---
title: 'Plan reviewer scope narrowed: drop executor-resolvable claim verification,
  keep approach/completeness/docstring checks'
type: decision
created: '2026-04-27T16:06:26Z'
modified: '2026-06-20T01:00:51Z'
related:
- 0005-phase-trust-model-plan-review-as-designated.md
- 0038-cross-reference-repetition-in-prompt-instructions.md
- 0110-review-phase-rewrite-or-loop-back-semantics.md
---

On 2026-04-27, Leon narrowed the plan-review phase's evaluation surface (`koan/phases/plan_review.py`). Prior doctrine, formalized 2026-02-10: plan-review was the CRITIC role and "uses the actual codebase as an external tool to check every file path, function name, signature, and type claim in plan.md against reality." Leon's revised framing on 2026-04-27: "issues that would be easy to resolve during execution (incorrect line numbers, import errors, mismatching function names, etc.) should not be flagged -- we want the review focus on issues that matter, not issues that will end up being resolved automatically anyway." Implementation dropped the verify-every-claim mandate and added an explicit DO-NOT-FLAG enumeration: incorrect line numbers, mismatching or renamed function names, file-path typos, missing or wrong imports, syntax errors in illustrative code snippets, and minor wording inconsistencies between plan steps. The reviewer's evaluation dimensions were rewritten to: Approach soundness, Completeness vs `brief.md`, Ordering, Risks, Missing constraints, and Docstring discipline. Rejected alternatives: keep verification but downgrade severity to Minor (the verification work itself is wasted); silent rewrite-without-report (loses signal).

**Update (feat/epoch refactor):** the plan-review phase was removed. Its evaluation surface (approach soundness, completeness vs brief.md, ordering, risks, missing constraints, docstring discipline) and the DO-NOT-FLAG enumeration of executor-resolvable issues now live in the PLAN_REVIEWER charter of the mechanical reviewer sub-agent (koan/phases/reviewer.py, spawned by koan_artifact_write on a plan) and in the producer plan phase that reconciles those findings inline before advancing.
