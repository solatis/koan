# Tests for koan.subagent (spawn_subagent) and MCP tool handlers.

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koan.audit import EventLog, Projection
from koan.audit.events import RunnerDiagnosticEvent
from koan.phases import PhaseContext, StepGuidance
from koan.runners.base import RunnerDiagnostic, StreamEvent
from koan.state import AppState


# -- Fake Context for handler tests -------------------------------------------

class _FakeContext:
    """Minimal fastmcp Context substitute for calling handler closures in tests."""
    def __init__(self, agent):
        self._agent = agent

    async def get_state(self, key):
        if key == "agent":
            return self._agent
        return None


class FakeRunner:
    name = "fake"

    def build_command(self, boot_prompt, mcp_url, model, system_prompt="", **kwargs):
        # Return a command that exits immediately with code 1
        return ["python3", "-c", "import sys; sys.exit(1)"]

    def parse_stream_event(self, line):
        return []


class FakeRunnerSuccess:
    """Runner that exits 0. Handshake is set via MCP path, not stream."""
    name = "fake"

    def build_command(self, boot_prompt, mcp_url, model, system_prompt="", **kwargs):
        return ["python3", "-c", "pass"]

    def parse_stream_event(self, line):
        return []


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
        from koan.web.mcp_endpoint import build_mcp_server

        phase_mod = _fake_phase_module()
        event_log = AsyncMock()
        event_log.emit_step_transition = AsyncMock()

        app_state = AppState()
        app_state.run.phase = "intake"

        # role=orchestrator passes _check_or_raise for koan_complete_step on intake
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

        _, handlers = build_mcp_server(app_state)
        ctx = _FakeContext(agent)

        result = await handlers.koan_complete_step(ctx, thoughts="")

        assert "Extract" in result[0].text
        assert agent.step == 1
        event_log.emit_step_transition.assert_called_once()

    @pytest.mark.anyio
    async def test_validation_failure_raises(self):
        from fastmcp.exceptions import ToolError
        from koan.state import AgentState
        from koan.web.mcp_endpoint import build_mcp_server

        phase_mod = _fake_phase_module()
        phase_mod.validate_step_completion = MagicMock(return_value="Must write landscape.md first")

        app_state = AppState()
        app_state.run.phase = "intake"

        agent = AgentState(
            agent_id="test-2",
            role="orchestrator",
            subagent_dir="/tmp/test",
            step=4,
            phase_module=phase_mod,
            phase_ctx=PhaseContext(run_dir="/tmp", subagent_dir="/tmp/test"),
            event_log=AsyncMock(),
        )
        app_state.agents[agent.agent_id] = agent

        _, handlers = build_mcp_server(app_state)
        ctx = _FakeContext(agent)

        with pytest.raises(ToolError):
            await handlers.koan_complete_step(ctx, thoughts="")

    @pytest.mark.anyio
    async def test_loop_back_calls_on_loop_back(self):
        from koan.state import AgentState
        from koan.web.mcp_endpoint import build_mcp_server

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

        _, handlers = build_mcp_server(app_state)
        ctx = _FakeContext(agent)

        await handlers.koan_complete_step(ctx, thoughts="")

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

            result = await spawn_subagent(task, app_state, runner=FakeRunner())

        assert result.exit_code == 1

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
            "run_dir": str(tmp_path),
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

            result = await spawn_subagent(task, app_state, runner=FakeRunnerSuccess())

        assert result.exit_code == 0

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
        app_state.runner_config.config = config

        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "run_dir": str(tmp_path),
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
        from koan.web.mcp_endpoint import build_mcp_server

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

        _, handlers = build_mcp_server(app_state)
        ctx = _FakeContext(agent)

        with patch("koan.web.mcp_endpoint._check_or_raise"), \
             patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
            result = await handlers.koan_request_scouts(ctx, questions=[
                {"id": "a", "prompt": "Q1"},
                {"id": "b", "prompt": "Q2"},
                {"id": "c", "prompt": "Q3"},
            ])

        assert "Finding A" in result[0].text
        assert "Finding B" in result[0].text
        assert "Finding C" in result[0].text
        # Verify ordering: A before B before C
        assert result[0].text.index("Finding A") < result[0].text.index("Finding B")
        assert result[0].text.index("Finding B") < result[0].text.index("Finding C")

    @pytest.mark.anyio
    async def test_semaphore_bounds_concurrency(self, tmp_path):
        """Scout concurrency is bounded by semaphore from config."""
        from koan.state import AgentState
        from koan.web.mcp_endpoint import build_mcp_server

        app_state = FakeAppState(port=9999, run_dir=str(tmp_path))
        # Set via sub-state path; handler reads app_state.runner_config.config.scout_concurrency
        app_state.runner_config.config.scout_concurrency = 1

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

        _, handlers = build_mcp_server(app_state)
        ctx = _FakeContext(agent)

        with patch("koan.web.mcp_endpoint._check_or_raise"), \
             patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
            await handlers.koan_request_scouts(ctx, questions=[
                {"id": "x", "prompt": "Q1"},
                {"id": "y", "prompt": "Q2"},
                {"id": "z", "prompt": "Q3"},
            ])

        assert max_concurrent <= 1, f"Expected max 1 concurrent, got {max_concurrent}"

    @pytest.mark.anyio
    async def test_missing_state_json_treated_as_failure(self, tmp_path):
        """Scout with missing state.json is unsuccessful even if exit code 0."""
        from koan.state import AgentState
        from koan.web.mcp_endpoint import build_mcp_server

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
            # Exit 0 but return no final_response -- treated as no findings
            from koan.subagent import SubagentResult
            return SubagentResult(exit_code=0)

        _, handlers = build_mcp_server(app_state)
        ctx = _FakeContext(agent)

        with patch("koan.web.mcp_endpoint._check_or_raise"), \
             patch("koan.subagent.spawn_subagent", side_effect=fake_spawn):
            result = await handlers.koan_request_scouts(ctx, questions=[
                {"id": "q", "prompt": "Q1"},
            ])

        assert result[0].text == "No findings returned."


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
            "run_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            await spawn_subagent(task, app_state, runner=FakeRunner())

        # Bootstrap failure is emitted as agent_exited with error="bootstrap_failure"
        # and the fold populates projection.notifications as Notification objects.
        notifs = app_state.projection_store.projection.notifications
        boot_notifs = [n for n in notifs if "bootstrap_failure" in n.message]
        assert len(boot_notifs) >= 1
        notif = boot_notifs[0]
        assert notif.level == "error"

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
        app_state.runner_config.config = config
        subagent_dir = str(tmp_path / "sub")
        Path(subagent_dir).mkdir()

        task = {
            "role": "intake",
            "run_dir": str(tmp_path),
            "subagent_dir": subagent_dir,
        }

        with patch("koan.subagent.PHASE_MODULE_MAP", {"intake": _fake_phase_module()}):
            from koan.subagent import spawn_subagent

            result = await spawn_subagent(task, app_state)

        assert result.exit_code == 1

        # Verify agent_spawn_failed event in projection notifications (new model: Notification objects)
        notifs = app_state.projection_store.projection.notifications
        spawn_fails = [n for n in notifs if n.level == "error"]
        assert len(spawn_fails) >= 1
        # Message should mention the binary_not_found error
        assert any("not found" in n.message.lower() or "binary" in n.message.lower() for n in spawn_fails)

        # Verify events.jsonl contains a runner_diagnostic
        events_path = Path(subagent_dir) / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text().strip().split("\n")
        diag_events = [json.loads(l) for l in lines if "runner_diagnostic" in l]
        assert len(diag_events) >= 1
        assert diag_events[0]["code"] == "binary_not_found"


