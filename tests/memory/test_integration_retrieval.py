from __future__ import annotations

import os
from pathlib import Path

import pytest

from koan.memory.retrieval import RetrievalIndex, inject, search

requires_keys = pytest.mark.skipif(
    not os.environ.get("VOYAGE_API_KEY"),
    reason="VOYAGE_API_KEY required",
)


def _write_entry(mem_dir: Path, n: int, title: str, body: str, etype: str = "context") -> None:
    slug = title.lower().replace(" ", "-")
    path = mem_dir / f"{n:04d}-{slug}.md"
    path.write_text(
        f"---\ntitle: {title}\ntype: {etype}\ncreated: 2024-01-01\nmodified: 2024-01-01\n---\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture
def mem_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".koan" / "memory"
    d.mkdir(parents=True)
    return d


@requires_keys
@pytest.mark.anyio
async def test_end_to_end_search(mem_dir: Path) -> None:
    _write_entry(mem_dir, 1, "Database choice", "We chose PostgreSQL for its ACID guarantees.", "decision")
    _write_entry(mem_dir, 2, "Auth system", "We use JWT tokens for authentication.", "decision")
    _write_entry(mem_dir, 3, "Caching layer", "Redis is used for session caching and rate limiting.", "context")
    _write_entry(mem_dir, 4, "Deployment", "The service is deployed on Kubernetes in AWS.", "context")
    _write_entry(mem_dir, 5, "Testing strategy", "We use pytest for all Python tests.", "procedure")

    index = RetrievalIndex(mem_dir)
    results = await search(index, "caching and Redis session management", k=2)

    assert len(results) > 0
    top_ids = [r.entry_id for r in results]
    assert 3 in top_ids


@requires_keys
@pytest.mark.anyio
async def test_search_type_filter_narrows_results(mem_dir: Path) -> None:
    _write_entry(mem_dir, 1, "Decision one", "We chose React for the frontend.", "decision")
    _write_entry(mem_dir, 2, "Procedure one", "Run pytest to execute all tests.", "procedure")
    _write_entry(mem_dir, 3, "Procedure two", "Use uv run to install dependencies.", "procedure")

    index = RetrievalIndex(mem_dir)
    results = await search(index, "running tests and procedures", k=5, type_filter="procedure")

    assert len(results) > 0
    assert all(r.entry.type == "procedure" for r in results)


@requires_keys
@pytest.mark.anyio
async def test_rag_inject_returns_relevant_entries(mem_dir: Path) -> None:
    _write_entry(mem_dir, 1, "Auth decision", "JWT chosen over sessions for stateless auth.", "decision")
    _write_entry(mem_dir, 2, "DB decision", "PostgreSQL for relational data.", "decision")
    _write_entry(mem_dir, 3, "Caching lesson", "Redis TTL must match session timeout.", "lesson")

    index = RetrievalIndex(mem_dir)
    results = await inject(
        index,
        directive="authentication and session management decisions",
        anchor="implementing the login flow using JWT",
        k=3,
    )

    assert len(results) > 0
    for r in results:
        assert r.entry_id in {1, 2, 3}
