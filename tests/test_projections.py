# Tests for koan.projections (ProjectionStore, fold) and koan.events (build_artifact_diff).
# New architecture: server-authoritative JSON Patch. fold() is the only business logic.
# Projection has 3 top-level fields: settings, run, notifications.

from __future__ import annotations

import asyncio

import pytest

from koan.projections import (
    Agent,
    ArtifactInfo,
    BaseToolEntry,
    Conversation,
    ConversationFocus,
    Projection,
    ProjectionStore,
    QuestionFocus,
    Run,
    RunConfig,
    Settings,
    StepEntry,
    TextEntry,
    ThinkingEntry,
    ToolAggregateEntry,
    ToolBashEntry,
    ToolEditEntry,
    ToolFailedEntry,
    ToolGenericEntry,
    ToolGlobEntry,
    ToolGrepEntry,
    ToolKoanEntry,
    ToolReadEntry,
    ToolWebFetchEntry,
    ToolWebSearchEntry,
    ToolWriteEntry,
    VersionedEvent,
    WorkflowInfo,
    fold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(
    event_type: str,
    payload: dict,
    agent_id: str | None = None,
    version: int = 1,
) -> VersionedEvent:
    return VersionedEvent(
        version=version,
        event_type=event_type,
        timestamp="2026-01-01T00:00:00Z",
        agent_id=agent_id,
        payload=payload,
    )


def _proj_with_run(active_preset: str = "$last") -> Projection:
    """Return a Projection with an active run (post run_started).

    M5: 'profile' renamed to 'active_preset' in run_started payload.
    """
    p = Projection()
    return fold(p, _e("run_started", {
        "active_preset": active_preset,
        "scout_concurrency": 8,
    }))


def _proj_with_primary(agent_id: str = "a1", role: str = "intake") -> Projection:
    """Return a Projection with an active run and a running primary agent."""
    p = _proj_with_run()
    p = fold(p, _e("agent_spawned", {
        "agent_id": agent_id,
        "role": role,
        "label": "",
        "model": "opus",
        "is_primary": True,
        "started_at_ms": 1000,
    }, agent_id=agent_id))
    return p


# ---------------------------------------------------------------------------
# fold: run lifecycle
# ---------------------------------------------------------------------------

class TestFoldRunLifecycle:

    def test_run_started_creates_run(self):
        p = Projection()
        assert p.run is None
        r = fold(p, _e("run_started", {"active_preset": "my-preset", "scout_concurrency": 8}))
        assert r.run is not None
        assert r.run.config.active_preset == "my-preset"
        assert r.run.config.scout_concurrency == 8

    def test_run_started_resets_run_on_new_start(self):
        """A second run_started replaces the run entirely."""
        p = _proj_with_run("$last")
        # Simulate a new run
        r = fold(p, _e("run_started", {"active_preset": "custom-preset", "scout_concurrency": 4}))
        assert r.run is not None
        assert r.run.config.active_preset == "custom-preset"
        assert r.run.agents == {}

    def test_phase_started_sets_phase(self):
        p = _proj_with_run()
        r = fold(p, _e("phase_started", {"phase": "intake"}))
        assert r.run.phase == "intake"

    def test_phase_started_without_run_is_noop(self):
        p = Projection()
        r = fold(p, _e("phase_started", {"phase": "intake"}))
        assert r.run is None

    def test_workflow_completed_sets_completion(self):
        p = _proj_with_run()
        r = fold(p, _e("workflow_completed", {"success": True, "summary": "done"}))
        assert r.run.completion is not None
        assert r.run.completion.success is True
        assert r.run.completion.summary == "done"

    def test_workflow_completed_without_run_is_noop(self):
        p = Projection()
        r = fold(p, _e("workflow_completed", {"success": True}))
        assert r.run is None

    def test_workflow_selected_sets_workflow(self):
        p = _proj_with_run()
        r = fold(p, _e("workflow_selected", {"workflow": "plan"}))
        assert r.run.workflow == "plan"

    def test_workflow_selected_does_not_set_available_workflows(self):
        """After workflow_selected, Run no longer carries an available_workflows attribute -- the workflows registry now lives at Settings.workflows."""
        p = _proj_with_run()
        r = fold(p, _e("workflow_selected", {"workflow": "plan"}))
        assert not hasattr(r.run, "available_workflows")

    def test_workflow_selected_without_run_is_noop(self):
        p = Projection()
        r = fold(p, _e("workflow_selected", {"workflow": "plan"}))
        assert r.run is None

    def test_run_cleared_resets_run_to_none(self):
        p = _proj_with_run()
        r = fold(p, _e("workflow_completed", {"success": True, "summary": "done"}))
        assert r.run is not None
        r2 = fold(r, _e("run_cleared", {}))
        assert r2.run is None

    def test_run_cleared_without_run_is_noop(self):
        p = Projection()
        r = fold(p, _e("run_cleared", {}))
        assert r.run is None


# ---------------------------------------------------------------------------
# fold: settings_listed (Settings full snapshot, M2) -- tests at end of file.
# M2: the 13 individual settings fold cases are consolidated into one
# settings_listed full-snapshot case. Tests for the deleted cases are removed.


# ---------------------------------------------------------------------------
# fold: agent lifecycle
# ---------------------------------------------------------------------------

class TestFoldAgentLifecycle:

    def test_agent_spawned_primary_creates_agent(self):
        p = _proj_with_run()
        r = fold(p, _e("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True,
            "model": "opus", "started_at_ms": 1000,
        }, agent_id="a1"))
        assert "a1" in r.run.agents
        agent = r.run.agents["a1"]
        assert agent.is_primary is True
        assert agent.status == "running"
        assert agent.role == "intake"

    def test_agent_spawned_sets_conversation_focus(self):
        p = _proj_with_run()
        r = fold(p, _e("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True, "started_at_ms": 0,
        }, agent_id="a1"))
        assert r.run.focus is not None
        assert isinstance(r.run.focus, ConversationFocus)
        assert r.run.focus.agent_id == "a1"

    def test_agent_spawned_scout_transitions_from_queued_same_id(self):
        p = _proj_with_run()
        # Queue the scout first
        p = fold(p, _e("scout_queued", {"scout_id": "s1", "label": "eng", "model": "haiku"}))
        assert p.run.agents["s1"].status == "queued"
        # Spawn with the same id
        r = fold(p, _e("agent_spawned", {
            "agent_id": "s1", "role": "scout", "is_primary": False, "started_at_ms": 2000,
        }, agent_id="s1"))
        assert r.run.agents["s1"].status == "running"
        assert r.run.agents["s1"].started_at_ms == 2000

    def test_agent_spawned_scout_transitions_by_label_when_id_differs(self):
        """scout_queued keys by label, agent_spawned keys by UUID.
        The fold must match by label and re-key under the UUID."""
        p = _proj_with_run()
        # Queue keyed by label
        p = fold(p, _e("scout_queued", {"scout_id": "eng", "label": "eng", "model": "haiku"}))
        assert "eng" in p.run.agents
        assert p.run.agents["eng"].status == "queued"
        # Spawn with a UUID — different key
        uuid_id = "aaaa-bbbb-cccc"
        r = fold(p, _e("agent_spawned", {
            "agent_id": uuid_id, "role": "scout", "label": "eng",
            "is_primary": False, "started_at_ms": 3000, "model": "haiku",
        }, agent_id=uuid_id))
        # Old label key should be gone, new UUID key should exist
        assert "eng" not in r.run.agents
        assert uuid_id in r.run.agents
        assert r.run.agents[uuid_id].status == "running"
        assert r.run.agents[uuid_id].agent_id == uuid_id
        assert r.run.agents[uuid_id].label == "eng"
        # Only one agent entry, not two
        assert len(r.run.agents) == 1

    def test_scout_queued_adds_agent_with_queued_status(self):
        p = _proj_with_run()
        r = fold(p, _e("scout_queued", {"scout_id": "s1", "label": "eng", "model": "haiku"}))
        assert "s1" in r.run.agents
        assert r.run.agents["s1"].status == "queued"
        assert r.run.agents["s1"].label == "eng"

    def test_agents_cleared_removes_non_primary(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("scout_queued", {"scout_id": "s1", "label": "eng", "model": "haiku"}))
        p = fold(p, _e("agent_spawned", {
            "agent_id": "s1", "role": "scout", "label": "eng",
            "model": "haiku", "is_primary": False, "started_at_ms": 2000,
        }, agent_id="s1"))
        assert len(p.run.agents) == 2
        r = fold(p, _e("agents_cleared", {}))
        assert "a1" in r.run.agents
        assert "s1" not in r.run.agents
        assert len(r.run.agents) == 1

    def test_agents_cleared_on_empty_run(self):
        p = _proj_with_run()
        r = fold(p, _e("agents_cleared", {}))
        assert r.run.agents == {}

    def test_agent_exited_sets_done_status(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("agent_exited", {"exit_code": 0}, agent_id="a1"))
        assert r.run.agents["a1"].status == "done"
        assert r.run.agents["a1"].error is None

    def test_agent_exited_with_error_sets_failed(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("agent_exited", {"exit_code": 1, "error": "boom"}, agent_id="a1"))
        assert r.run.agents["a1"].status == "failed"
        assert r.run.agents["a1"].error == "boom"
        # Tracked-agent error surfaces inline (executor: koan_request_executor
        # tool result; orchestrator: agent.error). No notification toast.
        assert r.notifications == []

    def test_agent_exited_accumulates_usage_into_conversation(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("agent_exited", {
            "exit_code": 0,
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }, agent_id="a1"))
        assert r.run.agents["a1"].conversation.input_tokens == 10
        assert r.run.agents["a1"].conversation.output_tokens == 20

    def test_agent_exited_unknown_agent_noop(self):
        p = _proj_with_run()
        r = fold(p, _e("agent_exited", {"exit_code": 0}, agent_id="ghost"))
        # No change to agents
        assert r.run.agents == p.run.agents

    def test_agent_spawn_failed_appends_notification(self):
        p = Projection()
        r = fold(p, _e("agent_spawn_failed", {
            "role": "intake", "error_code": "binary_not_found", "message": "not found",
        }))
        assert len(r.notifications) == 1
        assert "not found" in r.notifications[0].message
        assert r.notifications[0].level == "error"


