---
title: 'viewingPhaseId: null means "follow active phase" in the frontend conversation
  view; no "all phases" mode'
type: decision
created: '2026-07-02T07:52:15Z'
modified: '2026-07-02T07:52:15Z'
---

Frontend conversation view phase filtering — the user decided that `viewingPhaseId: null` in the Zustand store (`frontend/src/store/index.ts`) now means "follow the active run phase" (filter entries to those whose `phaseId` matches `run.phase`), replacing the previous semantics where null meant "show all entries unfiltered." The "all phases" viewing mode was removed entirely — there is no affordance to view the full accumulated run in a single scroll.

Rationale: the live-mode default of showing all phases in one scroll was confusing during multi-phase runs. Users expect the conversation view to show only the current phase's entries, with the view switching to the new phase on `koan_set_phase` transitions. The change is implemented in `selectFocusedEntries` (`frontend/src/store/selectors.ts`) by adding `s.run?.phase` as a third reselect input and resolving `viewingPhaseId ?? activePhase` as the filter key. The three call sites that write `null` — the phase-change `useEffect` in `ContentStream.tsx`, the ReturnBanner `onClick`, and the `onPhaseClick` handler in `App.tsx` — were already correct; only the meaning of null changed.

Alternatives rejected:
- Sentinel string `'all'` for show-all with null meaning "follow active phase" — required a store type change from `string | null` to `string | 'all' | null`, added complexity for a mode the user did not want, and touched more files.
- Keeping null = "all" and initializing `viewingPhaseId` to the active phase via a mount-effect — required a second write site to patch the default, was fragile on page refresh, and left the "all phases" code path reachable.

Decision surfaced during the plan phase of the UI live-mode phase grouping task, where the user explicitly chose to remove the "all phases" mode rather than keep it as an opt-in toggle.
