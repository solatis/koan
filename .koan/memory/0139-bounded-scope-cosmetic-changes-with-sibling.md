---
title: 'Bounded-scope cosmetic changes with sibling-pattern risk: add a verification-only
  sweep step with explicit no-silent-edit directive'
type: procedure
created: '2026-05-04T07:56:22Z'
modified: '2026-05-04T07:56:22Z'
related:
- 0114-safe-deletion-patterns-for-milestone-driven.md
- 0122-brief-contradictions-discovered-downstream-are.md
---

This entry documents a plan-authoring procedure observed in koan on 2026-05-04 during a plan workflow that changed user-visible "Runner" labels in `frontend/src/components/SettingsOverlay.tsx`. The intake phase had explicitly scoped the change to `SettingsOverlay.tsx` only, and brief.md had flagged in Open Questions: "Updating user-visible 'runner' labels without touching probe terminology may produce a UI that says 'Agent' in some places and 'Runner' in others if the probe path renders any of these strings."

To handle the open question, plan-spec added a final verification-only step to `plan.md` instructing the executor to grep across `frontend/src/**/*.{ts,tsx}` for `\bRunner\b|\brunner type\b` outside the scoped file. The directive was explicit: if the search finds any user-visible "Runner" label outside `SettingsOverlay.tsx`, the executor MUST report it back in its summary rather than silently editing -- this was the territory flagged as Open Question in `brief.md`. The directive also explicitly excluded touching `RunnerInfo` interface usage, `runnerType` variable references, the `runners` API endpoint, or any internal symbol.

The executor honored this directive. The frontend sweep found two user-visible labels: `<FormRow label="Runner">` in `frontend/src/components/organisms/SettingsPage.tsx` and an error message `'Please select an installation for each required runner type'` in `frontend/src/components/organisms/NewRunForm.tsx`. The executor did NOT edit them; it surfaced them for user decision.

Pattern for future plan-spec work: when a cosmetic or bounded-scope change targets one file but the pattern may exist in siblings, add a final verification-only sweep step. The step (a) names the specific grep pattern, (b) explicitly excludes internal symbols from the match, (c) instructs the executor to report findings rather than edit, (d) cites the brief's Open Question as the user-decision authority. This honors brief scope without losing the safety of catching sibling-pattern drift, and produces explicit user-visible output rather than silent scope creep.
