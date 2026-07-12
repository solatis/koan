---
title: Plan prose claims about code behavior must be verified against the plan's own
  code snippets
type: lesson
created: '2026-07-04T11:29:41Z'
modified: '2026-07-04T11:29:41Z'
---

Plan authoring — a plan's prose description stated that single-op exploration entries should use `op.status` (the adapter's derived status field returning `'running'`, `'error'`, or `'done'`) for the `ToolCallRow` status prop. The code snippets throughout the same plan's implementation steps used `status={entry.inFlight ? 'running' : 'done'}` — inline logic that bypassed the adapter entirely. The prose described the desired end state (centralized status derivation through the adapter) while the snippets reflected the starting point (inline status computation). The mechanical plan reviewer caught the inconsistency. Root cause: plan authoring did not keep prose claims and code examples in sync; the prose was written to describe the adapter's intended behavior while the snippets were copied from the pre-extraction code without updating them to match. Prevention: during plan self-review, verify that every code snippet matches the plan's own surrounding prose claims about behavior. A snippet that contradicts the prose it sits inside is a defect regardless of which side is "correct" — the two must agree before the plan advances to execution.
