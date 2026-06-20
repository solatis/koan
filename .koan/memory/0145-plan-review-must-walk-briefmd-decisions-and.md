---
title: Plan review must walk brief.md Decisions and Constraints sections line by line,
  not only Out of Scope
type: lesson
created: '2026-05-08T07:31:23Z'
modified: '2026-06-20T01:01:07Z'
related:
- 0138-plan-spec-adding-a-new-module-logger-violated.md
- 0117-plan-review-reviewer-scope-narrowed-drop.md
---

This entry records a planning failure during a koan plan workflow on 2026-05-08 addressing maximization of Claude thinking visibility. The intake phase enumerated in `brief.md` a decision that effort clamping for non-Opus models follows the existing `_best_supported_thinking` pattern (lower a requested effort to the model's advertised maximum), reinforced by a Constraints-section line preferring clamping to silent downgrade. Despite both signals, plan-spec wrote a plan decision that "Claude model thinking_modes advertise the full vocabulary uniformly; letting the SDK handle fallback eliminates koan-side model gating" -- explicitly rejecting the brief's clamping requirement. Root cause: plan-spec walked the brief's decisions looking for guidance on one concern but did not match each plan-decision back against the brief's own Decisions and Constraints lists; a directive about a different concern was over-applied to override the clamping requirement. Plan-review caught the violation by walking each brief decision and constraint line by line and matching against each plan decision; the fix restored per-model accuracy and added an explicit clamp helper with an INFO log on actual clamp.

Lesson: brief.md Decisions and Constraints sections enforce as authoritatively as Out of Scope. Walk every normative section -- Decisions, Constraints, AND Out of Scope -- line by line and match each plan directive against each brief item. A plan rationalizing why a Decisions or Constraints item should not apply to a specific case is itself the violation; the brief is frozen and is the authority.

**Update (feat/epoch refactor):** the plan-review phase was removed. The walking discipline now applies to the mechanical PLAN_REVIEWER charter (koan/phases/reviewer.py) and to the producer plan phase that reconciles the reviewer findings inline.
