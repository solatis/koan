---
title: Plan-review produced unverified Critical finding about voyage-4-large; unverified
  bold claims during review cause unnecessary work
type: lesson
created: '2026-04-16T13:30:54Z'
modified: '2026-04-16T13:30:54Z'
---

The plan-review phase for the koan retrieval backend (`koan/memory/retrieval/`) produced an incorrect critical finding on 2026-04-16. The review agent flagged `VOYAGE_DIM = 1024` in `koan/memory/retrieval/index.py` as "Critical," asserting that `voyage-4-large` outputs 2048 dimensions and would cause PyArrow schema mismatches on first index write. The assertion was based on inference from the model name ("large" suggesting larger output size), with no documentation check performed.

The user verified against the Voyage AI documentation and confirmed the constant was correct: `voyage-4-large` supports 256, 512, 1024 (default), and 2048 output dimensions. The plan proceeded unchanged.

Root cause: the reviewer treated an assumption as a verified fact and labeled it "Critical." Unverified bold claims during adversarial review are particularly harmful because high-severity labels override the planner's judgment, create unnecessary revision cycles, and erode trust in the review phase itself. The cascade effect: if the planner had accepted the finding without checking, the schema would have been changed to 2048 dims, breaking compatibility with the voyage-4-large default output.

A review agent should cite the specific documentation, test result, or source code reference that grounds a critical claim. An unverified inference stated at high confidence is worse than a verified minor finding.
