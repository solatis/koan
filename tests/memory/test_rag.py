from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koan.memory.retrieval.rag import generate_queries, inject


# ---------------------------------------------------------------------------
# generate_queries
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_generate_queries_parses_llm_output() -> None:
    with patch("koan.memory.retrieval.rag.llm_generate", new=AsyncMock(return_value="query one\nquery two\nquery three\n")):
        result = await generate_queries("directive", "anchor")
    assert result == ["query one", "query two", "query three"]


@pytest.mark.anyio
async def test_generate_queries_truncates_to_three() -> None:
    with patch("koan.memory.retrieval.rag.llm_generate", new=AsyncMock(return_value="q1\nq2\nq3\nq4\nq5\n")):
        result = await generate_queries("d", "a")
    assert result == ["q1", "q2", "q3"]


@pytest.mark.anyio
async def test_generate_queries_filters_empty_lines() -> None:
    with patch("koan.memory.retrieval.rag.llm_generate", new=AsyncMock(return_value="q1\n\nq2\n")):
        result = await generate_queries("d", "a")
    assert result == ["q1", "q2"]


# ---------------------------------------------------------------------------
# inject
# ---------------------------------------------------------------------------

def _make_candidate(entry_id: int, rrf_score: float = 0.01) -> dict:
    return {
        "entry_id": entry_id,
        "file_path": "/nonexistent/path.md",
        "title": f"Entry {entry_id}",
        "type": "context",
        "created": "2024-01-01",
        "modified": "2024-01-01",
        "body": f"Body {entry_id}.",
        "_rrf_score": rrf_score,
    }


@pytest.mark.anyio
async def test_inject_calls_search_candidates_per_query(tmp_path: Path) -> None:
    from koan.memory.retrieval.index import RetrievalIndex
    index = RetrievalIndex(tmp_path)
    index._synced = True  # skip actual sync

    fixed_candidates = [_make_candidate(1), _make_candidate(2)]

    mock_sc = AsyncMock(return_value=fixed_candidates)
    mock_rr = AsyncMock(return_value=[])

    with patch("koan.memory.retrieval.rag.llm_generate", new=AsyncMock(return_value="query A\nquery B\n")):
        with patch("koan.memory.retrieval.rag.search_candidates", new=mock_sc):
            with patch("koan.memory.retrieval.rag.rerank_results", new=mock_rr):
                await inject(index, directive="find stuff", anchor="some context")

    # search_candidates called once per query (2 queries)
    assert mock_sc.call_count == 2
    # rerank_results called once with directive as query
    assert mock_rr.call_count == 1
    call_args = mock_rr.call_args
    assert call_args.args[0] == "find stuff"


@pytest.mark.anyio
async def test_inject_deduplicates_across_queries(tmp_path: Path) -> None:
    from koan.memory.retrieval.index import RetrievalIndex
    index = RetrievalIndex(tmp_path)
    index._synced = True

    # Query A returns entry 1 with score 0.05, query B returns entry 1 with score 0.1
    def make_sc_side_effect(*args, **kwargs):
        call_num = make_sc_side_effect.call_count
        make_sc_side_effect.call_count += 1
        if call_num == 0:
            return [_make_candidate(1, rrf_score=0.05), _make_candidate(2, rrf_score=0.02)]
        else:
            return [_make_candidate(1, rrf_score=0.10), _make_candidate(3, rrf_score=0.03)]
    make_sc_side_effect.call_count = 0

    mock_sc = AsyncMock(side_effect=make_sc_side_effect)
    captured_candidates: list[list[dict]] = []

    async def mock_rr(query, candidates, k, *args, **kwargs):
        captured_candidates.append(candidates)
        return []

    with patch("koan.memory.retrieval.rag.llm_generate", new=AsyncMock(return_value="q1\nq2\n")):
        with patch("koan.memory.retrieval.rag.search_candidates", new=mock_sc):
            with patch("koan.memory.retrieval.rag.rerank_results", new=AsyncMock(side_effect=mock_rr)):
                await inject(index, directive="d", anchor="a")

    merged = captured_candidates[0]
    ids = [c["entry_id"] for c in merged]
    # No duplicate entry_ids
    assert len(ids) == len(set(ids))
    # Entry 1 score should be max(0.05, 0.10) = 0.10
    e1 = next(c for c in merged if c["entry_id"] == 1)
    assert abs(e1["_rrf_score"] - 0.10) < 1e-9


@pytest.mark.anyio
async def test_inject_returns_top_k(tmp_path: Path) -> None:
    from koan.memory.retrieval.index import RetrievalIndex
    from koan.memory.retrieval.types import SearchResult
    from koan.memory.types import MemoryEntry

    index = RetrievalIndex(tmp_path)
    index._synced = True

    def make_result(n: int) -> SearchResult:
        return SearchResult(
            entry=MemoryEntry(title=f"T{n}", type="context", body=f"B{n}."),
            entry_id=n,
            score=1.0 - n * 0.1,
        )

    mock_sc = AsyncMock(return_value=[_make_candidate(i) for i in range(1, 6)])
    mock_rr = AsyncMock(return_value=[make_result(i) for i in range(1, 4)])

    with patch("koan.memory.retrieval.rag.llm_generate", new=AsyncMock(return_value="q1\n")):
        with patch("koan.memory.retrieval.rag.search_candidates", new=mock_sc):
            with patch("koan.memory.retrieval.rag.rerank_results", new=mock_rr):
                results = await inject(index, directive="d", anchor="a", k=3)

    assert len(results) <= 3
