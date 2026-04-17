from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import koan.cli.memory as cli_memory
from koan.cli.memory import cmd_rag, cmd_search
from koan.memory.retrieval.types import SearchResult
from koan.memory.store import MemoryStore
from koan.memory.types import MemoryEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _make_entry(n: int = 1, etype: str = "context") -> MemoryEntry:
    return MemoryEntry(
        title=f"Title {n}",
        type=etype,
        body=f"Body of entry {n}.",
        created="2024-01-01",
        modified="2024-01-01",
    )


def _make_result(n: int = 1, etype: str = "context") -> SearchResult:
    return SearchResult(entry=_make_entry(n, etype), entry_id=n, score=0.85)


FIXED_RESULTS = [_make_result(1), _make_result(2)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store_env(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path)
    store.init()
    monkeypatch.setattr("koan.cli.memory._make_store", lambda: store)
    return store


@pytest.fixture
def search_env(store_env, monkeypatch):
    mock_index = MagicMock()
    monkeypatch.setattr("koan.cli.memory._make_index", lambda _store: mock_index)
    monkeypatch.setattr(cli_memory, "retrieval_search", AsyncMock(return_value=FIXED_RESULTS))
    monkeypatch.setattr(cli_memory, "rag_inject", AsyncMock(return_value=FIXED_RESULTS))
    return {"store": store_env, "mock_index": mock_index}


# ---------------------------------------------------------------------------
# cmd_search tests
# ---------------------------------------------------------------------------

def test_cmd_search_human_readable(search_env, capsys) -> None:
    cmd_search(ns(query="test", type=None, k=5, json_output=False))
    out = capsys.readouterr().out
    assert "0001" in out
    assert "Title 1" in out


def test_cmd_search_json_output(search_env, capsys) -> None:
    cmd_search(ns(query="test", type=None, k=5, json_output=True))
    out = capsys.readouterr().out
    result = json.loads(out)
    assert "results" in result
    assert len(result["results"]) == 2


def test_cmd_search_type_filter_forwarded(search_env, monkeypatch) -> None:
    captured = {}

    async def mock_search(index, query, k=5, type_filter=None):
        captured["type_filter"] = type_filter
        return FIXED_RESULTS

    monkeypatch.setattr(cli_memory, "retrieval_search", mock_search)
    cmd_search(ns(query="x", type="decision", k=5, json_output=False))
    assert captured["type_filter"] == "decision"


# ---------------------------------------------------------------------------
# cmd_rag tests
# ---------------------------------------------------------------------------

def test_cmd_rag_json_output(search_env, capsys) -> None:
    cmd_rag(ns(directive="find stuff", anchor="some context", k=5, json_output=True))
    out = capsys.readouterr().out
    result = json.loads(out)
    assert "results" in result
    assert len(result["results"]) == 2


def test_cmd_rag_at_file_anchor(search_env, tmp_path, capsys) -> None:
    anchor_file = tmp_path / "anchor.txt"
    anchor_file.write_text("anchor content from file", encoding="utf-8")

    captured = {}

    async def mock_inject(index, directive, anchor, k=5):
        captured["anchor"] = anchor
        return FIXED_RESULTS

    import koan.cli.memory as cli_mod
    with patch.object(cli_mod, "rag_inject", mock_inject):
        cmd_rag(ns(
            directive="d",
            anchor=f"@{anchor_file}",
            k=5,
            json_output=False,
        ))

    assert captured["anchor"] == "anchor content from file"


def test_cmd_rag_missing_anchor_file_exits(search_env, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cmd_rag(ns(directive="d", anchor="@/nonexistent/file.txt", k=5, json_output=False))
    assert exc.value.code == 1
