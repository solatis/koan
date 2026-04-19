# Tests for koan.memory.store

from __future__ import annotations

from koan.memory.store import MemoryStore


class TestInit:
    def test_creates_flat_memory_directory(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        mem = tmp_path / ".koan" / "memory"
        assert mem.is_dir()
        # No type subdirectories
        assert not (mem / "decisions").exists()
        assert not (mem / "context").exists()
        assert not (mem / "lessons").exists()
        assert not (mem / "procedures").exists()
        # No user dir
        assert not (tmp_path / ".koan" / "user").exists()

    def test_idempotent(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        store.init()
        assert (tmp_path / ".koan" / "memory").is_dir()


class TestAddAndList:
    def test_add_writes_to_flat_directory(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        e = store.add_entry(
            type="decision",
            title="Use PostgreSQL",
            body="Documents DB choice. Chose PostgreSQL 16.2 over SQLite.",
        )
        assert e.file_path is not None
        assert e.file_path.exists()
        assert e.file_path.parent == tmp_path / ".koan" / "memory"
        assert e.file_path.name == "0001-use-postgresql.md"
        assert e.created != ""
        assert e.modified != ""

    def test_global_sequence_across_types(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        a = store.add_entry("decision", "D1", "Body.")
        b = store.add_entry("lesson", "L1", "Body.")
        c = store.add_entry("context", "C1", "Body.")
        assert a.file_path.name == "0001-d1.md"
        assert b.file_path.name == "0002-l1.md"
        assert c.file_path.name == "0003-c1.md"

    def test_list_all_types(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        store.add_entry("decision", "D1", "Body.")
        store.add_entry("lesson", "L1", "Body.")
        store.add_entry("context", "C1", "Body.")
        assert len(store.list_entries()) == 3

    def test_list_with_type_filter(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        store.add_entry("decision", "D1", "Body.")
        store.add_entry("decision", "D2", "Body.")
        store.add_entry("lesson", "L1", "Body.")
        assert len(store.list_entries(type="decision")) == 2
        assert len(store.list_entries(type="lesson")) == 1
        assert len(store.list_entries(type="procedure")) == 0

    def test_list_sorted_by_sequence(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        store.add_entry("decision", "First", "Body.")
        store.add_entry("lesson", "Second", "Body.")
        store.add_entry("decision", "Third", "Body.")
        entries = store.list_entries()
        assert [e.title for e in entries] == ["First", "Second", "Third"]


class TestGetEntry:
    def test_by_number(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        store.add_entry("decision", "First", "Body.")
        store.add_entry("lesson", "Second", "Body.")
        e = store.get_entry(2)
        assert e is not None
        assert e.title == "Second"
        assert e.type == "lesson"

    def test_missing(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        assert store.get_entry(99) is None


class TestEntryCount:
    def test_count_all(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        store.add_entry("decision", "D1", "Body.")
        store.add_entry("lesson", "L1", "Body.")
        assert store.entry_count() == 2

    def test_count_by_type(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        store.add_entry("decision", "D1", "Body.")
        store.add_entry("decision", "D2", "Body.")
        store.add_entry("lesson", "L1", "Body.")
        assert store.entry_count(type="decision") == 2
        assert store.entry_count(type="lesson") == 1
        assert store.entry_count(type="procedure") == 0


class TestForgetEntry:
    def test_deletes_file(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        e = store.add_entry("decision", "D1", "Body.")
        assert e.file_path is not None
        assert e.file_path.exists()
        store.forget_entry(e)
        assert not e.file_path.exists()
        assert store.entry_count(type="decision") == 0


class TestSummary:
    def test_no_summary(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        assert store.get_summary() is None

    def test_summary_exists(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()
        summary_path = tmp_path / ".koan" / "memory" / "summary.md"
        summary_path.write_text("# Project Summary\n\nOverview here.\n", "utf-8")
        assert store.get_summary() is not None
        assert "Overview here" in store.get_summary()
