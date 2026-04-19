# Tests for koan.audit.fold -- pure fold function over all event kinds.

from copy import copy

from koan.audit.events import (
    HeartbeatEvent,
    PhaseEndEvent,
    PhaseStartEvent,
    Projection,
    RunnerDiagnosticEvent,
    StepTransitionEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
)
from koan.audit.fold import fold


def _base_projection() -> Projection:
    return Projection(
        role="intake",
        phase="intake",
        model="test-model",
        status="running",
        step=0,
        total_steps=5,
        step_name="",
        updated_at="2026-01-01T00:00:00Z",
        event_count=0,
    )


class TestPhaseStart:
    def test_sets_running_and_clears_error(self):
        p = _base_projection()
        p.error = "old error"
        p.completion_summary = "old summary"
        e = PhaseStartEvent(
            ts="2026-01-01T00:01:00Z", seq=0,
            phase="scout", role="scout", model="m1", total_steps=3,
        )
        r = fold(p, e)
        assert r.status == "running"
        assert r.step == 0
        assert r.total_steps == 3
        assert r.role == "scout"
        assert r.phase == "scout"
        assert r.model == "m1"
        assert r.error is None
        assert r.completion_summary is None
        assert r.event_count == 1


class TestStepTransition:
    def test_updates_step_fields(self):
        p = _base_projection()
        e = StepTransitionEvent(ts="2026-01-01T00:02:00Z", seq=1, step=2, name="Verify", total_steps=5)
        r = fold(p, e)
        assert r.step == 2
        assert r.step_name == "Verify"
        assert r.total_steps == 5


class TestPhaseEnd:
    def test_completed(self):
        p = _base_projection()
        e = PhaseEndEvent(ts="2026-01-01T00:03:00Z", seq=2, outcome="completed")
        r = fold(p, e)
        assert r.status == "completed"
        assert r.error is None
        assert r.current_tool_call_id is None

    def test_failed_with_detail(self):
        p = _base_projection()
        e = PhaseEndEvent(ts="2026-01-01T00:03:00Z", seq=2, outcome="failed", detail="something broke")
        r = fold(p, e)
        assert r.status == "failed"
        assert r.error == "something broke"


class TestToolCall:
    def test_sets_last_action_and_tool_call_id(self):
        p = _base_projection()
        e = ToolCallEvent(
            ts="2026-01-01T00:04:00Z", seq=3,
            tool_call_id="tc-1", tool="read", input={"path": "/foo.py"},
        )
        r = fold(p, e)
        assert r.last_action == "read /foo.py"
        assert r.current_tool_call_id == "tc-1"

    def test_complete_step_captures_summary(self):
        p = _base_projection()
        e = ToolCallEvent(
            ts="2026-01-01T00:04:00Z", seq=3,
            tool_call_id="tc-2", tool="koan_complete_step",
            input={"thoughts": "I analyzed the code and found three patterns."},
        )
        r = fold(p, e)
        assert r.completion_summary == "I analyzed the code and found three patterns."

    def test_bash_summarization(self):
        p = _base_projection()
        e = ToolCallEvent(
            ts="2026-01-01T00:04:00Z", seq=3,
            tool_call_id="tc-3", tool="bash",
            input={"command": "npm test --coverage"},
        )
        r = fold(p, e)
        assert r.last_action == "bash npm"


class TestToolResult:
    def test_clears_tool_call_id_and_sets_result_at(self):
        p = _base_projection()
        p.current_tool_call_id = "tc-1"
        e = ToolResultEvent(
            ts="2026-01-01T00:05:00Z", seq=4,
            tool_call_id="tc-1", tool="read", lines=42, chars=1500,
        )
        r = fold(p, e)
        assert r.current_tool_call_id is None
        assert r.last_tool_result_at == "2026-01-01T00:05:00Z"
        assert "read" in r.last_action


class TestRunnerDiagnostic:
    def test_fatal_code_sets_failed(self):
        p = _base_projection()
        e = RunnerDiagnosticEvent(
            ts="2026-01-01T00:06:00Z", seq=5,
            code="bootstrap_failure", runner="claude", stage="handshake",
            message="Process exited before first koan_complete_step call",
        )
        r = fold(p, e)
        assert r.status == "failed"
        assert r.error == "Process exited before first koan_complete_step call"

    def test_non_fatal_code_preserves_status(self):
        p = _base_projection()
        e = RunnerDiagnosticEvent(
            ts="2026-01-01T00:06:00Z", seq=5,
            code="model_rate_limit", runner="claude", stage="request",
            message="Rate limited, retrying",
        )
        r = fold(p, e)
        assert r.status == "running"
        assert r.last_action == "Rate limited, retrying"


class TestHeartbeat:
    def test_only_updates_timestamp_and_count(self):
        p = _base_projection()
        p.last_action = "something"
        e = HeartbeatEvent(ts="2026-01-01T00:07:00Z", seq=6)
        r = fold(p, e)
        assert r.updated_at == "2026-01-01T00:07:00Z"
        assert r.event_count == 1
        assert r.last_action == "something"


class TestUsage:
    def test_accumulates_tokens(self):
        p = _base_projection()
        p.tokens_sent = 100
        p.tokens_received = 50
        e = UsageEvent(
            ts="2026-01-01T00:08:00Z", seq=7,
            input=200, output=100, cache_read=0, cache_write=0,
        )
        r = fold(p, e)
        assert r.tokens_sent == 300
        assert r.tokens_received == 150


class TestThinking:
    def test_only_updates_base(self):
        p = _base_projection()
        e = ThinkingEvent(ts="2026-01-01T00:09:00Z", seq=8, text="hmm", chars=3)
        r = fold(p, e)
        assert r.event_count == 1
        assert r.updated_at == "2026-01-01T00:09:00Z"


class TestPurity:
    def test_same_input_same_output(self):
        p = _base_projection()
        e = StepTransitionEvent(ts="2026-01-01T00:02:00Z", seq=1, step=2, name="X", total_steps=5)
        r1 = fold(p, e)
        r2 = fold(p, e)
        assert r1 == r2

    def test_input_not_mutated(self):
        p = _base_projection()
        p_before = copy(p)
        e = PhaseStartEvent(
            ts="2026-01-01T00:01:00Z", seq=0,
            phase="scout", role="scout", model="m1", total_steps=3,
        )
        fold(p, e)
        assert p == p_before
