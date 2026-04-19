---
title: Projection events record facts; derived state belongs in the fold function
type: decision
created: '2026-04-16T09:01:03Z'
modified: '2026-04-16T09:01:03Z'
related:
- 0007-dual-fold-system-audit-fold-per-subagent-disk-vs.md
- 0003-server-authoritative-projection-via-json-patch.md
---

The koan projection system in `koan/projections.py` uses an event-sourced fold architecture shared with the audit system in `koan/audit/fold.py`. On 2026-04-16, the architecture documentation in `docs/architecture.md` established the invariant that events record facts -- things that happened -- while derived state belongs in the fold function, not in the event log. The maintainer documented a specific anti-pattern to avoid: emitting a `subagent_idle` event to signal "no agent is currently running." The maintainer recorded that "no agent" is derived from the `agent_exited` event, not a fact in itself, and that emitting it as a separate event conflates the audit log with the projection. The documented correct pattern was: emit `agent_exited`, and let the fold function derive `primary_agent = None` from that event. The architecture documentation also established that `fold()` is required to be a pure function -- the maintainer specified that given the same event sequence it must produce the same projection with no I/O, randomness, or side effects, and that this purity guarantee is broken when derived state appears as events.
