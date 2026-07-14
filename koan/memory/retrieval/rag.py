from __future__ import annotations

from koan.logger import get_logger
from koan.memory.llm import generate as llm_generate

from .backend import rerank_results, search_candidates
from .index import RetrievalIndex
from .types import SearchResult

from koan.types import ModelSpec

log = get_logger("memory.retrieval.rag")

_QUERY_GEN_SYSTEM = (
    "You are a search query generator for a project memory system. "
    "Given a retrieval directive and anchor context, produce 1-3 concise search "
    "queries that will retrieve memory entries relevant to the directive. "
    "Output one query per line. No numbering, no bullets, no preamble."
)


async def generate_queries(directive: str, anchor: str, model: ModelSpec) -> list[str]:
    """Ask the memory LLM for 1-3 search queries relevant to the directive.

    The memory_llm model/key arrive via the explicit model parameter;
    no module global is read.

    Output budget is sized for reasoning models: a local reasoning model
    (e.g. Qwen3) spends output tokens on thinking before emitting query lines,
    and the old 256-token cap was exhausted mid-reasoning, raising
    UnexpectedModelBehavior. 2048 gives generous headroom while staying bounded
    to protect paid providers.
    """
    prompt = f"Directive: {directive}\n\nContext:\n{anchor}"
    raw = await llm_generate(prompt, model=model, system=_QUERY_GEN_SYSTEM)
    lines = [line.strip() for line in raw.splitlines()]
    queries = [q for q in lines if q][:3]
    log.debug("generated %d queries: %s", len(queries), queries)
    return queries


_generate_queries = generate_queries


async def inject(
    index: RetrievalIndex,
    embed: ModelSpec,
    llm: ModelSpec,
    directive: str,
    anchor: str,
    k: int = 5,
) -> list[SearchResult]:
    """Run the mechanical RAG injection pipeline.

    embed and llm ModelSpecs arrive via explicit parameters; the caller is
    responsible for resolving and validating them before calling. No module
    global is read.
    """

    await index.ensure_synced(embed)
    queries = await _generate_queries(directive, anchor, llm)

    # Gather candidates from each query, merge by entry_id (max RRF score)
    merged: dict[int, dict] = {}
    for query in queries:
        candidates = await search_candidates(index, query, embed, n=20)
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
    results = await rerank_results(directive, merged_list, k, embed)
    log.debug("reranked to %d results", len(results))
    return results


def render_injection_block(results: list[SearchResult]) -> str:
    """Render SearchResult list as a markdown block for step-1 injection.

    Returns "" when results is empty so the caller can omit the block
    without branching on truthiness elsewhere.
    """
    if not results:
        return ""
    lines: list[str] = [
        "## Relevant memory",
        "",
        "The following memory entries were retrieved based on the retrieval",
        "directive for this phase and the current workflow context. Treat",
        "them as prior knowledge -- decisions, procedures, lessons, and",
        "context from past workflow runs that are likely to matter here.",
        "",
    ]
    for r in results:
        lines.append(f"### {r.entry.title}")
        lines.append(f"*type: {r.entry.type} | modified: {r.entry.modified}*")
        lines.append("")
        lines.append(r.entry.body.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