# ---------------------------------------------------------------------------
# fold: conversation — pending fields and flush semantics
# ---------------------------------------------------------------------------

class TestFoldConversation:

    def test_thinking_flushes_pending_text_first(self):
        p = _proj_with_primary("a1")
        # Accumulate some text
        p = fold(p, _e("stream_delta", {"delta": "hello"}, agent_id="a1"))
        # Now thinking arrives — text should flush to TextEntry
        r = fold(p, _e("thinking", {"delta": "hmm"}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert len(conv.entries) == 1
        assert isinstance(conv.entries[0], TextEntry)
        assert conv.entries[0].text == "hello"
        assert conv.pending_text == ""
        assert conv.pending_thinking == "hmm"
        assert conv.is_thinking is True

    def test_thinking_accumulates(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("thinking", {"delta": "The "}, agent_id="a1"))
        r = fold(p, _e("thinking", {"delta": "answer"}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.pending_thinking == "The answer"

    def test_stream_delta_flushes_pending_thinking_first(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("thinking", {"delta": "consider"}, agent_id="a1"))
        r = fold(p, _e("stream_delta", {"delta": "result"}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert len(conv.entries) == 1
        assert isinstance(conv.entries[0], ThinkingEntry)
        assert conv.entries[0].content == "consider"
        assert conv.pending_thinking == ""
        assert conv.pending_text == "result"
        assert conv.is_thinking is False

    def test_stream_delta_accumulates(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("stream_delta", {"delta": "hello "}, agent_id="a1"))
        r = fold(p, _e("stream_delta", {"delta": "world"}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.pending_text == "hello world"

    def test_stream_cleared_flushes_both(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("thinking", {"delta": "thoughts"}, agent_id="a1"))
        p = fold(p, _e("stream_delta", {"delta": "text"}, agent_id="a1"))
        # At this point pending_thinking got flushed when stream_delta arrived
        # so pending_thinking = "", pending_text = "text"
        r = fold(p, _e("stream_cleared", {}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        # Both pending fields empty
        assert conv.pending_thinking == ""
        assert conv.pending_text == ""
        assert conv.is_thinking is False

    def test_agent_step_advanced_flushes_both_and_appends_step(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("thinking", {"delta": "thinking..."}, agent_id="a1"))
        # The stream_delta flush makes pending_thinking go to entry
        # Let's test from a state with just pending_text
        p2 = _proj_with_primary("a1")
        p2 = fold(p2, _e("stream_delta", {"delta": "output"}, agent_id="a1"))
        r = fold(p2, _e("agent_step_advanced", {"step": 1, "step_name": "Scout"}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        # pending_text flushed to TextEntry, then StepEntry appended
        assert len(conv.entries) == 2
        assert isinstance(conv.entries[0], TextEntry)
        assert isinstance(conv.entries[1], StepEntry)
        assert conv.entries[1].step == 1
        assert conv.entries[1].step_name == "Scout"
        assert conv.pending_text == ""
        assert conv.is_thinking is False

    def test_agent_step_advanced_step_0_no_entry(self):
        """step=0 is bootstrap — no StepEntry appended."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("agent_step_advanced", {"step": 0, "step_name": ""}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_agent_step_advanced_updates_step_and_step_name(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("agent_step_advanced", {"step": 2, "step_name": "Generate"}, agent_id="a1"))
        assert r.run.agents["a1"].step == 2
        assert r.run.agents["a1"].step_name == "Generate"

    def test_agent_step_advanced_accumulates_tokens(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("agent_step_advanced", {
            "step": 1, "step_name": "",
            "usage": {"input_tokens": 100, "output_tokens": 200},
        }, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert conv.input_tokens == 100
        assert conv.output_tokens == 200

    def test_agent_step_advanced_unknown_agent_noop(self):
        p = _proj_with_run()
        r = fold(p, _e("agent_step_advanced", {"step": 1, "step_name": "X"}, agent_id="ghost"))
        assert r.run.agents == {}


# ---------------------------------------------------------------------------
# fold: conversation — tool entries
# ---------------------------------------------------------------------------

class TestFoldTools:

    def test_tool_request_read_creates_top_level_entry(self):
        """Single read via tool_request creates a ToolReadEntry directly."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1000}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert len(conv.entries) == 1
        entry = conv.entries[0]
        assert isinstance(entry, ToolReadEntry)
        assert entry.call_id == "c1"
        assert entry.in_flight is True
        assert entry.started_at_ms == 1000
        # No aggregate for a single exploration tool
        assert not isinstance(entry, ToolAggregateEntry)

    def test_two_consecutive_reads_form_one_aggregate(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        assert isinstance(entries[0], ToolAggregateEntry)
        assert entries[0].started_at_ms == 1  # aggregate's started_at_ms is the first child's
        assert [c.call_id for c in entries[0].children] == ["c1", "c2"]

    def test_read_grep_ls_form_one_aggregate_three_children(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "grep", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c3", "tool": "glob", "ts_ms": 3}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        agg = entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert isinstance(agg.children[0], ToolReadEntry)
        assert isinstance(agg.children[1], ToolGrepEntry)
        assert isinstance(agg.children[2], ToolGlobEntry)

    def test_tool_request_bash_in_aggregate(self):
        """bash inside a run of exploration tools becomes an aggregate child."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c2", "tool": "bash", "ts_ms": 2}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        agg = entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert len(agg.children) == 2
        assert isinstance(agg.children[0], ToolReadEntry)
        assert isinstance(agg.children[1], ToolBashEntry)

    def test_tool_result_captured_bash_metrics(self):
        """bash metrics (exit_code, output_lines) applied to aggregate child."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "bash", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c2", "tool": "bash",
            "metrics": {"exit_code": 0, "output_lines": 5},
        }, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[1]
        assert isinstance(child, ToolBashEntry)
        assert child.exit_code == 0
        assert child.output_lines == 5

    def test_tool_result_captured_web_metrics(self):
        """web_search and web_fetch metrics applied to aggregate children."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "web_search", "ts_ms": 2}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c3", "tool": "web_fetch", "ts_ms": 3}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c2", "tool": "web_search",
            "metrics": {"result_count": 5},
        }, agent_id="a1"))
        r = fold(r, _e("tool_result_captured", {
            "call_id": "c3", "tool": "web_fetch",
            "metrics": {"content_size_bytes": 2048},
        }, agent_id="a1"))
        agg = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(agg.children[1], ToolWebSearchEntry)
        assert agg.children[1].result_count == 5
        assert isinstance(agg.children[2], ToolWebFetchEntry)
        assert agg.children[2].content_size_bytes == 2048

    def test_read_range_derivation(self):
        """offset/limit from tool_input_delta produce correct range."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2}, agent_id="a1"))
        # tool_input_delta with offset/limit
        r = fold(p, _e("tool_input_delta", {
            "call_id": "c1", "tool": "read",
            "tool_input": {"file_path": "/foo.py", "offset": 10, "limit": 80},
        }, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[0]
        assert isinstance(child, ToolReadEntry)
        assert child.offset == 10
        assert child.limit == 80
        assert child.range == "11–90"  # offset+1 to offset+limit
        # Whole-file read: limit is None
        r2 = fold(r, _e("tool_input_delta", {
            "call_id": "c2", "tool": "read",
            "tool_input": {"file_path": "/bar.py"},
        }, agent_id="a1"))
        child2 = r2.run.agents["a1"].conversation.entries[0].children[1]
        assert child2.limit is None
        assert child2.range is None

    def test_ts_ms_on_tool_request(self):
        """tool_request carries real timestamps on aggregate entries."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1000}, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2000}, agent_id="a1"))
        agg = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert agg.started_at_ms == 1000  # first child's started_at_ms
        assert agg.children[0].started_at_ms == 1000
        assert agg.children[1].started_at_ms == 2000

    def test_read_bash_read_produces_single_aggregate_three_children(self):
        """read -> bash -> read: bash is in the exploration set, so all three
        form a single ToolAggregateEntry with 3 children."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "bash", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c3", "tool": "read", "ts_ms": 3}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        agg = entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert len(agg.children) == 3
        assert isinstance(agg.children[0], ToolReadEntry)
        assert isinstance(agg.children[1], ToolBashEntry)
        assert isinstance(agg.children[2], ToolReadEntry)

    def test_tool_write_appends_entry(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_write", {"call_id": "c1", "file": "/out.py"}, agent_id="a1"))
        assert isinstance(r.run.agents["a1"].conversation.entries[0], ToolWriteEntry)
        assert r.run.agents["a1"].last_tool == "write /out.py"

    def test_tool_edit_appends_entry(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_edit", {"call_id": "c1", "file": "/edit.py"}, agent_id="a1"))
        assert isinstance(r.run.agents["a1"].conversation.entries[0], ToolEditEntry)

    def test_tool_request_bash_creates_top_level_entry(self):
        """Single bash via tool_request creates a ToolBashEntry."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "bash", "ts_ms": 5}, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolBashEntry)
        assert entry.call_id == "c1"
        assert entry.in_flight is True
        assert entry.started_at_ms == 5
        assert entry.command == ""  # filled by tool_input_delta

    def test_tool_request_grep_creates_top_level_entry(self):
        """Single grep via tool_request creates a ToolGrepEntry."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "grep", "ts_ms": 5}, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolGrepEntry)
        assert entry.call_id == "c1"
        assert entry.in_flight is True

    def test_tool_request_glob_creates_top_level_entry(self):
        """Single glob via tool_request creates a ToolGlobEntry."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "glob", "ts_ms": 9}, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolGlobEntry)
        assert entry.call_id == "c1"
        assert entry.in_flight is True

    def test_tool_request_web_search_creates_top_level_entry(self):
        """Single web_search via tool_request creates a ToolWebSearchEntry."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "web_search", "ts_ms": 7}, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolWebSearchEntry)
        assert entry.call_id == "c1"

    def test_tool_request_web_fetch_creates_top_level_entry(self):
        """Single web_fetch via tool_request creates a ToolWebFetchEntry."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "web_fetch", "ts_ms": 8}, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolWebFetchEntry)
        assert entry.call_id == "c1"

    def test_tool_aggregate_invariant_single_tool_is_not_aggregate(self):
        """A single exploration tool is a top-level entry, never a single-child aggregate."""
        for tool in ("read", "grep", "glob", "bash", "web_search", "web_fetch"):
            p = _proj_with_primary("a1")
            r = fold(p, _e("tool_request", {"call_id": "c1", "tool": tool, "ts_ms": 1}, agent_id="a1"))
            entries = r.run.agents["a1"].conversation.entries
            assert len(entries) == 1
            assert not isinstance(entries[0], ToolAggregateEntry), f"{tool} should not create aggregate"

    def test_tool_called_appends_generic_entry(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_called", {
            "call_id": "c1", "tool": "fetch", "args": {}, "summary": "http://example.com"
        }, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolGenericEntry)
        assert entry.tool_name == "fetch"
        assert entry.in_flight is True

    def test_tool_called_koan_prefix_skipped(self):
        """koan_ prefixed tools (except koan_reflect) are skipped in the tool_called fold path.

        Using koan_suggest_next as the representative koan tool here;
        koan_complete_step was removed in M6.
        """
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_called", {"call_id": "c1", "tool": "koan_suggest_next", "args": {}}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_tool_called_mcp_koan_prefix_skipped(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_called", {"call_id": "c1", "tool": "mcp__koan__step", "args": {}}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_tool_called_renderable_koan_creates_koan_entry(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_called", {
            "call_id": "c1", "tool": "koan_reflect",
            "args": {"question": "How does X work?", "context": "subsystem Y"},
            "summary": "question='How does X work?'",
        }, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolKoanEntry)
        assert entry.tool_name == "koan_reflect"
        assert entry.args == {"question": "How does X work?", "context": "subsystem Y"}
        assert entry.in_flight is True
        assert entry.result is None

    def test_tool_completed_koan_entry_parses_result(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_called", {
            "call_id": "c1", "tool": "koan_reflect",
            "args": {"question": "Q"},
        }, agent_id="a1"))
        result_json = '{"answer": "A", "citations": [{"id": "1", "title": "T"}], "iterations": 3}'
        r = fold(p, _e("tool_completed", {
            "call_id": "c1", "tool": "koan_reflect", "result": result_json,
        }, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolKoanEntry)
        assert entry.in_flight is False
        assert entry.result == {"answer": "A", "citations": [{"id": "1", "title": "T"}], "iterations": 3}

    def test_tool_completed_sets_attachments(self):
        """Attachment manifest from tool_completed event attaches to the entry."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_called", {
            "call_id": "c1", "tool": "koan_reflect",
            "args": {"question": "Q"},
        }, agent_id="a1"))
        manifest = [
            {"upload_id": "u1", "filename": "spec.pdf", "size": 1024,
             "content_type": "application/pdf", "path": "/run/uploads/u1/spec.pdf"},
        ]
        result_json = '{"answer": "A"}'
        r = fold(p, _e("tool_completed", {
            "call_id": "c1", "tool": "koan_reflect", "result": result_json,
            "attachments": manifest,
        }, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolKoanEntry)
        assert entry.in_flight is False
        assert entry.attachments is not None
        assert len(entry.attachments) == 1
        a = entry.attachments[0]
        assert a.upload_id == "u1"
        assert a.filename == "spec.pdf"
        assert a.size == 1024
        assert a.content_type == "application/pdf"

    def test_tool_completed_no_attachments_leaves_field_none(self):
        """When tool_completed has no attachments, entry.attachments stays None."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "bash"}, agent_id="a1"))
        r = fold(p, _e("tool_completed", {"call_id": "c1", "tool": "bash"}, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert entry.in_flight is False
        assert entry.attachments is None

    def test_tool_called_non_renderable_koan_still_skipped(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_called", {
            "call_id": "c1", "tool": "koan_memorize", "args": {},
        }, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_tool_completed_marks_aggregate_child_done(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_completed", {"call_id": "c1", "tool": "read", "ts_ms": 5}, agent_id="a1"))
        agg = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        # c1 completed, c2 still in-flight — sibling untouched
        by_id = {c.call_id: c for c in agg.children}
        assert by_id["c1"].in_flight is False
        assert by_id["c1"].completed_at_ms == 5
        assert by_id["c2"].in_flight is True
        assert by_id["c2"].completed_at_ms is None

    def test_tool_completed_for_top_level_tool_still_works(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "bash"}, agent_id="a1"))
        assert p.run.agents["a1"].conversation.entries[0].in_flight is True
        r = fold(p, _e("tool_completed", {"call_id": "c1", "tool": "bash"}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries[0].in_flight is False

    def test_tool_completed_unknown_call_id_is_noop(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        r = fold(p, _e("tool_completed", {"call_id": "missing", "tool": "read"}, agent_id="a1"))
        # Projection shape unchanged; c1 still in-flight (top-level entry).
        entry = r.run.agents["a1"].conversation.entries[0]
        assert entry.in_flight is True

    def test_tool_flushes_pending_fields(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("stream_delta", {"delta": "output"}, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert len(conv.entries) == 2
        assert isinstance(conv.entries[0], TextEntry)   # flushed
        assert isinstance(conv.entries[1], ToolReadEntry)  # top-level entry
        assert conv.pending_text == ""

    def test_tool_events_per_agent_not_primary_only(self):
        """Every agent gets its own conversation; scout tool events go to scout."""
        p = _proj_with_run()
        p = fold(p, _e("scout_queued", {"scout_id": "s1", "label": "eng", "model": None}))
        p = fold(p, _e("agent_spawned", {"agent_id": "s1", "role": "scout", "is_primary": False, "started_at_ms": 0}, agent_id="s1"))
        r = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="s1"))
        assert len(r.run.agents["s1"].conversation.entries) == 1
        assert isinstance(r.run.agents["s1"].conversation.entries[0], ToolReadEntry)

    # --- tool_result_captured -----------------------------------------------

    def test_tool_result_captured_attaches_read_metrics(self):
        p = _proj_with_primary("a1")
        # Two reads form an aggregate so tool_result_captured targets a child.
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c1", "tool": "read",
            "metrics": {"lines_read": 42, "bytes_read": 1024},
        }, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[0]
        assert isinstance(child, ToolReadEntry)
        assert child.lines_read == 42
        assert child.bytes_read == 1024

    def test_tool_result_captured_grep_leaves_read_siblings_alone(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "grep", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c2", "tool": "grep",
            "metrics": {"matches": 7, "files_matched": 3},
        }, agent_id="a1"))
        agg = r.run.agents["a1"].conversation.entries[0]
        read_child = agg.children[0]
        grep_child = agg.children[1]
        assert isinstance(read_child, ToolReadEntry)
        assert read_child.lines_read is None  # untouched
        assert isinstance(grep_child, ToolGrepEntry)
        assert grep_child.matches == 7
        assert grep_child.files_matched == 3

    def test_tool_result_captured_unknown_call_id_is_noop(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        before = p.run.agents["a1"].conversation.entries[0]
        r = fold(p, _e("tool_result_captured", {
            "call_id": "missing", "tool": "read",
            "metrics": {"lines_read": 1},
        }, agent_id="a1"))
        # Projection shape unchanged — returns same projection reference semantics
        assert r.run.agents["a1"].conversation.entries[0] == before

    def test_tool_result_captured_no_metrics_is_noop(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {"call_id": "c1", "tool": "read"}, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[0]
        assert child.lines_read is None
        assert child.bytes_read is None

    def test_tool_result_captured_glob_metrics(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "glob", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "glob", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c1", "tool": "glob",
            "metrics": {"matches": 12, "files_matched": 12},
        }, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[0]
        assert isinstance(child, ToolGlobEntry)
        assert child.matches == 12
        assert child.files_matched == 12


# ---------------------------------------------------------------------------
# fold: stable entry ids
# ---------------------------------------------------------------------------

class TestEntryIds:

    def test_entries_receive_distinct_monotonic_ids_after_flush(self):
        """Two top-level entries flushed in sequence get distinct ids 'e0' and 'e1'."""
        p = _proj_with_primary("a1")
        # thinking delta then step_advanced: flushes ThinkingEntry then StepEntry
        p = fold(p, _e("thinking", {"delta": "hmm"}, agent_id="a1"))
        r = fold(p, _e("agent_step_advanced", {"step": 1, "step_name": "Plan"}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert len(conv.entries) == 2
        assert conv.entries[0].entry_id == "e0"
        assert conv.entries[1].entry_id == "e1"

    def test_noop_fold_leaves_entry_ids_unchanged(self):
        """A fold that returns projection unchanged does not alter assigned ids."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("thinking", {"delta": "hmm"}, agent_id="a1"))
        p = fold(p, _e("agent_step_advanced", {"step": 1, "step_name": "Plan"}, agent_id="a1"))
        # tool_result_captured with unknown call_id is a documented noop
        r = fold(p, _e("tool_result_captured", {
            "call_id": "missing", "tool": "read", "metrics": {"lines_read": 1},
        }, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert conv.entries[0].entry_id == "e0"
        assert conv.entries[1].entry_id == "e1"

    def test_aggregate_child_has_empty_entry_id_parent_has_non_empty(self):
        """ToolAggregateEntry gets an entry_id; its children do not."""
        p = _proj_with_primary("a1")
        # Two reads form an aggregate so children exist.
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        agg = conv.entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert agg.entry_id == "e1"  # aggregate gets new id (first read had e0)
        # Children are keyed by call_id; entry_id stays '' (intentionally unset)
        assert agg.children[0].call_id == "c1"
        assert agg.children[0].entry_id == ""

    def test_to_wire_includes_entry_id_excludes_next_entry_id(self):
        """Serialized wire dict has entryId on entries but no nextEntryId on conversation."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("stream_delta", {"delta": "hello"}, agent_id="a1"))
        r = fold(p, _e("agent_step_advanced", {"step": 1, "step_name": "Plan"}, agent_id="a1"))
        wire = r.to_wire()
        conv_wire = wire["run"]["agents"]["a1"]["conversation"]
        # counter is excluded from the wire
        assert "nextEntryId" not in conv_wire
        # every top-level entry carries entryId
        for entry in conv_wire["entries"]:
            assert "entryId" in entry, f"entryId missing on entry type={entry.get('type')}"
            assert entry["entryId"] != ""


# ---------------------------------------------------------------------------
# fold: focus transitions
# ---------------------------------------------------------------------------

class TestFoldFocus:

    def test_questions_asked_sets_question_focus(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("questions_asked", {"token": "t1", "questions": [{"question": "Q?"}]}, agent_id="a1"))
        assert isinstance(r.run.focus, QuestionFocus)
        assert r.run.focus.agent_id == "a1"
        assert r.run.focus.token == "t1"
        assert len(r.run.focus.questions) == 1

    def test_questions_answered_resets_to_conversation_focus(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("questions_asked", {"token": "t1", "questions": []}, agent_id="a1"))
        r = fold(p, _e("questions_answered", {"token": "t1", "cancelled": False}, agent_id="a1"))
        assert isinstance(r.run.focus, ConversationFocus)
        assert r.run.focus.agent_id == "a1"

    # M2: connections_listed/configured_models_listed/presets_listed/active_changed/
    # default_scout_concurrency_changed/retry_settings_changed fold tests removed --
    # these events are consolidated into settings_listed (tests at end of file).


# ---------------------------------------------------------------------------
# fold: resources (artifacts)
# ---------------------------------------------------------------------------

class TestFoldArtifacts:

    def test_artifact_created(self):
        p = _proj_with_run()
        r = fold(p, _e("artifact_created", {"path": "foo.md", "size": 100, "modified_at": 1000}))
        assert "foo.md" in r.run.artifacts
        assert r.run.artifacts["foo.md"].size == 100

    def test_artifact_modified(self):
        p = _proj_with_run()
        p = fold(p, _e("artifact_created", {"path": "foo.md", "size": 50, "modified_at": 500}))
        r = fold(p, _e("artifact_modified", {"path": "foo.md", "size": 200, "modified_at": 2000}))
        assert r.run.artifacts["foo.md"].size == 200

    def test_artifact_removed(self):
        p = _proj_with_run()
        p = fold(p, _e("artifact_created", {"path": "foo.md", "size": 100, "modified_at": 1000}))
        r = fold(p, _e("artifact_removed", {"path": "foo.md"}))
        assert "foo.md" not in r.run.artifacts

    def test_artifact_events_without_run_noop(self):
        p = Projection()
        r = fold(p, _e("artifact_created", {"path": "foo.md", "size": 100, "modified_at": 1000}))
        assert r.run is None

    def test_run_events_do_not_touch_settings(self):
        """Artifact events must not modify settings."""
        p = _proj_with_run()
        r = fold(p, _e("artifact_created", {"path": "foo.md", "size": 100, "modified_at": 1000}))
        assert r.settings == p.settings


# ---------------------------------------------------------------------------
# fold: artifact review -- removed in M5
# ---------------------------------------------------------------------------

class TestFoldArtifactReviewRemoved:
    """M5 deleted the inline-review apparatus. artifact_review_started and
    artifact_review_cleared are no longer known event types; the fold treats
    them as unknown and returns the projection unchanged."""

    def test_artifact_review_started_unknown_noop(self):
        p = _proj_with_run()
        r = fold(p, _e("artifact_review_started", {"path": "plan.md"}))
        # Unknown event: projection unchanged, no active_artifact_review field
        assert r == p
        assert not hasattr(r.run, "active_artifact_review")

    def test_artifact_review_cleared_unknown_noop(self):
        p = _proj_with_run()
        r = fold(p, _e("artifact_review_cleared", {}))
        assert r == p


# ---------------------------------------------------------------------------
# fold: safety
# ---------------------------------------------------------------------------

class TestFoldSafety:

    def test_unknown_event_type_returns_unchanged(self):
        p = _proj_with_run()
        r = fold(p, _e("completely_unknown", {"data": 42}))
        assert r == p

    def test_fold_is_pure(self):
        p = _proj_with_run()
        e = _e("phase_started", {"phase": "brief-generation"})
        r1 = fold(p, e)
        r2 = fold(p, e)
        assert r1 == r2
        assert p.run.phase == ""  # original unchanged

    def test_fold_exception_propagates_and_store_stays_consistent(self, monkeypatch):
        """A fold failure propagates (fail fast) and commits nothing.

        Every folded event is produced in-process, so a fold failure is a
        producer bug; swallowing it froze the projection silently (the
        settings_listed identity=None incident). The store must fail before
        committing: no version bump, no appended event, projection unchanged.
        """
        import pytest
        import koan.projections as proj_mod

        def always_raise(projection, event):
            raise RuntimeError("simulated fold failure")

        monkeypatch.setattr(proj_mod, "fold", always_raise)
        store = proj_mod.ProjectionStore()
        prev = store.projection
        with pytest.raises(RuntimeError, match="simulated fold failure"):
            store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        assert store.projection == prev
        assert store.version == 0
        assert store.events == []


# ---------------------------------------------------------------------------
# ProjectionStore
# ---------------------------------------------------------------------------

class TestProjectionStore:

    def test_push_increments_version(self):
        store = ProjectionStore()
        assert store.version == 0
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        assert store.version == 1

    def test_fold_applied(self):
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        assert store.projection.run is not None

    def test_get_snapshot_camelcase(self):
        """get_snapshot() must return camelCase keys (via to_wire)."""
        store = ProjectionStore()
        snap = store.get_snapshot()
        state = snap["state"]
        # Top-level fields are camelCase
        assert "settings" in state
        assert "run" in state
        assert "notifications" in state
        # Nested camelCase: M5 settings no longer has defaultProfile (profiles removed)
        settings = state["settings"]
        assert "defaultScoutConcurrency" in settings  # not default_scout_concurrency
        # M5: connections, presets, active replace profiles/defaultProfile
        assert "connections" in settings
        assert "presets" in settings
        assert "active" in settings

    def test_get_snapshot_includes_version(self):
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        snap = store.get_snapshot()
        assert snap["version"] == 1

    def test_subscriber_receives_dict_not_event(self):
        """Subscribers get plain dicts (SSE-ready), not VersionedEvent objects."""
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        msg = q.get_nowait()
        assert isinstance(msg, dict)
        assert msg["type"] == "patch"
        assert "version" in msg
        assert "patch" in msg

    @pytest.mark.anyio
    async def test_subscriber_receives_patch(self):
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        assert msg["type"] == "patch"
        assert msg["version"] == 1
        assert isinstance(msg["patch"], list)
        store.unsubscribe(q)

    @pytest.mark.anyio
    async def test_unsubscribe_stops_delivery(self):
        store = ProjectionStore()
        q = store.subscribe()
        store.unsubscribe(q)
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        assert q.empty()

    def test_no_patch_broadcast_when_no_state_change(self):
        """koan_ tools produce no state change; no patch broadcast."""
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        store.push_event("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True,
            "started_at_ms": 0, "label": "", "model": None,
        }, agent_id="a1")
        q = store.subscribe()
        # koan MCP tool is filtered -- no state change -> no patch broadcast.
        # Using koan_suggest_next as representative; koan_complete_step removed in M6.
        store.push_event("tool_called", {
            "call_id": "c1", "tool": "koan_suggest_next", "args": {},
        }, agent_id="a1")
        assert q.empty()


# ---------------------------------------------------------------------------
# JSON Patch paths — verify camelCase patch operations
# ---------------------------------------------------------------------------

class TestJSONPatchPaths:

    def test_patch_has_camelcase_run_path(self):
        """run_started must produce a patch with /run path."""
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        msg = q.get_nowait()
        ops = msg["patch"]
        paths = [op["path"] for op in ops]
        assert any("/run" in p for p in paths)

    def test_patch_has_camelcase_agent_fields(self):
        """Agent fields use camelCase in patch paths: lastTool, stepName, etc."""
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        store.push_event("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True,
            "started_at_ms": 0, "label": "", "model": None,
        }, agent_id="a1")
        store.push_event("agent_step_advanced", {"step": 1, "step_name": "Scout"}, agent_id="a1")
        q = store.subscribe()
        store.push_event("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1")
        msg = q.get_nowait()
        ops = msg["patch"]
        # Check some paths contain camelCase
        all_paths = " ".join(op["path"] for op in ops)
        # lastTool should be camelCase
        assert "lastTool" in all_paths or "conversation" in all_paths

    def test_patch_pending_thinking_camelcase_path(self):
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        store.push_event("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True,
            "started_at_ms": 0, "label": "", "model": None,
        }, agent_id="a1")
        q = store.subscribe()
        store.push_event("thinking", {"delta": "hmm"}, agent_id="a1")
        msg = q.get_nowait()
        ops = msg["patch"]
        all_paths = " ".join(op["path"] for op in ops)
        # pendingThinking must be camelCase
        assert "pendingThinking" in all_paths

    # M2: test_patch_active_changed_camelcase removed -- active_changed is
    # consolidated into settings_listed (camelcase patch covered by the
    # settings_listed patch test at end of file).

    def test_run_cleared_produces_run_replace_patch(self):
        # run_cleared must emit at least one patch op touching /run.
        # jsonpatch emits a "replace" op (value: null) when an object becomes None.
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        q = store.subscribe()
        store.push_event("run_cleared", {})
        msg = q.get_nowait()
        ops = msg["patch"]
        assert any(op.get("path") == "/run" for op in ops)


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------

class TestSnapshotRoundTrip:

    def test_snapshot_state_is_camelcase(self):
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        state = store.get_snapshot()["state"]
        run = state["run"]
        assert "config" in run
        assert "scoutConcurrency" in run["config"]   # not scout_concurrency
        assert "agents" in run
        assert "isPrimary" not in run  # no agents yet

    def test_snapshot_agent_camelcase(self):
        store = ProjectionStore()
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        store.push_event("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True,
            "started_at_ms": 1000, "label": "", "model": "opus",
        }, agent_id="a1")
        state = store.get_snapshot()["state"]
        agent = state["run"]["agents"]["a1"]
        assert "isPrimary" in agent         # not is_primary
        assert "startedAtMs" in agent       # not started_at_ms
        assert "stepName" in agent          # not step_name
        assert "lastTool" in agent          # not last_tool
        assert "conversation" in agent
        conv = agent["conversation"]
        assert "pendingThinking" in conv    # not pending_thinking
        assert "pendingText" in conv        # not pending_text
        assert "isThinking" in conv         # not is_thinking


# ---------------------------------------------------------------------------
# build_artifact_diff (unchanged — regression guard)
# ---------------------------------------------------------------------------

class TestBuildArtifactDiff:

    def test_created(self):
        from koan.events import build_artifact_diff
        old = {}
        new = [{"path": "foo.md", "size": 100, "modified_at": 1.0}]
        events = build_artifact_diff(old, new)
        assert len(events) == 1
        assert events[0][0] == "artifact_created"
        assert events[0][1]["path"] == "foo.md"
        assert events[0][1]["modified_at"] == 1000

    def test_removed(self):
        from koan.events import build_artifact_diff
        old = {"foo.md": {"path": "foo.md", "size": 100, "modified_at": 1000}}
        new = []
        events = build_artifact_diff(old, new)
        assert len(events) == 1
        assert events[0][0] == "artifact_removed"

    def test_modified_by_size(self):
        from koan.events import build_artifact_diff
        old = {"foo.md": {"path": "foo.md", "size": 50, "modified_at": 1000}}
        new = [{"path": "foo.md", "size": 100, "modified_at": 1.0}]
        events = build_artifact_diff(old, new)
        assert len(events) == 1
        assert events[0][0] == "artifact_modified"

    def test_unchanged_no_events(self):
        from koan.events import build_artifact_diff
        old = {"foo.md": {"path": "foo.md", "size": 100, "modified_at": 1000}}
        new = [{"path": "foo.md", "size": 100, "modified_at": 1.0}]
        assert build_artifact_diff(old, new) == []

    def test_mixed_diff(self):
        from koan.events import build_artifact_diff
        old = {
            "a.md": {"path": "a.md", "size": 10, "modified_at": 1000},
            "b.md": {"path": "b.md", "size": 20, "modified_at": 2000},
        }
        new = [
            {"path": "a.md", "size": 15, "modified_at": 1.0},
            {"path": "c.md", "size": 30, "modified_at": 3.0},
        ]
        events = build_artifact_diff(old, new)
        types = [e[0] for e in events]
        assert "artifact_modified" in types
        assert "artifact_created" in types
        assert "artifact_removed" in types


# ---------------------------------------------------------------------------
# fold: reflect_inline_trace domain event
# ---------------------------------------------------------------------------

class TestFoldReflectInlineTrace:
    """reflect_inline_trace appends trace events to the in-flight ToolKoanEntry's
    result.traces array and updates metadata (model, maxIterations, iteration).

    Correlated by agent_id only (koan MCP tools block, so at most one
    in-flight koan entry per agent at any time). Fold case is pure.
    """

    def _with_inflight_koan_entry(self, tool_name: str = "koan_reflect") -> tuple:
        """Return (projection, agent_id) with an in-flight ToolKoanEntry."""
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {
            "call_id": "c1", "tool": tool_name,
        }, agent_id="a1"))
        return p, "a1"

    def _trace(self, trace: dict, agent_id: str = "a1") -> VersionedEvent:
        return _e("reflect_inline_trace", {"trace": trace}, agent_id=agent_id)

    def test_meta_sets_model_and_max_iterations(self):
        """meta trace sets result.model, result.maxIterations, result.iteration, and initializes traces."""
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, self._trace({
            "kind": "meta", "model": "gemini-flash-latest",
            "maxIterations": 10, "iteration": 0,
        }, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert isinstance(entry, ToolKoanEntry)
        assert entry.result["model"] == "gemini-flash-latest"
        assert entry.result["maxIterations"] == 10
        assert entry.result["iteration"] == 0
        assert entry.result["traces"] == []

    def test_thinking_start_appends_to_traces(self):
        """thinking_start trace is appended to result.traces."""
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, self._trace({"kind": "thinking_start"}, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.result["traces"] == [{"kind": "thinking", "status": "running", "delta": ""}]

    def test_thinking_end_appends_to_traces(self):
        """thinking_end without a running thinking entry is a no-op (traces empty)."""
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, self._trace({"kind": "thinking_end"}, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.result.get("traces", []) == []

    def test_search_running_appends_to_traces(self):
        """search (running) trace is appended with all fields."""
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, self._trace({
            "kind": "search", "status": "running",
            "query": "auth", "type_filter": "decision", "iteration": 1,
        }, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.result["traces"] == [{
            "kind": "search", "status": "running",
            "query": "auth", "type_filter": "decision", "iteration": 1,
        }]

    def test_search_done_updates_last_running(self):
        """search_done updates the last running search entry with resultCount and status done."""
        p, aid = self._with_inflight_koan_entry()
        p = fold(p, self._trace({
            "kind": "search", "status": "running",
            "query": "auth", "type_filter": "decision", "iteration": 1,
        }, aid))
        r = fold(p, self._trace({
            "kind": "search_done", "query": "auth",
            "resultCount": 5, "iteration": 1,
        }, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert len(entry.result["traces"]) == 1
        t = entry.result["traces"][0]
        assert t["status"] == "done"
        assert t["resultCount"] == 5

    def test_search_done_no_running_is_noop(self):
        """search_done without a prior running search leaves traces unchanged (empty)."""
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, self._trace({
            "kind": "search_done", "query": "auth",
            "resultCount": 3, "iteration": 1,
        }, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        # traces is not set because search_done branch does not append
        assert entry.result.get("traces", []) == []

    def test_multiple_traces_accumulate(self):
        """meta, thinking_start, search running, search_done, thinking_end accumulate in order."""
        p, aid = self._with_inflight_koan_entry()
        p = fold(p, self._trace({
            "kind": "meta", "model": "opus", "maxIterations": 10, "iteration": 0,
        }, aid))
        p = fold(p, self._trace({"kind": "thinking_start"}, aid))
        p = fold(p, self._trace({
            "kind": "search", "status": "running",
            "query": "auth", "type_filter": "", "iteration": 1,
        }, aid))
        p = fold(p, self._trace({
            "kind": "search_done", "query": "auth",
            "resultCount": 2, "iteration": 1,
        }, aid))
        r = fold(p, self._trace({"kind": "thinking_end"}, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        traces = entry.result["traces"]
        assert traces[0] == {"kind": "thinking", "status": "done", "delta": ""}
        assert traces[1]["kind"] == "search"
        assert traces[1]["status"] == "done"
        assert traces[1]["resultCount"] == 2
        assert traces[1]["query"] == "auth"
        assert len(traces) == 2

    def test_iteration_updates_on_trace(self):
        """iteration field is updated from the trace's iteration field when present."""
        p, aid = self._with_inflight_koan_entry()
        p = fold(p, self._trace({
            "kind": "meta", "model": "opus", "maxIterations": 10, "iteration": 0,
        }, aid))
        r = fold(p, self._trace({
            "kind": "search", "status": "running",
            "query": "x", "type_filter": "", "iteration": 2,
        }, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.result["iteration"] == 2

    def test_no_inflight_entry_is_noop(self):
        """When there is no in-flight ToolKoanEntry the event is dropped silently."""
        p = _proj_with_primary("a1")
        r = fold(p, self._trace({"kind": "thinking_start"}, "a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_inflight_remains_true(self):
        """After emitting reflect_inline_trace, entry.in_flight stays True."""
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, self._trace({"kind": "thinking_start"}, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.in_flight is True

    def test_preserves_existing_result_fields(self):
        """reflect_inline_trace preserves answer set by a prior text trace."""
        p, aid = self._with_inflight_koan_entry()
        p = fold(p, self._trace({"kind": "text", "delta": "hello", "iteration": 1}, aid))
        r = fold(p, self._trace({"kind": "thinking_start", "iteration": 1}, aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.result["answer"] == "hello"
        assert entry.result["traces"] == [
            {"kind": "text", "delta": "hello"},
            {"kind": "thinking", "status": "running", "delta": ""},
        ]

    def test_tool_completed_merges_not_replaces_result(self):
        """tool_completed merges parsed result into existing result, preserving traces/model."""
        p, aid = self._with_inflight_koan_entry()
        p = fold(p, self._trace({
            "kind": "meta", "model": "opus", "maxIterations": 10, "iteration": 0,
        }, aid))
        p = fold(p, self._trace({"kind": "thinking_start"}, aid))
        p = fold(p, self._trace({"kind": "thinking_end"}, aid))
        result_json = '{"answer": "final", "citations": [{"id": "1", "title": "T"}], "iterations": 3}'
        r = fold(p, _e("tool_completed", {
            "call_id": "c1", "tool": "koan_reflect", "result": result_json,
        }, agent_id=aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert isinstance(entry, ToolKoanEntry)
        assert entry.in_flight is False
        assert entry.result["answer"] == "final"
        assert entry.result["model"] == "opus"
        assert entry.result["traces"] == [{"kind": "thinking", "status": "done", "delta": ""}]
        assert entry.result["iterations"] == 3

    def test_tool_completed_cleans_up_dangling_thinking(self):
        """tool_completed closes a dangling running thinking entry by setting status to done."""
        p, aid = self._with_inflight_koan_entry()
        p = fold(p, self._trace({"kind": "thinking_start"}, aid))
        result_json = '{"answer": "done", "iterations": 1}'
        r = fold(p, _e("tool_completed", {
            "call_id": "c1", "tool": "koan_reflect", "result": result_json,
        }, agent_id=aid))
        entry = r.run.agents[aid].conversation.entries[0]
        traces = entry.result["traces"]
        assert traces[-1] == {"kind": "thinking", "status": "done", "delta": ""}
        assert traces[0] == {"kind": "thinking", "status": "done", "delta": ""}


# ---------------------------------------------------------------------------
# fold: tool_attachments domain event
# ---------------------------------------------------------------------------

class TestFoldToolAttachments:
    """tool_attachments overwrites the in-flight tool entry's attachments field.

    Correlated by agent_id. Targets the first in-flight non-aggregate entry.
    ToolAggregateEntry is never targeted (it has no in_flight field).
    """

    _full_manifest = [
        {
            "upload_id": "u1",
            "filename": "note.txt",
            "size": 42,
            "content_type": "text/plain",
            "path": "/run/uploads/u1/note.txt",
        }
    ]

    def _with_inflight_bash(self, agent_id: str = "a1") -> tuple:
        """Return projection with an in-flight ToolBashEntry."""
        p = _proj_with_primary(agent_id)
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "bash"}, agent_id=agent_id))
        return p, agent_id

    def test_tool_attachments_overwrites_entry_attachments(self):
        from koan.projections import AttachmentEntry
        p, aid = self._with_inflight_bash()
        r = fold(p, _e("tool_attachments", {"attachments": self._full_manifest}, agent_id=aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert isinstance(entry, ToolBashEntry)
        assert entry.attachments is not None
        assert len(entry.attachments) == 1
        att = entry.attachments[0]
        assert isinstance(att, AttachmentEntry)
        assert att.upload_id == "u1"
        assert att.filename == "note.txt"
        assert att.path == "/run/uploads/u1/note.txt"
        # in_flight must remain True -- domain events do not close the lifecycle
        assert entry.in_flight is True

    def test_tool_attachments_malformed_manifest_is_noop(self):
        """Malformed manifest (missing required fields) is silently dropped."""
        p, aid = self._with_inflight_bash()
        bad_manifest = [{"filename": "bad.txt"}]  # missing upload_id and path
        r = fold(p, _e("tool_attachments", {"attachments": bad_manifest}, agent_id=aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.attachments is None  # unchanged

    def test_tool_attachments_no_inflight_entry_is_noop(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_attachments", {"attachments": self._full_manifest}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_tool_attachments_does_not_target_aggregate_entry(self):
        """ToolAggregateEntry has no in_flight field; it is skipped."""
        p = _proj_with_primary("a1")
        # Two reads form a ToolAggregateEntry (not a ToolBashEntry).
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "read", "ts_ms": 2}, agent_id="a1"))
        from koan.projections import ToolAggregateEntry
        assert isinstance(p.run.agents["a1"].conversation.entries[0], ToolAggregateEntry)
        # tool_attachments should be a no-op (no non-aggregate in-flight entry).
        # Projection unchanged: fold logs a warning and returns projection.
        r = fold(p, _e("tool_attachments", {"attachments": self._full_manifest}, agent_id="a1"))
        assert isinstance(r.run.agents["a1"].conversation.entries[0], ToolAggregateEntry)
        # ToolAggregateEntry has no attachments field -- just verify entry type unchanged
        assert len(r.run.agents["a1"].conversation.entries) == 1


# ---------------------------------------------------------------------------
# M2: TestProviderStatusListedFold and TestProviderModelsListedFold removed --
# provider_status_listed, provider_models_listed, model_registry_listed, and
# model_capabilities_listed are consolidated into settings_listed. The deleted
# wire types (ConnectionStatusWire, ProviderModelWire, ProviderFamilyWire,
# ModelRegistryEntryWire, ResolvedCapabilitiesWire) no longer exist.


# ---------------------------------------------------------------------------
# fold: tool_failed -- validation-rejected calls become ToolFailedEntry
# ---------------------------------------------------------------------------

class TestToolFailedFold:

    def test_tool_failed_replaces_koan_entry_retaining_ids(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {
            "call_id": "c1", "tool": "koan_ask_question", "ts_ms": 1000,
        }, agent_id="a1"))
        p = fold(p, _e("tool_input_delta", {
            "call_id": "c1", "tool": "koan_ask_question",
            "tool_input": {"x": 1}, "delta": '{"x": 1}',
        }, agent_id="a1"))
        before = p.run.agents["a1"].conversation.entries[0]
        assert isinstance(before, ToolKoanEntry)
        assert before.entry_id != ""
        r = fold(p, _e("tool_failed", {
            "call_id": "c1", "tool": "koan_ask_question",
            "error": "1 validation error: questions must be a list",
            "ts_ms": 2000,
        }, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, ToolFailedEntry)
        assert entry.entry_id == before.entry_id
        assert entry.phase_id == before.phase_id
        assert entry.in_flight is False
        assert entry.failed is True
        assert entry.tool_name == "koan_ask_question"
        assert entry.error == "1 validation error: questions must be a list"
        # The malformed structured payload survives only as an opaque string.
        assert entry.raw_input == '{"x": 1}'
        assert not hasattr(entry, "args") or not getattr(entry, "args", None)

    def test_tool_failed_marks_aggregate_child_in_place(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_request", {"call_id": "c2", "tool": "grep", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_failed", {
            "call_id": "c2", "tool": "grep", "error": "bad args", "ts_ms": 3,
        }, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        agg = entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert len(agg.children) == 2
        failed_child = agg.children[1]
        assert failed_child.call_id == "c2"
        assert failed_child.failed is True
        assert failed_child.in_flight is False
        assert failed_child.completed_at_ms == 3
        # Sibling untouched.
        assert agg.children[0].failed is False
        assert agg.children[0].in_flight is True

    def test_tool_failed_top_level_exploration_then_no_promotion(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {"call_id": "c1", "tool": "read", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_failed", {
            "call_id": "c1", "tool": "read", "error": "bad args", "ts_ms": 2,
        }, agent_id="a1"))
        r = fold(p, _e("tool_request", {"call_id": "c2", "tool": "grep", "ts_ms": 3}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 2
        assert isinstance(entries[0], ToolFailedEntry)
        assert isinstance(entries[1], ToolGrepEntry)

    def test_tool_failed_unknown_call_id_is_noop(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_failed", {
            "call_id": "nope", "tool": "read", "error": "x", "ts_ms": 1,
        }, agent_id="a1"))
        assert r is p


# ---------------------------------------------------------------------------
# fold: koan tool input sanitization (tool_input_delta)
# ---------------------------------------------------------------------------

class TestKoanInputSanitize:

    def _ask_entry_after_delta(self, tool_input: dict):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {
            "call_id": "c1", "tool": "koan_ask_question", "ts_ms": 1,
        }, agent_id="a1"))
        r = fold(p, _e("tool_input_delta", {
            "call_id": "c1", "tool": "koan_ask_question",
            "tool_input": tool_input, "delta": "",
        }, agent_id="a1"))
        return r.run.agents["a1"].conversation.entries[0]

    def test_sanitize_ask_question_string_questions_dropped(self):
        # The production payload: the model sent questions as a JSON string.
        entry = self._ask_entry_after_delta(
            {"questions": '[{"question": "which approach?"}]'}
        )
        assert "questions" not in (entry.tool_input or {})
        assert "questions" not in entry.args

    def test_sanitize_ask_question_bad_options_dropped_item_kept(self):
        entry = self._ask_entry_after_delta(
            {"questions": [{"question": "q?", "options": "a,b"}]}
        )
        qs = entry.tool_input["questions"]
        assert qs == [{"question": "q?"}]
        assert entry.args["questions"] == [{"question": "q?"}]

    def test_sanitize_valid_input_passthrough(self):
        ti = {"questions": [
            {"question": "q?", "context": "ctx", "options": [{"label": "a"}]},
        ]}
        entry = self._ask_entry_after_delta(ti)
        assert entry.tool_input == ti
        assert entry.args == ti

    def test_sanitize_non_tabled_tool_passthrough(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_request", {
            "call_id": "c1", "tool": "koan_memorize", "ts_ms": 1,
        }, agent_id="a1"))
        ti = {"anything": {"goes": ["here", 1, None]}}
        r = fold(p, _e("tool_input_delta", {
            "call_id": "c1", "tool": "koan_memorize",
            "tool_input": ti, "delta": "",
        }, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert entry.tool_input == ti
        assert entry.args == ti


# ---------------------------------------------------------------------------
# fold: settings_listed (Settings full snapshot, M2)
# ---------------------------------------------------------------------------

_SETTINGS_LISTED_PAYLOAD = {
    "connections": [
        {"id": "anthropic-1", "route": "anthropic", "locality": None, "available": True},
        {"id": "openai-1", "route": "openai", "locality": None, "available": False},
    ],
    "configured_models": [
        {
            "id": "cm-sonnet", "connection_id": "anthropic-1", "model_id": "claude-sonnet-4-5",
            "resolved_from": None, "embedding_dim": None,
            "identity": {"vendor": "anthropic", "family": "claude-sonnet", "version": "4.5", "snapshot": None, "kind": "chat"},
            "resolved": True,
            "caps": {"kind": "chat", "thinking_levels": ["low", "medium"], "prompt_caching": "explicit", "native_tools": ["web_fetch", "web_search"], "supports_tools": True, "embedding_dims": None, "resolved": True, "provenance": {}},
        },
        {
            "id": "cm-unknown", "connection_id": "openai-1", "model_id": "some-unknown-model",
            "resolved_from": None, "embedding_dim": None,
            "identity": None, "resolved": False,
            "caps": {"kind": "chat", "thinking_levels": [], "prompt_caching": "none", "native_tools": [], "supports_tools": True, "embedding_dims": None, "resolved": False, "provenance": {}},
        },
    ],
    "offerings_by_connection": {
        "anthropic-1": [
            {
                "wire_id": "claude-sonnet-4-5",
                "identity": {"vendor": "anthropic", "family": "claude-sonnet", "version": "4.5", "snapshot": None, "kind": "chat"},
                "display_name": "anthropic/claude-sonnet-4.5",
                "caps": {"kind": "chat", "thinking_levels": ["low", "medium"], "prompt_caching": "explicit", "native_tools": ["web_fetch", "web_search"], "supports_tools": True, "embedding_dims": None, "resolved": True, "provenance": {}},
            },
        ],
    },
    "presets": {
        "$last": {"slots": {"strong": {"configured_model_id": "cm-sonnet", "thinking": "high"}}},
    },
    "active": "$last",
    "memory_bindings": {"embedding": {"configured_model_id": "cm-sonnet"}},
    "default_scout_concurrency": 12,
    "max_retry_attempts": 7,
    "max_retry_wait_seconds": 45.0,
    "workflows": [
        {"id": "plan", "description": "Plan and execute", "phases": [{"id": "intake", "description": "Gather requirements"}], "initial_phase": "intake"},
    ],
    "embedding_models": [
        {"model_id": "voyage-4-large", "dimensions": [256, 512, 1024, 2048], "default_dimension": 1024},
    ],
}


class TestSettingsListedFold:

    def test_settings_listed_populates_all_fields(self):
        """settings_listed fold sets every Settings field from the payload."""
        from koan.projections import OfferingWire, IdentityWire
        p = Projection()
        r = fold(p, _e("settings_listed", _SETTINGS_LISTED_PAYLOAD))
        s = r.settings
        # connections (reshaped: route replaces connection_type, available added)
        assert len(s.connections) == 2
        assert s.connections[0].id == "anthropic-1"
        assert s.connections[0].route == "anthropic"
        assert s.connections[0].available is True
        assert s.connections[1].available is False
        # configured_models (with identity + caps)
        assert len(s.configured_models) == 2
        cm0 = s.configured_models[0]
        assert cm0.id == "cm-sonnet"
        assert cm0.resolved is True
        assert cm0.identity is not None
        assert cm0.caps.prompt_caching == "explicit"
        cm1 = s.configured_models[1]
        assert cm1.resolved is False
        assert cm1.identity is None
        # offerings_by_connection
        assert "anthropic-1" in s.offerings_by_connection
        assert len(s.offerings_by_connection["anthropic-1"]) == 1
        off = s.offerings_by_connection["anthropic-1"][0]
        assert isinstance(off, OfferingWire)
        assert off.wire_id == "claude-sonnet-4-5"
        assert isinstance(off.identity, IdentityWire)
        assert off.identity.family == "claude-sonnet"
        # presets / active / memory_bindings / scalars / workflows / embedding_models
        assert "$last" in s.presets
        assert s.presets["$last"].slots["strong"].configured_model_id == "cm-sonnet"
        assert s.active == "$last"
        assert s.memory_bindings == {"embedding": {"configured_model_id": "cm-sonnet"}}
        assert s.default_scout_concurrency == 12
        assert s.max_retry_attempts == 7
        assert s.max_retry_wait_seconds == 45.0
        assert len(s.workflows) == 1
        assert s.workflows[0].id == "plan"
        assert len(s.embedding_models) == 1
        assert s.embedding_models[0].model_id == "voyage-4-large"

    def test_settings_listed_replaces_previous(self):
        """A second settings_listed event replaces the first entirely."""
        p = Projection()
        r = fold(p, _e("settings_listed", _SETTINGS_LISTED_PAYLOAD))
        assert len(r.settings.connections) == 2
        # Second snapshot with a single connection replaces the whole list.
        r2 = fold(r, _e("settings_listed", {
            "connections": [{"id": "solo", "route": "openai", "locality": None, "available": True}],
            "configured_models": [], "offerings_by_connection": {}, "presets": {},
            "active": "$last", "memory_bindings": None, "default_scout_concurrency": 8,
            "max_retry_attempts": 10, "max_retry_wait_seconds": 60.0, "workflows": [], "embedding_models": [],
        }))
        assert len(r2.settings.connections) == 1
        assert r2.settings.connections[0].id == "solo"
        # Offerings cleared by the replace.
        assert r2.settings.offerings_by_connection == {}

    def test_settings_listed_with_empty_payload_clears_fields(self):
        """An empty settings_listed payload clears all list/dict fields to defaults."""
        p = Projection()
        p = fold(p, _e("settings_listed", _SETTINGS_LISTED_PAYLOAD))
        r = fold(p, _e("settings_listed", {
            "connections": [], "configured_models": [], "offerings_by_connection": {}, "presets": {},
            "active": "$last", "memory_bindings": None, "default_scout_concurrency": 8,
            "max_retry_attempts": 10, "max_retry_wait_seconds": 60.0, "workflows": [], "embedding_models": [],
        }))
        assert r.settings.connections == []
        assert r.settings.configured_models == []
        assert r.settings.offerings_by_connection == {}
        assert r.settings.presets == {}
        assert r.settings.workflows == []
        assert r.settings.embedding_models == []

    def test_settings_listed_does_not_touch_run(self):
        """settings_listed must not modify run state."""
        p = _proj_with_run()
        r = fold(p, _e("settings_listed", _SETTINGS_LISTED_PAYLOAD))
        assert r.run is not None
        assert r.run.config == p.run.config

    def test_settings_listed_camelcase_patch(self):
        """The settings_listed JSON patch uses camelCase paths (alias_generator)."""
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("settings_listed", _SETTINGS_LISTED_PAYLOAD)
        msg = q.get_nowait()
        ops = msg["patch"]
        all_paths = " ".join(op["path"] for op in ops)
        # offeringsByConnection is camelCase on the wire.
        assert "/settings/offeringsByConnection" in all_paths
        # configuredModels is camelCase.
        assert "/settings/configuredModels" in all_paths

    def test_settings_listed_offerings_by_connection(self):
        """offerings_by_connection is populated from the payload (replace-all)."""
        p = Projection()
        r = fold(p, _e("settings_listed", _SETTINGS_LISTED_PAYLOAD))
        assert "anthropic-1" in r.settings.offerings_by_connection
        offerings = r.settings.offerings_by_connection["anthropic-1"]
        assert len(offerings) == 1
        assert offerings[0].caps.prompt_caching == "explicit"
