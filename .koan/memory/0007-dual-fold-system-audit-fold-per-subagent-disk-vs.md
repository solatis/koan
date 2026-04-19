---
title: Dual fold system -- audit fold (per-subagent disk) vs projection fold (workflow
  SSE)
type: decision
created: '2026-04-16T07:35:36Z'
modified: '2026-04-16T07:35:36Z'
related:
- 0003-server-authoritative-projection-via-json-patch.md
---

The state-management layer of koan (`koan/audit/fold.py`, `koan/projections.py`) was designed around two independent fold systems. On 2026-03-29, Leon documented the distinction in `docs/architecture.md` (section "Two Fold Systems"). Leon designed the audit fold to process per-subagent audit events from each subagent's `events.jsonl`, materialize a per-subagent `Projection` object written to `state.json` on disk after every event, and serve debugging and post-mortem consumers. Leon designed the projection fold to process workflow-level projection events emitted by `ProjectionStore.push_event()`, maintain a single in-memory `Projection` covering all agents and run state for the entire workflow, and serve the browser frontend via SSE. Leon chose to keep the two systems independent rather than merging them: the audit fold needed per-event disk writes for durability, while the projection fold needed to stay in-memory for SSE streaming throughput. Leon established the rule that state visible only in logs belongs to the audit fold, while state visible in the browser UI belongs to the projection fold.
