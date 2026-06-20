---
title: Unverified high-confidence review findings cause unnecessary work; review claims
  need cited evidence
type: lesson
created: '2026-04-16T13:30:54Z'
modified: '2026-06-20T00:41:22Z'
related:
- 0225-koan-review-and-execution-are-triggered.md
- 0117-plan-review-reviewer-scope-narrowed-drop.md
---

A koan artifact reviewer produced an incorrect Critical finding for the retrieval backend (`koan/memory/retrieval/`) on 2026-04-16, during what was then the standalone plan-review phase. The reviewer flagged `VOYAGE_DIM = 1024` in `koan/memory/retrieval/index.py` as Critical, asserting that `voyage-4-large` outputs 2048 dimensions and would cause PyArrow schema mismatches on first index write. The assertion was pure inference from the model name ('large' implying larger output), with no documentation check performed.

Leon verified against the Voyage AI documentation and confirmed the constant was correct: `voyage-4-large` supports 256, 512, 1024 (default), and 2048 output dimensions, and the plan proceeded unchanged.

Root cause: the reviewer treated an assumption as a verified fact and stamped it Critical. Unverified high-confidence claims during adversarial review are especially harmful because a high-severity label overrides the producer's judgment, triggers unnecessary revision cycles, and erodes trust in review -- had the producer accepted the finding unchecked, the schema would have been changed to 2048 dimensions and broken the voyage-4-large default.

Prevention: a review finding cites the specific documentation, test result, or source reference that grounds a Critical or otherwise high-severity claim; an unverified inference stated at high confidence is worse than a verified minor finding. This discipline applies to the mechanical fresh-context reviewer sub-agent koan spawns on `koan_artifact_write` -- whose freeform findings land in a `<stem>.review.md` sidecar for the producer to reconcile -- not to a separate review phase.
