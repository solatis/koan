# Tests for koan.memory.parser

from __future__ import annotations

from pathlib import Path

import pytest

from koan.memory.parser import ParseError, parse_entry


WELL_FORMED = """\
---
title: PostgreSQL for Auth Service
type: decision
created: 2026-04-10T14:23:00Z
modified: 2026-04-10T14:23:00Z
related: [0002-infrastructure.md]
---

This entry documents the choice of primary data store.

On 2026-04-10, user decided to migrate the auth service from SQLite
to PostgreSQL 16.2. Rationale: concurrency.
"""

WELL_FORMED_MINIMAL = """\
---
title: Migration Steps
type: procedure
---

A short-body entry is still valid under the new format.
"""


def _write(tmp_path: Path, content: str, name: str = "entry.md") -> Path:
    p = tmp_path / name
    p.write_text(content, "utf-8")
    return p


class TestParseEntry:
    def test_well_formed(self, tmp_path):
        p = _write(tmp_path, WELL_FORMED)
        e = parse_entry(p)
        assert e.title == "PostgreSQL for Auth Service"
        assert e.type == "decision"
        assert e.created == "2026-04-10T14:23:00Z"
        assert e.modified == "2026-04-10T14:23:00Z"
        assert e.related == ["0002-infrastructure.md"]
        assert "choice of primary data store" in e.body
        assert "PostgreSQL 16.2" in e.body
        assert e.file_path == p

    def test_minimal_entry(self, tmp_path):
        p = _write(tmp_path, WELL_FORMED_MINIMAL)
        e = parse_entry(p)
        assert e.title == "Migration Steps"
        assert e.type == "procedure"
        assert e.created == ""
        assert e.modified == ""
        assert "still valid" in e.body

    def test_missing_frontmatter(self, tmp_path):
        p = _write(tmp_path, "Just some text without frontmatter.")
        with pytest.raises(ParseError, match="missing YAML frontmatter"):
            parse_entry(p)

    def test_missing_required_fields(self, tmp_path):
        content = "---\ntitle: Foo\n---\n\nBody text.\n"
        p = _write(tmp_path, content)
        with pytest.raises(ParseError, match="missing required frontmatter fields"):
            parse_entry(p)

    def test_only_title_and_type_required(self, tmp_path):
        content = "---\ntitle: Foo\ntype: decision\n---\n\nBody.\n"
        p = _write(tmp_path, content)
        e = parse_entry(p)
        assert e.title == "Foo"
        assert e.body == "Body."
