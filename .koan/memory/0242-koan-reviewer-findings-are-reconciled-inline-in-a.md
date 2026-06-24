---
title: 'koan reviewer findings are reconciled inline in a ## Review section, replacing
  the .review.md sidecar'
type: decision
created: '2026-06-22T22:49:58Z'
modified: '2026-06-22T22:49:58Z'
related:
- 0241-koan-artifact-lifecycle-living-documents-with.md
---

koan's mechanical-reviewer pipeline (`artifact_write_core` in `koan/tools/koan_tools.py`, `koan/phases/reviewer.py`, and the plan/milestone/tech-plan producer phases) was changed so reviewer findings live inline in the reviewed artifact instead of a koan-owned `.review.md` sidecar. Leon decided this on 2026-06-22: writing a reviewed artifact (a plan, `milestones.md`, or `tech-plan.md`) via `koan_artifact_write` still mechanically spawns a fresh-context read-only reviewer; its freeform findings return to the orchestrator as the tool result, and the orchestrator reconciles each inline -- a `## Review` section in the same artifact with one `### Finding N [INCORPORATED | OVERRULED | ESCALATED]` entry per finding. The sidecar helpers (`is_review_sidecar`, `sidecar_name_for`) and the write/edit special-paths were deleted, so a `*.review.md` name now simply fails the artifact-name grammar. Rationale: the findings were already returned and reconciled in the same turn, so the sidecar was a pure audit copy; an inline section serves the identical purpose with one fewer file and no special-cased filename (the `.review.md` middle dot collided with the `^[a-z0-9][a-z0-9_-]*\.md$` grammar and caused a crash). Alternatives rejected: patch the grammar to admit the sidecar name (fixes only the crash symptom, keeps the coupling); have koan auto-inject the inline section (keeps a koan-owned write path the change is meant to remove).
