---
title: phase_summaries dict stored on Run projection, wire-visible
type: decision
created: '2026-04-17T09:37:19Z'
modified: '2026-04-17T09:37:19Z'
related:
- 0007-dual-fold-system-audit-fold-per-subagent-disk-vs-projection-fold-workflow-sse.md
- 0041-per-phase-summary-capture-rides-on-orchestrators.md
---

This entry documents the storage location for koan's per-phase summary state used by mechanical RAG injection. On 2026-04-17, user decided that `phase_summaries: dict[str, str]` lives on the `Run` projection model in `koan/projections.py` and is serialized to the SSE wire alongside every other Run field. Frontend ignores the field for now; future UI work may surface it. Alternatives rejected: storing on `AppState` only (would lose event-log restorability -- the projection is reconstructable from events but AppState is not), or storing on the projection but excluding from `to_wire()` (would break the invariant that the projection IS what the frontend sees, regressing the symmetric fold design captured in entry 7). User stated the wire-visibility "is not a secret, it's just not necessary right now" -- the field is data-only and exposing it carries no risk. Decision surfaced during intake of the RAG-wiring workflow on 2026-04-17.
