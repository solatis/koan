# Tests for koan.subagent (spawn_subagent).
#
# M4: TestBuildClaudeToolLists, TestCodexPostBuildArgs, TestGeminiPostBuildArgs,
# and the two xfail legacy-spawn tests removed (claude/codex/gemini agents deleted).
# koan.runners.base import removed (runners package deleted).
# FakeAgent/FakeAgentSuccess cleaned of legacy register_process/exit_code/stderr_output
# members (those were already not in the Agent protocol after M9 docstring update).

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koan.agents.base import Agent, AgentDiagnostic, AgentError
from koan.audit import EventLog, Projection
from koan.audit.events import AgentDiagnosticEvent
from koan.phases import PhaseContext, StepGuidance
# StreamEvent imported from koan.agents.events (relocated from koan.runners.base in M4).
from koan.agents.events import StreamEvent
from koan.state import AppState


class FakeAgent:
    """Agent test double that exits immediately (bootstrap failure).

    Yields nothing so spawn_subagent reaches the handshake gate with
    handshake_observed=False, producing a bootstrap_failure diagnostic.
    """
    name = "fake"

    async def run(self, options):
        return
        yield  # noqa: unreachable -- makes this an async generator

    async def interrupt(self):
        raise NotImplementedError

    async def compact(self):
        raise NotImplementedError


class FakeAgentSuccess:
    """Agent test double that exits cleanly. Handshake set externally."""
    name = "fake"

    async def run(self, options):
        return
        yield  # noqa: unreachable -- makes this an async generator

    async def interrupt(self):
        raise NotImplementedError

    async def compact(self):
        raise NotImplementedError


def FakeAppState(port: int = 9999, run_dir: str = "") -> AppState:
    """Construct a real AppState with the given server port and run_dir.

    Tests that previously used a FakeAppState dataclass now use real AppState
    so they exercise the actual sub-state structure rather than a stub.
    """
    st = AppState()
    st.server.port = port
    st.run.run_dir = run_dir
    return st


def _fake_phase_module():
    mod = MagicMock()
    mod.ROLE = "intake"
    mod.TOTAL_STEPS = 3
    mod.PHASE_ROLE_CONTEXT = "test"
    mod.STEP_NAMES = {1: "Extract", 2: "Scout", 3: "Write"}
    mod.validate_step_completion = MagicMock(return_value=None)
    mod.get_next_step = MagicMock(return_value=1)
    mod.step_guidance = MagicMock(return_value=StepGuidance(
        title="Extract",
        instructions=["Read the conversation."],
    ))
    mod.on_loop_back = AsyncMock()
    return mod


# -- EventLog tests -----------------------------------------------------------

class TestEventLog:
    @pytest.mark.anyio
    async def test_serialization(self, tmp_path):
        log = EventLog(str(tmp_path), "intake", "intake", "test-model")
        await log.open()

        await log.emit_phase_start(5)
        await log.emit_step_transition(1, "Extract", 5)
        await log.append({"kind": "heartbeat"})

        await log.close()

        # Verify events.jsonl
        events_path = tmp_path / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) == 3

        for line in lines:
            parsed = json.loads(line)
            assert "ts" in parsed
            assert "seq" in parsed

        # Verify state.json
        state_path = tmp_path / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["role"] == "intake"
        assert state["phase"] == "intake"
        assert state["step"] == 1
        assert state["step_name"] == "Extract"
        assert state["event_count"] == 3

    @pytest.mark.anyio
    async def test_agent_diagnostic_fanout(self, tmp_path):
        log = EventLog(str(tmp_path), "scout", "scout")
        await log.open()

        diag = AgentDiagnostic(
            code="bootstrap_failure",
            agent="claude",
            stage="handshake",
            message="Process exited before completing its first turn",
        )
        await log.emit_agent_diagnostic(diag)
        await log.close()

        # Check events.jsonl
        events_path = tmp_path / "events.jsonl"
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["kind"] == "agent_diagnostic"
        assert event["code"] == "bootstrap_failure"

        # Check state.json reflects failed status
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["status"] == "failed"
        assert "first turn" in state["error"]


# -- Step-machine core tests --------------------------------------------------
# advance_step (koan_complete_step entrypoint) was removed in M6.
# Tests now call _step_phase_handshake_core and _step_within_phase_core directly,
# which are the same cores the resolver (resolve_turn_outcome) uses.

