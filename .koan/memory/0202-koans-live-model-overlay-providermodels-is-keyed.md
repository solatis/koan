---
title: koan's live model overlay (provider_models) is keyed by connection id, not
  provider type, so same-type connections keep independent model lists
type: decision
created: '2026-06-11T02:49:49Z'
modified: '2026-06-11T02:49:49Z'
related:
- 0184-local-ai-lm-studio-support-keyless-openai.md
- 0127-static-shared-state-surfaces-via-projection.md
- 0195-koans-frontend-profile-management-ui-was-deleted.md
- 0183-koan-does-not-validate-provider-api-keys-on-save.md
---

koan's live model overlay -- `provider_models` on `ProviderConfigState` (`koan/state.py`), surfaced through the `provider_models_listed` projection event into `Settings.provider_models` and `Settings.provider_families` -- is keyed by connection id rather than by provider type. The wire models `ProviderModelWire` and `ProviderFamilyWire` (`koan/projections.py`) carry a `connection_id` field (camelCase `connectionId` on the SSE wire); `_push_provider_models` (`koan/web/app.py`) stamps it onto each model and family from the overlay dict key; and `buildConnectionViews` (`frontend/src/App.tsx`) joins a connection's live models and newest-in-family pins by `connectionId === conn.id`. Rationale: the overlay was previously keyed by provider type, so listing a second connection of the same type (e.g. two OpenAI accounts with different keys) overwrote the first's model list and the frontend showed both connections the same list. The user accepted this re-keying into scope on 2026-06-11 -- a latent collision surfaced during investigation of a settings bug, not a separately reported defect. Alternative rejected: leaving the overlay keyed by provider type. Two refresh facts hold alongside: a connection save schedules a best-effort, non-blocking `asyncio.create_task(_refresh_one_provider_models(...))` for listing-capable types (it never blocks the save response or surfaces a listing error, preserving the no-validation-on-save rule), and the explicit Test action lists synchronously and returns `{ok: true, count: N}` so the badge shows the real model count. This refines the earlier description of `provider_models` as a per-provider overlay.
