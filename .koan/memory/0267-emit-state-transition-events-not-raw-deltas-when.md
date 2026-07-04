---
title: Emit state-transition events, not raw deltas, when the frontend only needs
  binary state indicators from a streaming agent
type: procedure
created: '2026-07-01T13:17:46Z'
modified: '2026-07-01T13:17:46Z'
related:
- 0019-projection-events-record-facts-derived-state.md
---

koan projection system (koan/projections.py, koan/tools/koan_tools.py) —
when adding a streaming state indicator to a ToolKoanEntry result where the
frontend component only needs to know whether the agent is in a binary state
(e.g., thinking / not-thinking), emit transition events (thinking_start /
thinking_end) from the tool handler's trace callback rather than forwarding
every raw agent delta as a projection event.

The wrong approach is forwarding raw deltas directly: each thinking delta
from the agent's PartStartEvent / PartDeltaEvent stream becomes a separate
JSON Patch operation over SSE, generating hundreds of operations for content
the frontend discards (it renders a static "Thinking..." label, not the
actual thinking text). The correct approach tracks an is_thinking boolean in
the callback, emits a single start event on the false→true transition, and
emits a single end event when any non-thinking trace arrives.

Violating this leads to unnecessary JSON Patch volume on the SSE channel,
degrading frontend rendering performance for no user-visible benefit.
