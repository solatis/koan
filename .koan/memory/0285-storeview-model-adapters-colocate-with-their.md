---
title: "Store\u2192view-model adapters colocate with their grouping utilities when\
  \ they form halves of the same pipeline"
type: decision
created: '2026-07-04T11:29:41Z'
modified: '2026-07-04T11:29:41Z'
---

Frontend component architecture — the team adopted a colocation rule for store→view-model adapter modules: when an adapter maps store types to view-model types and feeds its output into a grouping utility, the two files live side by side in the same directory because they are halves of the same pipeline. The concrete instance: `frontend/src/components/organisms/explorationAdapter.ts` (maps `ExplorationChild[]` → `ExplorationOp[]`) was placed next to `toolAggregateGrouping.ts` (groups `ExplorationOp[]` → `FamilyGroup[]`) under `frontend/src/components/organisms/`. Rationale: the adapter and the grouping utility share the `ExplorationOp` type as their interface contract; colocating them makes the pipeline boundary visible in the file tree and keeps the type definition, the mapping, and the grouping in one discoverable cluster. Alternatives rejected: placing the adapter in a `src/utils/` directory (does not exist in the koan frontend and would scatter pipeline halves across unrelated directory trees); placing it in a `src/components/lib/` directory (does not exist); keeping the adapter functions inline in `ContentStream.tsx` (the adapter is consumed by both the aggregate-card rendering path and the single-op `ToolCallRow` family-variant path — a shared module prevents format drift between the two consumers). Decision surfaced during the ToolAggregateCard integration workflow when the four adapter functions (`toExplorationOp`, `runningLabelFor`, `findRunningChild`, `aggregateElapsedMs`) were extracted from `ContentStream.tsx`.
