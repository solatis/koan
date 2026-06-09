# Negative-presence guard: assert advance_step (koan_complete_step entrypoint)
# is no longer importable, and that production code under koan/ is clean of
# koan_complete_step references (excluding koan/web/static/ and evals/).
#
# Mirrors the M1/M4 test_mcp_removed.py pattern.

import subprocess
import sys

import pytest


def test_advance_step_not_importable():
    """advance_step was deleted in M6 and must not be importable from koan_tools."""
    import koan.tools.koan_tools as kt
    assert not hasattr(kt, "advance_step"), (
        "advance_step is still present in koan.tools.koan_tools -- must be removed (M6)"
    )


def test_koan_complete_step_absent_from_production_code():
    """Production code under koan/ must contain no koan_complete_step references.

    Uses the safe grep form (--include=*.py to limit to Python source files):
    grep exits 1 when no matches are found, which is the success condition.
    evals/ and koan/web/static/ are excluded (pinned fixture and static assets).
    """
    result = subprocess.run(
        [
            "grep",
            "-rqn",
            "--include=*.py",
            "--exclude-dir=static",
            "--exclude-dir=evals",
            "koan_complete_step",
            "koan/",
        ],
        capture_output=True,
        text=True,
        cwd=_project_root(),
    )
    # grep exits 1 when no match found (which is what we want -- clean).
    assert result.returncode == 1, (
        "koan_complete_step found in production Python source under koan/ "
        "(excluding koan/web/static/ and evals/). "
        "All references must be removed in M6."
    )


def test_advance_step_absent_from_production_code():
    """No advance_step reference should remain in production Python source under koan/."""
    result = subprocess.run(
        [
            "grep",
            "-rqn",
            "--include=*.py",
            "--exclude-dir=static",
            "--exclude-dir=evals",
            r"\badvance_step\b",
            "koan/",
        ],
        capture_output=True,
        text=True,
        cwd=_project_root(),
    )
    assert result.returncode == 1, (
        "advance_step found in production Python source under koan/ -- must be removed (M6)"
    )


def test_boot_prompt_absent_from_production_code():
    """No .boot_prompt attribute access should remain in production Python source under koan/."""
    result = subprocess.run(
        [
            "grep",
            "-rqn",
            "--include=*.py",
            "--exclude-dir=static",
            "--exclude-dir=evals",
            r"\.boot_prompt",
            "koan/",
        ],
        capture_output=True,
        text=True,
        cwd=_project_root(),
    )
    assert result.returncode == 1, (
        ".boot_prompt found in production Python source under koan/ -- must be removed (M6)"
    )


def test_handshake_observed_absent_from_production_code():
    """No handshake_observed reference should remain in production Python source under koan/."""
    result = subprocess.run(
        [
            "grep",
            "-rqn",
            "--include=*.py",
            "--exclude-dir=static",
            "--exclude-dir=evals",
            "handshake_observed",
            "koan/",
        ],
        capture_output=True,
        text=True,
        cwd=_project_root(),
    )
    assert result.returncode == 1, (
        "handshake_observed found in production Python source under koan/ -- "
        "must be replaced by first_turn_completed (M6)"
    )


def _project_root() -> str:
    """Return the koan project root (parent of the koan/ package directory)."""
    import pathlib
    # This file is in tests/; go up one level.
    return str(pathlib.Path(__file__).parent.parent)
