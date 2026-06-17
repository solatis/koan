from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import voyageai

from koan.logger import get_logger

from ..parser import parse_entry
from .index import RetrievalIndex, _embed_query
from .types import SearchResult

if TYPE_CHECKING:
    from koan.types import ModelSpec

log = get_logger("memory.retrieval.backend")


def _rrf_score(ranks: list[int], k: int = 60) -> float:
    return sum(1.0 / (k + r) for r in ranks)


def _rrf_merge(dense_hits: list[dict], fts_hits: list[dict]) -> list[dict]:
    # Map entry_id -> (row, list of ranks)
    rows: dict[int, dict] = {}
    ranks: dict[int, list[int]] = {}

    for rank, row in enumerate(dense_hits):
        eid = row["entry_id"]
        rows[eid] = row
        ranks.setdefault(eid, []).append(rank)

    for rank, row in enumerate(fts_hits):
        eid = row["entry_id"]
        rows[eid] = row
        ranks.setdefault(eid, []).append(rank)

    merged = []
    for eid, row in rows.items():
        score = _rrf_score(ranks[eid])
        merged.append({**row, "_rrf_score": score})

    merged.sort(key=lambda r: r["_rrf_score"], reverse=True)
    return merged


async def _voyage_rerank(
    query: str, candidates: list[dict], k: int, model: "ModelSpec"
) -> list[dict]:
    """Rerank candidates using the voyage reranker (model='rerank-2.5').

    The embedding ModelSpec provides the api_key for the voyage connection.
    The reranker stays voyage-coupled and always uses model='rerank-2.5'
    (the reranker is not separately configurable, brief D9). The embedding
    model/key arrive via the explicit model parameter; no module global is read.
    """
    log.debug("voyage_rerank: %d candidates, k=%d", len(candidates), k)
    client = voyageai.AsyncClient(api_key=model.api_key)
    result = await client.rerank(
        query=query,
        documents=[c["body"] for c in candidates],
        model="rerank-2.5",
        top_k=k,
    )
    reranked = []
    for item in result.results:
        row = {**candidates[item.index], "_rerank_score": item.relevance_score}
        reranked.append(row)
    return reranked


# search_candidates and rerank_results are split out from search() so the
# RAG pipeline (rag.py) can call search_candidates per generated query, merge
# candidates across queries, then rerank_results once on the merged pool.
# Without the split, the RAG path would run the Voyage reranker N times
# (once per query) or duplicate the reranker logic.
async def search_candidates(
    index: RetrievalIndex, query: str, model: "ModelSpec", n: int = 20
) -> list[dict]:
    """Gather candidates by embedding the query and running hybrid search.

    The embedding model/key arrive via the explicit model parameter.
    """
    query_vec = await _embed_query(query, model)
    dense = await index.dense_search(query_vec, n)
    fts = await index.fts_search(query, n)
    log.debug("search_candidates query=%r dense=%d fts=%d", query, len(dense), len(fts))
    merged = _rrf_merge(dense, fts)
    log.debug("rrf_merge produced %d candidates", len(merged))
    return merged


async def rerank_results(
    query: str,
    candidates: list[dict],
    k: int,
    model: "ModelSpec",
    type_filter: str | None = None,
) -> list[SearchResult]:
    """Rerank candidates using the voyage reranker and return top k results.

    The embedding model/key arrive via the explicit model parameter.
    """
    if type_filter:
        candidates = [c for c in candidates if c["type"] == type_filter]
        log.debug("type_filter=%r narrowed to %d candidates", type_filter, len(candidates))
    if not candidates:
        return []
    reranked = await _voyage_rerank(query, candidates, k, model)
    log.debug("reranked %d candidates to top %d", len(candidates), len(reranked))
    for c in reranked:
        log.debug("  entry_id=%d score=%.4f title=%r", c["entry_id"], c["_rerank_score"], c.get("title", ""))
    results = []
    for c in reranked:
        entry = parse_entry(Path(c["file_path"]))
        results.append(SearchResult(
            entry=entry,
            entry_id=c["entry_id"],
            score=c["_rerank_score"],
        ))
    return results


async def search(
    index: RetrievalIndex,
    query: str,
    model: "ModelSpec",
    k: int = 5,
    type_filter: str | None = None,
) -> list[SearchResult]:
    """Run hybrid search and return top k reranked results.

    The embedding model/key arrive via the explicit model parameter;
    no module global is read.
    """
    await index.ensure_synced(model)
    candidates = await search_candidates(index, query, model, n=20)
    return await rerank_results(query, candidates, k, model, type_filter)
