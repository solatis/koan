---
title: 'tech-plan-review verification authority: scout-authorized codebase verification
  + dropped do-not-flag list (counter-pattern to plan-review)'
type: decision
created: '2026-04-29T06:01:01Z'
modified: '2026-04-29T06:01:01Z'
related:
- 0110-review-phase-rewrite-or-loop-back-semantics.md
- 0117-plan-review-reviewer-scope-narrowed-drop.md
- 0086-phase-module-scope-field-convention-general.md
---

This entry documents the tech-plan-review module's design (`koan/phases/tech_plan_review.py`), added to koan on 2026-04-29. Leon confirmed the design during plan-review when an internal finding surfaced: an earlier draft of plan.md had carried plan-review's "MUST NOT verify file paths or function names against the codebase" rule into tech-plan-review's PHASE_ROLE_CONTEXT spec. The fix applied to plan.md before executor handoff: tech-plan-review's strict rules explicitly drop the do-not-flag-executor-resolvable list (file paths, function names, line numbers, imports, snippet syntax) that plan-review carries, and explicitly authorize and encourage `koan_request_scouts` for verifying integration-point claims in tech-plan.md against the actual codebase. Rationale: architectural review IS exactly the moment when codebase verification matters -- the architecture must integrate with existing structure, and verifying that a proposed component boundary respects existing module boundaries, that a data-model schema aligns with existing tables/types, and that a chosen integration seam exists where the architecture says it does cannot be deferred to the executor. Rejected alternative: copy plan_review.py wholesale and rename -- would have suppressed the verification work tech-plan-review must do. The phase joins plan-review, milestone-review, and exec-review in following the rewrite-or-loop-back doctrine, but its verification authority is the counter-pattern to plan-review's mechanical-claim-deference rule (which defers executor-resolvable issues like file paths and function names). The permission-fence update at koan/lib/permissions.py adds tech-plan-review to _ORCHESTRATOR_SCOUT_PHASES so the scout authorization is structural, not just prompt-level.
