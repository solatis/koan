---
title: Tech-plan reviewer verifies integration-point claims by direct read/bash (no
  scouts), unlike the plan reviewer's defer-to-executor stance
type: decision
created: '2026-04-29T06:01:01Z'
modified: '2026-06-20T01:00:59Z'
related:
- 0110-review-phase-rewrite-or-loop-back-semantics.md
- 0117-plan-review-reviewer-scope-narrowed-drop.md
- 0086-phase-module-scope-field-convention-general.md
---

This entry documents the tech-plan-review module's design (`koan/phases/tech_plan_review.py`), added to koan on 2026-04-29. Leon confirmed the design during plan-review when an internal finding surfaced: an earlier draft had carried plan-review's "MUST NOT verify file paths or function names against the codebase" rule into tech-plan-review's spec. The fix: tech-plan-review's strict rules explicitly drop the do-not-flag-executor-resolvable list (file paths, function names, line numbers, imports, snippet syntax) that plan-review carries, and explicitly authorize and encourage `koan_request_scouts` for verifying integration-point claims in tech-plan.md against the actual codebase. Rationale: architectural review IS exactly the moment when codebase verification matters -- verifying that a proposed component boundary respects existing module boundaries, that a data-model schema aligns with existing tables/types, and that a chosen integration seam exists cannot be deferred to the executor. Rejected alternative: copy plan_review.py wholesale and rename (would have suppressed the verification work tech-plan-review must do).

**Update (feat/epoch refactor):** REVERSED. The tech-plan-review phase was removed, and the new mechanical reviewer model gives NO reviewer scouts -- including the tech-plan reviewer. The TECH_PLAN_REVIEWER charter (koan/phases/reviewer.py) verifies integration-point claims via direct Read/bash and koan_reflect/koan_search in its fresh context, NOT via koan_request_scouts. The earlier rationale (architectural review needs codebase verification, unlike plan-review which defers executor-resolvable claims) still holds, but it is satisfied by the reviewer's own read/bash access rather than by dispatching scouts; the counter-pattern to plan-review is now codebase-verification-via-direct-tools, not via-scouts.
