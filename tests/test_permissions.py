# Unit tests for koan.lib.permissions -- exhaustive permission matrix coverage.

import pytest

from koan.lib.permissions import (
    PLANNING_ROLES,
    READ_TOOLS,
    ROLE_PERMISSIONS,
    STEP_1_BLOCKED_TOOLS,
    WRITE_TOOLS,
    _UNIVERSAL_MEMORY_TOOLS,
    check_permission,
)


ALL_ROLES = list(ROLE_PERMISSIONS.keys())

# Union of every tool name the permission system knows about.
ALL_KOAN_TOOLS: frozenset[str] = frozenset().union(
    *(perms for perms in ROLE_PERMISSIONS.values()),
    READ_TOOLS,
)


# -- Read tools always pass ----------------------------------------------------

class TestReadToolsAlwaysAllowed:
    def test_known_roles(self):
        for role in ALL_ROLES:
            for tool in READ_TOOLS:
                # bash is phase-gated for orchestrator (requires execution/impl-validation phase)
                if role == "orchestrator" and tool == "bash":
                    continue
                r = check_permission(role, tool)
                assert r["allowed"], f"{tool} should be allowed for {role}"
    
    def test_orchestrator_bash_needs_phase(self):
        """bash is phase-gated for the orchestrator role."""
        r = check_permission("orchestrator", "bash", current_phase="intake")
        assert not r["allowed"]
        r = check_permission("orchestrator", "bash", current_phase="execution")
        assert r["allowed"]

    def test_unknown_role(self):
        for tool in READ_TOOLS:
            r = check_permission("nonexistent-role", tool)
            assert r["allowed"], f"{tool} should be allowed even for unknown role"


# -- Unknown role blocks non-read tools ----------------------------------------

class TestUnknownRoleBlocked:
    def test_non_read_tool_denied(self):
        r = check_permission("nonexistent-role", "koan_complete_step")
        assert not r["allowed"]
        assert "Unknown role" in r["reason"]

    def test_write_denied(self):
        r = check_permission("nonexistent-role", "edit")
        assert not r["allowed"]


# -- Step 1 blocking ----------------------------------------------------------

class TestStep1Blocking:
    def setup_method(self):
        self.blocked = list(STEP_1_BLOCKED_TOOLS)

    def test_intake_step_1_allows(self):
        """Intake no longer blocks tools at step 1 (gather step uses all tools)."""
        for tool in self.blocked:
            r = check_permission("intake", tool, current_step=1)
            assert r["allowed"], f"intake step 1 should allow {tool}"

    def test_orchestrator_brief_generation_step_1_blocks(self):
        """Orchestrator at brief-generation step 1 blocks write/edit/scouts/ask."""
        for tool in self.blocked:
            r = check_permission(
                "orchestrator", tool,
                current_step=1,
                current_phase="brief-generation",
            )
            assert not r["allowed"], (
                f"orchestrator brief-generation step 1 should block {tool}"
            )

    def test_orchestrator_brief_generation_step_2_allows_write(self):
        """Orchestrator at brief-generation step 2 allows write/edit."""
        for tool in ("write", "edit"):
            r = check_permission(
                "orchestrator", tool,
                current_step=2,
                current_phase="brief-generation",
            )
            assert r["allowed"], (
                f"orchestrator brief-generation step 2 should allow {tool}"
            )

    def test_orchestrator_intake_step_1_allows_all(self):
        """Orchestrator at intake phase step 1 allows all base tools."""
        for tool in self.blocked:
            r = check_permission(
                "orchestrator", tool,
                current_step=1,
                current_phase="intake",
            )
            assert r["allowed"], f"orchestrator intake step 1 should allow {tool}"


# -- Orchestrator phase-aware permissions -------------------------------------

class TestOrchestratorPhasePermissions:
    def test_koan_request_scouts_intake_allowed(self):
        r = check_permission("orchestrator", "koan_request_scouts", current_phase="intake")
        assert r["allowed"]

    def test_koan_request_scouts_brief_generation_denied(self):
        r = check_permission("orchestrator", "koan_request_scouts", current_phase="brief-generation")
        assert not r["allowed"]


    def test_koan_request_executor_execution_allowed(self):
        r = check_permission("orchestrator", "koan_request_executor", current_phase="execution")
        assert r["allowed"]

    def test_koan_request_executor_execute_phase_allowed(self):
        r = check_permission("orchestrator", "koan_request_executor", current_phase="execute")
        assert r["allowed"]

    def test_koan_request_executor_intake_denied(self):
        r = check_permission("orchestrator", "koan_request_executor", current_phase="intake")
        assert not r["allowed"]

    def test_story_tools_execution_allowed(self):
        for tool in ("koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story"):
            r = check_permission("orchestrator", tool, current_phase="execution")
            assert r["allowed"], f"{tool} should be allowed during execution"

    def test_story_tools_intake_denied(self):
        for tool in ("koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story"):
            r = check_permission("orchestrator", tool, current_phase="intake")
            assert not r["allowed"], f"{tool} should not be allowed during intake"

    def test_bash_execution_allowed(self):
        r = check_permission("orchestrator", "bash", current_phase="execution")
        assert r["allowed"]

    def test_bash_intake_denied(self):
        r = check_permission("orchestrator", "bash", current_phase="intake")
        assert not r["allowed"]

    def test_koan_set_phase_always_allowed(self):
        for phase in ("intake", "brief-generation", "execution", "implementation-validation"):
            r = check_permission("orchestrator", "koan_set_phase", current_phase=phase)
            assert r["allowed"], f"koan_set_phase should be allowed in phase '{phase}'"

    def test_koan_complete_step_always_allowed(self):
        for phase in ("intake", "brief-generation", "execution"):
            r = check_permission("orchestrator", "koan_complete_step", current_phase=phase)
            assert r["allowed"]

    def test_koan_search_allowed_in_every_phase(self):
        for phase in ("intake", "brief-generation", "execution", "implementation-validation", "curation"):
            r = check_permission("orchestrator", "koan_search", current_phase=phase)
            assert r["allowed"], f"koan_search should be allowed in phase '{phase}'"


