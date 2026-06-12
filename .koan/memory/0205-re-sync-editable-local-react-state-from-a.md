---
title: Re-sync editable local React state from a projection-derived value on a per-item
  value signature, never on the derived object's identity
type: procedure
created: '2026-06-11T05:08:53Z'
modified: '2026-06-11T05:08:53Z'
related:
- 0204-settingsnew-run-connection-dropdown-silently.md
- 0116-render-loop-in-overallfeedback-masqueraded-as-sse.md
- 0085-mirror-projection-fields-into-ephemeral-zustand.md
---

koan frontend connected components (`ConnectedSettingsPage`, `ConnectedNewRunForm` in `frontend/src/App.tsx`) -- when a connected component holds editable local `useState` seeded from a `settings`-derived `useMemo`, and a `useEffect` re-syncs that local state from the derived value, key the effect on a value signature (`JSON.stringify` of the derived map, or a per-item value compare against a `useRef` of the previous derived snapshot) and re-seed only the items whose value changed. Never key it on the derived object's identity or on `settings`. The wrong approach -- `useEffect(() => setLocal(derived), [derived])` or `[settings]` -- over-fires because `frontend/src/sse/connect.ts` deep-clones and replaces `settings` on every SSE patch, so the derived `useMemo` gets a new identity each patch; the effect then re-runs on unrelated patches (notably the `provider_models_listed` patch from `listConnectionModels`) and wholesale-reseeds local state, wiping an in-progress edit such as a connection chosen but model not yet picked. A wholesale re-seed of every item on any change also clobbers an in-progress edit on item A when an unrelated item B's persisted value changes; the per-item compare avoids that. The value-keyed effect intentionally omits the derived object from its dependency array, so an `// eslint-disable-next-line react-hooks/exhaustive-deps` is expected there.
