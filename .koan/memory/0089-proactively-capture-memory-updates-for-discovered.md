---
title: Proactively capture memory updates for discovered inconsistencies, even outside
  the current task scope
type: procedure
created: '2026-04-23T15:37:44Z'
modified: '2026-04-23T15:37:44Z'
related:
- 0040-memory-captures-persistent-always-true-information-not-future-plans-or-speculative-principles.md
---

This entry records a behavioral rule for koan curation agents and, more broadly, for any koan agent that writes to `.koan/memory/` via `koan_memorize` / `koan_forget`. On 2026-04-23, Leon stated the procedure during a standalone curation run: when an agent discovers an inconsistency, stale entry, or problem in existing memory -- even when the discovery is incidental to the user's stated task -- the agent must double-check the finding against its source (a direct re-read of the suspect entry in `.koan/memory/NNNN-*.md`, the codebase, or the relevant doc) and then proactively propose memory updates to fix it via `koan_memory_propose`. This rule holds even when the discovery falls outside the scope of the current task directive, and even when addressing it produces more memory writes than the directive appeared to authorize. Rationale Leon gave: memory quality compounds -- a known-stale entry left in place because it was 'out of scope' becomes a silent defect that future RAG retrievals surface as authoritative, misleading downstream agents. The cost of proposing an extra update is one approval cycle; the cost of leaving decay in the store propagates indefinitely. The rule pairs with existing entry #40 (memory captures persistent 'always true' information) by ensuring that entries which were once true but have since become false are corrected rather than preserved out of task-scope timidity. Procedure surfaced during a 2026-04-23 curation run in which Leon supplied a single-task directive and explicitly authorized the curation agent to expand scope when it finds decay.
