# Unit tests for _check_or_raise in koan.web.mcp_endpoint.
#
# Validates run_dir resolution from phase_ctx vs agent.run_dir,
# and confirms the permission-denied JSON envelope shape.

import json

import pytest
from fastmcp.exceptions import ToolError

from koan.phases import PhaseContext
from koan.state import AgentState
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


# -- phase_ctx.run_dir enforcement -------------------------------------------

class TestPhaseCtxRunDir:
    def test_phase_ctx_run_dir_enforced(self):
        ctx = PhaseContext(run_dir="/tmp/run", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, "write", {"path": "/home/evil.sh"})

    def test_phase_ctx_run_dir_allows_inside(self):
        ctx = PhaseContext(run_dir="/tmp/run", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        _check_or_raise(agent, "write", {"path": "/tmp/run/foo.md"})


# -- No phase_ctx -------------------------------------------------------------

class TestNoPhaseCtx:
    def test_no_phase_ctx_no_crash(self):
        agent = _make_agent()
        _check_or_raise(agent, "write")

    def test_agent_run_dir_fallback(self):
        agent = _make_agent(run_dir="/tmp/run")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, "write", {"path": "/home/evil.sh"})


# -- Empty run_dir everywhere ------------------------------------------------

class TestEmptyRunDir:
    def test_phase_ctx_empty_run_dir_no_crash(self):
        ctx = PhaseContext(run_dir="", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        _check_or_raise(agent, "write")


# -- Error envelope shape -----------------------------------------------------

class TestPermissionDeniedEnvelope:
    def test_envelope_has_error_and_message(self):
        agent = _make_agent(role="scout")
        with pytest.raises(ToolError) as exc_info:
            _check_or_raise(agent, "koan_ask_question", {"questions": []})
        body = json.loads(str(exc_info.value))
        assert body["error"] == "permission_denied"
        assert "message" in body


# -- Unknown role --------------------------------------------------------------

class TestUnknownRole:
    def test_unknown_role_raises(self):
        agent = _make_agent(role="nonexistent")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, "koan_complete_step")