class TestStepMachineCores:
    @pytest.mark.anyio
    async def test_handshake_core_step_0_to_1_returns_guidance(self):
        """_step_phase_handshake_core delivers step-1 guidance and sets step=1."""
        from koan.state import AgentState
        from koan.tools.koan_tools import _step_phase_handshake_core

        phase_mod = _fake_phase_module()
        event_log = AsyncMock()
        event_log.emit_step_transition = AsyncMock()

        app_state = AppState()
        app_state.run.phase = "intake"

        agent = AgentState(
            agent_id="test-1",
            role="orchestrator",
            subagent_dir="/tmp/test",
            step=0,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(run_dir="/tmp", subagent_dir="/tmp/test"),
            event_log=event_log,
        )
        app_state.agents[agent.agent_id] = agent

        # Core returns guidance string directly.
        result = await _step_phase_handshake_core(agent, app_state)

        assert "Extract" in result
        assert agent.step == 1
        event_log.emit_step_transition.assert_called_once()

    @pytest.mark.anyio
    async def test_within_phase_core_advances_step(self):
        """_step_within_phase_core advances to the given next_step."""
        from koan.state import AgentState
        from koan.tools.koan_tools import _step_within_phase_core

        phase_mod = _fake_phase_module()
        phase_mod.get_next_step = MagicMock(return_value=2)
        phase_mod.TOTAL_STEPS = 3
        phase_mod.STEP_NAMES = {1: "Extract", 2: "Scout", 3: "Write"}

        app_state = AppState()
        app_state.run.phase = "intake"

        agent = AgentState(
            agent_id="test-2",
            role="orchestrator",
            subagent_dir="/tmp/test",
            step=1,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(run_dir="/tmp", subagent_dir="/tmp/test"),
            event_log=AsyncMock(),
        )
        app_state.agents[agent.agent_id] = agent

        await _step_within_phase_core(agent, app_state, phase_mod, agent.phase_ctx, 2)

        assert agent.step == 2

    @pytest.mark.anyio
    async def test_within_phase_core_loop_back_calls_on_loop_back(self):
        """_step_within_phase_core calls on_loop_back when next_step <= current_step."""
        from koan.state import AgentState
        from koan.tools.koan_tools import _step_within_phase_core

        phase_mod = _fake_phase_module()
        phase_mod.get_next_step = MagicMock(return_value=2)

        app_state = AppState()
        app_state.run.phase = "intake"

        agent = AgentState(
            agent_id="test-3",
            role="orchestrator",
            subagent_dir="/tmp/test",
            step=4,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(run_dir="/tmp", subagent_dir="/tmp/test"),
            event_log=AsyncMock(),
        )
        app_state.agents[agent.agent_id] = agent

        await _step_within_phase_core(agent, app_state, phase_mod, agent.phase_ctx, 2)

        phase_mod.on_loop_back.assert_called_once_with(4, 2, agent.phase_ctx)
        assert agent.step == 2


# -- _build_phase_ctx tests ---------------------------------------------------

class TestBuildPhaseCtx:
    def test_build_phase_ctx_reads_workflow_history(self):
        """_build_phase_ctx resolves workflow_name from workflow_history."""
        from koan.subagent import _build_phase_ctx

        task = {
            "run_dir": "/tmp/run",
            "workflow_history": [
                {"name": "milestones", "phase": "intake", "started_at": 1.0}
            ],
        }
        ctx = _build_phase_ctx(task, "/tmp/sub")
        assert ctx.workflow_name == "milestones"

    def test_build_phase_ctx_defaults_when_history_missing(self):
        """_build_phase_ctx returns empty workflow_name when workflow_history is absent."""
        from koan.subagent import _build_phase_ctx

        ctx = _build_phase_ctx({"run_dir": "/tmp/run"}, "/tmp/sub")
        assert ctx.workflow_name == ""


# -- spawn_subagent tests -----------------------------------------------------

