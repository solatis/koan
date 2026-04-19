# Tests for koan/memory/ops.py -- pure CRUD and validation layer.

from __future__ import annotations

import os
import time

import pytest

from koan.memory.store import MemoryStore
from koan.memory import ops


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_store(tmp_path) -> MemoryStore:
    store = MemoryStore(tmp_path)
    store.init()
    return store


# ---------------------------------------------------------------------------
# memorize
# ---------------------------------------------------------------------------

def test_memorize_create_returns_correct_shape(tmp_path):
    store = make_store(tmp_path)
    result = ops.memorize(store, "decision", "My decision", "Body text.")
    assert result["op"] == "created"
    assert result["type"] == "decision"
    assert isinstance(result["entry_id"], int)
    assert isinstance(result["file_path"], str)
    assert "created" in result
    assert "modified" in result


def test_memorize_create_file_exists_on_disk(tmp_path):
    store = make_store(tmp_path)
    result = ops.memorize(store, "context", "Some context", "Body.")
    from pathlib import Path
    assert Path(result["file_path"]).is_file()


def test_memorize_update_returns_correct_shape(tmp_path):
    store = make_store(tmp_path)
    created = ops.memorize(store, "lesson", "Original", "Body.")
    entry_id = created["entry_id"]
    result = ops.memorize(store, "lesson", "Updated", "New body.", entry_id=entry_id)
    assert result["op"] == "updated"
    assert result["entry_id"] == entry_id


def test_memorize_update_type_mismatch_raises(tmp_path):
    store = make_store(tmp_path)
    created = ops.memorize(store, "decision", "Title", "Body.")
    with pytest.raises(ValueError, match="type"):
        ops.memorize(store, "context", "Title", "Body.", entry_id=created["entry_id"])


def test_memorize_update_missing_entry_raises(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="9999"):
        ops.memorize(store, "decision", "Title", "Body.", entry_id=9999)


def test_memorize_invalid_type_raises(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="bogus"):
        ops.memorize(store, "bogus", "Title", "Body.")


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------

def test_forget_deletes_entry(tmp_path):
    from pathlib import Path
    store = make_store(tmp_path)
    created = ops.memorize(store, "procedure", "To delete", "Body.")
    entry_id = created["entry_id"]
    result = ops.forget(store, entry_id)
    assert result["op"] == "forgotten"
    assert not Path(result["file_path"]).exists()


def test_forget_type_mismatch_raises(tmp_path):
    store = make_store(tmp_path)
    created = ops.memorize(store, "decision", "Title", "Body.")
    with pytest.raises(ValueError, match="type"):
        ops.forget(store, created["entry_id"], type="context")


def test_forget_missing_entry_raises(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="9999"):
        ops.forget(store, 9999)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_status_empty_store(tmp_path):
    store = make_store(tmp_path)
    result = await ops.status(store)
    assert result["summary"] == "" or result["summary"] is None
    assert result["entries"] == []
    assert result["regenerated"] is False


@pytest.mark.anyio
async def test_status_fresh_summary_no_regen(tmp_path):
    store = make_store(tmp_path)
    ops.memorize(store, "context", "Entry A", "Body A.")

    # Write summary.md with mtime newer than the entry file.
    summary_path = tmp_path / ".koan" / "memory" / "summary.md"
    summary_path.write_text("Dummy summary.", encoding="utf-8")
    future_mtime = time.time() + 2
    os.utime(summary_path, (future_mtime, future_mtime))

    result = await ops.status(store)
    assert result["regenerated"] is False
