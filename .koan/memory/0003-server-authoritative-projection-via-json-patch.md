---
title: Server-authoritative projection via JSON Patch over symmetric dual fold
type: decision
created: '2026-04-16T07:13:57Z'
modified: '2026-04-16T07:13:57Z'
---

The koan projection system maintains frontend-visible workflow state for the browser dashboard, served via Server-Sent Events from `koan/projections.py`. On 2026-03-29, Leon decided to replace a dual fold architecture with a server-authoritative JSON Patch model. The prior design maintained two independent fold implementations -- one in Python (`koan/projections.py`) and one in TypeScript (`frontend/src/sse/connect.ts`) -- required to produce identical projections from the same event sequence. Two production bugs traced directly to these folds diverging: fragmented thinking cards in the activity feed, and scout events appearing incorrectly in the primary agent's conversation feed. Leon's decision: Python computes the fold and the RFC 6902 JSON Patch diff after each event; the browser applies patches mechanically via `fast-json-patch` with no fold logic, no event interpretation, and no business rules. Simultaneously, Leon adopted camelCase for all wire-format keys so patches apply directly to the Zustand store without a field-renaming layer. The correctness guarantee is now structural: one fold in one place.
