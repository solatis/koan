# Unit tests for _check_or_raise in koan.web.mcp_endpoint.
#
# Validates epic_dir resolution from phase_ctx vs agent.epic_dir,
# and confirms the permission-denied JSON envelope shape.

import json

import pytest
from fastmcp.exceptions import ToolError

from koan.phases import PhaseContext
from koan.state import AgentState
from koan.web.mcp_endpoint import _check_or_raise


def _make_agent(
    role="intake",
    epic_dir="",
    step=2,
    phase_ctx=None,
):
    a = AgentState(agent_id="test", role=role, subagent_dir="/tmp/sub")
    a.epic_dir = epic_dir
    a.step = step
    a.phase_ctx = phase_ctx
    return a


# -- phase_ctx.epic_dir enforcement -------------------------------------------

class TestPhaseCtxEpicDir:
    def test_phase_ctx_epic_dir_enforced(self):
        ctx = PhaseContext(epic_dir="/tmp/epic", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, "write", {"path": "/home/evil.sh"})

    def test_phase_ctx_epic_dir_allows_inside(self):
        ctx = PhaseContext(epic_dir="/tmp/epic", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        _check_or_raise(agent, "write", {"path": "/tmp/epic/foo.md"})


# -- No phase_ctx -------------------------------------------------------------

class TestNoPhaseCtx:
    def test_no_phase_ctx_no_crash(self):
        agent = _make_agent()
        _check_or_raise(agent, "write")

    def test_agent_epic_dir_fallback(self):
        agent = _make_agent(epic_dir="/tmp/epic")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, "write", {"path": "/home/evil.sh"})


# -- Empty epic_dir everywhere ------------------------------------------------

class TestEmptyEpicDir:
    def test_phase_ctx_empty_epic_dir_no_crash(self):
        ctx = PhaseContext(epic_dir="", subagent_dir="/tmp/sub")
        agent = _make_agent(phase_ctx=ctx)
        _check_or_raise(agent, "write")


# -- Error envelope shape -----------------------------------------------------

class TestPermissionDeniedEnvelope:
    def test_envelope_has_error_and_message(self):
        agent = _make_agent(role="scout")
        with pytest.raises(ToolError) as exc_info:
            _check_or_raise(agent, "koan_set_confidence", {"level": "high"})
        body = json.loads(str(exc_info.value))
        assert body["error"] == "permission_denied"
        assert "message" in body


# -- Unknown role --------------------------------------------------------------

class TestUnknownRole:
    def test_unknown_role_raises(self):
        agent = _make_agent(role="nonexistent")
        with pytest.raises(ToolError, match="permission_denied"):
            _check_or_raise(agent, "koan_complete_step")
