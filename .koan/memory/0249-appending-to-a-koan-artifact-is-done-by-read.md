---
title: Appending to a koan artifact is done by read + insert_after on the last line,
  not a dedicated append edit_type
type: decision
created: '2026-06-24T03:41:49Z'
modified: '2026-06-24T03:41:49Z'
related:
- 0175-stateless-hash-anchored-edit-protocol-fnv1a32.md
- 0242-koan-reviewer-findings-are-reconciled-inline-in-a.md
---

koan's hash-anchored artifact edit protocol (`apply_anchored_edit` in `koan/tools/line_anchors.py`, surfaced through `koan_artifact_edit`) has no `append` edit_type. When the inline-review model required the orchestrator to append a `## Review` section to a plan, `milestones.md`, or `tech-plan.md`, Leon decided appending is done by composing existing primitives: read the artifact with `koan_artifact_read` to get current anchors, copy the last line's anchor token, then call `koan_artifact_edit` with `edit_type="insert_after"` on that anchor. This works because an anchor is `fnv1a32(line_content)` -- derived from the line text only, not its position -- so `insert_after` on the last line appends and preserves the trailing newline. Rationale: Leon prefers a small set of flexible building blocks reused via composition over adding new edit verbs. Alternatives rejected: a dedicated `append`/`prepend` edit_type (a new building block for what `insert_after` already does); letting an empty anchor mean end-of-file/start-of-file on the insert verbs (overloads the empty-anchor case, which is an error today); whole-file rewrite via `koan_artifact_write` (abandons surgical edits). Accepted cost: one extra `koan_artifact_read` per append, because `koan_artifact_write` returns only `{ok, filename}` and no anchors. The decision surfaced during a 2026-06-24 run after guidance that instructed a nonexistent `edit_type="append"` crashed the orchestrator.
