# Tests for koan.subagent (spawn_subagent) and MCP tool handlers.

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koan.audit import EventLog, Projection
from koan.audit.events import RunnerDiagnosticEvent
from koan.phases import PhaseContext, StepGuidance
from koan.runners.base import RunnerDiagnostic, StreamEvent


# -- Fixtures -----------------------------------------------------------------

@dataclass
class FakeConfig:
    model_tiers: Any = None
    scout_concurrency: int = 2


@dataclass
class FakeAppState:
    agents: dict = field(default_factory=dict)
    config: FakeConfig = field(default_factory=FakeConfig)
    balanced_profile: Any = None
    port: int = 9999
    active_interaction: Any = None
    interaction_queue: Any = field(default_factory=lambda: __import__("collections").deque())
    interaction_queue_max: int = 8
    frozen_logs: list = field(default_factory=list)
    epic_dir: str | None = None
    projection_store: object = field(default_factory=lambda: __import__('koan.projections', fromlist=['ProjectionStore']).ProjectionStore())


class FakeRunner:
    name = "fake"

    def build_command(self, boot_prompt, mcp_url, model):
        # Return a command that exits immediately with code 1
        return ["python3", "-c", "import sys; sys.exit(1)"]

    def parse_stream_event(self, line):
        return []


class FakeRunnerSuccess:
    """Runner that exits 0. Handshake is set via MCP path, not stream."""
    name = "fake"

    def build_command(self, boot_prompt, mcp_url, model):
        return ["python3", "-c", "pass"]

    def parse_stream_event(self, line):
        return []


def _fake_phase_module():
    mod = MagicMock()
    mod.ROLE = "intake"
    mod.TOTAL_STEPS = 3
    mod.SYSTEM_PROMPT = "test"
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
    async def test_runner_diagnostic_fanout(self, tmp_path):
        log = EventLog(str(tmp_path), "scout", "scout")
        await log.open()

        diag = RunnerDiagnostic(
            code="bootstrap_failure",
            runner="claude",
            stage="handshake",
            message="Process exited before first koan_complete_step call",
        )
        await log.emit_runner_diagnostic(diag)
        await log.close()

        # Check events.jsonl
        events_path = tmp_path / "events.jsonl"
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["kind"] == "runner_diagnostic"
        assert event["code"] == "bootstrap_failure"

        # Check state.json reflects failed status
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["status"] == "failed"
        assert "koan_complete_step" in state["error"]


# -- koan_complete_step tests -------------------------------------------------

class TestCompleteStep:
    @pytest.mark.anyio
    async def test_step_0_to_1_returns_guidance(self):
        from koan.state import AgentState

        phase_mod = _fake_phase_module()
        event_log = AsyncMock()
        event_log.emit_step_transition = AsyncMock()

        agent = AgentState(
            agent_id="test-1",
            role="intake",
            subagent_dir="/tmp/test",
            step=0,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(epic_dir="/tmp", subagent_dir="/tmp/test"),
            event_log=event_log,
        )

        from koan.web.mcp_endpoint import _agent_ctx, koan_complete_step

        token = _agent_ctx.set(agent)
        try:
            with patch("koan.web.mcp_endpoint._check_or_raise"):
                result = await koan_complete_step(thoughts="")
        finally:
            _agent_ctx.reset(token)

        assert "Extract" in result
        assert agent.step == 1
        event_log.emit_step_transition.assert_called_once()

    @pytest.mark.anyio
    async def test_validation_failure_raises(self):
        from koan.state import AgentState

        phase_mod = _fake_phase_module()
        phase_mod.validate_step_completion = MagicMock(return_value="Must write landscape.md first")

        agent = AgentState(
            agent_id="test-2",
            role="intake",
            subagent_dir="/tmp/test",
            step=4,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(epic_dir="/tmp", subagent_dir="/tmp/test"),
            event_log=AsyncMock(),
        )

        from fastmcp.exceptions import ToolError

        from koan.web.mcp_endpoint import _agent_ctx, koan_complete_step

        token = _agent_ctx.set(agent)
        try:
            with patch("koan.web.mcp_endpoint._check_or_raise"):
                with pytest.raises(ToolError):
                    await koan_complete_step(thoughts="")
        finally:
            _agent_ctx.reset(token)

    @pytest.mark.anyio
    async def test_loop_back_calls_on_loop_back(self):
        from koan.state import AgentState

        phase_mod = _fake_phase_module()
        phase_mod.get_next_step = MagicMock(return_value=2)

        agent = AgentState(
            agent_id="test-3",
            role="intake",
            subagent_dir="/tmp/test",
            step=4,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(epic_dir="/tmp", subagent_dir="/tmp/test"),
            event_log=AsyncMock(),
        )

        from koan.web.mcp_endpoint import _agent_ctx, koan_complete_step

        token = _agent_ctx.set(agent)
        try:
            with patch("koan.web.mcp_endpoint._check_or_raise"):
                await koan_complete_step(thoughts="")
        finally:
            _agent_ctx.reset(token)

        phase_mod.on_loop_back.assert_called_once_with(4, 2, agent.phase_ctx)
        assert agent.step == 2


