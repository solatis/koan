---
title: Proactively capture memory updates for discovered inconsistencies, even outside
  the current task scope
type: procedure
created: '2026-04-23T15:37:44Z'
modified: '2026-06-19T12:20:19Z'
related:
- 0040-memory-captures-persistent-always-true-information-not-future-plans-or-speculative-principles.md
---

This entry records a behavioral rule for koan curation agents and, more broadly, for any koan agent that writes to `.koan/memory/`. On 2026-04-23, Leon stated the procedure during a standalone curation run: when an agent discovers an inconsistency, stale entry, or problem in existing memory -- even when the discovery is incidental to the user's stated task -- the agent must double-check the finding against its source (a direct re-read of the suspect entry in `.koan/memory/NNNN-*.md`, the codebase, or the relevant doc) and then proactively fix it. This holds even when the discovery falls outside the scope of the current task directive, and even when addressing it produces more memory writes than the directive appeared to authorize. Rationale Leon gave: memory quality compounds -- a known-stale entry left in place because it was 'out of scope' becomes a silent defect that future RAG retrievals surface as authoritative, misleading downstream agents. The cost of fixing is small; the cost of leaving decay propagates indefinitely.

**Update (feat/epoch refactor):** koan_memory_propose was removed when curation became auto-apply. The procedure is unchanged in intent, but the fix is now written DIRECTLY via koan_memorize / koan_forget after self-critique, not proposed through koan_memory_propose.
