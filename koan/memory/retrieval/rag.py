from __future__ import annotations

from koan.logger import get_logger
from koan.memory.llm import generate as llm_generate

from .backend import rerank_results, search_candidates
from .index import RetrievalIndex
from .types import SearchResult

log = get_logger("memory.retrieval.rag")

_QUERY_GEN_SYSTEM = (
    "You are a search query generator for a project memory system. "
    "Given a retrieval directive and anchor context, produce 1-3 concise search "
    "queries that will retrieve memory entries relevant to the directive. "
    "Output one query per line. No numbering, no bullets, no preamble."
)


async def generate_queries(directive: str, anchor: str) -> list[str]:
    prompt = f"Directive: {directive}\n\nContext:\n{anchor}"
    raw = await llm_generate(prompt, system=_QUERY_GEN_SYSTEM, max_tokens=256)
    lines = [line.strip() for line in raw.splitlines()]
    queries = [q for q in lines if q][:3]
    log.debug("generated %d queries: %s", len(queries), queries)
    return queries


_generate_queries = generate_queries


async def inject(
    index: RetrievalIndex,
    directive: str,
    anchor: str,
    k: int = 5,
) -> list[SearchResult]:
    await index.ensure_synced()
    queries = await _generate_queries(directive, anchor)

    # Gather candidates from each query, merge by entry_id (max RRF score)
    merged: dict[int, dict] = {}
    for query in queries:
        candidates = await search_candidates(index, query, n=20)
        log.debug("query=%r returned %d candidates", query, len(candidates))
        for c in candidates:
            eid = c["entry_id"]
            if eid not in merged or c["_rrf_score"] > merged[eid]["_rrf_score"]:
                merged[eid] = c

    merged_list = sorted(merged.values(), key=lambda r: r["_rrf_score"], reverse=True)
    log.debug("merged pool: %d unique entries", len(merged_list))
    # Rerank against the directive (the human-authored intent statement), not
    # the generated queries. The directive unifies all queries and is what the
    # reranker should optimize for -- one API call instead of N.
    results = await rerank_results(directive, merged_list, k)
    log.debug("reranked to %d results", len(results))
    return results