# -- spawn_subagent tests -----------------------------------------------------

class TestSpawnSubagent:
    @pytest.mark.anyio
    async def test_bootstrap_failure_detection(self, tmp_path):
        app_state = FakeAppState(port=9999)
        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "epic_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            exit_code = await spawn_subagent(task, app_state, runner=FakeRunner())

        assert exit_code == 1

        # Check that events.jsonl contains a runner_diagnostic
        events_path = Path(subagent_dir) / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text().strip().split("\n")
        diag_events = [json.loads(l) for l in lines if "runner_diagnostic" in l]
        assert len(diag_events) >= 1
        assert diag_events[0]["code"] == "bootstrap_failure"

    @pytest.mark.anyio
    async def test_successful_handshake_via_mcp(self, tmp_path):
        """Handshake is detected via MCP path (agent.handshake_observed), not stream."""
        app_state = FakeAppState(port=9999)
        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "epic_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        # Simulate MCP-path handshake: after process spawns, set flag on agent
        real_create_subprocess = asyncio.create_subprocess_exec

        async def patched_subprocess(*args, **kwargs):
            proc = await real_create_subprocess(*args, **kwargs)
            # Mark handshake for all registered agents (simulating MCP call)
            for ag in app_state.agents.values():
                ag.handshake_observed = True
            return proc

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}), \
             patch("asyncio.create_subprocess_exec", side_effect=patched_subprocess):
            from koan.subagent import spawn_subagent

            exit_code = await spawn_subagent(task, app_state, runner=FakeRunnerSuccess())

        assert exit_code == 0

        # Verify state.json shows completed
        state = json.loads((Path(subagent_dir) / "state.json").read_text())
        assert state["status"] == "completed"

    @pytest.mark.anyio
    async def test_model_field_propagated_to_agent_state(self, tmp_path):
        """AgentState.model is set via RunnerRegistry when runner is resolved."""
        from koan.config import KoanConfig
        from koan.types import AgentInstallation, Profile, ProfileTier

        config = KoanConfig(
            agent_installations=[
                AgentInstallation(alias="fake", runner_type="claude", binary="python3"),
            ],
            profiles=[
                Profile(name="test-profile", tiers={
                    "strong": ProfileTier(runner_type="claude", model="test-model", thinking="disabled"),
                }),
            ],
            active_profile="test-profile",
        )

        app_state = FakeAppState(port=9999)
        app_state.config = config

        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "epic_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            await spawn_subagent(task, app_state, runner=FakeRunner())

        # When runner is provided directly, model is None (legacy path)
        events = app_state.projection_store.events
        agent_spawned = [e for e in events if e.event_type == "agent_spawned"]
        assert len(agent_spawned) >= 1
        assert agent_spawned[0].payload.get("model") is None, \
            f"Expected None model for direct-runner path, got {agent_spawned[0].payload}"


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
        from koan.web.mcp_endpoint import _agent_ctx, _app_state, koan_request_scouts

        app_state = FakeAppState(port=9999, epic_dir=str(tmp_path))

        agent = AgentState(
            agent_id="scout-parent",
            role="intake",
            subagent_dir=str(tmp_path),
            epic_dir=str(tmp_path),
            phase_module=_fake_phase_module(),
            phase_ctx=PhaseContext(epic_dir=str(tmp_path), subagent_dir=str(tmp_path)),
            event_log=AsyncMock(),
        )

        findings = ["Finding A", "Finding B", "Finding C"]
        call_idx = 0

        async def fake_spawn(task, app, runner=None):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            sd = Path(task["subagent_dir"])
            # Write state.json with completed status
            (sd / "state.json").write_text(json.dumps({"status": "completed"}))
            # Write findings
            (sd / "findings.md").write_text(findings[idx])
            return 0

        import koan.web.mcp_endpoint as mcp_mod
        old_app_state = mcp_mod._app_state
        mcp_mod._app_state = app_state

        token = _agent_ctx.set(agent)
        try:
            with patch("koan.web.mcp_endpoint._check_or_raise"), \
                 patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
                result = await koan_request_scouts(questions=[
                    {"id": "a", "prompt": "Q1"},
                    {"id": "b", "prompt": "Q2"},
                    {"id": "c", "prompt": "Q3"},
                ])
        finally:
            _agent_ctx.reset(token)
            mcp_mod._app_state = old_app_state

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
        from koan.web.mcp_endpoint import _agent_ctx, koan_request_scouts

        app_state = FakeAppState(port=9999, epic_dir=str(tmp_path))
        app_state.config.scout_concurrency = 1  # serial execution

        agent = AgentState(
            agent_id="scout-parent",
            role="intake",
            subagent_dir=str(tmp_path),
            epic_dir=str(tmp_path),
            phase_module=_fake_phase_module(),
            phase_ctx=PhaseContext(epic_dir=str(tmp_path), subagent_dir=str(tmp_path)),
            event_log=AsyncMock(),
        )

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
            sd = Path(task["subagent_dir"])
            (sd / "state.json").write_text(json.dumps({"status": "completed"}))
            (sd / "findings.md").write_text("ok")
            return 0

        import koan.web.mcp_endpoint as mcp_mod
        old_app_state = mcp_mod._app_state
        mcp_mod._app_state = app_state

        token = _agent_ctx.set(agent)
        try:
            with patch("koan.web.mcp_endpoint._check_or_raise"), \
                 patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
                await koan_request_scouts(questions=[
                    {"id": "x", "prompt": "Q1"},
                    {"id": "y", "prompt": "Q2"},
                    {"id": "z", "prompt": "Q3"},
                ])
        finally:
            _agent_ctx.reset(token)
            mcp_mod._app_state = old_app_state

        assert max_concurrent <= 1, f"Expected max 1 concurrent, got {max_concurrent}"

    @pytest.mark.anyio
    async def test_missing_state_json_treated_as_failure(self, tmp_path):
        """Scout with missing state.json is unsuccessful even if exit code 0."""
        from koan.state import AgentState
        from koan.web.mcp_endpoint import _agent_ctx, koan_request_scouts

        app_state = FakeAppState(port=9999, epic_dir=str(tmp_path))

        agent = AgentState(
            agent_id="scout-parent",
            role="intake",
            subagent_dir=str(tmp_path),
            epic_dir=str(tmp_path),
            phase_module=_fake_phase_module(),
            phase_ctx=PhaseContext(epic_dir=str(tmp_path), subagent_dir=str(tmp_path)),
            event_log=AsyncMock(),
        )

        async def fake_spawn(task, app, runner=None):
            sd = Path(task["subagent_dir"])
            # Write findings but NO state.json
            (sd / "findings.md").write_text("stale findings")
            return 0

        import koan.web.mcp_endpoint as mcp_mod
        old_app_state = mcp_mod._app_state
        mcp_mod._app_state = app_state

        token = _agent_ctx.set(agent)
        try:
            with patch("koan.web.mcp_endpoint._check_or_raise"), \
                 patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
                result = await koan_request_scouts(questions=[
                    {"id": "q", "prompt": "Q1"},
                ])
        finally:
            _agent_ctx.reset(token)
            mcp_mod._app_state = old_app_state

        assert result == "No findings returned."


