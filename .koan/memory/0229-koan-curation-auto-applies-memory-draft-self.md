---
title: koan curation auto-applies memory (draft, self-critique, write directly), retiring
  the propose/approve gate
type: decision
created: '2026-06-19T11:19:25Z'
modified: '2026-06-19T11:19:25Z'
---

koan's curation phase (koan/phases/curation.py) was changed so the curator drafts each entry, self-critiques it against the 9-item draft-quality checklist, and writes it directly via koan_memorize / koan_forget -- the prior propose/approve gate was removed. Retired alongside it: the koan_memory_propose tool and its blocking future, the /api/memory/curation endpoint, the ActiveCurationBatch and Proposal projection types and the memory_curation_started/cleared events and fold cases, and the CurationTakeover approval UI together with its exclusively-used molecule cluster. The self-critique checklist is now the sole quality gate; the wrap-up report (counts of added/updated/deprecated/noop) is kept. Leon directed this. Rationale: the human approve-gate largely duplicated what the self-critique step already enforces, and koan's --yolo mode already auto-approved proposals, so universal direct-write generalizes that behavior. Implemented on the feat/epoch branch.
