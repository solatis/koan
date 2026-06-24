---
title: koan milestones are mutable and the milestone phase is one-time; the per-step
  edit gate is relaxed for living-doc families
type: decision
created: '2026-06-22T22:50:26Z'
modified: '2026-06-22T22:50:26Z'
related:
- 0241-koan-artifact-lifecycle-living-documents-with.md
---

koan's milestone handling (`koan/phases/milestone_spec.py`, `koan/tools/koan_tools.py`, `koan/lib/workflows.py`, `koan/tools/artifact_registry.py`) was changed so `milestones.md` is a living document. Leon decided this on 2026-06-22: the milestone phase is entered once per initiative -- the re-entry discard hook (which deleted `milestones.md` and draft plans) and the RE-DECOMPOSE mode were removed; `milestones.md` is thereafter edited in place ad hoc, with the orchestrator adjusting or injecting future milestones and completed milestones preserved by convention. The per-step edit gate (the `out_of_step` check over `edit_steps`) is relaxed for the living-document families (the `plan` family and `milestones`) so they are editable from any phase the orchestrator runs in, while create-step gating is kept so artifacts still originate in the right phase. Backward "falsify" of already-completed work was dropped; adjusting future work is just editing. `is_valid_transition` stays any-to-any-except-self -- only the suggested-default transition lists were pruned of backward edges, keeping the forward `execute -> plan` per-milestone loop. Rationale: the prior re-entry/discard design was severely over-engineered. Alternatives rejected: keep an explicit re-decompose rewrite path; add a mechanical guard blocking edits to completed milestone sections (preservation of the past is a norm, not a gate).
