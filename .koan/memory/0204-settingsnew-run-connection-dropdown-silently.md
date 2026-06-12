---
title: 'Settings/New-Run connection dropdown silently reverted: an identity-keyed
  re-sync over projection-derived local state is clobbered because the SSE store reissues
  `settings` on every patch'
type: lesson
created: '2026-06-11T05:08:41Z'
modified: '2026-06-11T05:08:41Z'
related:
- 0116-render-loop-in-overallfeedback-masqueraded-as-sse.md
- 0194-removing-a-field-from-the-projection-settingsrun.md
- 0085-mirror-projection-fields-into-ephemeral-zustand.md
- 0195-koans-frontend-profile-management-ui-was-deleted.md
---

koan's frontend model-role configuration UI (`ConnectedSettingsPage` and `ConnectedNewRunForm` in `frontend/src/App.tsx`) -- changing a role's connection dropdown did nothing: the selection snapped back and the model picker never enabled. `ConnectedSettingsPage.onRoleChange`'s `field === 'connection'` branch fetched the connection's model list but never recorded the chosen connection anywhere, and the `assignments` map it rendered from was derived purely from the projection store (`presets['$last']` + `memoryBindings` + `configuredModels`), so a connection chosen before its model had no home and the Select reverted on the next render.

Root cause has two layers. (1) A saved role in koan is a complete `connection:model` pair (persisted via `setConfiguredModel` + `setSlot`/`setMemoryBinding`); a connection alone cannot be persisted, so the "connection chosen, model not yet picked" interim has no persisted home and is held only in local component state. (2) The deeper, reusable mechanism: `frontend/src/sse/connect.ts` applies every SSE patch with `applyPatch(storeState, patch, false, false)` (fast-json-patch, mutate=false, which deep-clones) then `store.setState({ ...storeState })`, so `settings` -- and every `useMemo` derived from it -- gets a new object identity on every patch, not only on the initial snapshot. An identity-keyed re-sync (`useEffect(() => setLocal(derived), [derived])`) therefore re-fires on unrelated patches; specifically the `provider_models_listed` patch that `listConnectionModels` itself triggers re-fires the effect and reverts the just-picked connection.

Fix: hold the assignments in local `useState` seeded from the store-derived map, and re-sync on a `JSON.stringify` value signature applied per slot (re-seed only slots whose derived value changed, comparing against a `useRef` of the previous derived snapshot), so unrelated patches and the persistence of a sibling role cannot clobber an in-progress edit; the connection branch records the selection locally, and the model/thinking branches persist then optimistically reflect.

`ConnectedNewRunForm.onOverrideChange` carried the identical latent bug -- its per-run override re-sync was `useEffect(() => setOverrides(defaultOverrides), [defaultOverrides])`, identity-keyed and equally clobber-prone. The user directed "mirror New Run" as the working reference, but New Run itself was subtly broken; the mirror was corrected to the value-keyed/per-item form rather than copied verbatim, and New Run was then fixed the same way. The meta-lesson: verify that a "working" sibling component is actually correct before mirroring it. The general prevention rule is captured as a paired procedure on re-syncing editable local state from a projection-derived value.
