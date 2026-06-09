---
title: Koan memory writing discipline retuned from uniform 5-rule + 100-500 token
  discipline to per-type content guidelines on 2026-05-11
type: decision
created: '2026-05-12T03:14:53Z'
modified: '2026-05-12T03:14:53Z'
related:
- 0021-memory-entry-writing-discipline-temporally.md
---

This entry records the architectural choice that changed koan's memory writing discipline. The discipline lives in `docs/memory-system.md` and the runtime prompt at `koan/phases/curation.py`. On 2026-05-11, the user retuned the discipline -- in force since 2026-04-16 as a uniform 5-rule + 100-500 token specification -- to per-type content guidelines without size bounds.

Choice: keep the neo-Davidsonian bundling principle for decisions (rationale + rejected alternatives + surfacing context stay bundled); loosen for contexts, lessons, and procedures. Drop the explicit "100-500 tokens" range. Drop the rule that every statement must include a YYYY-MM-DD prose date; rely on frontmatter `created`/`modified` for temporal context. Soften attribution from categorical to trust-calibration-driven. Soften the mandatory "first 1-3 sentences situate the entry" opening to a retrieval-anchoring goal. Keep "no forward-looking language", "concrete naming", and "each entry stands alone" unchanged. Add per-type writing guidelines (decision / context / lesson / procedure) with shape templates and a worked example for each. Add explicit title-writing rules because titles participate in the embedding text.

Rationale: the user identified that explicit numeric guidance like "100-500 tokens" biases LLM output toward the stated number; the existing 137 entries averaged ~500 tokens at the high end of the range. Claude Desktop's UI-surfaced memory entries (~120 tokens, factual-style, fact-then-consequence shape) suggested a sharper grain might improve embedding match accuracy. The change is theoretical, not driven by recorded retrieval failures.

Alternatives rejected: structural change (separate `headline` field in the schema with body kept for human reading and headline driving embedding) -- rejected to keep the change writing-discipline-only; abandoning the neo-Davidsonian bundling principle entirely -- rejected because decisions need bundled rationale; bulk rewriting the 137 existing entries -- rejected in favor of forward-only migration; adding a memory-retrieval benchmark before shipping -- rejected because the user chose "ship now, eval later"; uniform discipline with per-type notes appended -- rejected because the user explicitly chose "different guidelines per type".

Decision surfaced during a plan workflow on 2026-05-11 that began with the user observing that koan's entries felt "out of tune" compared to Claude Desktop's. A post-implementation human-review checkpoint after N>=5 new-discipline entries is the success criterion; there is no empirical eval.
