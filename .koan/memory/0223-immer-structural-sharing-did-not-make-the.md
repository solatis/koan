---
title: Immer structural sharing did not make the settings value-signature re-sync
  redundant -- provider_models_listed is a genuine settings change
type: lesson
created: '2026-06-18T00:38:25Z'
modified: '2026-06-18T00:38:25Z'
related:
- 0204-settingsnew-run-connection-dropdown-silently.md
- 0205-re-sync-editable-local-react-state-from-a.md
- 0222-koan-frontend-rendering-reshaped-to-a-reagentre.md
---

When koan's frontend SSE applicator (`frontend/src/sse/connect.ts`) was changed to apply patches with Immer structural sharing -- so `settings` keeps a stable reference across unrelated patches -- it was assumed, as a planning premise, that the value-signature re-sync in `ConnectedSettingsPage` / `ConnectedNewRunForm` (`frontend/src/components/organisms/`) had become redundant and could be simplified to an identity-keyed effect. Reading the code falsified this before any change was made. Root cause: the re-sync's clobber never depended only on the old every-patch `settings` churn; it depends on `provider_models_listed`, a genuine `settings` change emitted by `listConnectionModels` exactly when the user picks a connection before its model. Because the role-slot assignment `useMemo` keys on the whole `settings` object, that event recomputes its identity even under structural sharing, and an identity-keyed re-sync would still wholesale-reseed and wipe the in-progress "connection chosen, model not yet picked" selection (which has no persisted home and lives only in local state). Prevention: the per-item value-signature re-sync was preserved unchanged; the only sound simplification -- narrowing the `useMemo` to the slices it consumes, excluding `providerModels` -- was deferred. General rule: structural sharing removes re-renders caused by UNRELATED patches but not by a RELATED state change that recomputes a coarse `useMemo` over the whole slice; verify which events actually touch a derived value before assuming reference stability protects it.
