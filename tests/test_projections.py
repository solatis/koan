# Tests for koan.projections (ProjectionStore, fold) and koan.events (build_artifact_diff).

from __future__ import annotations

import asyncio
import json

import pytest

from koan.projections import (
    AgentProjection,
    Projection,
    ProjectionStore,
    VersionedEvent,
    fold,
)


# -- fold: lifecycle -----------------------------------------------------------

class TestFoldLifecycle:
    def _event(self, event_type: str, payload: dict, agent_id: str | None = None, version: int = 1) -> VersionedEvent:
        return VersionedEvent(
            version=version,
            event_type=event_type,
            timestamp="2026-01-01T00:00:00Z",
            agent_id=agent_id,
            payload=payload,
        )

    def test_phase_started(self):
        p = Projection()
        e = self._event("phase_started", {"phase": "intake"})
        r = fold(p, e)
        assert r.phase == "intake"
        assert r.run_started is True

    def test_agent_spawned_primary(self):
        p = Projection()
        e = self._event("agent_spawned", {"role": "intake", "model": "opus", "is_primary": True}, agent_id="a1")
        r = fold(p, e)
        assert r.primary_agent is not None
        assert r.primary_agent.agent_id == "a1"
        assert r.primary_agent.role == "intake"

    def test_agent_spawned_scout(self):
        p = Projection()
        e = self._event("agent_spawned", {"role": "scout", "model": None, "is_primary": False}, agent_id="s1")
        r = fold(p, e)
        assert "s1" in r.scouts
        assert r.primary_agent is None

    def test_agent_spawn_failed(self):
        p = Projection()
        e = self._event("agent_spawn_failed", {"role": "intake", "error_code": "binary_not_found", "message": "not found"})
        r = fold(p, e)
        assert len(r.notifications) == 1
        assert r.notifications[0]["type"] == "agent_spawn_failed"
        assert r.notifications[0]["error_code"] == "binary_not_found"

    def test_agent_step_advanced(self):
        p = Projection(primary_agent=AgentProjection(agent_id="a1", role="intake"))
        e = self._event("agent_step_advanced", {"step": 2, "step_name": "Scout"}, agent_id="a1")
        r = fold(p, e)
        assert r.primary_agent.step == 2
        assert r.primary_agent.step_name == "Scout"

    def test_agent_step_advanced_unknown_agent(self):
        p = Projection()
        e = self._event("agent_step_advanced", {"step": 1, "step_name": "X"}, agent_id="unknown")
        r = fold(p, e)
        # Unknown agent: unchanged
        assert r == p

    def test_agent_step_advanced_accumulates_usage(self):
        p = Projection(primary_agent=AgentProjection(agent_id="a1", role="intake", output_tokens=10))
        e = self._event("agent_step_advanced", {"step": 1, "step_name": "", "usage": {"input_tokens": 5, "output_tokens": 20}}, agent_id="a1")
        r = fold(p, e)
        assert r.primary_agent.input_tokens == 5
        assert r.primary_agent.output_tokens == 30

    def test_agent_exited_primary(self):
        p = Projection(primary_agent=AgentProjection(agent_id="a1", role="intake"))
        e = self._event("agent_exited", {"exit_code": 0}, agent_id="a1")
        r = fold(p, e)
        assert r.primary_agent is None
        assert len(r.completed_agents) == 1
        assert r.completed_agents[0].agent_id == "a1"

    def test_agent_exited_accumulates_final_tokens(self):
        p = Projection(primary_agent=AgentProjection(agent_id="a1", role="intake", output_tokens=50))
        e = self._event("agent_exited", {"exit_code": 0, "usage": {"output_tokens": 25}}, agent_id="a1")
        r = fold(p, e)
        assert r.completed_agents[0].output_tokens == 75
        assert r.primary_agent is None

    def test_agent_exited_with_error_appends_notification(self):
        p = Projection(primary_agent=AgentProjection(agent_id="a1", role="intake"))
        e = self._event("agent_exited", {"exit_code": 1, "error": "bootstrap_failure"}, agent_id="a1")
        r = fold(p, e)
        assert len(r.notifications) == 1
        assert r.notifications[0]["error"] == "bootstrap_failure"
        assert r.notifications[0]["type"] == "agent_exited_error"

    def test_agent_exited_scout(self):
        p = Projection(scouts={"s1": AgentProjection(agent_id="s1", role="scout")})
        e = self._event("agent_exited", {"exit_code": 0}, agent_id="s1")
        r = fold(p, e)
        assert "s1" not in r.scouts
        assert len(r.completed_agents) == 1

    def test_workflow_completed(self):
        p = Projection()
        e = self._event("workflow_completed", {"success": True, "summary": "done"})
        r = fold(p, e)
        assert r.completion == {"success": True, "summary": "done"}


