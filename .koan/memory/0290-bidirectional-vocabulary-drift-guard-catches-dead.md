---
title: Bidirectional vocabulary-drift guard catches dead EventType entries, not just
  missing folds
type: lesson
created: '2026-07-13T05:23:35Z'
modified: '2026-07-13T05:23:35Z'
related:
- settings_listed consolidation
- projections.py
- vocabulary drift
---

When adding the vocabulary-drift test `test_every_event_type_has_fold_case_and_vice_versa` in M2 (projections.py), the bidirectional assertion (every EventType literal has a fold case AND every fold case is in EventType) caught `tool_aggregate` — a pre-existing dead EventType entry that was declared in the Literal but never emitted via push_event and had no fold case. This was a latent drift that existed before the M2 consolidation. The lesson: when adding a bidirectional drift guard, expect it to surface pre-existing dead entries, not just the new code's missing folds. The fix is to remove the dead entry (not to add a no-op fold case for it). Future EventType additions must satisfy both directions of the guard.
