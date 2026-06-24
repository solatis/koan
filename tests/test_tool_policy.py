# Unit tests for ToolPolicy, compose_toolset, and phase_gate_message.
#
# Verifies that compose_toolset produces the correct per-role tool set
# (phase-independent static vocabulary) and that phase_gate_message correctly
# gates the orchestrator's phase-conditional tools at call time.

from __future__ import annotations

import pytest

from koan.tools.tool_policy import (
    build_tool_policy,
    compose_toolset,
    phase_gate_message,
    # _ORCHESTRATOR_STORY_TOOLS removed in M1; story tools deleted.
    _ORCHESTRATOR_SCOUT_PHASES,
    _ORCHESTRATOR_BASH_PHASES,
    _ORCHESTRATOR_EXECUTOR_PHASES,
    _UNIVERSAL_MEMORY_TOOLS,
    _UNIVERSAL_READ_TOOLS,
    _NON_BASH_READ_TOOLS,
)

# -- Shared constants for assertions ------------------------------------------

# Tools that must always be present regardless of role or phase.
_ALWAYS_PRESENT = _UNIVERSAL_MEMORY_TOOLS | _UNIVERSAL_READ_TOOLS | _NON_BASH_READ_TOOLS


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture(scope="module")
def policy():
    """Build the ToolPolicy once for the whole module; it is stateless."""
    return build_tool_policy()


# -- Helper -------------------------------------------------------------------

def _compose(policy, role, phase=None):
    """Thin wrapper so tests read more like assertions than calls.

    The phase parameter is accepted for call-site readability (test class
    fixtures set self.PHASE) but is NOT forwarded to compose_toolset --
    toolset composition is now role-based only, and phase-appropriateness
    is enforced at call time by phase_gate_message.
    """
    return compose_toolset(policy, role)


# -- Tests: orchestrator in a planning phase ----------------------------------

class TestOrchestratorPlanningPhase:
    """Orchestrator in a planning phase (e.g. plan).

    The static role-based toolset always includes bash, koan_request_scouts,
    and koan_request_executor; phase-appropriateness is enforced at call time
    by phase_gate_message rather than by omitting tools from the vocabulary.
    Story tools were removed in M1.
    """

    PHASE = "plan"  # a member of _ORCHESTRATOR_SCOUT_PHASES

    def test_universals_present(self, policy):
        """Universal memory and read-only artifact tools must always appear."""
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert _ALWAYS_PRESENT <= toolset, (
            f"Expected {_ALWAYS_PRESENT!r} to be a subset of {toolset!r}"
        )

    def test_scouts_present(self, policy):
        """koan_request_scouts is always registered in the static orchestrator toolset.

        Phase-appropriateness is enforced by phase_gate_message at call time;
        the tool is present in the vocabulary regardless of phase.
        """
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert "koan_request_scouts" in toolset

    def test_bash_present(self, policy):
        """Bash is always registered in the orchestrator's static toolset.

        Phase-appropriateness is enforced by phase_gate_message at call time
        (bash is gated to _ORCHESTRATOR_BASH_PHASES); the tool is present in
        the registered vocabulary regardless of phase.
        """
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert "bash" in toolset

    def test_executor_tool_present(self, policy):
        """koan_request_executor is always registered in the orchestrator's static toolset.

        Phase-appropriateness is enforced by phase_gate_message at call time
        (gated to _ORCHESTRATOR_EXECUTOR_PHASES); the tool is present in the
        registered vocabulary regardless of phase.
        """
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert "koan_request_executor" in toolset

    def test_step_machine_tools_present(self, policy):
        """koan_set_phase and koan_suggest_next must always be present for orchestrator.

        koan_complete_step was removed in M6; koan_suggest_next is the
        orchestrator-only hand-back suggestion tool that replaced it.
        """
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert "koan_set_phase" in toolset
        assert "koan_suggest_next" in toolset
        assert "koan_complete_step" not in toolset

    def test_memory_tools_present(self, policy):
        """Orchestrator-specific memory tools (memorize, forget, reflect) present."""
        toolset = _compose(policy, "orchestrator", self.PHASE)
        for tool in ("koan_memorize", "koan_forget", "koan_reflect"):
            assert tool in toolset, f"{tool!r} must be in orchestrator toolset"


