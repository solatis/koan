---
title: Re-sync editable local React state from a projection-derived value on a per-item
  value signature, never on the derived object's identity
type: procedure
created: '2026-06-11T05:08:53Z'
modified: '2026-06-18T00:39:00Z'
related:
- 0204-settingsnew-run-connection-dropdown-silently.md
- 0116-render-loop-in-overallfeedback-masqueraded-as-sse.md
- 0085-mirror-projection-fields-into-ephemeral-zustand.md
- 0223-immer-structural-sharing-did-not-make-the.md
---

koan frontend connected components (`ConnectedSettingsPage`, `ConnectedNewRunForm`, in `frontend/src/components/organisms/`) hold editable local `useState` seeded from a `settings`-derived `useMemo` (role-slot assignments / per-run overrides); a `useEffect` re-syncs that local state when the persisted value changes. Key that effect on a per-item value signature (`JSON.stringify` of each derived item, compared against a `useRef` of the previous derived snapshot) and re-seed only the items whose value changed -- never key it on the derived object's identity or on `settings`. The clobber it prevents: `provider_models_listed` (emitted by `listConnectionModels` when the user picks a connection before its model) is a genuine `settings` change, so the `settings`-derived `useMemo` recomputes a new identity; an identity-keyed re-sync (`useEffect(() => setLocal(derived), [derived])` or `[settings]`) re-fires on it and wholesale-reseeds, wiping the in-progress "connection chosen, model not yet picked" edit (which has no persisted home and lives only in local state). A wholesale re-seed also clobbers an in-progress edit on item A when an unrelated item B's persisted value changes; the per-item compare avoids that. The value-keyed effect intentionally omits the derived object from its dependency array, so an `// eslint-disable-next-line react-hooks/exhaustive-deps` is expected there. Note: changing `connect.ts` to Immer structural-sharing patch application removed the original every-patch `settings` churn (the prior deep-clone-and-spread reissued `settings` on every patch), but it did NOT make this rule redundant -- the `provider_models_listed` clobber above remains, so keep the value-signature keying and do not switch to identity-keying. The only sound simplification is narrowing the derived `useMemo` to the slices it consumes (excluding `providerModels`).
