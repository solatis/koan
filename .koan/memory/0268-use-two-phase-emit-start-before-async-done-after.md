---
title: "Use two-phase emit (start before async, done after) for running\u2192done\
  \ lifecycle state in the projection fold"
type: procedure
created: '2026-07-01T13:17:46Z'
modified: '2026-07-01T13:17:46Z'
related:
- 0019-projection-events-record-facts-derived-state.md
---

koan projection system (koan/projections.py) — when a ToolKoanEntry result
needs to show running→done lifecycle for an async operation (e.g., a search
query), use a two-phase emit pattern: emit a start event before the async
work begins and a done event after it completes. The projection fold manages
the lifecycle by appending a {status: "running"} entry on the start event
and updating it to {status: "done"} on the done event, matching by scanning
the traces array backwards for the last running entry.

The wrong approach is single-phase emit — emitting only a done event after
the async work completes. This hides the running state from the user, who
sees nothing until the operation finishes, making the tool card appear
unresponsive during the wait.

Violating this leads to tool cards that show no progress indication during
async operations, degrading perceived responsiveness.