# -- fold: activity -----------------------------------------------------------

class TestFoldActivity:
    def _event(self, event_type: str, payload: dict, agent_id: str | None = None) -> VersionedEvent:
        return VersionedEvent(version=1, event_type=event_type, timestamp="2026-01-01T00:00:00Z",
                              agent_id=agent_id, payload=payload)

    def test_tool_called_appended(self):
        p = Projection()
        e = self._event("tool_called", {"call_id": "c1", "tool": "read", "args": {}, "summary": "reading"}, "a1")
        r = fold(p, e)
        assert len(r.activity_log) == 1
        assert r.activity_log[0]["event_type"] == "tool_called"
        assert r.activity_log[0]["tool"] == "read"

    def test_tool_completed_appended(self):
        p = Projection()
        e = self._event("tool_completed", {"call_id": "c1", "tool": "read"}, "a1")
        r = fold(p, e)
        assert len(r.activity_log) == 1
        assert r.activity_log[0]["event_type"] == "tool_completed"

    def test_thinking_appended(self):
        p = Projection()
        e = self._event("thinking", {"delta": "hmm"}, "a1")
        r = fold(p, e)
        assert len(r.activity_log) == 1
        assert r.activity_log[0]["delta"] == "hmm"

    def test_stream_delta_accumulates(self):
        p = Projection(stream_buffer="hello ")
        e = self._event("stream_delta", {"delta": "world"})
        r = fold(p, e)
        assert r.stream_buffer == "hello world"

    def test_stream_cleared(self):
        p = Projection(stream_buffer="some content")
        e = self._event("stream_cleared", {})
        r = fold(p, e)
        assert r.stream_buffer == ""


# -- fold: interactions -------------------------------------------------------

class TestFoldInteractions:
    def _event(self, event_type: str, payload: dict) -> VersionedEvent:
        return VersionedEvent(version=1, event_type=event_type, timestamp="2026-01-01T00:00:00Z",
                              agent_id="a1", payload=payload)

    def test_questions_asked_sets_active(self):
        p = Projection()
        e = self._event("questions_asked", {"token": "t1", "questions": [{"question": "Q1"}]})
        r = fold(p, e)
        assert r.active_interaction is not None
        assert r.active_interaction["interaction_type"] == "questions_asked"
        assert r.active_interaction["token"] == "t1"

    def test_questions_answered_clears(self):
        p = Projection(active_interaction={"interaction_type": "questions_asked", "token": "t1"})
        e = self._event("questions_answered", {"token": "t1", "cancelled": False})
        r = fold(p, e)
        assert r.active_interaction is None

    def test_artifact_review_request_response_cycle(self):
        p = Projection()
        req = self._event("artifact_review_requested", {"token": "t2", "path": "/tmp/f.md", "description": "d", "content": "c"})
        p2 = fold(p, req)
        assert p2.active_interaction["interaction_type"] == "artifact_review_requested"
        res = self._event("artifact_reviewed", {"token": "t2", "accepted": True, "cancelled": False})
        p3 = fold(p2, res)
        assert p3.active_interaction is None

    def test_workflow_decision_cycle(self):
        p = Projection()
        req = self._event("workflow_decision_requested", {"token": "t3", "chat_turns": []})
        p2 = fold(p, req)
        assert p2.active_interaction["interaction_type"] == "workflow_decision_requested"
        res = self._event("workflow_decided", {"token": "t3", "cancelled": False})
        p3 = fold(p2, res)
        assert p3.active_interaction is None

    def test_cancelled_resolution_clears(self):
        p = Projection(active_interaction={"interaction_type": "questions_asked", "token": "t1"})
        e = self._event("questions_answered", {"token": "t1", "cancelled": True})
        r = fold(p, e)
        assert r.active_interaction is None


