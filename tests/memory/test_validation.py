# Tests for koan.memory.validation

from __future__ import annotations

from koan.memory.types import MemoryEntry
from koan.memory.validation import validate_entry


def _valid_entry(**overrides) -> MemoryEntry:
    defaults = dict(
        title="PostgreSQL for Auth",
        type="decision",
        body="Chose PostgreSQL 16.2 over SQLite.",
    )
    defaults.update(overrides)
    return MemoryEntry(**defaults)


class TestValidEntry:
    def test_passes(self):
        assert validate_entry(_valid_entry()) == []


class TestMissingRequired:
    def test_missing_title(self):
        errors = validate_entry(_valid_entry(title=""))
        assert any("title" in e for e in errors)

    def test_missing_type(self):
        errors = validate_entry(_valid_entry(type=""))
        assert any("type" in e for e in errors)

    def test_missing_body(self):
        errors = validate_entry(_valid_entry(body=""))
        assert any("body" in e for e in errors)


class TestInvalidType:
    def test_invalid_type(self):
        errors = validate_entry(_valid_entry(type="opinion"))
        assert any("invalid type" in e for e in errors)
