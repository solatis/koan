# Unit tests for koan/artifacts.py and the artifact-related projection fold.
#
# Artifacts are plain markdown files (no driver-managed frontmatter). The module
# now only lists artifacts; the frontmatter helpers were removed when the artifact
# tools became thin wrappers over read/write/edit (see docs/tools.md).
#
# Projection fold tests (produced_phase_id) are appended below -- they test that
# artifact_created stamps the active run.phase and that artifact_modified
# preserves it.

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


# -- Projection fold: produced_phase_id ----------------------------------------

def _make_projection_with_phase(phase: str):
    """Build a Projection with a Run whose phase is set to `phase`."""
    from koan.projections import Projection, VersionedEvent, fold

    proj = Projection()
    proj = fold(proj, VersionedEvent(
        version=1,
        event_type="run_started",
        timestamp="2026-01-01T00:00:00+00:00",
        agent_id=None,
        payload={"active_preset": "default"},
    ))
    proj = fold(proj, VersionedEvent(
        version=2,
        event_type="phase_started",
        timestamp="2026-01-01T00:00:01+00:00",
        agent_id=None,
        payload={"phase": phase},
    ))
    return proj


def test_fold_artifact_created_stamps_produced_phase_id() -> None:
    """artifact_created must stamp the active run.phase as produced_phase_id."""
    from koan.projections import VersionedEvent, fold

    proj = _make_projection_with_phase("plan")
    proj = fold(proj, VersionedEvent(
        version=3,
        event_type="artifact_created",
        timestamp="2026-01-01T00:00:02+00:00",
        agent_id=None,
        payload={"path": "plan.md", "size": 42, "modified_at": 1000},
    ))

    assert proj.run is not None
    info = proj.run.artifacts.get("plan.md")
    assert info is not None
    assert info.produced_phase_id == "plan"


def test_fold_artifact_modified_preserves_produced_phase_id() -> None:
    """artifact_modified must carry produced_phase_id forward unchanged."""
    from koan.projections import VersionedEvent, fold

    proj = _make_projection_with_phase("plan")
    proj = fold(proj, VersionedEvent(
        version=3,
        event_type="artifact_created",
        timestamp="2026-01-01T00:00:02+00:00",
        agent_id=None,
        payload={"path": "plan.md", "size": 42, "modified_at": 1000},
    ))
    # Simulate the active phase advancing before the artifact is modified.
    proj = fold(proj, VersionedEvent(
        version=4,
        event_type="phase_started",
        timestamp="2026-01-01T00:00:03+00:00",
        agent_id=None,
        payload={"phase": "execute"},
    ))
    proj = fold(proj, VersionedEvent(
        version=5,
        event_type="artifact_modified",
        timestamp="2026-01-01T00:00:04+00:00",
        agent_id=None,
        payload={"path": "plan.md", "size": 99, "modified_at": 2000},
    ))

    assert proj.run is not None
    info = proj.run.artifacts.get("plan.md")
    assert info is not None
    # Must still reflect the CREATING phase, not the current (execute) phase.
    assert info.produced_phase_id == "plan"
    assert info.size == 99
