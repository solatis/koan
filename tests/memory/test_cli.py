# Tests for koan/cli/memory.py -- CLI-specific behavior only.
# Business logic (create/update/delete/type validation) is covered by
# test_ops.py and test_mcp_memory.py; this file tests only CLI concerns:
# stdin body reading, stdout JSON wiring, stale+no-API-key early exit,
# human-readable table format, and placeholder command exits.

from __future__ import annotations

import argparse
import json
import sys
from io import StringIO

import pytest

from koan.cli.memory import cmd_memorize, cmd_forget, cmd_status, cmd_memory
from koan.memory import ops
from koan.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def store_env(tmp_path, monkeypatch):
    """Create a MemoryStore in tmp_path and monkeypatch _make_store to return it."""
    store = MemoryStore(tmp_path)
    store.init()
    monkeypatch.setattr("koan.cli.memory._make_store", lambda: store)
    return store


def ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_memorize_stdin_body(store_env, monkeypatch, capsys):
    """Stdin fallback path: body=None reads from sys.stdin."""
    monkeypatch.setattr("sys.stdin", StringIO("body from stdin"))
    cmd_memorize(ns(type="context", title="T", body=None, related=[], entry_id=None))
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["op"] == "created"


def test_forget_prints_json_to_stdout(store_env, capsys):
    """Output wiring: cmd_forget prints valid JSON with op=forgotten to stdout."""
    created = ops.memorize(store_env, "decision", "To delete", "Body.")
    cmd_forget(ns(entry_id=created["entry_id"], type=None))
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["op"] == "forgotten"


def test_status_stale_no_api_key_exits(store_env, monkeypatch, capsys):
    """Early-exit guard: stale summary without API key exits with code 1."""
    ops.memorize(store_env, "context", "Entry", "Body.")
    # summary.md is absent -> summary_is_stale() returns True
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        cmd_status(ns(type=None, json_output=True))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err


def test_status_human_readable_output(store_env, tmp_path, capsys):
    """Human-readable format: table header and entry titles appear in stdout."""
    ops.memorize(store_env, "context", "Alpha entry", "Body.")
    ops.memorize(store_env, "decision", "Beta entry", "Body.")

    # Write a fresh summary.md so no regeneration is attempted.
    import os, time
    summary_path = tmp_path / ".koan" / "memory" / "summary.md"
    summary_path.write_text("Dummy summary.", encoding="utf-8")
    future = time.time() + 2
    os.utime(summary_path, (future, future))

    cmd_status(ns(type=None, json_output=False))
    out = capsys.readouterr().out
    assert "entry_id" in out
    assert "type" in out
    assert "title" in out
    assert "Alpha entry" in out
    assert "Beta entry" in out


def test_placeholder_commands_exit(store_env, capsys):
    """Placeholder subcommands exit with code 1 and print 'not yet implemented'."""
    for cmd in ("reflect",):
        with pytest.raises(SystemExit) as exc:
            cmd_memory(ns(memory_command=cmd))
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "not yet implemented" in err
