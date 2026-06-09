---
title: 'plan-review reviewer scope narrowed: drop mechanical claim verification; add
  docstring-discipline check'
type: decision
created: '2026-04-27T16:06:26Z'
modified: '2026-04-27T16:06:26Z'
related:
- 0005-phase-trust-model-plan-review-as-designated.md
- 0038-cross-reference-repetition-in-prompt-instructions.md
- 0110-review-phase-rewrite-or-loop-back-semantics.md
---

On 2026-04-27, Leon narrowed the plan-review phase's evaluation surface (`koan/phases/plan_review.py`). Prior doctrine, formalized 2026-02-10: plan-review was the CRITIC role and "uses the actual codebase as an external tool to check every file path, function name, signature, and type claim in plan.md against reality." Leon's revised framing on 2026-04-27: "issues that would be easy to resolve during execution (e.g. incorrect line numbers, import errors, mismatching function names, etc.) should not be flagged -- they're minor, not worthy of fixing. ... we want the review focus on issues that matter, not issues that will end up being resolved automatically anyway." The implementation, applied to `koan/phases/plan_review.py` `PHASE_ROLE_CONTEXT` and `step_guidance(2, ctx)`, dropped the verify-every-claim mandate and added an explicit DO-NOT-FLAG enumeration listing: incorrect line numbers, mismatching or renamed function names, file-path typos, missing or wrong imports, syntax errors in illustrative code snippets, and minor wording inconsistencies between plan steps. The reviewer's evaluation dimensions were rewritten to: Approach soundness, Completeness vs `brief.md`, Ordering, Risks, Missing constraints, and Docstring discipline (a new dimension that flags any newly-added or modified function in the plan whose Implementation step lacks a docstring directive). Rationale Leon endorsed: mechanical references are resolved automatically by the executor at write time, so reviewer attention spent verifying them is wasted; loop-back rounds caused by such findings add no value. Rejected alternatives: (a) keep verification but downgrade severity to Minor -- rejected because the verification work itself is wasted, not just the reporting; (b) silent rewrite-without-report by the reviewer -- rejected because it loses signal. The doctrine update was applied with cross-reference repetition: the DO-NOT-FLAG enumeration appears in `PHASE_ROLE_CONTEXT` and again at step 2 of `step_guidance`.