# -- _claude_post_build_args --------------------------------------------------

class TestClaudePostBuildArgs:
    """Unit tests for the pure _claude_post_build_args helper.

    The helper composes claude-only argv entries without I/O. Tests exercise
    the full whitelist/dir/permission_mode combinations directly.
    """

    from koan.subagent import CLAUDE_TOOL_WHITELISTS as _WHITELISTS

    def test_orchestrator_full_args(self):
        from koan.subagent import _claude_post_build_args, CLAUDE_TOOL_WHITELISTS
        args = _claude_post_build_args("orchestrator", "/run", "/proj", [])
        assert "--tools" in args
        tools_idx = args.index("--tools")
        assert args[tools_idx + 1] == CLAUDE_TOOL_WHITELISTS["orchestrator"]
        assert "--disable-slash-commands" in args
        assert "--strict-mcp-config" in args
        assert "--add-dir" in args
        # Both dirs present
        add_dir_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        add_dirs = [args[i + 1] for i in add_dir_indices]
        assert "/proj" in add_dirs
        assert "/run" in add_dirs
        assert "--permission-mode" in args
        pm_idx = args.index("--permission-mode")
        assert args[pm_idx + 1] == "acceptEdits"

    def test_executor_gets_executor_whitelist(self):
        from koan.subagent import _claude_post_build_args, CLAUDE_TOOL_WHITELISTS
        args = _claude_post_build_args("executor", "/run", "/proj", [])
        tools_idx = args.index("--tools")
        assert args[tools_idx + 1] == CLAUDE_TOOL_WHITELISTS["executor"]

    def test_scout_gets_scout_whitelist(self):
        from koan.subagent import _claude_post_build_args, CLAUDE_TOOL_WHITELISTS
        args = _claude_post_build_args("scout", "/run", "/proj", [])
        tools_idx = args.index("--tools")
        assert args[tools_idx + 1] == CLAUDE_TOOL_WHITELISTS["scout"]

    def test_unknown_role_omits_tools_flag(self):
        from koan.subagent import _claude_post_build_args
        args = _claude_post_build_args("bogus", "/run", "/proj", [])
        assert "--tools" not in args

    def test_empty_run_dir_skipped(self):
        from koan.subagent import _claude_post_build_args
        args = _claude_post_build_args("orchestrator", "", "/proj", [])
        add_dir_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        add_dirs = [args[i + 1] for i in add_dir_indices]
        assert "/proj" in add_dirs
        assert "" not in add_dirs

    def test_empty_project_dir_skipped(self):
        from koan.subagent import _claude_post_build_args
        args = _claude_post_build_args("orchestrator", "/run", "", [])
        add_dir_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        add_dirs = [args[i + 1] for i in add_dir_indices]
        assert "/run" in add_dirs
        assert "" not in add_dirs

    def test_both_dirs_empty(self):
        from koan.subagent import _claude_post_build_args
        args = _claude_post_build_args("orchestrator", "", "", [])
        assert "--add-dir" not in args

    def test_permission_mode_always_present(self):
        from koan.subagent import _claude_post_build_args
        # Even with empty dirs and unknown role, permission mode is always set.
        args = _claude_post_build_args("bogus", "", "", [])
        assert "--permission-mode" in args
        pm_idx = args.index("--permission-mode")
        assert args[pm_idx + 1] == "acceptEdits"

    def test_koan_mcp_tools_preapproved(self):
        from koan.subagent import _claude_post_build_args
        # Every role must have koan MCP calls pre-approved so the CLI does not
        # prompt for permission on koan_* tools.
        for role in ("orchestrator", "executor", "scout", "bogus"):
            args = _claude_post_build_args(role, "/run", "/proj", [])
            assert "--allowedTools" in args, role
            at_idx = args.index("--allowedTools")
            assert args[at_idx + 1] == "mcp__koan__*,Bash", role


    def test_additional_dirs_emitted_after_run_dir(self):
        from koan.subagent import _claude_post_build_args
        args = _claude_post_build_args(
            "orchestrator", "/run", "/proj", ["/extra1", "/extra2"]
        )
        add_dir_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        add_dirs = [args[i + 1] for i in add_dir_indices]
        assert add_dirs == ["/proj", "/run", "/extra1", "/extra2"]

    def test_additional_dirs_empty_strings_skipped(self):
        from koan.subagent import _claude_post_build_args
        args = _claude_post_build_args(
            "orchestrator", "/run", "/proj", ["", "/real", ""]
        )
        add_dir_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        add_dirs = [args[i + 1] for i in add_dir_indices]
        assert add_dirs == ["/proj", "/run", "/real"]
        assert "" not in add_dirs

    def test_additional_dirs_default_empty(self):
        from koan.subagent import _claude_post_build_args
        # Existing behavior preserved: empty list adds nothing beyond proj/run.
        args = _claude_post_build_args("orchestrator", "/run", "/proj", [])
        add_dir_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        add_dirs = [args[i + 1] for i in add_dir_indices]
        assert add_dirs == ["/proj", "/run"]


