---
title: Inject only immutable content into an agent's cached context; read mutable/living
  documents on demand instead of injecting them
type: lesson
created: '2026-06-29T08:48:43Z'
modified: '2026-06-29T08:48:43Z'
related:
- 0257-phase-handovers-are-injected-immutable-artifacts.md
---

When koan's phase-handover injection (`koan/tools/handoff_artifacts.py`) was designed, the first proposal over-engineered the mutable case: it would inject `milestones.md` once into the conversation and then exclude already-injected artifacts from the on-demand listing, planning to handle later mutations via re-reads. Leon corrected this to a simpler rule -- inject ONLY immutable artifacts (`brief.md`, `core-flows.md`, `tech-plan.md`), never inject living-document families (the `plan` family, `milestones.md`), and list everything not injected so the living documents are always available and read fresh. Root cause of the over-engineering: conflating "an artifact this phase requires" with "an artifact that must be injected," then trying to keep a mutable injected copy fresh via dedup-plus-re-read instead of simply not injecting it. Prevention: in any cached-context injection scheme, inject only content that is immutable for the time it stays in context; mutable or living content is read on demand at the point of use, so it can never go stale inside the cached prefix and the cache never has to be invalidated to refresh it.