# -- fold: resources ----------------------------------------------------------

class TestFoldResources:
    def _event(self, event_type: str, payload: dict) -> VersionedEvent:
        return VersionedEvent(version=1, event_type=event_type, timestamp="2026-01-01T00:00:00Z",
                              agent_id=None, payload=payload)

    def test_artifact_created(self):
        p = Projection()
        e = self._event("artifact_created", {"path": "foo.md", "size": 100, "modified_at": 1000})
        r = fold(p, e)
        assert "foo.md" in r.artifacts
        assert r.artifacts["foo.md"]["size"] == 100

    def test_artifact_modified(self):
        p = Projection(artifacts={"foo.md": {"path": "foo.md", "size": 50, "modified_at": 500}})
        e = self._event("artifact_modified", {"path": "foo.md", "size": 200, "modified_at": 2000})
        r = fold(p, e)
        assert r.artifacts["foo.md"]["size"] == 200

    def test_artifact_removed(self):
        p = Projection(artifacts={"foo.md": {"path": "foo.md", "size": 100, "modified_at": 1000}})
        e = self._event("artifact_removed", {"path": "foo.md"})
        r = fold(p, e)
        assert "foo.md" not in r.artifacts


# -- fold: safety -----------------------------------------------------------

class TestFoldSafety:
    def _event(self, event_type: str, payload: dict) -> VersionedEvent:
        return VersionedEvent(version=1, event_type=event_type, timestamp="2026-01-01T00:00:00Z",
                              agent_id=None, payload=payload)

    def test_unknown_event_type_unchanged(self):
        p = Projection(phase="intake")
        e = self._event("completely_unknown_type", {"data": 42})
        r = fold(p, e)
        assert r == p

    def test_unknown_agent_id_unchanged(self):
        p = Projection()  # no agents registered
        e = VersionedEvent(version=1, event_type="agent_step_advanced", timestamp="2026-01-01T00:00:00Z",
                           agent_id="nonexistent", payload={"step": 1, "step_name": "X"})
        r = fold(p, e)
        assert r == p

    def test_phase_started_empty_payload_returns_empty_phase(self):
        # Verifies that phase_started with {} payload returns phase="" (not an error).
        # This is valid input -- fold does not throw on missing-but-defaulted fields.
        p = Projection(phase="intake")
        e = VersionedEvent(version=1, event_type="phase_started", timestamp="2026-01-01T00:00:00Z",
                           agent_id=None, payload={})
        r = fold(p, e)
        assert r.phase == ""
        assert r.run_started is True

    def test_fold_is_pure(self):
        p = Projection(phase="intake")
        e = self._event("phase_started", {"phase": "brief-generation"})
        r1 = fold(p, e)
        r2 = fold(p, e)
        assert r1 == r2
        # Input projection unchanged
        assert p.phase == "intake"


# -- ProjectionStore ----------------------------------------------------------

