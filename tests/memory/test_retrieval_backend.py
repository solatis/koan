from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from koan.memory.retrieval.backend import _rrf_merge, rerank_results
from koan.memory.retrieval.index import RetrievalIndex, _content_hash
from koan.memory.retrieval.types import SearchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".koan" / "memory"
    d.mkdir(parents=True)
    return d


def write_entry(mem_dir: Path, n: int, title: str, body: str, etype: str = "context") -> Path:
    slug = title.lower().replace(" ", "-")
    path = mem_dir / f"{n:04d}-{slug}.md"
    path.write_text(
        f"---\ntitle: {title}\ntype: {etype}\ncreated: 2024-01-01\nmodified: 2024-01-01\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# _content_hash
# ---------------------------------------------------------------------------

def test_content_hash_changes_on_edit(mem_dir: Path) -> None:
    path = write_entry(mem_dir, 1, "Stable entry", "Original body.")
    h1 = _content_hash(path)
    path.write_text(
        "---\ntitle: Stable entry\ntype: context\ncreated: 2024-01-01\nmodified: 2024-01-01\n---\n\nModified body.\n",
        encoding="utf-8",
    )
    h2 = _content_hash(path)
    assert h1 != h2


# ---------------------------------------------------------------------------
# RetrievalIndex sync
# ---------------------------------------------------------------------------

FAKE_VECTOR = [0.1] * 1024


@pytest.mark.anyio
async def test_sync_indexes_new_files(mem_dir: Path) -> None:
    write_entry(mem_dir, 1, "Entry One", "Body of entry one.")
    write_entry(mem_dir, 2, "Entry Two", "Body of entry two.")

    index = RetrievalIndex(mem_dir)

    with patch("koan.memory.retrieval.index._embed_texts", new=AsyncMock(return_value=[FAKE_VECTOR, FAKE_VECTOR])):
        await index.ensure_synced()

    with patch("koan.memory.retrieval.index._embed_texts", new=AsyncMock(return_value=[])):
        rows = await index.dense_search(FAKE_VECTOR, n=10)

    assert len(rows) == 2


@pytest.mark.anyio
async def test_sync_skips_unchanged_files(mem_dir: Path) -> None:
    write_entry(mem_dir, 1, "Stable", "Body.")
    index = RetrievalIndex(mem_dir)

    mock_embed = AsyncMock(return_value=[FAKE_VECTOR])
    with patch("koan.memory.retrieval.index._embed_texts", new=mock_embed):
        await index.ensure_synced()
        # Reset synced flag to force a second sync
        index._synced = False
        await index.ensure_synced()

    # embed called only once (second sync sees matching hash)
    assert mock_embed.call_count == 1


@pytest.mark.anyio
async def test_sync_removes_deleted_files(mem_dir: Path) -> None:
    p1 = write_entry(mem_dir, 1, "Keep", "Body one.")
    p2 = write_entry(mem_dir, 2, "Delete", "Body two.")
    index = RetrievalIndex(mem_dir)

    with patch("koan.memory.retrieval.index._embed_texts", new=AsyncMock(return_value=[FAKE_VECTOR, FAKE_VECTOR])):
        await index.ensure_synced()

    # Delete second file and re-sync
    p2.unlink()
    index._synced = False
    with patch("koan.memory.retrieval.index._embed_texts", new=AsyncMock(return_value=[])):
        await index.ensure_synced()

    rows = await index.dense_search(FAKE_VECTOR, n=10)
    assert len(rows) == 1
    assert rows[0]["entry_id"] == 1


# ---------------------------------------------------------------------------
# _rrf_merge
# ---------------------------------------------------------------------------

def test_rrf_merge_deduplicates() -> None:
    dense = [
        {"entry_id": 1, "body": "b1", "title": "t1", "type": "context"},
        {"entry_id": 2, "body": "b2", "title": "t2", "type": "context"},
    ]
    fts = [
        {"entry_id": 1, "body": "b1", "title": "t1", "type": "context"},
        {"entry_id": 3, "body": "b3", "title": "t3", "type": "context"},
    ]
    merged = _rrf_merge(dense, fts)
    ids = [r["entry_id"] for r in merged]
    # No duplicates
    assert len(ids) == len(set(ids))
    # Entry 1 appears in both lists so has highest score
    assert ids[0] == 1


# ---------------------------------------------------------------------------
# rerank_results
# ---------------------------------------------------------------------------

def _make_candidate(entry_id: int, etype: str = "context") -> dict:
    return {
        "entry_id": entry_id,
        "file_path": "/nonexistent/path.md",
        "title": f"Title {entry_id}",
        "type": etype,
        "created": "2024-01-01",
        "modified": "2024-01-01",
        "body": f"Body for entry {entry_id}.",
        "_rrf_score": 1.0 / (60 + entry_id),
    }


@pytest.mark.anyio
async def test_search_applies_type_filter(mem_dir: Path) -> None:
    write_entry(mem_dir, 1, "Decision A", "Body.", etype="decision")
    write_entry(mem_dir, 2, "Context B", "Body.", etype="context")

    candidates = [
        {**_make_candidate(1), "type": "decision", "file_path": str(mem_dir / "0001-decision-a.md")},
        {**_make_candidate(2), "type": "context", "file_path": str(mem_dir / "0002-context-b.md")},
    ]

    mock_rerank_result = type("R", (), {
        "results": [type("I", (), {"index": 0, "relevance_score": 0.9})()]
    })()

    with patch("koan.memory.retrieval.backend._voyage_api_key", return_value="fake-key"):
        with patch("voyageai.AsyncClient.rerank", new=AsyncMock(return_value=mock_rerank_result)):
            results = await rerank_results("query", candidates, k=5, type_filter="decision")

    assert all(r.entry.type == "decision" for r in results)


@pytest.mark.anyio
async def test_search_returns_top_k(mem_dir: Path) -> None:
    # Write 5 entries
    for i in range(1, 6):
        write_entry(mem_dir, i, f"Entry {i}", f"Body {i}.", etype="context")

    candidates = [
        {**_make_candidate(i), "file_path": str(mem_dir / f"{i:04d}-entry-{i}.md")}
        for i in range(1, 6)
    ]

    # Mock reranker returns top 3 results
    mock_results = [
        type("I", (), {"index": i, "relevance_score": 1.0 - i * 0.1})()
        for i in range(3)
    ]
    mock_rerank_result = type("R", (), {"results": mock_results})()

    with patch("koan.memory.retrieval.backend._voyage_api_key", return_value="fake-key"):
        with patch("voyageai.AsyncClient.rerank", new=AsyncMock(return_value=mock_rerank_result)):
            results = await rerank_results("query", candidates, k=3)

    assert len(results) <= 3
