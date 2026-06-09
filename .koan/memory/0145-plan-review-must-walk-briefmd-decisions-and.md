---
title: Plan-review must walk brief.md Decisions and Constraints sections, not only
  Out of Scope
type: lesson
created: '2026-05-08T07:31:23Z'
modified: '2026-05-08T07:31:23Z'
related:
- 0138-plan-spec-adding-a-new-module-logger-violated.md
- 0117-plan-review-reviewer-scope-narrowed-drop-mechanical.md
---

This entry records a planning failure during a koan plan workflow on 2026-05-08 addressing maximization of Claude thinking visibility. The intake phase enumerated in `brief.md` decision 8: "Effort clamping for non-Opus models follows the existing `_best_supported_thinking` pattern. When the role table requests `max` but the resolved model only advertises up to `high`, the clamp lowers the requested effort to the model's maximum supported value." The same brief's Constraints section reinforced this with: "Behaviour on non-Opus models when effort exceeds their advertised supported set must be deterministic and observable -- prefer clamping to silent downgrade."

Despite both signals, plan-spec wrote decision 7 in plan.md: "Claude model `thinking_modes` advertise the full vocabulary uniformly. Letting the SDK handle fallback eliminates koan-side model gating." This explicitly rejected the brief's clamping requirement. Root cause: plan-spec walked the brief's "decisions" looking for guidance on the model-to-parameter mapping (for which the brief said "no model-to-parameter mappings") but did not match each plan-decision back against the brief's own Decisions and Constraints lists. The "no model-to-parameter mappings" directive (about effort assignment) was over-applied to override decision 8's clamping requirement (about model-capability advertising), which is a different concern.

Plan-review caught the violation by walking each brief decision and constraint line by line and matching against each plan decision. The fix restored per-model accuracy in `ClaudeSDKAgent.list_models` (Opus advertises `xhigh`/`max`; Sonnet and Haiku do not) and added the `_claude_clamp` helper in `koan/agents/registry.py` to clamp explicitly via `_best_supported_thinking`, with an INFO log line on actual clamp.

Lesson for plan-review: brief.md Decisions and Constraints sections enforce as authoritatively as Out of Scope. The walking discipline previously applied to Out of Scope generalizes: walk every normative section -- Decisions, Constraints, AND Out of Scope -- line by line and match each plan directive against each brief item. A plan rationalizing why a Decisions or Constraints item should not apply to a specific case is itself the violation; the brief is frozen and is the authority.