# -- Exhaustive role x tool matrix ---------------------------------------------

def _build_matrix():
    """Generate (role, tool, expected_allowed) for every role x tool pair.

    Expected result: allowed iff the tool is in READ_TOOLS or in that role's
    ROLE_PERMISSIONS entry.  Step is set to 2 to avoid step-1 blocking.
    Only applies to non-orchestrator roles (orchestrator is phase-aware).
    """
    cases = []
    for role in ALL_ROLES:
        if role == "orchestrator":
            continue  # orchestrator uses phase-aware checks, tested separately
        # _UNIVERSAL_MEMORY_TOOLS are allowed for all roles via fast-path.
        allowed_set = ROLE_PERMISSIONS[role] | READ_TOOLS | _UNIVERSAL_MEMORY_TOOLS
        for tool in sorted(ALL_KOAN_TOOLS):
            expected = tool in allowed_set
            cases.append((role, tool, expected))
    return cases


_MATRIX = _build_matrix()
_MATRIX_IDS = [f"{role}-{tool}-{'allow' if exp else 'deny'}" for role, tool, exp in _MATRIX]


class TestExhaustiveRoleToolMatrix:
    """Mechanically verify every non-orchestrator role x tool combination."""

    @pytest.mark.parametrize("role,tool,expected", _MATRIX, ids=_MATRIX_IDS)
    def test_role_tool(self, role, tool, expected):
        r = check_permission(role, tool, current_step=2)
        assert r["allowed"] == expected, (
            f"role={role} tool={tool}: expected allowed={expected}, got {r}"
        )


# -- Path scoping --------------------------------------------------------------

class TestPathScoping:
    def setup_method(self):
        self.run_dir = "/tmp/run"

    def test_write_inside_run_dir_allowed(self):
        r = check_permission(
            "intake", "write",
            run_dir=self.run_dir,
            tool_args={"path": "/tmp/run/foo.md"},
            current_step=2,
        )
        assert r["allowed"]

    def test_write_outside_run_dir_denied(self):
        r = check_permission(
            "intake", "write",
            run_dir=self.run_dir,
            tool_args={"path": "/home/user/evil.sh"},
            current_step=2,
        )
        assert not r["allowed"]
        assert "outside run directory" in r["reason"]

    def test_edit_outside_run_dir_denied(self):
        r = check_permission(
            "planner", "edit",
            run_dir=self.run_dir,
            tool_args={"path": "/etc/passwd"},
            current_step=2,
        )
        assert not r["allowed"]

    def test_write_at_run_dir_root_allowed(self):
        r = check_permission(
            "intake", "write",
            run_dir=self.run_dir,
            tool_args={"path": "/tmp/run"},
            current_step=2,
        )
        assert r["allowed"]

    def test_orchestrator_write_inside_run_dir_allowed(self):
        r = check_permission(
            "orchestrator", "write",
            run_dir=self.run_dir,
            tool_args={"path": "/tmp/run/brief.md"},
            current_phase="brief-generation",
            current_step=2,
        )
        assert r["allowed"]

    def test_orchestrator_write_outside_run_dir_denied(self):
        r = check_permission(
            "orchestrator", "write",
            run_dir=self.run_dir,
            tool_args={"path": "/home/user/evil.sh"},
            current_phase="intake",
            current_step=2,
        )
        assert not r["allowed"]
        assert "outside run directory" in r["reason"]


# -- Executor unrestricted write -----------------------------------------------

class TestExecutorUnrestricted:
    def test_write_outside_run_dir_allowed(self):
        r = check_permission(
            "executor", "write",
            run_dir="/tmp/run",
            tool_args={"path": "/home/user/code.py"},
            current_step=2,
        )
        assert r["allowed"]


# -- No run_dir / no path arg ------------------------------------------------

class TestNoEpicDirNoPathArg:
    def test_no_run_dir_allows_write(self):
        r = check_permission("intake", "write", current_step=2)
        assert r["allowed"]

    def test_no_path_arg_allows_write(self):
        r = check_permission(
            "intake", "write",
            run_dir="/tmp/run",
            tool_args={"content": "hello"},
            current_step=2,
        )
        assert r["allowed"]

    def test_no_tool_args_allows_write(self):
        r = check_permission(
            "intake", "write",
            run_dir="/tmp/run",
            current_step=2,
        )
        assert r["allowed"]
