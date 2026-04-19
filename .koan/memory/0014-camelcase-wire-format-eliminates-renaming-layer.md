---
title: 'CamelCase wire format: eliminates renaming layer between projection and Zustand
  store'
type: decision
created: '2026-04-16T08:37:35Z'
modified: '2026-04-16T08:37:35Z'
related:
- 0003-server-authoritative-projection-via-json-patch.md
- 0007-dual-fold-system-audit-fold-per-subagent-disk-vs.md
---

The SSE wire format for koan's projection system (`koan/projections.py`, `frontend/src/sse/connect.ts`) was designed to use camelCase keys for all serialized projection fields. On 2026-03-29, Leon documented this decision in `docs/projections.md` (Design Decisions -- "Why camelCase on the wire"). Leon's rationale: emitting snake_case from the server would require a `mapProjectionToStore()` renaming function in the frontend TypeScript plus a `projectionState` shadow object for patch application (patches must apply to the pre-renamed dict, not the renamed Zustand store); every new projection field would require a rename entry in that mapping. Leon identified this mapping layer as frontend business logic, contradicting his "frontend has zero business logic" principle. By adopting camelCase -- via Pydantic's `alias_generator=to_camel` in `KoanBaseModel` (`koan/projections.py`) -- patches produced by `jsonpatch.make_patch()` apply directly to the Zustand store in `frontend/src/store/`, and snapshot state spreads directly into the store at reconnect with no field renaming.
