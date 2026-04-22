# Unit tests for pure-function helpers in koan.memory.retrieval.reflect.
# No LLM client involvement; all tests run without API keys.

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from koan.memory.retrieval.reflect import (
    Citation,
    _dispatch_search,
    _resolve_citations,
)
from koan.memory.retrieval.types import SearchResult
from koan.memory.types import MemoryEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(n: int = 1, etype: str = "context", title: str | None = None) -> MemoryEntry:
    return MemoryEntry(
        title=title or f"Entry {n}",
        type=etype,
        body=f"Body of entry {n}.",
        created="2024-01-01",
        modified="2024-01-01",
    )


def _make_result(n: int = 1, etype: str = "context") -> SearchResult:
    return SearchResult(entry=_make_entry(n, etype), entry_id=n, score=0.9)


# ---------------------------------------------------------------------------
# _resolve_citations
# ---------------------------------------------------------------------------

class TestResolveCitations:
    def test_all_ids_present(self):
        retrieved = {1: _make_entry(1, title="Alpha"), 2: _make_entry(2, title="Beta")}
        result = _resolve_citations([1, 2], retrieved)
        assert result == [Citation(id=1, title="Alpha"), Citation(id=2, title="Beta")]

    def test_unknown_ids_dropped(self):
        retrieved = {1: _make_entry(1, title="Alpha")}
        result = _resolve_citations([1, 99], retrieved)
        assert len(result) == 1
        assert result[0].id == 1

    def test_all_unknown_returns_empty(self):
        result = _resolve_citations([5, 6, 7], {})
        assert result == []

    def test_empty_input(self):
        result = _resolve_citations([], {1: _make_entry(1)})
        assert result == []


# ---------------------------------------------------------------------------
# _dispatch_search
# ---------------------------------------------------------------------------

class TestDispatchSearch:
    @pytest.mark.anyio
    async def test_invalid_type_returns_error_no_raise(self):
        """Returns error payload without raising; no index call needed."""
        from unittest.mock import MagicMock
        index = MagicMock()
        retrieved: dict = {}
        payload = await _dispatch_search(index, {"query": "x", "type": "invalid"}, retrieved)
        assert "error" in payload
        assert payload["results"] == []
        assert "invalid" in payload["error"]

    @pytest.mark.anyio
    async def test_updates_retrieved_dict(self):
        """_dispatch_search should add all returned entries to the retrieved dict."""
        from unittest.mock import MagicMock
        index = MagicMock()
        results = [_make_result(3), _make_result(7)]
        retrieved: dict = {}

        with patch(
            "koan.memory.retrieval.reflect.retrieval_search",
            AsyncMock(return_value=results),
        ):
            payload = await _dispatch_search(index, {"query": "test"}, retrieved)

        assert 3 in retrieved
        assert 7 in retrieved
        assert retrieved[3] == results[0].entry
        assert retrieved[7] == results[1].entry
        assert len(payload["results"]) == 2

    @pytest.mark.anyio
    async def test_caps_k_at_20(self):
        """k values above 20 are clamped to 20 before hitting the index."""
        from unittest.mock import MagicMock, call
        index = MagicMock()

        captured_kwargs: dict = {}

        async def fake_search(idx, query, k=5, type_filter=None):
            captured_kwargs["k"] = k
            return []

        with patch("koan.memory.retrieval.reflect.retrieval_search", fake_search):
            await _dispatch_search(index, {"query": "x", "k": 100}, {})

        assert captured_kwargs["k"] == 20

    @pytest.mark.anyio
    async def test_runtime_error_returns_error_payload(self):
        """A RuntimeError from the index (e.g. missing API key) returns an error dict."""
        from unittest.mock import MagicMock
        index = MagicMock()

        with patch(
            "koan.memory.retrieval.reflect.retrieval_search",
            AsyncMock(side_effect=RuntimeError("voyage key missing")),
        ):
            payload = await _dispatch_search(index, {"query": "x"}, {})

        assert "error" in payload
        assert "voyage key missing" in payload["error"]
        assert payload["results"] == []
