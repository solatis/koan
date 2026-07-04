# Vocabulary drift guard -- provider-vocabulary-guard pattern (memory #219).
#
# These tests assert that the fanned-out role/phase/tool vocabulary tables stay
# in sync. A future role/phase/tool change that misses a table fails here
# instead of crashing at runtime or booting stale.
#
# M6: added as part of the *-review phase collapse. The final vocabulary is:
#   Roles:  intake, scout, orchestrator, planner, executor, reviewer
#   Phases: intake, core-flows, tech-plan, milestone, plan, execute, curation, frame
#   Tools:  see KOAN_MCP_TOOLS in koan/agents/events.py

from __future__ import annotations

import sys


# ---------------------------------------------------------------------------
# Role vocabulary consistency
# ---------------------------------------------------------------------------

def test_every_subagentrole_has_role_model_tier() -> None:
    """Every SubagentRole literal must have an entry in ROLE_MODEL_TIER.

    A role without a tier cannot be dispatched to any model and will crash
    at spawn time. This guard catches the mismatch at test time instead.
    """
    from typing import get_args
    from koan.types import SubagentRole, ROLE_MODEL_TIER

    roles = set(get_args(SubagentRole))
    for role in roles:
        assert role in ROLE_MODEL_TIER, (
            f"SubagentRole {role!r} has no entry in ROLE_MODEL_TIER -- "
            "add it or remove the role"
        )


def test_every_subagentrole_has_role_permissions() -> None:
    """Every SubagentRole literal must have an entry in ROLE_PERMISSIONS.

    compose_toolset looks up role_tools[role]; a missing key produces an
    empty frozenset which silently strips all tools from the role.
    """
    from typing import get_args
    from koan.types import SubagentRole
    from koan.tools.tool_policy import ROLE_PERMISSIONS

    roles = set(get_args(SubagentRole))
    for role in roles:
        assert role in ROLE_PERMISSIONS, (
            f"SubagentRole {role!r} has no entry in ROLE_PERMISSIONS -- "
            "add it (even an empty frozenset) or remove the role"
        )


def test_spawnable_roles_in_phase_module_map() -> None:
    """Spawnable roles (scout, executor, reviewer) must all be in PHASE_MODULE_MAP.

    spawn_tracked_subagent looks up the role in PHASE_MODULE_MAP to get the
    phase module. A missing entry raises KeyError at spawn time.
    """
    from koan.phases import PHASE_MODULE_MAP

    spawnable = {"scout", "executor", "reviewer"}
    for role in spawnable:
        assert role in PHASE_MODULE_MAP, (
            f"Spawnable role {role!r} not in PHASE_MODULE_MAP -- "
            "add its phase module"
        )


# ---------------------------------------------------------------------------
# Phase vocabulary consistency
# ---------------------------------------------------------------------------

_FINAL_PHASE_SET = frozenset({
    "intake", "core-flows", "tech-plan", "milestone",
    "plan", "execute", "curation", "frame",
})

_REMOVED_REVIEW_PHASES = frozenset({
    "plan-review", "milestone-review", "tech-plan-review", "exec-review",
})


def test_workflow_phase_union_matches_final_set() -> None:
    """Union of available_phases across all workflows must equal the final 8-phase set.

    The 4 *-review phases (plan-review, milestone-review, tech-plan-review,
    exec-review) were collapsed in M6 and must not appear in any workflow.
    """
    from koan.lib.workflows import WORKFLOWS

    union: set[str] = set()
    for wf in WORKFLOWS.values():
        union.update(wf.available_phases)

    assert union == _FINAL_PHASE_SET, (
        f"Workflow phase union mismatch.\n"
        f"  Unexpected phases: {union - _FINAL_PHASE_SET}\n"
        f"  Missing phases:    {_FINAL_PHASE_SET - union}"
    )


def test_no_review_phase_in_any_workflow() -> None:
    """No workflow must contain any *-review phase after M6."""
    from koan.lib.workflows import WORKFLOWS

    for name, wf in WORKFLOWS.items():
        for phase in wf.available_phases:
            assert phase not in _REMOVED_REVIEW_PHASES, (
                f"Workflow {name!r} still contains removed phase {phase!r}"
            )


