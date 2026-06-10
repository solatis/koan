---
title: Frontend-read shared state surfaces via the projection (Settings.*), not new
  HTTP read endpoints -- static config, dynamic overlays, and derived surfaces alike
type: decision
created: '2026-04-29T07:23:53Z'
modified: '2026-06-10T22:48:49Z'
related:
- 0184-local-ai-lm-studio-support-keyless-openai.md
- 0195-koans-frontend-profile-management-ui-was-deleted.md
---

The koan projection at `koan/projections.py` (the `Settings` and `Run` snapshot/patch broadcast over SSE) is the canonical channel for shared state the frontend READS from the backend: read data is exposed as a `Settings.*` field populated by an event and a fold case, and new HTTP GET endpoints for such data are rejected. Mutations are the complement -- commands legitimately use HTTP routes (e.g. POST /api/config/models) while reads ride the projection.

On 2026-04-29 Leon established this for static data: the workflows registry from `koan/lib/workflows.py:WORKFLOWS` was exposed as `Settings.workflows` populated by a `workflows_listed` initial event from `_push_initial_config_events` in `koan/web/app.py`, rather than a dedicated GET endpoint. The agent had proposed `/api/workflows`; Leon redirected, reasoning the projection is the canonical shared-state channel and a parallel HTTP discovery surface fits the architecture poorly even for static data. Rejected: (1) a dedicated HTTP endpoint -- duplicates the channel and bypasses the SSE projection; (2) a `Field(default_factory=...)` at construction time -- works for static data but diverges from the `_push_initial_config_events` pattern where the other config surfaces flow through initial events with their own fold cases.

The same rule governs DYNAMIC and DERIVED surfaces, not only static config. The live per-provider model overlay (`provider_models` on `ProviderConfigState`) is delivered through the `provider_models_listed` event into `Settings.provider_models`, not a read endpoint. On 2026-06-10 the 'newest in family' model pins were wired the same way after Leon explicitly directed 'projection, not a separate read endpoint': `_push_provider_models` in `koan/web/app.py` computes per-provider `{family, resolved, resolved_from}` (reusing the recognition layer's family parsing and version ordering) and carries them on the existing `provider_models_listed` event into a new `Settings.provider_families` field, with the fold left a dumb dict->wire pass-through. The pin WRITE reused the existing `setConfiguredModel` command (POST /api/config/models, passing `resolved_from`), confirming the read-via-projection / write-via-HTTP split.

The decision implies the procedural rule: when the frontend needs to READ shared state -- static config, a dynamic overlay, or a derived/computed surface -- route it through a `Settings.*` field plus an event and fold case, never a new HTTP GET; reserve HTTP routes for mutations.
