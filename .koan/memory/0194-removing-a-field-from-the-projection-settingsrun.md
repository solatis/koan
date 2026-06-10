---
title: Removing a field from the projection Settings/Run wire crashes frontend consumers
  at render; the SSE snapshot replaces the Zustand store wholesale and the untyped
  boundary hides it from tsc
type: lesson
created: '2026-06-09T04:45:54Z'
modified: '2026-06-09T04:45:54Z'
related:
- 0169-reshaping-a-core-config-type-left-stale.md
- 0192-a-clean-slate-config-schema-cutover-is-atomic.md
- 0014-camelcase-wire-format-eliminates-renaming-layer.md
---

koan's frontend mirrors server state in a Zustand store fed by the SSE projection (`frontend/src/sse/connect.ts`, `frontend/src/store/index.ts`). When the backend provider/model config reshape dropped `profiles` and `default_profile` from the `Settings` projection model in `koan/projections.py`, the still-unmigrated frontend kept reading `settings.profiles` in `NewRunForm.tsx` and called `Object.values()` on it, throwing `TypeError: Cannot convert undefined or null to object` and white-screening the landing page on launch.

Root cause has two parts. First, the SSE `snapshot` handler replaces the store's `settings` object wholesale (`store.setState({ ...state })`), so the store initialiser's default (`profiles: {}`) is overwritten by the backend payload, which no longer carries the key -- the field becomes `undefined`, not the default. The store default is therefore illusory: it protects only until the first snapshot lands. Second, the projection-to-Zustand boundary is untyped at runtime (the wire arrives as plain JSON), so `npx tsc --noEmit` does not flag the orphaned read the way it flags a typed reader; the failure surfaces only at render. This is the frontend twin of the backend hazard where a stale read of a removed config field crashes app boot -- the same missed-reader class, one layer further out.

Prevention: when changing the projection wire shape (`Settings` or `Run` in `koan/projections.py`), treat the frontend store types and every consuming component as readers that must migrate in the same change; grep `frontend/src` for the removed field name, and do not trust the store initialiser default to cover a removed field.
