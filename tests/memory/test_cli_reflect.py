# CLI tests for cmd_reflect.
# run_reflect_agent is monkeypatched; no LLM or index calls are made.

from __future__ import annotations

import argparse
import json
import sys
from io import StringIO
from unittest.mock import AsyncMock

import pytest  # noqa: F401 (used for pytest.raises)

from koan.memory.retrieval.reflect import (
    Citation,
    IterationCapExceeded,
    ReflectResult,
    ReflectTraceEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(
    question: str = "What do we know?",
    context: str | None = None,
    json_output: bool = False,
    show_trace: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        question=question,
        context=context,
        json_output=json_output,
        show_trace=show_trace,
    )


def _fake_reflect_result() -> ReflectResult:
    return ReflectResult(
        answer="The system uses LanceDB for vector storage.",
        citations=[
            Citation(id=1, title="DB choice", type="decision", modified_ms=1704067200000),
            Citation(id=2, title="Indexing strategy", type="context", modified_ms=1704067200000),
        ],
        iterations=3,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCmdReflect:
    # cmd_reflect is a synchronous function that calls asyncio.run() internally.
    # Tests must be synchronous too; calling asyncio.run() from within an anyio
    # event loop would raise "cannot be called from a running event loop".

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        """--json flag emits a valid JSON object with the expected shape."""
        import koan.cli.memory as cli_memory

        monkeypatch.setattr(cli_memory, "run_reflect_agent", AsyncMock(return_value=_fake_reflect_result()))
        monkeypatch.setattr(cli_memory, "_make_store", lambda: _MockStore(tmp_path))
        monkeypatch.setattr(cli_memory, "_make_index", lambda s: object())

        cli_memory.cmd_reflect(_make_args(json_output=True))

        captured = capsys.readouterr()
        body = json.loads(captured.out)
        assert body["answer"] == "The system uses LanceDB for vector storage."
        assert body["citations"] == [
            {"id": 1, "title": "DB choice"},
            {"id": 2, "title": "Indexing strategy"},
        ]
        assert body["iterations"] == 3

    def test_human_readable_output(self, tmp_path, monkeypatch, capsys):
        """Without --json, prints a briefing + citations header."""
        import koan.cli.memory as cli_memory

        monkeypatch.setattr(cli_memory, "run_reflect_agent", AsyncMock(return_value=_fake_reflect_result()))
        monkeypatch.setattr(cli_memory, "_make_store", lambda: _MockStore(tmp_path))
        monkeypatch.setattr(cli_memory, "_make_index", lambda s: object())

        cli_memory.cmd_reflect(_make_args())

        captured = capsys.readouterr()
        assert "# Briefing" in captured.out
        assert "The system uses LanceDB for vector storage." in captured.out
        assert "# Citations" in captured.out
        assert "DB choice" in captured.out
        assert "Indexing strategy" in captured.out

    def test_show_trace_prints_search_to_stderr(self, tmp_path, monkeypatch, capsys):
        """--show-trace causes search events to be printed to stderr."""
        import koan.cli.memory as cli_memory

        trace_event = ReflectTraceEvent(
            iteration=1, kind="search", query="vector storage", result_count=3
        )

        # Custom fake that invokes the on_trace callback before returning.
        async def fake_reflect(index, question, context=None, *, on_trace=None, max_iterations=10):
            if on_trace is not None:
                on_trace(trace_event)
            return _fake_reflect_result()

        monkeypatch.setattr(cli_memory, "run_reflect_agent", fake_reflect)
        monkeypatch.setattr(cli_memory, "_make_store", lambda: _MockStore(tmp_path))
        monkeypatch.setattr(cli_memory, "_make_index", lambda s: object())

        cli_memory.cmd_reflect(_make_args(show_trace=True))

        captured = capsys.readouterr()
        assert "[iter 1] search('vector storage') -> 3 results" in captured.err

    def test_iteration_cap_exits_nonzero(self, tmp_path, monkeypatch):
        """IterationCapExceeded causes a nonzero exit."""
        import koan.cli.memory as cli_memory

        monkeypatch.setattr(
            cli_memory, "run_reflect_agent",
            AsyncMock(side_effect=IterationCapExceeded(iterations=10)),
        )
        monkeypatch.setattr(cli_memory, "_make_store", lambda: _MockStore(tmp_path))
        monkeypatch.setattr(cli_memory, "_make_index", lambda s: object())

        with pytest.raises(SystemExit) as exc:
            cli_memory.cmd_reflect(_make_args())
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# Minimal store stub (avoids real filesystem init)
# ---------------------------------------------------------------------------

class _MockStore:
    def __init__(self, base: object) -> None:
        pass

    def init(self) -> None:
        pass
