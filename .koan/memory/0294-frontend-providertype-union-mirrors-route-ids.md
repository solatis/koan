---
title: "Frontend ProviderType union mirrors route IDs from koan/models/routes.py,\
  \ not provider labels \u2014 the contract between backend ConnectionWire.route and\
  \ the frontend type system"
type: decision
created: '2026-07-13T08:29:54Z'
modified: '2026-07-13T08:29:54Z'
related:
- 0219-adding-or-removing-a-koan-provider-type-requires.md
- 0291-settings-projection-consolidated-to-one.md
---

koan's frontend provider-type vocabulary — the `ProviderType` union in both `frontend/src/components/atoms/ProviderBadge.tsx` and `frontend/src/store/index.ts` uses route IDs from `koan/models/routes.py` (e.g., `'bedrock-converse'`, not `'bedrock'`), matching the `ConnectionWire.route` field in the `settings_listed` projection event. The `CODES` record (two-letter badge codes), `PROVIDER_LABELS` (display names), the CSS class in `ProviderBadge.css`, and the per-provider switch in `ConnectionForm.tsx` all key on these route IDs. The `LISTING_CAPABLE` set in `frontend/src/components/organisms/modelConfig.ts` (a local non-exported constant) also uses route IDs to gate which connections show the Test button. Rationale: route IDs are the sole validation source per the route registry in `koan/models/routes.py`; using them directly in the frontend eliminates a renaming layer between the projection wire format and the Zustand store. The `ConnectionWire.route` field carries the route ID, and the frontend `ProviderType` union must match it exactly — a mismatch produces a store that cannot resolve the connection's provider type. Alternatives rejected: a separate frontend provider-label vocabulary mapped from route IDs — rejected because it adds a mapping layer with no benefit when the route ID is already the stable identifier. Decision surfaced during the frontend Settings cutover when `buildConnectionViews()` was reduced to a trivial selector over `offerings_by_connection`; the route-ID union was the natural type for the selector's input.
