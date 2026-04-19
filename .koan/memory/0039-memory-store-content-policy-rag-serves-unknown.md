---
title: Memory store content policy -- RAG serves "unknown unknowns," implementation
  details go near code
type: decision
created: '2026-04-17T04:33:46Z'
modified: '2026-04-17T04:33:46Z'
related:
- 0037-code-comment-vs-memory-entry-filter-comment.md
---

The koan memory store's content policy was clarified by the user on 2026-04-17. The RAG system is intended for "unknown unknown" knowledge -- cross-cutting architecture decisions and constraints that do not have a coherent single location in the codebase. When an LLM is extremely likely to open a file anyway, implementation details should be placed as comments in close proximity to the actual implementation; this approach works well for both humans and LLMs. The memory store should not contain knowledge that an agent would encounter through normal file reading. This principle motivated the COMMENT classification added to koan/phases/curation.py on the same date, which filters single-function and single-module rationale out of memory candidates and into code comments.
