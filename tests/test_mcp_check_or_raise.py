# Unit tests for _check_or_raise in koan.web.mcp_endpoint.
#
# Validates run_dir resolution from phase_ctx vs agent.run_dir,
# and confirms the permission-denied JSON envelope shape.

import json

import pytest
from fastmcp.exceptions import ToolError

from koan.phases import PhaseContext
from koan.state import AgentState, AppState
from koan.web.mcp_endpoint import _check_or_raise


def _make_agent(
    role="intake",
    run_dir="",
    step=2,
    phase_ctx=None,
):
    a = AgentState(agent_id="test", role=role, subagent_dir="/tmp/sub")
    a.run_dir = run_dir
    a.step = step
    a.phase_ctx = phase_ctx
    return a


# _check_or_raise now requires app_state; a default AppState() provides a
# valid phase ("intake") which is sufficient for permission checks.

def _app() -> AppState:
    return AppState()


# -- phase_ctx.run_dir enforcement -------------------------------------------

class TestPhaseCtxRunDir:
    def test_phase_ctx_run_dir_enforced(self):
        ctx = PhaseContext(run_dir="/tmp/run", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, _app(), "write", {"path": "/home/evil.sh"})

    def test_phase_ctx_run_dir_allows_inside(self):
        ctx = PhaseContext(run_dir="/tmp/run", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        _check_or_raise(agent, _app(), "write", {"path": "/tmp/run/foo.md"})


# -- No phase_ctx -------------------------------------------------------------

class TestNoPhaseCtx:
    def test_no_phase_ctx_no_crash(self):
        agent = _make_agent()
        _check_or_raise(agent, _app(), "write")

    def test_agent_run_dir_fallback(self):
        agent = _make_agent(run_dir="/tmp/run")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, _app(), "write", {"path": "/home/evil.sh"})


# -- Empty run_dir everywhere ------------------------------------------------

class TestEmptyRunDir:
    def test_phase_ctx_empty_run_dir_no_crash(self):
        ctx = PhaseContext(run_dir="", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        _check_or_raise(agent, _app(), "write")


# -- Error envelope shape -----------------------------------------------------

class TestPermissionDeniedEnvelope:
    def test_envelope_has_error_and_message(self):
        agent = _make_agent(role="scout")
        with pytest.raises(ToolError) as exc_info:
            _check_or_raise(agent, _app(), "koan_ask_question", {"questions": []})
        body = json.loads(str(exc_info.value))
        assert body["error"] == "permission_denied"
        assert "message" in body


# -- Unknown role --------------------------------------------------------------

class TestUnknownRole:
    def test_unknown_role_raises(self):
        agent = _make_agent(role="nonexistent")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, _app(), "koan_complete_step")


# -- Middleware wiring check --------------------------------------------------

class TestMiddlewareWiring:
    """Verify that build_mcp_server produces handlers that work with a fake Context."""

    @pytest.mark.anyio
    async def test_handler_reachable_via_fake_context(self, tmp_path):
        """Build a server, register an agent, call a handler through FakeContext."""
        from koan.phases import PhaseContext, StepGuidance
        from unittest.mock import MagicMock, AsyncMock
        from koan.web.mcp_endpoint import build_mcp_server

        app_state = AppState()
        app_state.run.phase = "intake"

        phase_mod = MagicMock()
        phase_mod.ROLE = "intake"
        phase_mod.TOTAL_STEPS = 3
        phase_mod.PHASE_ROLE_CONTEXT = ""
        phase_mod.STEP_NAMES = {1: "Extract"}
        phase_mod.validate_step_completion = MagicMock(return_value=None)
        phase_mod.get_next_step = MagicMock(return_value=1)
        phase_mod.step_guidance = MagicMock(return_value=StepGuidance(
            title="Extract",
            instructions=["Read the conversation."],
        ))
        phase_mod.on_loop_back = AsyncMock()

        agent = AgentState(
            agent_id="test-wiring-001",
            role="orchestrator",
            subagent_dir=str(tmp_path),
            run_dir=str(tmp_path),
            step=1,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
            event_log=AsyncMock(),
        )
        app_state.agents[agent.agent_id] = agent

        _, handlers = build_mcp_server(app_state)

        class FakeContext:
            async def get_state(self, key):
                if key == "agent":
                    return agent
                return None

        # koan_complete_step at step 1 should validate and advance
        result = await handlers.koan_complete_step(FakeContext(), thoughts="")
        assert isinstance(result, list)
        assert len(result[0].text) > 0