class TestSpawnSubagent:
    @pytest.mark.anyio
    async def test_bootstrap_failure_detection(self, tmp_path):
        app_state = FakeAppState(port=9999)
        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "run_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            result = await spawn_subagent(task, app_state, agent_impl=FakeAgent())

        assert result.exit_code == 1

        # Check that events.jsonl contains an agent_diagnostic
        events_path = Path(subagent_dir) / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text().strip().split("\n")
        diag_events = [json.loads(l) for l in lines if "agent_diagnostic" in l]
        assert len(diag_events) >= 1
        assert diag_events[0]["code"] == "bootstrap_failure"

    @pytest.mark.anyio
    async def test_successful_handshake_via_first_turn(self, tmp_path):
        """Handshake is detected via first_turn_completed (set by run_agent_loop)."""
        app_state = FakeAppState(port=9999)
        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "run_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        # Simulate the first-turn signal: set first_turn_completed on the
        # AgentState during run(). With FakeAgent the run() body has direct
        # access to app_state, replacing the removed koan_complete_step approach.
        class _HandshakingAgent:
            name = "fake"

            async def run(self, options):
                for ag in app_state.agents.values():
                    ag.first_turn_completed = True
                return
                yield  # noqa: unreachable -- makes this an async generator

            def register_process(self, registry, agent_id):
                pass

            @property
            def exit_code(self):
                return 0

            @property
            def stderr_output(self):
                return ""

            async def interrupt(self):
                raise NotImplementedError

            async def compact(self):
                raise NotImplementedError

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            result = await spawn_subagent(task, app_state, agent_impl=_HandshakingAgent())

        assert result.exit_code == 0

        # Verify state.json shows completed
        state = json.loads((Path(subagent_dir) / "state.json").read_text())
        assert state["status"] == "completed"

    # test_model_field_propagated_to_agent_state removed in M4: tested legacy
    # AgentInstallation/runner_type spawn path which is deleted.


# -- fold purity (supplementary) ----------------------------------------------

class TestFoldPurity:
    def test_identical_results(self):
        from koan.audit.events import StepTransitionEvent
        from koan.audit.fold import fold

        p = Projection(role="intake", phase="intake", step=0, total_steps=5)
        e = StepTransitionEvent(ts="2026-01-01T00:00:00Z", seq=1, step=2, name="X", total_steps=5)
        r1 = fold(p, e)
        r2 = fold(p, e)
        assert r1 == r2

    def test_does_not_mutate_input(self):
        from copy import copy

        from koan.audit.events import PhaseStartEvent
        from koan.audit.fold import fold

        p = Projection(role="intake", phase="intake")
        p_copy = copy(p)
        e = PhaseStartEvent(ts="2026-01-01T00:00:00Z", seq=0, phase="scout", role="scout", total_steps=3)
        fold(p, e)
        assert p == p_copy


# -- koan_request_scouts tests ------------------------------------------------

class TestRequestScouts:
    @pytest.mark.anyio
    async def test_aggregation_ordering(self, tmp_path):
        """Scouts results are aggregated in request order."""
        from koan.state import AgentState
        from koan.tools.koan_tools import ToolDeps, request_scouts_core

        app_state = FakeAppState(port=9999, run_dir=str(tmp_path))

        agent = AgentState(
            agent_id="scout-parent",
            role="orchestrator",
            subagent_dir=str(tmp_path),
            run_dir=str(tmp_path),
            phase_module=_fake_phase_module(),
            phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
            event_log=AsyncMock(),
        )
        app_state.agents[agent.agent_id] = agent

        findings = ["Finding A", "Finding B", "Finding C"]
        call_idx = 0

        async def fake_spawn(task, app, runner=None):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            from koan.subagent import SubagentResult
            return SubagentResult(exit_code=0, final_response=findings[idx])

        # Cores return a str directly (no content blocks).
        with patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
            result = await request_scouts_core(
                ToolDeps(app_state=app_state, agent=agent),
                questions=[
                    {"id": "a", "prompt": "Q1"},
                    {"id": "b", "prompt": "Q2"},
                    {"id": "c", "prompt": "Q3"},
                ],
            )

        assert "Finding A" in result
        assert "Finding B" in result
        assert "Finding C" in result
        # Verify ordering: A before B before C
        assert result.index("Finding A") < result.index("Finding B")
        assert result.index("Finding B") < result.index("Finding C")

    @pytest.mark.anyio
    async def test_semaphore_bounds_concurrency(self, tmp_path):
        """Scout concurrency is bounded by semaphore from config."""
        from koan.state import AgentState
        from koan.tools.koan_tools import ToolDeps, request_scouts_core

        app_state = FakeAppState(port=9999, run_dir=str(tmp_path))
        app_state.provider_config.config.scout_concurrency = 1

        agent = AgentState(
            agent_id="scout-parent",
            role="orchestrator",
            subagent_dir=str(tmp_path),
            run_dir=str(tmp_path),
            phase_module=_fake_phase_module(),
            phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
            event_log=AsyncMock(),
        )
        app_state.agents[agent.agent_id] = agent

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def fake_spawn(task, app, runner=None):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            from koan.subagent import SubagentResult
            return SubagentResult(exit_code=0, final_response="ok")

        with patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
            await request_scouts_core(
                ToolDeps(app_state=app_state, agent=agent),
                questions=[
                    {"id": "x", "prompt": "Q1"},
                    {"id": "y", "prompt": "Q2"},
                    {"id": "z", "prompt": "Q3"},
                ],
            )

        assert max_concurrent <= 1, f"Expected max 1 concurrent, got {max_concurrent}"

    @pytest.mark.anyio
    async def test_missing_state_json_treated_as_failure(self, tmp_path):
        """Scout with missing state.json is unsuccessful even if exit code 0."""
        from koan.state import AgentState
        from koan.tools.koan_tools import ToolDeps, request_scouts_core

        app_state = FakeAppState(port=9999, run_dir=str(tmp_path))

        agent = AgentState(
            agent_id="scout-parent",
            role="orchestrator",
            subagent_dir=str(tmp_path),
            run_dir=str(tmp_path),
            phase_module=_fake_phase_module(),
            phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
            event_log=AsyncMock(),
        )
        app_state.agents[agent.agent_id] = agent

        async def fake_spawn(task, app, runner=None):
            from koan.subagent import SubagentResult
            return SubagentResult(exit_code=0)

        with patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
            result = await request_scouts_core(
                ToolDeps(app_state=app_state, agent=agent),
                questions=[{"id": "q", "prompt": "Q1"}],
            )

        assert result == "No findings returned."


