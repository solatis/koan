---
title: "Exploration tool entry types serve dual role \u2014 top-level ConversationEntry\
  \ and ToolAggregateEntry child"
type: decision
created: '2026-07-03T04:03:32Z'
modified: '2026-07-03T04:03:32Z'
---

The koan projection fold's exploration tool types in `koan/projections.py` — the team decided that the six exploration tool entry types (`tool_read`, `tool_grep`, `tool_glob`, `tool_bash`, `tool_web_search`, `tool_web_fetch`) each serve a dual role: valid both as a top-level `ConversationEntry` (a single exploration call renders as a `ToolCallRow` family variant in the frontend) and as a child of `ToolAggregateEntry` (two or more consecutive exploration calls group into a `ToolAggregateCard` organism). Rationale: a single type system avoids duplicating field definitions across separate top-level and aggregate-child types, and the rendering branch — single call → `ToolCallRow`, grouped calls → `ToolAggregateCard` — is a frontend concern that the backend type system should not encode. Alternatives rejected: separate `AggregateChild` types distinct from top-level entries (adds type duplication and forces the frontend to map between two parallel type hierarchies); a flag on `ToolAggregateEntry` marking single-child aggregates (violates the invariant that aggregates represent grouped runs of two or more tools). Decision surfaced during the exploration `ToolAggregateCard` redesign, replacing the prior design where exploration tools had dedicated aggregate-child types (`AggregateReadChild`, `AggregateGrepChild`, `AggregateLsChild`) distinct from their top-level representations.