# -- Tests: negative-presence (M1 removals) -----------------------------------

class TestM1Removals:
    """Negative-presence tests asserting M1 dead-code removal is complete.

    The legacy "execution" phase, the four koan_*_story tools, story_phases,
    phase_dag, and the orchestrator.py module must all be gone.
    """

    def test_story_tools_absent_from_execute_phase(self, policy):
        """Story tools must not appear in any phase after M1."""
        _STORY_TOOLS = {
            "koan_select_story", "koan_complete_story",
            "koan_retry_story", "koan_skip_story",
        }
        for tool in _STORY_TOOLS:
            toolset = _compose(policy, "orchestrator", "execute")
            assert tool not in toolset, f"{tool!r} must not be in execute toolset"

    def test_execution_phase_not_in_scout_phases(self, policy):
        """The legacy 'execution' phase must not appear in scout phases."""
        assert "execution" not in _ORCHESTRATOR_SCOUT_PHASES

    def test_story_phases_not_on_tool_policy(self, policy):
        """ToolPolicy must not have a story_phases field after M1."""
        assert not hasattr(policy, "story_phases"), (
            "ToolPolicy.story_phases was not removed in M1"
        )

    def test_phase_dag_not_importable(self):
        """koan.lib.phase_dag must not be importable after M1."""
        import importlib
        import importlib.util
        spec = importlib.util.find_spec("koan.lib.phase_dag")
        assert spec is None, "koan.lib.phase_dag still importable after M1 removal"

    def test_orchestrator_phase_module_not_importable(self):
        """koan.phases.orchestrator must not be importable after M1."""
        import importlib.util
        spec = importlib.util.find_spec("koan.phases.orchestrator")
        assert spec is None, "koan.phases.orchestrator still importable after M1 removal"

    def test_executor_phases_present_on_policy(self, policy):
        """executor_phases is present on ToolPolicy (re-added in M4 of living-docs initiative).

        koan_request_executor is phase-gated to execute; executor_phases carries
        the allowlist that compose_toolset checks.
        """
        assert hasattr(policy, "executor_phases"), (
            "ToolPolicy.executor_phases is missing -- re-add it for the phase gate"
        )
        assert "execute" in policy.executor_phases

    def test_koan_request_executor_in_koan_mcp_tools(self):
        """koan_request_executor must appear in KOAN_MCP_TOOLS (re-added in M4 of living-docs initiative).

        The projection fold uses KOAN_MCP_TOOLS to classify koan tool calls;
        the tool must be present so executor launches are tracked.
        """
        from koan.agents.events import KOAN_MCP_TOOLS
        assert "koan_request_executor" in KOAN_MCP_TOOLS

    def test_request_executor_core_importable(self):
        """request_executor_core must be importable from koan.tools.koan_tools (re-added in M4 of living-docs initiative)."""
        import koan.tools.koan_tools as kt
        assert hasattr(kt, "request_executor_core"), (
            "request_executor_core missing from koan.tools.koan_tools"
        )


# -- Tests: orchestrator in execute phase -------------------------------------

class TestOrchestratorExecutePhase:
    """Orchestrator in the execute phase.

    All three phase-conditional tools (koan_request_executor, bash,
    koan_request_scouts) are always present in the static toolset.
    Phase-appropriateness for scouts (not allowed in execute) is enforced
    by phase_gate_message at call time, not by omitting it from the vocabulary.
    """

    PHASE = "execute"

    def test_executor_tool_present(self, policy):
        """koan_request_executor is always registered in the static orchestrator toolset."""
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert "koan_request_executor" in toolset

    def test_bash_present(self, policy):
        """bash is always registered in the orchestrator's static toolset."""
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert "bash" in toolset

    def test_scouts_present(self, policy):
        """koan_request_scouts is always registered in the static orchestrator toolset.

        Although execute is not a scout phase, the tool is still registered;
        phase_gate_message returns a denial when it is invoked in execute.
        """
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert "koan_request_scouts" in toolset

    def test_universals_present(self, policy):
        """Universal memory and read-only artifact tools always present."""
        toolset = _compose(policy, "orchestrator", self.PHASE)
        assert _ALWAYS_PRESENT <= toolset


