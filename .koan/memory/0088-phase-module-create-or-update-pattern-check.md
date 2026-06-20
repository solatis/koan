---
title: 'Phase module create-or-(re-decompose) pattern: a phase that owns an artifact
  checks existence at step 1 to choose mode; routine post-execution UPDATE lives in
  the execute phase'
type: procedure
created: '2026-04-23T13:25:59Z'
modified: '2026-06-20T04:13:13Z'
---

koan phase modules that own a run-directory artifact choose their mode by checking whether that artifact already exists at step 1, then writing at step 2 -- a reusable pattern Leon designed. The milestone phase (`koan/phases/milestone_spec.py`) is the canonical case, keyed on whether `milestones.md` exists: if it does not, CREATE mode decomposes the initiative; if it does, the non-CREATE branch is RE-DECOMPOSE -- entered when the user explicitly redirects after a major deviation that requires changing the milestone graph itself, revising the sketches but never marking `[done]` or adding Outcome sections (discard of non-executed artifacts on re-entry fires automatically). Routine post-execution UPDATE -- marking a milestone `[done]`, adding its Outcome, advancing the next `[pending]` -- is NOT done by the producer phase; it lives in the execute phase, which always follows. The split keeps the producer focused on decomposition while routine bookkeeping rides with execution.
