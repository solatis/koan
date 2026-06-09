---
title: /api/memory/entries is the unified memory listing + search HTTP surface; no
  separate /api/memory/search endpoint
type: decision
created: '2026-04-22T04:11:04Z'
modified: '2026-04-22T04:11:04Z'
related:
- 0020-memory-retrieval-static-directive-mechanical.md
- 0053-new-read-only-memory-tools-must-be-added-to.md
---

This entry documents the shape of the memory HTTP read surface for the koan browser frontend, implemented in `koan/web/app.py::api_memory_entries`. On 2026-04-22, Leon decided that the memory search feature exposed to the sidebar UI would extend the existing `GET /api/memory/entries` listing endpoint with optional `q` and `type` query parameters rather than add a second `GET /api/memory/search` route. Leon's rationale: the use case "is effectively 'list memories' with an empty filter", so one URL serving both the unfiltered listing and the hybrid-search result is the simpler surface. Alternative rejected: a second `/api/memory/search` endpoint -- Leon noted no behavioral gain for added code. Implementation: absent or empty `q` returns the existing full listing (optionally narrowed by server-side `type=`); non-empty `q` routes through `koan.memory.retrieval.backend.search(index, q, k=20, type_filter=...)` and returns the reranked results in the existing `MemoryEntryWire` shape (seq, type, title, createdMs, modifiedMs) with the server-supplied order preserved (no client-side re-sort) and no `score` field exposed on the wire. Invalid `type` returns HTTP 422; `RuntimeError` from the search pipeline is logged at warning level and degrades silently to `{"entries": []}`. Distinct from `koan_search` (the agent-invoked MCP tool): `koan_search` serves orchestrator reasoning with typed responses, while this REST surface serves the browser sidebar with the listing wire shape for interactive filtering.