# -- Orchestrator write/edit denied (all phases) --

class TestOrchestratorWriteEditDenied:
    """Orchestrator write/edit are denied in all phases since all artifact mutations
    flow through koan_artifact_write."""

    def test_write_denied_intake(self):
        agent = _make_agent(role="orchestrator")
        app = _app()
        app.run.phase = "intake"
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, app, "write", {"path": "/tmp/run/plan.md"})

    def test_edit_denied_intake(self):
        agent = _make_agent(role="orchestrator")
        app = _app()
        app.run.phase = "intake"
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, app, "edit", {"path": "/tmp/run/plan.md"})

    def test_write_denied_plan_spec(self):
        agent = _make_agent(role="orchestrator")
        app = _app()
        app.run.phase = "plan-spec"
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, app, "write", {"path": "/tmp/run/plan.md"})

    def test_write_denied_execute(self):
        agent = _make_agent(role="orchestrator")
        app = _app()
        app.run.phase = "execute"
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, app, "write", {"path": "/tmp/run/plan.md"})


# -- koan_artifact_propose removed (M5) -- denied for all roles ----------------

class TestArtifactProposeRemoved:
    """koan_artifact_propose was deleted in M5; the permission fence denies all roles."""

    def test_orchestrator_denied(self):
        agent = _make_agent(role="orchestrator")
        app = _app()
        app.run.phase = "plan-spec"
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, app, "koan_artifact_propose", {"filename": "plan.md"})

    def test_scout_denied(self):
        agent = _make_agent(role="scout")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, _app(), "koan_artifact_propose", {"filename": "plan.md"})

    def test_executor_denied(self):
        agent = _make_agent(role="executor")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, _app(), "koan_artifact_propose", {"filename": "plan.md"})


# -- koan_artifact_list / koan_artifact_view universal -------------------------

class TestUniversalArtifactReadTools:
    """list/view are allowed for all roles via _UNIVERSAL_READ_TOOLS fast-path."""

    def test_artifact_list_orchestrator(self):
        agent = _make_agent(role="orchestrator")
        _check_or_raise(agent, _app(), "koan_artifact_list", {})

    def test_artifact_list_scout(self):
        agent = _make_agent(role="scout")
        _check_or_raise(agent, _app(), "koan_artifact_list", {})

    def test_artifact_list_executor(self):
        agent = _make_agent(role="executor")
        _check_or_raise(agent, _app(), "koan_artifact_list", {})

    def test_artifact_list_planner(self):
        agent = _make_agent(role="planner")
        _check_or_raise(agent, _app(), "koan_artifact_list", {})

    def test_artifact_view_orchestrator(self):
        agent = _make_agent(role="orchestrator")
        _check_or_raise(agent, _app(), "koan_artifact_view", {"filename": "plan.md"})

    def test_artifact_view_scout(self):
        agent = _make_agent(role="scout")
        _check_or_raise(agent, _app(), "koan_artifact_view", {"filename": "plan.md"})

    def test_artifact_view_executor(self):
        agent = _make_agent(role="executor")
        _check_or_raise(agent, _app(), "koan_artifact_view", {"filename": "plan.md"})

    def test_unknown_role_artifact_read_denied(self):
        """Unknown role falls through to default-deny after universal fast-paths."""
        agent = _make_agent(role="unknown-role")
        # list/view are universal -- even unknown roles can use them
        _check_or_raise(agent, _app(), "koan_artifact_list", {})
        _check_or_raise(agent, _app(), "koan_artifact_view", {"filename": "plan.md"})
