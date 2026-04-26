# Unit tests for koan/artifacts.py frontmatter helpers.

from __future__ import annotations

import pytest
from pathlib import Path


# -- split_frontmatter ---------------------------------------------------------

def test_split_frontmatter_no_frontmatter():
    from koan.artifacts import split_frontmatter
    text = "# Hello\nsome body\n"
    meta, body = split_frontmatter(text)
    assert meta is None
    assert body == text


def test_split_frontmatter_round_trip():
    from koan.artifacts import split_frontmatter, dump_frontmatter
    original_meta = {"status": "Final", "created": "2026-01-01T00:00:00Z", "last_modified": "2026-01-02T00:00:00Z"}
    original_body = "# Hello\n\nsome body\n"
    composed = dump_frontmatter(original_meta) + original_body
    meta, body = split_frontmatter(composed)
    assert meta == original_meta
    assert body == original_body


def test_split_frontmatter_malformed_returns_none():
    from koan.artifacts import split_frontmatter
    # Starts with '---' but no closing delimiter
    text = "---\nstatus: Draft\n# body\n"
    meta, body = split_frontmatter(text)
    assert meta is None
    assert body == text


def test_dump_frontmatter_field_order():
    from koan.artifacts import dump_frontmatter
    meta = {"status": "In-Progress", "created": "2026-01-01T00:00:00Z", "last_modified": "2026-01-02T00:00:00Z"}
    result = dump_frontmatter(meta)
    # Must start with opening delimiter and have fields in insertion order
    lines = result.splitlines()
    assert lines[0] == "---"
    assert lines[1].startswith("status:")
    assert lines[2].startswith("created:")
    assert lines[3].startswith("last_modified:")
    # Last non-empty line is the closing delimiter
    assert lines[-1] == "---"


# -- write_artifact_atomic -----------------------------------------------------

def test_write_artifact_atomic_sets_defaults(tmp_path):
    from koan.artifacts import write_artifact_atomic, split_frontmatter
    target = tmp_path / "test.md"
    meta = write_artifact_atomic(target, "hello", status=None)
    assert meta["status"] == "In-Progress"
    assert "created" in meta
    assert "last_modified" in meta
    # Verify on-disk file has frontmatter
    text = target.read_text()
    parsed_meta, body = split_frontmatter(text)
    assert parsed_meta is not None
    assert parsed_meta["status"] == "In-Progress"
    assert body == "hello"


def test_write_artifact_atomic_preserves_created(tmp_path):
    from koan.artifacts import write_artifact_atomic, split_frontmatter
    target = tmp_path / "test.md"
    first_meta = write_artifact_atomic(target, "first", status=None)
    original_created = first_meta["created"]

    second_meta = write_artifact_atomic(target, "second", status=None)
    assert second_meta["created"] == original_created
    # last_modified should be updated (may be same timestamp if fast enough, but key exists)
    assert "last_modified" in second_meta

    _, body = split_frontmatter(target.read_text())
    assert body == "second"


def test_write_artifact_atomic_status_explicit(tmp_path):
    from koan.artifacts import write_artifact_atomic, split_frontmatter
    target = tmp_path / "test.md"
    meta = write_artifact_atomic(target, "body", status="Final")
    assert meta["status"] == "Final"
    parsed_meta, _ = split_frontmatter(target.read_text())
    assert parsed_meta["status"] == "Final"


def test_write_artifact_atomic_invalid_status_raises(tmp_path):
    from koan.artifacts import write_artifact_atomic
    target = tmp_path / "test.md"
    with pytest.raises(ValueError, match="invalid status"):
        write_artifact_atomic(target, "body", status="bogus")


# -- read_artifact_status ------------------------------------------------------

def test_read_artifact_status_no_frontmatter_returns_none(tmp_path):
    from koan.artifacts import read_artifact_status
    f = tmp_path / "plain.md"
    f.write_text("# No frontmatter\n")
    assert read_artifact_status(f) is None


def test_read_artifact_status_extracts_status(tmp_path):
    from koan.artifacts import read_artifact_status, write_artifact_atomic
    f = tmp_path / "artifact.md"
    write_artifact_atomic(f, "body", status="Final")
    assert read_artifact_status(f) == "Final"


# -- list_artifacts ------------------------------------------------------------

def test_list_artifacts_includes_status(tmp_path):
    from koan.artifacts import list_artifacts, write_artifact_atomic
    # File with frontmatter
    with_fm = tmp_path / "with-fm.md"
    write_artifact_atomic(with_fm, "body", status="In-Progress")
    # File without frontmatter
    plain = tmp_path / "plain.md"
    plain.write_text("# No frontmatter\n")

    results = list_artifacts(tmp_path)
    by_path = {r["path"]: r for r in results}

    assert "status" in by_path["plain.md"]
    assert by_path["plain.md"]["status"] is None

    assert by_path["with-fm.md"]["status"] == "In-Progress"
