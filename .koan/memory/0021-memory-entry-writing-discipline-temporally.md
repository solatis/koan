---
title: Memory entry writing discipline -- temporally grounded, event-style prose
type: procedure
created: '2026-04-16T09:02:41Z'
modified: '2026-04-16T09:02:41Z'
---

The koan memory system stores entries in `.koan/memory/NNNN-*.md` files within the project repository. On 2026-04-16, the memory system specification in `docs/memory-system.md` established five writing discipline rules for all memory entry bodies. The maintainer recorded the rationale as grounded in SimpleMem's finding (Liu et al., 2026) that removing temporal normalization reduced Temporal F1 by 56.7%. Rule 1: every statement includes a date in YYYY-MM-DD form -- the date the fact became true or was observed. Rule 2: claims are attributed to their source ("user stated", "LLM inferred", "post-mortem identified"); user-stated facts carry higher trust than LLM-inferred facts. Rule 3: no forward-looking language ("we will", "should") -- instead write "On [date], user stated the plan was to..." Rule 4: name things concretely -- not "the database" but "PostgreSQL 16.2" or "the auth service's primary data store." Rule 5: each entry must stand alone, interpretable without any other file, true regardless of when it is read. The specification further established that the first 1-3 sentences situate the entry in the project by naming a specific subsystem, following Anthropic's contextual retrieval technique to reduce retrieval failures by 35%.