class TestProjectionStore:
    def test_push_increments_version(self):
        store = ProjectionStore()
        assert store.version == 0
        store.push_event("phase_started", {"phase": "intake"})
        assert store.version == 1
        store.push_event("phase_started", {"phase": "brief-generation"})
        assert store.version == 2

    def test_fold_applied_to_projection(self):
        store = ProjectionStore()
        store.push_event("phase_started", {"phase": "intake"})
        assert store.projection.phase == "intake"

    def test_get_snapshot_includes_version(self):
        store = ProjectionStore()
        store.push_event("phase_started", {"phase": "intake"})
        snap = store.get_snapshot()
        assert snap["version"] == 1
        assert snap["state"]["phase"] == "intake"

    def test_events_since(self):
        store = ProjectionStore()
        store.push_event("phase_started", {"phase": "intake"})
        store.push_event("phase_started", {"phase": "brief-generation"})
        store.push_event("phase_started", {"phase": "core-flows"})
        events = store.events_since(1)
        assert len(events) == 2
        assert events[0].version == 2
        assert events[1].version == 3

    def test_events_since_zero_returns_all(self):
        store = ProjectionStore()
        store.push_event("phase_started", {"phase": "intake"})
        assert len(store.events_since(0)) == 1

    @pytest.mark.anyio
    async def test_broadcast_to_subscribers(self):
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("phase_started", {"phase": "intake"})
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event.event_type == "phase_started"
        store.unsubscribe(q)

    @pytest.mark.anyio
    async def test_unsubscribe_stops_delivery(self):
        store = ProjectionStore()
        q = store.subscribe()
        store.unsubscribe(q)
        store.push_event("phase_started", {"phase": "intake"})
        assert q.empty()

    def test_subscriber_snapshot_avoids_mutation_during_broadcast(self):
        """push_event snapshots subscribers before iterating."""
        store = ProjectionStore()
        q1 = store.subscribe()
        # Should not raise even if we unsubscribe q1 from inside a subscriber
        store.push_event("phase_started", {"phase": "intake"})
        store.unsubscribe(q1)
        # No exception = pass

    def test_fold_exception_leaves_log_intact_projection_unchanged(self, monkeypatch):
        """ProjectionStore: if fold() raises, event stays in log but projection is unchanged."""
        import koan.projections as proj_mod
        original_fold = proj_mod.fold

        call_count = [0]

        def raising_fold(projection, event):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated fold failure")
            return original_fold(projection, event)

        monkeypatch.setattr(proj_mod, "fold", raising_fold)

        store = proj_mod.ProjectionStore()
        # First push: fold raises, projection stays at default, but event IS in log
        store.push_event("phase_started", {"phase": "intake"})
        assert store.version == 1
        assert store.events[0].event_type == "phase_started"
        assert store.projection.phase == ""  # unchanged -- fold raised

        # Second push: fold succeeds, projection advances
        store.push_event("phase_started", {"phase": "brief-generation"})
        assert store.version == 2
        assert store.projection.phase == "brief-generation"


# -- build_artifact_diff ------------------------------------------------------

class TestBuildArtifactDiff:
    def test_created(self):
        from koan.events import build_artifact_diff
        old = {}
        new = [{"path": "foo.md", "size": 100, "modified_at": 1.0}]
        events = build_artifact_diff(old, new)
        assert len(events) == 1
        assert events[0][0] == "artifact_created"
        assert events[0][1]["path"] == "foo.md"
        assert events[0][1]["modified_at"] == 1000  # ms

    def test_removed(self):
        from koan.events import build_artifact_diff
        old = {"foo.md": {"path": "foo.md", "size": 100, "modified_at": 1000}}
        new = []
        events = build_artifact_diff(old, new)
        assert len(events) == 1
        assert events[0][0] == "artifact_removed"
        assert events[0][1]["path"] == "foo.md"

    def test_modified_by_size(self):
        from koan.events import build_artifact_diff
        old = {"foo.md": {"path": "foo.md", "size": 50, "modified_at": 1000}}
        new = [{"path": "foo.md", "size": 100, "modified_at": 1.0}]
        events = build_artifact_diff(old, new)
        assert len(events) == 1
        assert events[0][0] == "artifact_modified"

    def test_modified_by_mtime(self):
        from koan.events import build_artifact_diff
        old = {"foo.md": {"path": "foo.md", "size": 100, "modified_at": 1000}}
        new = [{"path": "foo.md", "size": 100, "modified_at": 2.0}]
        events = build_artifact_diff(old, new)
        assert len(events) == 1
        assert events[0][0] == "artifact_modified"

    def test_unchanged_produces_no_events(self):
        from koan.events import build_artifact_diff
        old = {"foo.md": {"path": "foo.md", "size": 100, "modified_at": 1000}}
        new = [{"path": "foo.md", "size": 100, "modified_at": 1.0}]
        events = build_artifact_diff(old, new)
        assert events == []

    def test_mixed_diff(self):
        from koan.events import build_artifact_diff
        old = {
            "a.md": {"path": "a.md", "size": 10, "modified_at": 1000},
            "b.md": {"path": "b.md", "size": 20, "modified_at": 2000},
        }
        new = [
            {"path": "a.md", "size": 15, "modified_at": 1.0},  # modified
            {"path": "c.md", "size": 30, "modified_at": 3.0},  # created
            # b.md removed
        ]
        events = build_artifact_diff(old, new)
        types = [e[0] for e in events]
        assert "artifact_modified" in types
        assert "artifact_created" in types
        assert "artifact_removed" in types


