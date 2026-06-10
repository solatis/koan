---
title: 'koan frontend model-config UI: profile editor deleted outright, then replaced
  by the connections/configured-models/slots UI wired in App.tsx connected components
  (the 11 components stay store-free)'
type: decision
created: '2026-06-09T04:46:07Z'
modified: '2026-06-10T09:52:54Z'
related:
- 0194-removing-a-field-from-the-projection-settingsrun.md
- 0155-provider-config-reshaped-to-modelspec.md
- 0189-koan-providermodel-config-layered-as-flat.md
- 0196-koan-freezes-a-runs-resolved.md
---

koan's frontend landing page (`NewRunForm.tsx`) and settings page (`SettingsPage.tsx`) once carried a "profile" surface -- a profile selector and a profile/tier editor -- left orphaned after the backend replaced profiles with the connections + configured-models + strong/standard/cheap role-slots + presets model. The orphaned reads crashed the landing page on launch; during the bug investigation Leon directed deleting the frontend profile surface outright (its types, props, state, the `/api/profiles` client functions, and the Settings Profiles card) rather than null-guarding the crash, because a guarded-but-dead profile editor whose Save hits the deleted `/api/profiles` route (HTTP 404) is a worse interim state than no UI.

On 2026-06-10 the planned redesign landed: a provider/model config UI was integrated into the live app. Eleven approved presentational components (atoms RoleMarker/ProviderBadge; molecules InlineNotice/ConnectionRow/ConnectionForm/ModelPicker/RoleRow/RoleCard; organisms NoProvidersBlock/SettingsPage/NewRunForm) are wired to the projection state and the `/api/config/*` client by two connected components in `App.tsx` -- `ConnectedSettingsPage` and `ConnectedNewRunForm`. The presentational/connected boundary is a deliberate invariant: none of the eleven components import the store or the API client; all fetching, per-control auto-save, revert-on-reject error toasts, and run-start wiring live in the App.tsx connected components only. The frontend therefore now HAS a model/provider selection UI -- the earlier "deliberate gap, do not re-add profile-style UI" guidance is superseded, and the new config UI must not be treated as a regression to remove.

A run's models still derive from the active preset in `~/.koan/config.yaml` (`api_start_run` reads `cfg.active`), but the resolved config plus any per-run overrides is now denormalized -- frozen onto `RunState` and serialized to `<run_dir>/run-config.yaml` at start-run -- rather than read live on each agent spawn.