def test_no_review_phase_in_any_transitions() -> None:
    """No workflow transitions dict must reference any *-review phase after M6."""
    from koan.lib.workflows import WORKFLOWS

    for wf_name, wf in WORKFLOWS.items():
        for from_phase, successors in wf.transitions.items():
            for succ in successors:
                assert succ not in _REMOVED_REVIEW_PHASES, (
                    f"Workflow {wf_name!r} transitions[{from_phase!r}] "
                    f"still references removed phase {succ!r}"
                )


def test_workflow_phase_type_literal_matches_final_set() -> None:
    """WorkflowPhase literal must contain exactly the final 8 phases, no *-review."""
    from typing import get_args
    from koan.types import WorkflowPhase

    literal_phases = set(get_args(WorkflowPhase))
    assert literal_phases == _FINAL_PHASE_SET, (
        f"WorkflowPhase literal mismatch.\n"
        f"  Unexpected: {literal_phases - _FINAL_PHASE_SET}\n"
        f"  Missing:    {_FINAL_PHASE_SET - literal_phases}"
    )


# ---------------------------------------------------------------------------
# Tool vocabulary consistency
# ---------------------------------------------------------------------------

_REMOVED_TOOLS = frozenset({
    # Removed in M1: legacy "execution" phase that gated these is deleted.
    "koan_select_story",
    "koan_complete_story",
    "koan_retry_story",
    "koan_skip_story",
    # Removed in M7: curation writes memory directly via koan_memorize/koan_forget;
    # the propose/approve gate is retired.
    "koan_memory_propose",
})

_REQUIRED_ARTIFACT_TOOLS = frozenset({
    "koan_artifact_write",
    "koan_artifact_edit",
    "koan_artifact_list",
    "koan_artifact_read",
})


def test_koan_mcp_tools_contains_no_removed_tool() -> None:
    """KOAN_MCP_TOOLS must not contain any removed tool (M1/M4 removals)."""
    from koan.agents.events import KOAN_MCP_TOOLS

    for tool in _REMOVED_TOOLS:
        assert tool not in KOAN_MCP_TOOLS, (
            f"Removed tool {tool!r} still in KOAN_MCP_TOOLS -- remove it"
        )


def test_koan_mcp_tools_contains_live_artifact_tools() -> None:
    """KOAN_MCP_TOOLS must include all four live artifact tools (M3 additions)."""
    from koan.agents.events import KOAN_MCP_TOOLS

    for tool in _REQUIRED_ARTIFACT_TOOLS:
        assert tool in KOAN_MCP_TOOLS, (
            f"Live artifact tool {tool!r} missing from KOAN_MCP_TOOLS -- add it"
        )


def test_scout_phases_no_review_phase() -> None:
    """_ORCHESTRATOR_SCOUT_PHASES must contain no *-review phase after M6."""
    from koan.tools.tool_policy import _ORCHESTRATOR_SCOUT_PHASES

    for phase in _REMOVED_REVIEW_PHASES:
        assert phase not in _ORCHESTRATOR_SCOUT_PHASES, (
            f"Removed phase {phase!r} still in _ORCHESTRATOR_SCOUT_PHASES"
        )


# ---------------------------------------------------------------------------
# *-review module non-importability (M6 deletion guard)
# ---------------------------------------------------------------------------

def test_plan_review_module_deleted() -> None:
    """koan.phases.plan_review must not be importable after M6 deletion."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.plan_review")


def test_milestone_review_module_deleted() -> None:
    """koan.phases.milestone_review must not be importable after M6 deletion."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.milestone_review")


def test_tech_plan_review_module_deleted() -> None:
    """koan.phases.tech_plan_review must not be importable after M6 deletion."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.tech_plan_review")


def test_exec_review_module_deleted() -> None:
    """koan.phases.exec_review must not be importable after M6 deletion."""
    import importlib
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("koan.phases.exec_review")