class TestCodexPostBuildArgs:
    """Unit tests for the pure _codex_post_build_args helper."""

    def test_emits_add_dir_for_project_run_and_extras(self):
        from koan.subagent import _codex_post_build_args
        args = _codex_post_build_args("/run", "/proj", ["/a", "/b"])
        add_dir_indices = [i for i, x in enumerate(args) if x == "--add-dir"]
        assert [args[i + 1] for i in add_dir_indices] == ["/proj", "/run", "/a", "/b"]

    def test_empty_inputs_emit_nothing(self):
        from koan.subagent import _codex_post_build_args
        assert _codex_post_build_args("", "", []) == []

    def test_empty_strings_skipped(self):
        from koan.subagent import _codex_post_build_args
        args = _codex_post_build_args("", "/proj", ["", "/x"])
        add_dir_indices = [i for i, x in enumerate(args) if x == "--add-dir"]
        assert [args[i + 1] for i in add_dir_indices] == ["/proj", "/x"]


class TestGeminiPostBuildArgs:
    """Unit tests for the pure _gemini_post_build_args helper."""

    def test_emits_include_directories_for_project_run_and_extras(self):
        from koan.subagent import _gemini_post_build_args
        args = _gemini_post_build_args("/run", "/proj", ["/a", "/b"])
        inc_indices = [i for i, x in enumerate(args) if x == "--include-directories"]
        assert [args[i + 1] for i in inc_indices] == ["/proj", "/run", "/a", "/b"]
        assert "--add-dir" not in args  # gemini uses a different flag name

    def test_empty_inputs_emit_nothing(self):
        from koan.subagent import _gemini_post_build_args
        assert _gemini_post_build_args("", "", []) == []

    def test_empty_strings_skipped(self):
        from koan.subagent import _gemini_post_build_args
        args = _gemini_post_build_args("", "/proj", ["", "/x"])
        inc_indices = [i for i, x in enumerate(args) if x == "--include-directories"]
        assert [args[i + 1] for i in inc_indices] == ["/proj", "/x"]
