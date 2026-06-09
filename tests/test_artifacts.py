# Unit tests for koan/artifacts.py.
#
# Artifacts are plain markdown files (no driver-managed frontmatter). The module
# now only lists artifacts; the frontmatter helpers were removed when the artifact
# tools became thin wrappers over read/write/edit (see docs/tools.md).

from __future__ import annotations

import pytest


# -- list_artifacts ------------------------------------------------------------

def test_list_artifacts_reports_path_size_mtime(tmp_path):
    from koan.artifacts import list_artifacts

    (tmp_path / "one.md").write_text("body\n")
    (tmp_path / "two.md").write_text("# heading\n")
    # Non-markdown files are ignored.
    (tmp_path / "notes.txt").write_text("ignore me\n")

    results = list_artifacts(tmp_path)
    by_path = {r["path"]: r for r in results}

    assert set(by_path) == {"one.md", "two.md"}
    for info in by_path.values():
        assert "path" in info
        assert "size" in info
        assert "modified_at" in info
        assert "status" not in info


def test_list_artifacts_includes_stories_excludes_subagents(tmp_path):
    from koan.artifacts import list_artifacts

    stories = tmp_path / "stories"
    (stories / "s1").mkdir(parents=True)
    (stories / "s1" / "plan.md").write_text("plan\n")
    subagents = stories / "s1" / "subagents"
    subagents.mkdir()
    (subagents / "scout.md").write_text("scratch\n")

    paths = {r["path"] for r in list_artifacts(tmp_path)}
    assert "stories/s1/plan.md" in paths
    assert not any("subagents" in p for p in paths)


# -- Negative-presence guards --------------------------------------------------
# Confirm removed symbols are truly gone; ImportError here means the deletion
# was applied correctly and no stale reference can import them.

@pytest.mark.parametrize("name", [
    "split_frontmatter",
    "dump_frontmatter",
    "compose_artifact",
    "write_artifact_atomic",
    "now_iso",
    "STATUS_VALUES",
    "read_artifact_status",
])
def test_removed_frontmatter_symbols_are_gone(name):
    """Frontmatter machinery was removed -- artifacts are plain files now."""
    import koan.artifacts as artifacts
    assert not hasattr(artifacts, name), f"{name} should have been removed from koan.artifacts"