# -- Tests: executor role -----------------------------------------------------

class TestExecutorRole:
    """Executor role.

    Has bash unconditionally; has koan_complete_step; no orchestrator tools.
    """

    PHASE = "execute"

    def test_universals_present(self, policy):
        """Universal memory and read-only artifact tools always present."""
        toolset = _compose(policy, "executor", self.PHASE)
        assert _ALWAYS_PRESENT <= toolset

    def test_bash_present(self, policy):
        """Non-orchestrator roles always have bash regardless of phase."""
        toolset = _compose(policy, "executor", self.PHASE)
        assert "bash" in toolset

    def test_koan_complete_step_absent(self, policy):
        """koan_complete_step removed in M6 -- not in executor toolset."""
        toolset = _compose(policy, "executor", self.PHASE)
        assert "koan_complete_step" not in toolset

    def test_no_story_tools(self, policy):
        """Story management tools are gone after M1; executors must not have them."""
        _STORY_TOOLS = {
            "koan_select_story", "koan_complete_story",
            "koan_retry_story", "koan_skip_story",
        }
        toolset = _compose(policy, "executor", self.PHASE)
        for tool in _STORY_TOOLS:
            assert tool not in toolset

    def test_no_orchestrator_set_phase(self, policy):
        """koan_set_phase is orchestrator-only."""
        toolset = _compose(policy, "executor", self.PHASE)
        assert "koan_set_phase" not in toolset

    def test_write_edit_present(self, policy):
        """Executors have write and edit (unrestricted file access)."""
        toolset = _compose(policy, "executor", self.PHASE)
        assert "write" in toolset
        assert "edit" in toolset


# -- Tests: scout role --------------------------------------------------------

class TestReviewerRole:
    """Reviewer role.

    Read-only: has bash, universals, koan_artifact_read/list, koan_reflect.
    Must NOT have write, edit, koan_artifact_write, koan_artifact_edit,
    koan_request_scouts, or koan_set_phase.

    Added in M3 as a fresh-context, blocking sub-agent spawned mechanically
    by artifact_write_core when an artifact's family carries a reviewer charter.
    """

    PHASE = "plan"

    def test_universals_present(self, policy):
        """Universal memory and read-only artifact tools always present."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert _ALWAYS_PRESENT <= toolset

    def test_bash_present(self, policy):
        """Non-orchestrator roles always have bash -- reviewers are no exception."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "bash" in toolset

    def test_koan_reflect_present(self, policy):
        """koan_reflect is the only koan-specific tool the reviewer needs beyond universals."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "koan_reflect" in toolset

    def test_write_absent(self, policy):
        """Reviewer is strictly read-only: write must not appear."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "write" not in toolset

    def test_edit_absent(self, policy):
        """Reviewer is strictly read-only: edit must not appear."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "edit" not in toolset

    def test_koan_artifact_write_absent(self, policy):
        """Reviewer must not have koan_artifact_write."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "koan_artifact_write" not in toolset

    def test_koan_artifact_edit_absent(self, policy):
        """Reviewer must not have koan_artifact_edit."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "koan_artifact_edit" not in toolset

    def test_koan_request_scouts_absent(self, policy):
        """Reviewer has no scout delegation -- verifies claims directly."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "koan_request_scouts" not in toolset

    def test_koan_set_phase_absent(self, policy):
        """koan_set_phase is orchestrator-only; reviewer must not have it."""
        toolset = _compose(policy, "reviewer", self.PHASE)
        assert "koan_set_phase" not in toolset


class TestScoutRole:
    """Scout role.

    Minimal tool set: read tools and universals (koan_complete_step removed in M6).
    """

    PHASE = "plan"

    def test_universals_present(self, policy):
        """Universal memory and read-only artifact tools always present."""
        toolset = _compose(policy, "scout", self.PHASE)
        assert _ALWAYS_PRESENT <= toolset

    def test_koan_complete_step_absent(self, policy):
        """koan_complete_step removed in M6 -- not in scout toolset either.

        Scouts advance through steps by ending each turn; the loop resolver
        delivers the next step and terminates at exhaustion.
        """
        toolset = _compose(policy, "scout", self.PHASE)
        assert "koan_complete_step" not in toolset

    def test_bash_present(self, policy):
        """Non-orchestrator roles always have bash."""
        toolset = _compose(policy, "scout", self.PHASE)
        assert "bash" in toolset

    def test_no_write_edit(self, policy):
        """Scouts must not have write or edit (read-only role)."""
        toolset = _compose(policy, "scout", self.PHASE)
        assert "write" not in toolset
        assert "edit" not in toolset

    def test_no_orchestrator_tools(self, policy):
        """Scouts do not have orchestrator-specific tools."""
        toolset = _compose(policy, "scout", self.PHASE)
        assert "koan_set_phase" not in toolset
        assert "koan_reflect" not in toolset