# -- Diagnostic fan-out tests -------------------------------------------------

class TestDiagnosticFanout:
    @pytest.mark.anyio
    async def test_state_projection_retains_diagnostic_structure(self, tmp_path):
        """state.json projection includes structured diagnostic fields."""
        log = EventLog(str(tmp_path), "scout", "scout")
        await log.open()

        diag = RunnerDiagnostic(
            code="bootstrap_failure",
            runner="codex",
            stage="handshake",
            message="Process exited before first koan_complete_step call",
            details={"stderr": "connection refused"},
        )
        await log.emit_runner_diagnostic(diag)
        await log.close()

        state = json.loads((tmp_path / "state.json").read_text())
        assert state["status"] == "failed"
        assert state["diagnostic"] is not None
        assert state["diagnostic"]["code"] == "bootstrap_failure"
        assert state["diagnostic"]["runner"] == "codex"
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
            "epic_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            await spawn_subagent(task, app_state, runner=FakeRunner())

        # Bootstrap failure is emitted as agent_exited with error="bootstrap_failure"
        # and the fold populates projection.notifications.
        notifs = app_state.projection_store.projection.notifications
        boot_notifs = [n for n in notifs if n.get("error") == "bootstrap_failure"]
        assert len(boot_notifs) >= 1
        notif = boot_notifs[0]
        assert notif["type"] == "agent_exited_error"
        assert "agent_id" in notif
        assert "exit_code" in notif

    def test_fold_populates_diagnostic_field(self):
        """fold() sets diagnostic dict on runner_diagnostic events."""
        from koan.audit.fold import fold

        p = Projection(role="scout", phase="scout")
        e = RunnerDiagnosticEvent(
            ts="2026-01-01T00:00:00Z",
            seq=1,
            code="bootstrap_failure",
            runner="codex",
            stage="handshake",
            message="failed",
            details={"stderr": "timeout"},
        )
        r = fold(p, e)
        assert r.diagnostic is not None
        assert r.diagnostic["code"] == "bootstrap_failure"
        assert r.diagnostic["runner"] == "codex"
        assert r.diagnostic["stage"] == "handshake"
        assert r.diagnostic["details"] == {"stderr": "timeout"}
        assert r.status == "failed"


