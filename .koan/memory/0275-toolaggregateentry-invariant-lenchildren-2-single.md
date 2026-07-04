---
title: "ToolAggregateEntry invariant len(children) >= 2 \u2014 single exploration\
  \ calls are top-level entries, never single-child aggregates"
type: decision
created: '2026-07-03T04:03:39Z'
modified: '2026-07-03T04:03:39Z'
related:
- 0272-exploration-tool-entry-types-serve-dual-role-top.md
---

The koan projection fold's `ToolAggregateEntry` in `koan/projections.py` — the team decided that every `ToolAggregateEntry` must carry two or more children, enforced by an assertion in `_append_exploration_child`. A single exploration tool call is emitted as a top-level `ConversationEntry`, never wrapped in a single-child aggregate. Rationale: the aggregate card exists to group consecutive exploration calls into a compact summary; a single-child aggregate would render the same information as a standalone `ToolCallRow` but with the aggregate card's heavier chrome, degrading information density with no benefit. The invariant also simplifies the frontend: the `ToolAggregateCard` organism never needs to handle the single-child edge case. Alternatives rejected: allowing single-child aggregates (blurs the semantic distinction between solo and grouped tools and forces every consumer to handle both paths); emitting a different entry type for single versus grouped exploration calls (adds a backend branch for a frontend rendering concern). Decision surfaced during the exploration `ToolAggregateCard` redesign, alongside the unified exploration entry types decision where the six exploration tool types gained their dual top-level/aggregate-child role.
