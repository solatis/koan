# Tests for koan.projections (ProjectionStore, fold) and koan.events (build_artifact_diff).
# New architecture: server-authoritative JSON Patch. fold() is the only business logic.
# Projection has 3 top-level fields: settings, run, notifications.

from __future__ import annotations

import asyncio

import pytest

from koan.projections import (
    Agent,
    AggregateGrepChild,
    AggregateLsChild,
    AggregateReadChild,
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
    ToolGenericEntry,
    ToolWriteEntry,
    VersionedEvent,
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


def _proj_with_run(profile: str = "balanced") -> Projection:
    """Return a Projection with an active run (post run_started)."""
    p = Projection()
    return fold(p, _e("run_started", {
        "profile": profile,
        "installations": {},
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
        r = fold(p, _e("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8}))
        assert r.run is not None
        assert r.run.config.profile == "balanced"
        assert r.run.config.scout_concurrency == 8

    def test_run_started_resets_run_on_new_start(self):
        """A second run_started replaces the run entirely."""
        p = _proj_with_run("balanced")
        # Simulate a new run
        r = fold(p, _e("run_started", {"profile": "fast", "installations": {}, "scout_concurrency": 4}))
        assert r.run is not None
        assert r.run.config.profile == "fast"
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

    def test_workflow_selected_without_run_is_noop(self):
        p = Projection()
        r = fold(p, _e("workflow_selected", {"workflow": "plan"}))
        assert r.run is None


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
        # Error notification appended
        assert len(r.notifications) == 1
        assert "boom" in r.notifications[0].message

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

    def test_tool_read_creates_aggregate_with_one_child(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_read", {
            "call_id": "c1", "file": "/foo.py", "lines": "1-10", "ts_ms": 1000,
        }, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert len(conv.entries) == 1
        agg = conv.entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert agg.started_at_ms == 1000
        assert len(agg.children) == 1
        child = agg.children[0]
        assert isinstance(child, AggregateReadChild)
        assert child.file == "/foo.py"
        assert child.lines == "1-10"
        assert child.in_flight is True
        assert child.started_at_ms == 1000
        assert r.run.agents["a1"].last_tool == "read /foo.py:1-10"

    def test_two_consecutive_reads_form_one_aggregate(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": "", "ts_ms": 1}, agent_id="a1"))
        r = fold(p, _e("tool_read", {"call_id": "c2", "file": "/b", "lines": "", "ts_ms": 2}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        assert isinstance(entries[0], ToolAggregateEntry)
        assert entries[0].started_at_ms == 1  # aggregate's started_at_ms is the first child's
        assert [c.call_id for c in entries[0].children] == ["c1", "c2"]

    def test_read_grep_ls_form_one_aggregate_three_children(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": "", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_grep", {"call_id": "c2", "pattern": "foo", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_ls", {"call_id": "c3", "path": "/d", "ts_ms": 3}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 1
        agg = entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert isinstance(agg.children[0], AggregateReadChild)
        assert isinstance(agg.children[1], AggregateGrepChild)
        assert isinstance(agg.children[2], AggregateLsChild)

    def test_read_bash_read_produces_three_top_level_entries(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": "", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_bash", {"call_id": "c2", "command": "ls"}, agent_id="a1"))
        r = fold(p, _e("tool_read", {"call_id": "c3", "file": "/b", "lines": "", "ts_ms": 3}, agent_id="a1"))
        entries = r.run.agents["a1"].conversation.entries
        assert len(entries) == 3
        assert isinstance(entries[0], ToolAggregateEntry)
        assert len(entries[0].children) == 1
        assert isinstance(entries[1], ToolBashEntry)
        assert isinstance(entries[2], ToolAggregateEntry)
        assert len(entries[2].children) == 1
        assert entries[2].children[0].call_id == "c3"

    def test_tool_write_appends_entry(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_write", {"call_id": "c1", "file": "/out.py"}, agent_id="a1"))
        assert isinstance(r.run.agents["a1"].conversation.entries[0], ToolWriteEntry)
        assert r.run.agents["a1"].last_tool == "write /out.py"

    def test_tool_edit_appends_entry(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_edit", {"call_id": "c1", "file": "/edit.py"}, agent_id="a1"))
        assert isinstance(r.run.agents["a1"].conversation.entries[0], ToolEditEntry)

    def test_tool_bash_appends_entry(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_bash", {"call_id": "c1", "command": "ls -la"}, agent_id="a1"))
        entry = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(entry, ToolBashEntry)
        assert entry.command == "ls -la"

    def test_tool_grep_single_event_wraps_in_aggregate(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_grep", {"call_id": "c1", "pattern": "def foo", "ts_ms": 5}, agent_id="a1"))
        agg = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert isinstance(agg.children[0], AggregateGrepChild)
        assert agg.children[0].pattern == "def foo"

    def test_tool_ls_single_event_wraps_in_aggregate(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_ls", {"call_id": "c1", "path": "/src", "ts_ms": 9}, agent_id="a1"))
        agg = r.run.agents["a1"].conversation.entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert isinstance(agg.children[0], AggregateLsChild)
        assert agg.children[0].path == "/src"

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
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_called", {"call_id": "c1", "tool": "koan_complete_step", "args": {}}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_tool_called_mcp_koan_prefix_skipped(self):
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_called", {"call_id": "c1", "tool": "mcp__koan__step", "args": {}}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries == []

    def test_tool_completed_marks_aggregate_child_done(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": "", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_read", {"call_id": "c2", "file": "/b", "lines": "", "ts_ms": 2}, agent_id="a1"))
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
        p = fold(p, _e("tool_bash", {"call_id": "c1", "command": "ls"}, agent_id="a1"))
        assert p.run.agents["a1"].conversation.entries[0].in_flight is True
        r = fold(p, _e("tool_completed", {"call_id": "c1", "tool": "bash"}, agent_id="a1"))
        assert r.run.agents["a1"].conversation.entries[0].in_flight is False

    def test_tool_completed_unknown_call_id_is_noop(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": ""}, agent_id="a1"))
        r = fold(p, _e("tool_completed", {"call_id": "missing", "tool": "read"}, agent_id="a1"))
        # Projection shape unchanged; c1 still in-flight.
        agg = r.run.agents["a1"].conversation.entries[0]
        assert agg.children[0].in_flight is True

    def test_tool_flushes_pending_fields(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("stream_delta", {"delta": "output"}, agent_id="a1"))
        r = fold(p, _e("tool_read", {"call_id": "c1", "file": "/f", "lines": ""}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        assert len(conv.entries) == 2
        assert isinstance(conv.entries[0], TextEntry)   # flushed
        assert isinstance(conv.entries[1], ToolAggregateEntry)
        assert conv.pending_text == ""

    def test_tool_events_per_agent_not_primary_only(self):
        """Every agent gets its own conversation; scout tool events go to scout."""
        p = _proj_with_run()
        p = fold(p, _e("scout_queued", {"scout_id": "s1", "label": "eng", "model": None}))
        p = fold(p, _e("agent_spawned", {"agent_id": "s1", "role": "scout", "is_primary": False, "started_at_ms": 0}, agent_id="s1"))
        r = fold(p, _e("tool_read", {"call_id": "c1", "file": "/f", "lines": ""}, agent_id="s1"))
        assert len(r.run.agents["s1"].conversation.entries) == 1
        assert isinstance(r.run.agents["s1"].conversation.entries[0], ToolAggregateEntry)

    # --- tool_result_captured -----------------------------------------------

    def test_tool_result_captured_attaches_read_metrics(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": "", "ts_ms": 1}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c1", "tool": "read",
            "metrics": {"lines_read": 42, "bytes_read": 1024},
        }, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[0]
        assert isinstance(child, AggregateReadChild)
        assert child.lines_read == 42
        assert child.bytes_read == 1024

    def test_tool_result_captured_grep_leaves_read_siblings_alone(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": "", "ts_ms": 1}, agent_id="a1"))
        p = fold(p, _e("tool_grep", {"call_id": "c2", "pattern": "x", "ts_ms": 2}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c2", "tool": "grep",
            "metrics": {"matches": 7, "files_matched": 3},
        }, agent_id="a1"))
        agg = r.run.agents["a1"].conversation.entries[0]
        read_child = agg.children[0]
        grep_child = agg.children[1]
        assert isinstance(read_child, AggregateReadChild)
        assert read_child.lines_read is None  # untouched
        assert isinstance(grep_child, AggregateGrepChild)
        assert grep_child.matches == 7
        assert grep_child.files_matched == 3

    def test_tool_result_captured_unknown_call_id_is_noop(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": ""}, agent_id="a1"))
        before = p.run.agents["a1"].conversation.entries[0]
        r = fold(p, _e("tool_result_captured", {
            "call_id": "missing", "tool": "read",
            "metrics": {"lines_read": 1},
        }, agent_id="a1"))
        # Projection shape unchanged — returns same projection reference semantics
        assert r.run.agents["a1"].conversation.entries[0] == before

    def test_tool_result_captured_no_metrics_is_noop(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": ""}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {"call_id": "c1", "tool": "read"}, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[0]
        assert child.lines_read is None
        assert child.bytes_read is None

    def test_tool_result_captured_ls_metrics(self):
        p = _proj_with_primary("a1")
        p = fold(p, _e("tool_ls", {"call_id": "c1", "path": "/d", "ts_ms": 1}, agent_id="a1"))
        r = fold(p, _e("tool_result_captured", {
            "call_id": "c1", "tool": "ls",
            "metrics": {"entries": 12, "directories": 3},
        }, agent_id="a1"))
        child = r.run.agents["a1"].conversation.entries[0].children[0]
        assert isinstance(child, AggregateLsChild)
        assert child.entries == 12
        assert child.directories == 3


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

    def test_installation_created_adds_to_dict(self):
        p = Projection()
        r = fold(p, _e("installation_created", {
            "alias": "claude-default", "runner_type": "claude",
            "binary": "/fake/bin/claude", "extra_args": [],
        }))
        assert "claude-default" in r.settings.installations
        inst = r.settings.installations["claude-default"]
        assert inst.runner_type == "claude"
        assert inst.available is False  # not yet probed

    def test_probe_completed_sets_available_flag(self):
        p = Projection()
        p = fold(p, _e("installation_created", {
            "alias": "claude-default", "runner_type": "claude",
            "binary": "/fake/bin/claude", "extra_args": [],
        }))
        r = fold(p, _e("probe_completed", {"results": {"claude-default": True}}))
        assert r.settings.installations["claude-default"].available is True

    def test_probe_completed_sets_unavailable(self):
        p = Projection()
        p = fold(p, _e("installation_created", {
            "alias": "claude-default", "runner_type": "claude",
            "binary": "/fake/bin/claude", "extra_args": [],
        }))
        r = fold(p, _e("probe_completed", {"results": {"claude-default": False}}))
        assert r.settings.installations["claude-default"].available is False

    def test_probe_completed_ignores_unknown_aliases(self):
        """probe_completed for an alias not in installations is silently ignored."""
        p = Projection()
        r = fold(p, _e("probe_completed", {"results": {"ghost": True}}))
        assert r.settings.installations == {}

    def test_installation_modified_updates(self):
        p = Projection()
        p = fold(p, _e("installation_created", {
            "alias": "my-claude", "runner_type": "claude",
            "binary": "/old/claude", "extra_args": [],
        }))
        r = fold(p, _e("installation_modified", {
            "alias": "my-claude", "runner_type": "claude",
            "binary": "/new/claude", "extra_args": ["--effort", "low"],
        }))
        assert r.settings.installations["my-claude"].binary == "/new/claude"
        assert r.settings.installations["my-claude"].extra_args == ["--effort", "low"]

    def test_installation_modified_preserves_available(self):
        """Modifying an installation keeps its probe result."""
        p = Projection()
        p = fold(p, _e("installation_created", {"alias": "c", "runner_type": "claude", "binary": "/b", "extra_args": []}))
        p = fold(p, _e("probe_completed", {"results": {"c": True}}))
        r = fold(p, _e("installation_modified", {"alias": "c", "runner_type": "claude", "binary": "/new", "extra_args": []}))
        assert r.settings.installations["c"].available is True

    def test_installation_removed(self):
        p = Projection()
        p = fold(p, _e("installation_created", {"alias": "c", "runner_type": "claude", "binary": "/b", "extra_args": []}))
        r = fold(p, _e("installation_removed", {"alias": "c"}))
        assert "c" not in r.settings.installations

    def test_profile_created(self):
        p = Projection()
        r = fold(p, _e("profile_created", {"name": "fast", "read_only": False, "tiers": {}}))
        assert "fast" in r.settings.profiles
        assert r.settings.profiles["fast"].read_only is False

    def test_profile_modified_updates(self):
        p = Projection()
        p = fold(p, _e("profile_created", {"name": "fast", "read_only": False, "tiers": {}}))
        r = fold(p, _e("profile_modified", {"name": "fast", "read_only": False, "tiers": {"scout": "haiku-default"}}))
        assert r.settings.profiles["fast"].tiers["scout"] == "haiku-default"

    def test_profile_removed(self):
        p = Projection()
        p = fold(p, _e("profile_created", {"name": "fast", "read_only": False, "tiers": {}}))
        r = fold(p, _e("profile_removed", {"name": "fast"}))
        assert "fast" not in r.settings.profiles

    def test_default_profile_changed(self):
        p = Projection()
        r = fold(p, _e("default_profile_changed", {"name": "fast"}))
        assert r.settings.default_profile == "fast"

    def test_default_scout_concurrency_changed(self):
        p = Projection()
        r = fold(p, _e("default_scout_concurrency_changed", {"value": 16}))
        assert r.settings.default_scout_concurrency == 16

    def test_settings_events_do_not_touch_run(self):
        """Settings events must not modify run state."""
        p = _proj_with_run()
        r = fold(p, _e("installation_created", {"alias": "c", "runner_type": "claude", "binary": "/b", "extra_args": []}))
        assert r.run is not None
        assert r.run.config == p.run.config


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
        p = fold(p, _e("installation_created", {"alias": "c", "runner_type": "claude", "binary": "/b", "extra_args": []}))
        r = fold(p, _e("artifact_created", {"path": "foo.md", "size": 100, "modified_at": 1000}))
        assert r.settings.installations == p.settings.installations


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

    def test_fold_exception_returns_unchanged(self, monkeypatch):
        """If fold raises internally, projection stays unchanged."""
        import koan.projections as proj_mod

        call_count = [0]
        original_fold = proj_mod.fold

        def raise_once(projection, event):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated fold failure")
            return original_fold(projection, event)

        # Test the store's exception handling
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        assert store.projection.run is not None

        monkeypatch.setattr(proj_mod, "fold", raise_once)
        store2 = proj_mod.ProjectionStore()
        prev = store2.projection
        store2.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        # fold raised — projection unchanged
        assert store2.projection == prev


# ---------------------------------------------------------------------------
# ProjectionStore
# ---------------------------------------------------------------------------

class TestProjectionStore:

    def test_push_increments_version(self):
        store = ProjectionStore()
        assert store.version == 0
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        assert store.version == 1

    def test_fold_applied(self):
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
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
        # Nested camelCase
        settings = state["settings"]
        assert "defaultProfile" in settings       # not default_profile
        assert "defaultScoutConcurrency" in settings  # not default_scout_concurrency

    def test_get_snapshot_includes_version(self):
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        snap = store.get_snapshot()
        assert snap["version"] == 1

    def test_subscriber_receives_dict_not_event(self):
        """Subscribers get plain dicts (SSE-ready), not VersionedEvent objects."""
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        msg = q.get_nowait()
        assert isinstance(msg, dict)
        assert msg["type"] == "patch"
        assert "version" in msg
        assert "patch" in msg

    @pytest.mark.anyio
    async def test_subscriber_receives_patch(self):
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
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
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        assert q.empty()

    def test_no_patch_broadcast_when_no_state_change(self):
        """koan_ tools produce no state change; no patch broadcast."""
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        store.push_event("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True,
            "started_at_ms": 0, "label": "", "model": None,
        }, agent_id="a1")
        q = store.subscribe()
        # koan MCP tool is filtered — no state change → no patch broadcast
        store.push_event("tool_called", {
            "call_id": "c1", "tool": "koan_complete_step", "args": {},
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
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        msg = q.get_nowait()
        ops = msg["patch"]
        paths = [op["path"] for op in ops]
        assert any("/run" in p for p in paths)

    def test_patch_has_camelcase_settings_path(self):
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("installation_created", {
            "alias": "claude-default", "runner_type": "claude",
            "binary": "/fake/bin/claude", "extra_args": [],
        })
        msg = q.get_nowait()
        ops = msg["patch"]
        paths = [op["path"] for op in ops]
        # Should contain /settings/installations/claude-default
        assert any("/settings/installations/claude-default" in p for p in paths)

    def test_patch_has_camelcase_agent_fields(self):
        """Agent fields use camelCase in patch paths: lastTool, stepName, etc."""
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        store.push_event("agent_spawned", {
            "agent_id": "a1", "role": "intake", "is_primary": True,
            "started_at_ms": 0, "label": "", "model": None,
        }, agent_id="a1")
        store.push_event("agent_step_advanced", {"step": 1, "step_name": "Scout"}, agent_id="a1")
        q = store.subscribe()
        store.push_event("tool_read", {"call_id": "c1", "file": "/f.py", "lines": ""}, agent_id="a1")
        msg = q.get_nowait()
        ops = msg["patch"]
        # Check some paths contain camelCase
        all_paths = " ".join(op["path"] for op in ops)
        # lastTool should be camelCase
        assert "lastTool" in all_paths or "conversation" in all_paths

    def test_patch_pending_thinking_camelcase_path(self):
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
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

    def test_patch_default_profile_camelcase(self):
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("default_profile_changed", {"name": "fast"})
        msg = q.get_nowait()
        ops = msg["patch"]
        all_paths = " ".join(op["path"] for op in ops)
        assert "defaultProfile" in all_paths


# ---------------------------------------------------------------------------
# Snapshot round-trip
# ---------------------------------------------------------------------------

class TestSnapshotRoundTrip:

    def test_snapshot_state_is_camelcase(self):
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
        state = store.get_snapshot()["state"]
        run = state["run"]
        assert "config" in run
        assert "scoutConcurrency" in run["config"]   # not scout_concurrency
        assert "agents" in run
        assert "isPrimary" not in run  # no agents yet

    def test_snapshot_agent_camelcase(self):
        store = ProjectionStore()
        store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
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

    def test_snapshot_settings_camelcase(self):
        store = ProjectionStore()
        store.push_event("installation_created", {
            "alias": "claude-default", "runner_type": "claude",
            "binary": "/fake/bin/claude", "extra_args": [],
        })
        state = store.get_snapshot()["state"]
        inst = state["settings"]["installations"]["claude-default"]
        assert "runnerType" in inst         # not runner_type
        assert "extraArgs" in inst          # not extra_args


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
# Tool name normalization (runner integration — unchanged)
# ---------------------------------------------------------------------------

class TestToolNameNormalization:

    def test_claude_normalizes_Read(self):
        import json
        from koan.runners.claude import ClaudeRunner
        runner = ClaudeRunner(subagent_dir="/tmp/test")
        line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/f"}}]},
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
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]},
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
            "message": {"content": [{"type": "tool_use", "name": "koan_complete_step", "input": {}}]},
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
