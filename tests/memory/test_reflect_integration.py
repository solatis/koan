# Integration test for run_reflect_agent.
# Requires GEMINI_API_KEY (or GOOGLE_API_KEY) and VOYAGE_API_KEY.
# These tests are skipped in CI unless the keys are present.
# Primary evaluation path is evals/; this test exists as a smoke check.

from __future__ import annotations

import os
from pathlib import Path

import pytest

from koan.memory.retrieval import RetrievalIndex, run_reflect_agent, ReflectTraceEvent

_SKIP_NO_KEYS = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    or not os.environ.get("VOYAGE_API_KEY"),
    reason="GEMINI_API_KEY and VOYAGE_API_KEY required for reflect integration tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_entry(
    mem_dir: Path,
    n: int,
    title: str,
    body: str,
    etype: str = "context",
) -> None:
    slug = title.lower().replace(" ", "-")
    path = mem_dir / f"{n:04d}-{slug}.md"
    # Use full ISO timestamps so iso_to_ms produces deterministic positive values.
    path.write_text(
        f"---\ntitle: {title}\ntype: {etype}\ncreated: 2024-01-01T00:00:00Z\nmodified: 2024-01-01T00:00:00Z\n---\n\n{body}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".koan" / "memory"
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

@_SKIP_NO_KEYS
@pytest.mark.anyio
async def test_reflect_cites_fixture_entries(mem_dir: Path) -> None:
    """run_reflect_agent returns citations that all come from the fixture entry set."""
    # Five entries across three types so the model has enough to synthesize.
    _write_entry(
        mem_dir, 1,
        "Vector embedding model",
        "The project uses VoyageAI voyage-4-large for dense embeddings. "
        "This was chosen for its high accuracy on code and technical prose.",
        etype="decision",
    )
    _write_entry(
        mem_dir, 2,
        "Full-text search backend",
        "LanceDB provides both the vector store and the BM25 full-text search index. "
        "The two are merged using reciprocal rank fusion before reranking.",
        etype="context",
    )
    _write_entry(
        mem_dir, 3,
        "Reranker choice",
        "VoyageAI rerank-2.5 is used as the cross-encoder reranker. "
        "It is called once per search after RRF merging to produce final results.",
        etype="decision",
    )
    _write_entry(
        mem_dir, 4,
        "Index sync latency",
        "The retrieval index must be synced before searches run. "
        "ensure_synced() is idempotent and fast after the first call.",
        etype="lesson",
    )
    _write_entry(
        mem_dir, 5,
        "Search entry point",
        "koan memory search runs hybrid dense+BM25 search with reranking. "
        "Use --type to narrow results to a specific memory type.",
        etype="procedure",
    )

    fixture_ids = {1, 2, 3, 4, 5}
    valid_types = {"decision", "context", "lesson", "procedure"}
    expected_modified_ms = 1704067200000  # 2024-01-01T00:00:00Z

    # Record all trace events so we can verify thinking/text deltas are emitted.
    trace_events: list[ReflectTraceEvent] = []

    def record_trace(ev: ReflectTraceEvent) -> None:
        trace_events.append(ev)

    index = RetrievalIndex(mem_dir)
    result = await run_reflect_agent(
        index,
        question="How does the memory retrieval system work, and what models does it use?",
        on_trace=record_trace,
    )

    assert len(result.citations) >= 2, (
        f"expected at least 2 citations, got {len(result.citations)}"
    )
    for c in result.citations:
        assert c.id in fixture_ids, (
            f"citation id {c.id} not in fixture set {fixture_ids}"
        )
        # Each citation must carry type and a positive modified_ms.
        assert c.type in valid_types, f"citation {c.id} has invalid type {c.type!r}"
        assert c.modified_ms == expected_modified_ms, (
            f"citation {c.id} has unexpected modified_ms {c.modified_ms}"
        )
    assert result.iterations >= 1
    assert len(result.answer) > 50

    # The trace recorder must have seen at least one thinking or text event,
    # confirming pydantic-ai streaming deltas flow through on_trace.
    model_output_kinds = {ev.kind for ev in trace_events if ev.kind in {"thinking", "text"}}
    assert model_output_kinds, (
        f"expected at least one thinking or text trace event; got kinds: "
        f"{[ev.kind for ev in trace_events]}"
    )
