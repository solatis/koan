---
title: 'Removing event-sourced projection fields with shared readers: delete the shared
  reader first, then drop each field with its last reader'
type: lesson
created: '2026-06-22T23:56:44Z'
modified: '2026-06-22T23:56:44Z'
---

When koan removed the `frozen` and `executed` fields from `ArtifactInfo` (`koan/projections.py`), the work had to be ordered carefully because both fields had multiple readers: the milestone re-entry discard hook in `koan/tools/koan_tools.py` read BOTH (via `_frozen_artifact_names` and `_executed_artifact_names`), while `frozen` was additionally read by the write/edit validators and `executed` by the execute-target validator. An initial decomposition would have forced two separate units of work to each edit the discard hook (one to drop its `frozen` read, one to delete the hook), an ownership overlap that an adversarial decomposition review caught. The fix: sequence the removal so the SHARED reader (the discard hook) is deleted first, after which each field has a single clean drop point -- `frozen` drops together with the write/edit validators, `executed` drops together with the execute-target validator. Root cause of the near-miss: a field read by N call sites cannot be dropped until all N readers are migrated, and a reader shared across several fields, if left until last, forces multiple change-units to edit the same function. Prevention: when removing an event-sourced projection field, inventory every reader first; delete any reader shared across the fields being dropped before the field-specific readers; and drop each field in the same change as its final reader, keeping the test suite green at each boundary.