# -- spawn_subagent: binary not found (real integration) ----------------------

class TestBinaryNotFoundSpawn:
    @pytest.mark.anyio
    async def test_missing_binary_returns_controlled_failure(self, tmp_path):
        """spawn_subagent with a nonexistent binary returns exit 1 with diagnostics."""
        from koan.config import KoanConfig
        from koan.types import AgentInstallation, Profile, ProfileTier

        config = KoanConfig(
            agent_installations=[
                AgentInstallation(
                    alias="bad-claude", runner_type="claude",
                    binary="/nonexistent/path/claude",
                ),
            ],
            profiles=[
                Profile(name="test-profile", tiers={
                    "strong": ProfileTier(runner_type="claude", model="opus", thinking="high"),
                }),
            ],
            active_profile="test-profile",
        )

        app_state = FakeAppState(port=9999)
        app_state.config = config
        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "epic_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}), \
             patch("koan.runners.registry.shutil.which", return_value=None):
            from koan.subagent import spawn_subagent

            exit_code = await spawn_subagent(task, app_state)

        assert exit_code == 1

        # Verify agent_spawn_failed event in projection notifications
        notifs = app_state.projection_store.projection.notifications
        spawn_fails = [n for n in notifs if n.get("type") == "agent_spawn_failed"]
        assert len(spawn_fails) >= 1
        assert spawn_fails[0]["error_code"] == "no_installation"

        # Verify events.jsonl contains a runner_diagnostic
        events_path = Path(subagent_dir) / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text().strip().split("\n")
        diag_events = [json.loads(l) for l in lines if "runner_diagnostic" in l]
        assert len(diag_events) >= 1
        assert diag_events[0]["code"] == "no_installation"