# -- Tests: phase_gate_message ------------------------------------------------


class TestPhaseGateMessage:
    """Tests for phase_gate_message -- call-time phase-appropriateness gate.

    The gate only applies to the orchestrator role; all other roles always
    get None regardless of tool or phase. Among orchestrator calls, only the
    three phase-conditional tools (bash, koan_request_scouts,
    koan_request_executor) can produce a non-None message; all other tool
    names return None.
    """

    def test_executor_in_plan_phase_denied(self, policy):
        """koan_request_executor in plan phase returns a non-None denial message.

        The executor tool is only allowed in _ORCHESTRATOR_EXECUTOR_PHASES (execute).
        """
        msg = phase_gate_message(policy, "orchestrator", "plan", "koan_request_executor")
        assert msg is not None
        assert "koan_request_executor" in msg
        assert "plan" in msg

    def test_executor_in_execute_phase_allowed(self, policy):
        """koan_request_executor in execute phase returns None (allowed)."""
        assert "execute" in _ORCHESTRATOR_EXECUTOR_PHASES
        msg = phase_gate_message(policy, "orchestrator", "execute", "koan_request_executor")
        assert msg is None

    def test_bash_in_plan_phase_denied(self, policy):
        """bash in plan phase returns a non-None denial message.

        bash is only allowed for orchestrator in _ORCHESTRATOR_BASH_PHASES.
        """
        assert "plan" not in _ORCHESTRATOR_BASH_PHASES
        msg = phase_gate_message(policy, "orchestrator", "plan", "bash")
        assert msg is not None
        assert "bash" in msg

    def test_bash_in_execute_phase_allowed(self, policy):
        """bash in execute phase returns None (allowed)."""
        assert "execute" in _ORCHESTRATOR_BASH_PHASES
        msg = phase_gate_message(policy, "orchestrator", "execute", "bash")
        assert msg is None

    def test_scouts_in_execute_phase_denied(self, policy):
        """koan_request_scouts in execute phase returns a non-None denial message.

        execute is not in _ORCHESTRATOR_SCOUT_PHASES.
        """
        assert "execute" not in _ORCHESTRATOR_SCOUT_PHASES
        msg = phase_gate_message(policy, "orchestrator", "execute", "koan_request_scouts")
        assert msg is not None
        assert "koan_request_scouts" in msg

    def test_scouts_in_plan_phase_allowed(self, policy):
        """koan_request_scouts in plan phase returns None (allowed).

        plan is in _ORCHESTRATOR_SCOUT_PHASES.
        """
        assert "plan" in _ORCHESTRATOR_SCOUT_PHASES
        msg = phase_gate_message(policy, "orchestrator", "plan", "koan_request_scouts")
        assert msg is None

    def test_non_orchestrator_role_always_none(self, policy):
        """Non-orchestrator roles always receive None from phase_gate_message.

        The gate is orchestrator-only; executor/scout/reviewer are unaffected
        regardless of tool or phase.
        """
        for role in ("executor", "scout", "reviewer"):
            for tool in ("bash", "koan_request_scouts", "koan_request_executor"):
                msg = phase_gate_message(policy, role, "plan", tool)
                assert msg is None, (
                    f"Expected None for role={role!r} tool={tool!r}, got {msg!r}"
                )

    def test_non_phase_conditional_tool_always_none(self, policy):
        """A tool not in the gate map (e.g. koan_set_phase) always returns None.

        Only the three phase-conditional tools can be denied; all other tool
        names short-circuit to None.
        """
        msg = phase_gate_message(policy, "orchestrator", "plan", "koan_set_phase")
        assert msg is None