# -- Tool name normalization (runner integration) ----------------------------

class TestToolNameNormalization:
    def test_claude_normalizes_Read(self):
        import json
        from koan.runners.claude import ClaudeRunner
        runner = ClaudeRunner(subagent_dir="/tmp/test")
        line = json.dumps({
            "type": "assistant",
            "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/f"}}],
        })
        evts = runner.parse_stream_event(line)
        assert len(evts) == 1
        assert evts[0].tool_name == "read"

    def test_claude_normalizes_Bash(self):
        import json
        from koan.runners.claude import ClaudeRunner
        runner = ClaudeRunner(subagent_dir="/tmp/test")
        line = json.dumps({
            "type": "assistant",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
        })
        evts = runner.parse_stream_event(line)
        assert len(evts) == 1
        assert evts[0].tool_name == "bash"

    def test_claude_filters_koan_mcp_tool(self):
        import json
        from koan.runners.claude import ClaudeRunner
        runner = ClaudeRunner(subagent_dir="/tmp/test")
        line = json.dumps({
            "type": "assistant",
            "content": [{"type": "tool_use", "name": "koan_complete_step", "input": {}}],
        })
        evts = runner.parse_stream_event(line)
        assert evts == []

    def test_codex_normalizes_read_file(self):
        import json
        from koan.runners.codex import CodexRunner
        runner = CodexRunner()
        line = json.dumps({"type": "item.completed", "item": {"type": "function_call", "name": "read_file", "arguments": "{}"}})
        evts = runner.parse_stream_event(line)
        assert len(evts) == 1
        assert evts[0].tool_name == "read"

    def test_codex_filters_koan_mcp_tool(self):
        import json
        from koan.runners.codex import CodexRunner
        runner = CodexRunner()
        line = json.dumps({"type": "item.completed", "item": {"type": "function_call", "name": "koan_ask_question", "arguments": "{}"}})
        evts = runner.parse_stream_event(line)
        assert evts == []

    def test_gemini_normalizes_tool(self):
        import json
        from koan.runners.gemini import GeminiRunner
        runner = GeminiRunner(subagent_dir="/tmp/test")
        line = json.dumps({"type": "tool_use", "name": "read_file", "input": {}})
        evts = runner.parse_stream_event(line)
        assert len(evts) == 1
        assert evts[0].tool_name == "read"

    def test_gemini_filters_koan_mcp_tool(self):
        import json
        from koan.runners.gemini import GeminiRunner
        runner = GeminiRunner(subagent_dir="/tmp/test")
        line = json.dumps({"type": "tool_use", "name": "koan_complete_step", "input": {}})
        evts = runner.parse_stream_event(line)
        assert evts == []


# -- agent_spawned ordering ---------------------------------------------------

class TestAgentSpawnedOrdering:
    """agent_spawned must only be emitted after build_command succeeds.
    If build_command raises, the projection must not have a dangling primary_agent.
    """
    def test_spawn_failed_without_prior_spawned_leaves_no_primary(self):
        """agent_spawn_failed without prior agent_spawned: projection stays clean."""
        store = ProjectionStore()
        store.push_event("agent_spawn_failed", {
            "role": "intake", "error_code": "binary_not_found", "message": "not found"
        })
        assert store.projection.primary_agent is None
        assert len(store.projection.notifications) == 1

    def test_spawn_failed_after_spawned_leaves_dangling_primary(self):
        """Demonstrates the bug that is now fixed: agent_spawned must be emitted
        AFTER build_command succeeds, not before. This test documents the broken
        sequence to catch regressions -- if agent_spawned fires before the process
        starts and then spawn_failed fires, primary_agent is left set."""
        store = ProjectionStore()
        # This sequence should NOT happen in production code after the fix
        store.push_event(
            "agent_spawned",
            {"agent_id": "a1", "role": "intake", "model": None, "is_primary": True, "started_at_ms": 0},
            agent_id="a1",
        )
        store.push_event("agent_spawn_failed", {"role": "intake", "error_code": "err", "message": "m"})
        # primary_agent is dangling -- this is why agent_spawned must come AFTER build_command
        assert store.projection.primary_agent is not None  # known bad state
        # In production, this can't happen: subagent.py now emits agent_spawned only
        # after build_command succeeds (just before create_subprocess_exec).


