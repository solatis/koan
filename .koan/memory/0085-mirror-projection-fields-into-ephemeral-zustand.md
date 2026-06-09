---
title: Mirror projection fields into ephemeral zustand state on the rising edge when
  the UI must survive a projection clear
type: procedure
created: '2026-04-23T11:51:50Z'
modified: '2026-04-23T11:51:50Z'
related:
- 0030-do-not-use-destructuring-defaults-as-display-value-fallbacks-for-potentially-absent-react-props.md
- 0019-projection-events-record-facts-derived-state-belongs-in-the-fold-function.md
---

This entry records the rising-edge snapshot pattern added to koan's React frontend on 2026-04-23, during the implementation of the last-completion banner (`frontend/src/App.tsx`, `frontend/src/store/index.ts`, `frontend/src/components/organisms/NewRunForm.tsx`). Leon adopted the following pattern for UI that must display information after the underlying projection field is cleared: add an ephemeral zustand field (e.g. `lastCompletion: CompletionInfo | null` with a `setLastCompletion` setter), then install a `useRef`-guarded `useEffect` in the top-level component that snapshots the projection value on the null->non-null transition only. The ref holds the previous observed value; the effect body checks `prevRef.current === null && current !== null` before calling the setter, preventing re-snapshot on every re-render and on any future event that re-emits the same object. The snapshot state is UI-only: not projected, not persisted (browser refresh clears it), and not mirrored server-side. The pattern applies whenever the backend clears a projection field after an event (e.g. `run_cleared` resets `projection.run`) but the UI needs to render "what just happened" on the next page. Leon rejected localStorage-backed persistence and a new projection field as over-engineering for a dismissible banner whose content is not authoritative. The dismiss action clears the ephemeral field by calling the setter with `null`.
