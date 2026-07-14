# Unit tests for pure-function helpers in koan.memory.retrieval.reflect.
# No LLM client involvement; all tests run without API keys.

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from koan.agents import adapter as adapter_mod
from koan.memory.retrieval.reflect import (
    Citation,
    _build_agent,
    _dispatch_search,
    _resolve_citations,
)
from koan.memory.retrieval.types import SearchResult
from koan.memory.types import MemoryEntry
from koan.types import CachingPolicy, ModelSpec
from koan.models.offering import resolve_offering


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(n: int = 1, etype: str = "context", title: str | None = None) -> MemoryEntry:
    return MemoryEntry(
        title=title or f"Entry {n}",
        type=etype,
        body=f"Body of entry {n}.",
        created="2024-01-01T00:00:00Z",
        modified="2024-01-01T00:00:00Z",
    )


def _make_result(n: int = 1, etype: str = "context") -> SearchResult:
    return SearchResult(entry=_make_entry(n, etype), entry_id=n, score=0.9)


# ---------------------------------------------------------------------------
# _resolve_citations
# ---------------------------------------------------------------------------

_EXPECTED_MODIFIED_MS = 1704067200000  # 2024-01-01T00:00:00Z in ms

class TestResolveCitations:
    def test_all_ids_present(self):
        retrieved = {1: _make_entry(1, title="Alpha"), 2: _make_entry(2, title="Beta")}
        result = _resolve_citations([1, 2], retrieved)
        assert len(result) == 2
        assert result[0].id == 1
        assert result[0].title == "Alpha"
        assert result[0].type == "context"
        assert result[0].modified_ms == _EXPECTED_MODIFIED_MS
        assert result[1].id == 2
        assert result[1].title == "Beta"

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

    def test_type_and_modified_ms_populated(self):
        """Citation carries entry type and modified_ms from the retrieved entry."""
        entry = _make_entry(1, etype="decision", title="A decision")
        result = _resolve_citations([1], {1: entry})
        assert len(result) == 1
        assert result[0].type == "decision"
        assert result[0].modified_ms == _EXPECTED_MODIFIED_MS


# ---------------------------------------------------------------------------
# _dispatch_search
# ---------------------------------------------------------------------------

class TestDispatchSearch:
    @pytest.mark.anyio
    async def test_invalid_type_returns_error_no_raise(self):
        """Returns error payload without raising; no index call needed."""
        from unittest.mock import MagicMock
        from koan.memory.retrieval.index import RetrievalIndex
        index = MagicMock(spec=RetrievalIndex)
        retrieved: dict = {}
        payload = await _dispatch_search(index, {"query": "x", "type": "invalid"}, retrieved, model=None)
        assert "error" in payload
        assert payload["results"] == []
        assert "invalid" in payload["error"]

    @pytest.mark.anyio
    async def test_updates_retrieved_dict(self):
        """_dispatch_search should add all returned entries to the retrieved dict."""
        from unittest.mock import MagicMock
        from koan.memory.retrieval.index import RetrievalIndex
        index = MagicMock(spec=RetrievalIndex)
        results = [_make_result(3), _make_result(7)]
        retrieved: dict = {}

        with patch(
            "koan.memory.retrieval.reflect.retrieval_search",
            AsyncMock(return_value=results),
        ):
            payload = await _dispatch_search(index, {"query": "test"}, retrieved, model=None)

        assert 3 in retrieved
        assert 7 in retrieved
        assert retrieved[3] == results[0].entry
        assert retrieved[7] == results[1].entry
        assert len(payload["results"]) == 2

    @pytest.mark.anyio
    async def test_caps_k_at_20(self):
        """k values above 20 are clamped to 20 before hitting the index."""
        from unittest.mock import MagicMock, call
        from koan.memory.retrieval.index import RetrievalIndex
        index = MagicMock(spec=RetrievalIndex)

        captured_kwargs: dict = {}

        async def fake_search(idx, query, model, k=5, type_filter=None):
            captured_kwargs["k"] = k
            return []

        with patch("koan.memory.retrieval.reflect.retrieval_search", fake_search):
            await _dispatch_search(index, {"query": "x", "k": 100}, {}, model=None)

        assert captured_kwargs["k"] == 20

    @pytest.mark.anyio
    async def test_runtime_error_returns_error_payload(self):
        """A RuntimeError from the index (e.g. missing API key) returns an error dict."""
        from unittest.mock import MagicMock
        from koan.memory.retrieval.index import RetrievalIndex
        index = MagicMock(spec=RetrievalIndex)

        with patch(
            "koan.memory.retrieval.reflect.retrieval_search",
            AsyncMock(side_effect=RuntimeError("voyage key missing")),
        ):
            payload = await _dispatch_search(index, {"query": "x"}, {}, model=None)

        assert "error" in payload
        assert "voyage key missing" in payload["error"]
        assert payload["results"] == []


# ---------------------------------------------------------------------------
# _build_agent routing regression
# ---------------------------------------------------------------------------

class TestBuildAgentRouting:
    def test_routes_settings_through_build_model_settings(self, monkeypatch):
        """_build_agent routes model settings through build_model_settings; sets no temperature.

        Guards that the memory reflect constructor never re-introduces a direct
        temperature override or diverges from the shared adapter seam.
        """
        from pydantic_ai.models.test import TestModel

        spec = ModelSpec(
            offering=resolve_offering("anthropic", "claude-sonnet-4-6"),
            thinking="high",
            settings={"anthropic_thinking": {"type": "adaptive"}},
            caching=CachingPolicy(),
            api_key="k",
        )

        # Replace build_model with a stub that returns a TestModel (no network needed).
        monkeypatch.setattr(
            adapter_mod,
            "build_model",
            lambda s, api_key=None, **_: TestModel(call_tools=[]),
        )

        # Wrap the real build_model_settings in a spy so we can assert it was called.
        real_build_model_settings = adapter_mod.build_model_settings
        calls: list = []

        def spy_build_model_settings(s):
            calls.append(s)
            return real_build_model_settings(s)

        monkeypatch.setattr(adapter_mod, "build_model_settings", spy_build_model_settings)

        _build_agent(spec)

        assert len(calls) == 1
        assert calls[0] is spec
