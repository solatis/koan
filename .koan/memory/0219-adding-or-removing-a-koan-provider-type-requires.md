---
title: Adding or removing a koan provider type requires sweeping the backend dispatch
  tables and frontend copies; a dynamic drift-guard test catches the missing-table
  boot crash but tsc misses the cast-joined and untyped frontend copies
type: procedure
created: '2026-06-14T10:05:51Z'
modified: '2026-06-14T10:05:51Z'
related:
- 0169-reshaping-a-core-config-type-left-stale.md
- 0192-a-clean-slate-config-schema-cutover-is-atomic.md
---

koan's provider-type vocabulary (`ProviderType` and `ALL_PROVIDER_TYPES` in koan/types.py) fans out into hand-maintained dispatch tables that must stay in sync: `_PROVIDER_PREFIX` and `_KEY_REQUIRING_PROVIDERS` (koan/agents/adapter.py), `_VALID_CONNECTION_TYPES` and `LISTING_CAPABLE` (koan/web/app.py), `PROVIDER_ID_MAP` (koan/agents/model_catalog.py), plus the per-provider build/listing/capability dispatch branches. A provider present in the vocabulary but missing from one table raises unknown_provider at runtime or crashes app boot, not a local test. When adding or removing a provider type, maintain the drift-guard test in tests/test_provider_vocabulary.py that ties every derived table to `ALL_PROVIDER_TYPES`. Write it dynamically (`CHAT_PROVIDER_TYPES = set(ALL_PROVIDER_TYPES) - {"voyage"}`, since voyage is embedding-only and absent from the chat build/listing tables) so an add or remove needs no edit to the guard: assert `_VALID_CONNECTION_TYPES == set(ALL_PROVIDER_TYPES)` and `set(_PROVIDER_PREFIX) == CHAT_PROVIDER_TYPES` (bidirectional, catching the missing-table direction), and `_KEY_REQUIRING_PROVIDERS`/`LISTING_CAPABLE <= CHAT_PROVIDER_TYPES` plus key-requiring-disjoint-from-keyless. The frontend hand-syncs provider identity across more copies the same change must sweep: two `ProviderType` definitions (ProviderBadge.tsx and store/index.ts, joined by a cast in App.tsx), three `LISTING_CAPABLE` sets (App.tsx, SettingsPage.tsx, ConnectionForm.tsx), plus `PROVIDER_LABELS`, `CODES`, the badge color, and the ConnectionForm per-provider switch case. `tsc` enforces only the copies typed against `ProviderType` (the `Record<ProviderType, ...>` maps, the exhaustive switch, the `ReadonlySet<ProviderType>` sets in SettingsPage/ConnectionForm); it does NOT catch the store `ProviderType` (cast-joined in App.tsx) or App.tsx's `LISTING_CAPABLE_TYPES` (an untyped `Set<string>`) -- confirm those two by hand. Violating this leaves a desynced table that crashes boot or a stale frontend copy that compiles clean.