# -- Diagnostic fan-out tests -------------------------------------------------

class TestDiagnosticFanout:
    @pytest.mark.anyio
    async def test_state_projection_retains_diagnostic_structure(self, tmp_path):
        """state.json projection includes structured diagnostic fields."""
        log = EventLog(str(tmp_path), "scout", "scout")
        await log.open()

        diag = AgentDiagnostic(
            code="bootstrap_failure",
            agent="codex",
            stage="handshake",
            message="Process exited before first koan_complete_step call",
            details={"stderr": "connection refused"},
        )
        await log.emit_agent_diagnostic(diag)
        await log.close()

        state = json.loads((tmp_path / "state.json").read_text())
        assert state["status"] == "failed"
        assert state["diagnostic"] is not None
        assert state["diagnostic"]["code"] == "bootstrap_failure"
        assert state["diagnostic"]["agent"] == "codex"
        assert state["diagnostic"]["stage"] == "handshake"
        assert state["diagnostic"]["message"] == diag.message
        assert state["diagnostic"]["details"] == {"stderr": "connection refused"}

    @pytest.mark.anyio
    async def test_sse_notification_includes_diagnostic_fields(self, tmp_path):
        """SSE notifications for bootstrap failure include full diagnostic object."""
        app_state = FakeAppState(port=9999)
        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "run_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            await spawn_subagent(task, app_state, agent_impl=FakeAgent())

        # Bootstrap failure is emitted as agent_exited with error="bootstrap_failure"
        # and the fold populates projection.notifications as Notification objects.
        notifs = app_state.projection_store.projection.notifications
        boot_notifs = [n for n in notifs if "bootstrap_failure" in n.message]
        assert len(boot_notifs) >= 1
        notif = boot_notifs[0]
        assert notif.level == "error"

    def test_fold_populates_diagnostic_field(self):
        """fold() sets diagnostic dict on agent_diagnostic events."""
        from koan.audit.fold import fold

        p = Projection(role="scout", phase="scout")
        e = AgentDiagnosticEvent(
            ts="2026-01-01T00:00:00Z",
            seq=1,
            code="bootstrap_failure",
            agent="codex",
            stage="handshake",
            message="failed",
            details={"stderr": "timeout"},
        )
        r = fold(p, e)
        assert r.diagnostic is not None
        assert r.diagnostic["code"] == "bootstrap_failure"
        assert r.diagnostic["agent"] == "codex"
        assert r.diagnostic["stage"] == "handshake"
        assert r.diagnostic["details"] == {"stderr": "timeout"}
        assert r.status == "failed"


# TestBinaryNotFoundSpawn, TestBuildClaudeToolLists, TestCodexPostBuildArgs, and
# TestGeminiPostBuildArgs removed in M4: all tested the deleted CLI agent path.
# AgentInstallation, _build_claude_tool_lists, _codex_post_build_args, and
# _gemini_post_build_args are all gone with the legacy agent modules.