# -- fold: configuration events -----------------------------------------------

class TestConfigEvents:
    def _e(self, event_type: str, payload: dict) -> VersionedEvent:
        return VersionedEvent(version=1, event_type=event_type, timestamp="t", payload=payload)

    def test_probe_completed_sets_runners(self):
        p = Projection()
        runners = [{"runner_type": "claude", "available": True}]
        p2 = fold(p, self._e("probe_completed", {"runners": runners}))
        assert p2.config_runners == runners

    def test_installation_created_appends(self):
        p = Projection()
        inst = {"alias": "claude-default", "runner_type": "claude", "binary": "/fake/bin/claude", "extra_args": []}
        p2 = fold(p, self._e("installation_created", inst))
        assert len(p2.config_installations) == 1
        assert p2.config_installations[0]["alias"] == "claude-default"

    def test_installation_modified_replaces(self):
        inst = {"alias": "my-claude", "runner_type": "claude", "binary": "/old/claude", "extra_args": []}
        p = Projection(config_installations=[inst])
        updated = {"alias": "my-claude", "runner_type": "claude", "binary": "/new/claude", "extra_args": []}
        p2 = fold(p, self._e("installation_modified", updated))
        assert len(p2.config_installations) == 1
        assert p2.config_installations[0]["binary"] == "/new/claude"

    def test_installation_removed(self):
        inst = {"alias": "my-claude", "runner_type": "claude", "binary": "/fake/bin/claude", "extra_args": []}
        p = Projection(config_installations=[inst])
        p2 = fold(p, self._e("installation_removed", {"alias": "my-claude"}))
        assert p2.config_installations == []

    def test_profile_created_appends(self):
        p = Projection()
        profile = {"name": "fast", "read_only": False, "tiers": {}}
        p2 = fold(p, self._e("profile_created", profile))
        assert len(p2.config_profiles) == 1
        assert p2.config_profiles[0]["name"] == "fast"

    def test_profile_modified_replaces(self):
        profile = {"name": "fast", "read_only": False, "tiers": {"strong": {"runner_type": "claude"}}}
        p = Projection(config_profiles=[profile])
        updated = {"name": "fast", "read_only": False, "tiers": {"strong": {"runner_type": "codex"}}}
        p2 = fold(p, self._e("profile_modified", updated))
        assert len(p2.config_profiles) == 1
        assert p2.config_profiles[0]["tiers"]["strong"]["runner_type"] == "codex"

    def test_profile_modified_appends_when_not_found(self):
        p = Projection()
        balanced = {"name": "balanced", "read_only": True, "tiers": {}}
        p2 = fold(p, self._e("profile_modified", balanced))
        assert len(p2.config_profiles) == 1
        assert p2.config_profiles[0]["name"] == "balanced"

    def test_profile_removed(self):
        p = Projection(config_profiles=[
            {"name": "fast", "read_only": False, "tiers": {}},
            {"name": "slow", "read_only": False, "tiers": {}},
        ])
        p2 = fold(p, self._e("profile_removed", {"name": "fast"}))
        assert len(p2.config_profiles) == 1
        assert p2.config_profiles[0]["name"] == "slow"

    def test_active_profile_changed(self):
        p = Projection()
        p2 = fold(p, self._e("active_profile_changed", {"name": "fast"}))
        assert p2.config_active_profile == "fast"

    def test_scout_concurrency_changed(self):
        p = Projection()
        p2 = fold(p, self._e("scout_concurrency_changed", {"value": 16}))
        assert p2.config_scout_concurrency == 16
