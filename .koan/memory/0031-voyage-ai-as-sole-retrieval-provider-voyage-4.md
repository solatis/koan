---
title: Voyage AI as sole retrieval provider -- voyage-4-large embedding + rerank-2.5
  reranking, single VOYAGE_API_KEY
type: decision
created: '2026-04-16T13:30:42Z'
modified: '2026-04-16T13:30:42Z'
---

The koan memory retrieval backend (`koan/memory/retrieval/`) chose Voyage AI as its sole external provider for both embedding and reranking. On 2026-04-16, when planning the retrieval backend implementation, the task description had specified Cohere `rerank-v3.5` for reranking (with `COHERE_API_KEY`) alongside Voyage for embedding. The user overrode this during plan-spec and directed consolidation onto Voyage only. Voyage AI's `voyage-4-large` model handles dense embeddings; `rerank-2.5` handles cross-encoder reranking after RRF fusion. Both are accessed via `voyageai.AsyncClient(api_key=VOYAGE_API_KEY)`, requiring only one environment variable.

The user's rationale: a single provider simplifies credential management (one `VOYAGE_API_KEY` instead of two), reduces the Python dependency count (no `cohere` package required alongside `voyageai`), and keeps the full retrieval pipeline within one vendor relationship. The `voyageai` package provides both `AsyncClient.embed()` and `AsyncClient.rerank()` under the same API key.
