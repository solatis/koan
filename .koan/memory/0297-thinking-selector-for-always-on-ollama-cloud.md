---
title: Thinking selector for always-on ollama cloud models disabled via frontend-only
  gating in the connected layer, not a backend thinking_controllable field
type: decision
created: '2026-07-14T12:02:56Z'
modified: '2026-07-14T12:02:56Z'
related:
- 0127-frontend-read-shared-state-via-projection.md
- 0292-settings-picker-content.md
---

koan's Settings and New Run UI — Leon directed disabling the thinking selector for ollama cloud models whose only thinking mode is `("medium",)` (always-on server-side thinking, no controllable effort). The approach is frontend-only: the connected components (`ConnectedSettingsPage.tsx`, `ConnectedNewRunForm.tsx`) check `conn.route === 'ollama-cloud' && thinkingLevels.length === 1 && thinkingLevels[0] === 'medium'` and pass `thinkingOptions: []` to `RoleRow.tsx`, which renders its existing disabled placeholder when the array is empty. Rationale: the detection is a UI-only concern derivable from data already in the projection (`ConnectionInfo.route` and `CapsInfo.thinkingLevels` on the `settings_listed` snapshot), so it should not widen the backend projection or store surface. Alternatives rejected: (1) a new `thinking_controllable` boolean field on `CapsWire` in `koan/models/capabilities.py` and the projection — rejected because it requires projection + store changes for a UI-only concern, and the frontend already has the data it needs; (2) a new `thinkingDisabled` prop on `RoleRow.tsx` — rejected because the existing `thinkingEnabled = thinkingOptions.length > 0` check already renders the disabled placeholder for an empty array, so a new prop adds interface surface for a case the existing mechanism handles; (3) disabling the selector for all ollama cloud models — rejected because discrete-effort models (gpt-oss, deepseek-pro with multi-mode thinking) may have controllable thinking via the `openai_reasoning_effort` knob. Decision surfaced when Leon identified the always-on thinking behavior during settings UI review and directed removing the non-functional selector.
