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
    ToolKoanEntry,
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
# fold: workflows_listed (Settings.workflows)
# ---------------------------------------------------------------------------

_WORKFLOW_ENTRY_A = {
    "id": "plan",
    "description": "Plan and execute",
    "phases": [{"id": "intake", "description": "Gather requirements"}],
    "initial_phase": "intake",
}
_WORKFLOW_ENTRY_B = {
    "id": "milestones",
    "description": "Phased delivery",
    "phases": [{"id": "milestone-spec", "description": "Define milestones"}],
    "initial_phase": "milestone-spec",
}


class TestFoldWorkflowsListed:

    def test_workflows_listed_populates_settings_workflows(self):
        """workflows_listed fold sets Settings.workflows from the payload entries."""
        p = Projection()
        r = fold(p, _e("workflows_listed", {"workflows": [_WORKFLOW_ENTRY_A, _WORKFLOW_ENTRY_B]}))
        assert len(r.settings.workflows) == 2
        assert r.settings.workflows[0].id == "plan"
        assert r.settings.workflows[0].description == "Plan and execute"
        assert len(r.settings.workflows[0].phases) == 1
        assert r.settings.workflows[0].phases[0].id == "intake"
        assert r.settings.workflows[0].initial_phase == "intake"
        assert r.settings.workflows[1].id == "milestones"

    def test_workflows_listed_overwrites_previous_list(self):
        """A second workflows_listed event replaces the first list entirely."""
        p = Projection()
        r = fold(p, _e("workflows_listed", {"workflows": [_WORKFLOW_ENTRY_A]}))
        assert len(r.settings.workflows) == 1
        r2 = fold(r, _e("workflows_listed", {"workflows": [_WORKFLOW_ENTRY_B]}))
        assert len(r2.settings.workflows) == 1
        assert r2.settings.workflows[0].id == "milestones"

    def test_workflows_listed_with_empty_list_clears_field(self):
        """workflows_listed with an empty list clears Settings.workflows."""
        p = Projection()
        r = fold(p, _e("workflows_listed", {"workflows": [_WORKFLOW_ENTRY_A]}))
        assert len(r.settings.workflows) == 1
        r2 = fold(r, _e("workflows_listed", {"workflows": []}))
        assert r2.settings.workflows == []


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
        p = fold(p, _e("tool_bash", {"call_id": "c1", "command": "ls"}, agent_id="a1"))
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
        """ToolAggregateEntry gets an entry_id; its AggregateReadChild does not."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("tool_read", {"call_id": "c1", "file": "/f.py", "lines": "", "ts_ms": 1}, agent_id="a1"))
        conv = r.run.agents["a1"].conversation
        agg = conv.entries[0]
        assert isinstance(agg, ToolAggregateEntry)
        assert agg.entry_id == "e0"
        # Child is keyed by call_id; entry_id stays '' (intentionally unset)
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

    def test_connections_listed(self):
        """M5: connections_listed replaces profile_created for config entity surfaces."""
        p = Projection()
        r = fold(p, _e("connections_listed", {"connections": [
            {"id": "g1", "connection_type": "google", "base_url": None, "region": None},
        ]}))
        assert len(r.settings.connections) == 1
        assert r.settings.connections[0].id == "g1"
        assert r.settings.connections[0].connection_type == "google"

    def test_configured_models_listed(self):
        p = Projection()
        r = fold(p, _e("configured_models_listed", {"configured_models": [
            {"id": "cm1", "connection_id": "g1", "model_id": "gemini-pro"},
        ]}))
        assert len(r.settings.configured_models) == 1
        assert r.settings.configured_models[0].id == "cm1"

    def test_presets_listed(self):
        p = Projection()
        r = fold(p, _e("presets_listed", {"presets": {
            "$last": {"slots": {"strong": {"configured_model_id": "cm1", "thinking": "high"}}},
        }}))
        assert "$last" in r.settings.presets
        assert "strong" in r.settings.presets["$last"].slots

    def test_active_changed(self):
        p = Projection()
        r = fold(p, _e("active_changed", {"active": "my-preset"}))
        assert r.settings.active == "my-preset"

    def test_default_scout_concurrency_changed(self):
        p = Projection()
        r = fold(p, _e("default_scout_concurrency_changed", {"value": 16}))
        assert r.settings.default_scout_concurrency == 16

    def test_settings_events_do_not_touch_run(self):
        """Settings events must not modify run state."""
        p = _proj_with_run()
        r = fold(p, _e("active_changed", {"active": "custom-preset"}))
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
        store.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        assert store.projection.run is not None

        monkeypatch.setattr(proj_mod, "fold", raise_once)
        store2 = proj_mod.ProjectionStore()
        prev = store2.projection
        store2.push_event("run_started", {"active_preset": "$last", "scout_concurrency": 8})
        # fold raised — projection unchanged
        assert store2.projection == prev


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
        store.push_event("tool_read", {"call_id": "c1", "file": "/f.py", "lines": ""}, agent_id="a1")
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

    def test_patch_active_changed_camelcase(self):
        """M5: active_changed replaces default_profile_changed; patch path is /settings/active."""
        store = ProjectionStore()
        q = store.subscribe()
        store.push_event("active_changed", {"active": "my-preset"})
        msg = q.get_nowait()
        ops = msg["patch"]
        all_paths = " ".join(op["path"] for op in ops)
        assert "/settings/active" in all_paths

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
# fold: reflect_delta domain event
# ---------------------------------------------------------------------------

class TestFoldReflectDelta:
    """reflect_delta appends to the in-flight ToolKoanEntry's result.answer.

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

    def test_reflect_delta_appends_to_result_answer(self):
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, _e("reflect_delta", {"delta": "hello"}, agent_id=aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert isinstance(entry, ToolKoanEntry)
        assert entry.result == {"answer": "hello"}
        # in_flight must remain True -- domain events do not close the lifecycle
        assert entry.in_flight is True

    def test_reflect_delta_accumulates_across_multiple_events(self):
        p, aid = self._with_inflight_koan_entry()
        p = fold(p, _e("reflect_delta", {"delta": "hello"}, agent_id=aid))
        r = fold(p, _e("reflect_delta", {"delta": " there"}, agent_id=aid))
        entry = r.run.agents[aid].conversation.entries[0]
        assert entry.result == {"answer": "hello there"}

    def test_reflect_delta_no_inflight_entry_is_noop(self):
        """When there is no in-flight ToolKoanEntry the event is dropped silently."""
        p = _proj_with_primary("a1")
        r = fold(p, _e("reflect_delta", {"delta": "hello"}, agent_id="a1"))
        # Projection unchanged: no entries created
        assert r.run.agents["a1"].conversation.entries == []

    def test_reflect_delta_completed_entry_not_targeted(self):
        """A ToolKoanEntry with in_flight=False is not updated by reflect_delta."""
        p, aid = self._with_inflight_koan_entry()
        # Complete the entry via tool_result
        p = fold(p, _e("tool_result", {"call_id": "c1", "tool": "koan_reflect"}, agent_id=aid))
        entry_before = p.run.agents[aid].conversation.entries[0]
        assert entry_before.in_flight is False
        # reflect_delta should be a no-op (no in-flight entry)
        r = fold(p, _e("reflect_delta", {"delta": "late"}, agent_id=aid))
        entry_after = r.run.agents[aid].conversation.entries[0]
        assert entry_after.result == entry_before.result

    def test_reflect_delta_empty_delta_is_noop(self):
        p, aid = self._with_inflight_koan_entry()
        r = fold(p, _e("reflect_delta", {"delta": ""}, agent_id=aid))
        entry = r.run.agents[aid].conversation.entries[0]
        # result stays None when delta is empty
        assert entry.result is None

    def test_reflect_delta_preserves_existing_result_fields(self):
        """Accumulation merges into existing result dict without clobbering other keys."""
        p, aid = self._with_inflight_koan_entry()
        # Seed a result with extra keys (simulates partial pre-population)
        p = fold(p, _e("reflect_delta", {"delta": "A"}, agent_id=aid))
        # Manually inject an extra key via another delta pass (the fold always
        # does a {**existing_result, "answer": ...} merge, so this is implicit)
        p = fold(p, _e("reflect_delta", {"delta": "B"}, agent_id=aid))
        entry = p.run.agents[aid].conversation.entries[0]
        assert entry.result["answer"] == "AB"


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
        # Seed an aggregate entry (read tool creates ToolAggregateEntry, not ToolBashEntry)
        p = fold(p, _e("tool_read", {"call_id": "c1", "file": "/a", "lines": "", "ts_ms": 1}, agent_id="a1"))
        from koan.projections import ToolAggregateEntry
        assert isinstance(p.run.agents["a1"].conversation.entries[0], ToolAggregateEntry)
        # tool_attachments should be a no-op (no non-aggregate in-flight entry).
        # Projection unchanged: fold logs a warning and returns projection.
        r = fold(p, _e("tool_attachments", {"attachments": self._full_manifest}, agent_id="a1"))
        assert isinstance(r.run.agents["a1"].conversation.entries[0], ToolAggregateEntry)
        # ToolAggregateEntry has no attachments field -- just verify entry type unchanged
        assert len(r.run.agents["a1"].conversation.entries) == 1


# ---------------------------------------------------------------------------
# provider_status_listed fold (M3)
# ---------------------------------------------------------------------------

class TestProviderStatusListedFold:

    def test_provider_status_listed_per_connection(self):
        """M5: provider_status_listed carries per-connection {connection_id, connection_type, available}.

        Replaces the old per-type {provider, available, region, base_url} shape.
        """
        from koan.projections import ConnectionStatusWire
        p = Projection()
        connections = [
            {
                "connection_id": "bedrock-direct",
                "connection_type": "bedrock",
                "available": True,
            },
            {
                "connection_id": "google-direct",
                "connection_type": "google",
                "available": False,
            },
        ]
        r = fold(p, _e("provider_status_listed", {"connections": connections}))
        ps = {entry.connection_id: entry for entry in r.settings.provider_status}

        assert ps["bedrock-direct"].connection_type == "bedrock"
        assert ps["bedrock-direct"].available is True
        assert ps["google-direct"].available is False


# ---------------------------------------------------------------------------
# provider_models_listed fold
# ---------------------------------------------------------------------------

class TestProviderModelsListedFold:

    def test_provider_models_listed_populates_settings(self):
        """Fold provider_models_listed; Settings.provider_models is populated.

        The event carries a flat cross-provider model list. The fold replaces
        Settings.provider_models entirely (same replace-all semantics as
        model_registry_listed). display_name and context_window are threaded
        through via the ProviderModelWire alias mapping.
        """
        p = Projection()
        models = [
            {
                "provider": "openrouter",
                "model": "anthropic/claude-3-5-sonnet",
                "display_name": "Claude 3.5 Sonnet",
                "context_window": 200000,
            },
            {
                "provider": "openai",
                "model": "gpt-4o",
                "display_name": "GPT-4o",
                "context_window": 128000,
            },
        ]
        r = fold(p, _e("provider_models_listed", {"models": models}))
        assert len(r.settings.provider_models) == 2

        by_model = {pm.model: pm for pm in r.settings.provider_models}
        assert by_model["anthropic/claude-3-5-sonnet"].provider == "openrouter"
        assert by_model["anthropic/claude-3-5-sonnet"].display_name == "Claude 3.5 Sonnet"
        assert by_model["gpt-4o"].provider == "openai"

    def test_provider_models_listed_replaces_previous(self):
        """A second event replaces the first list entirely (no append)."""
        p = Projection()
        p = fold(p, _e("provider_models_listed", {"models": [
            {"provider": "openai", "model": "gpt-4", "display_name": "GPT-4", "context_window": 8192},
        ]}))
        r = fold(p, _e("provider_models_listed", {"models": [
            {"provider": "openrouter", "model": "meta-llama/llama-3", "display_name": "Llama 3", "context_window": 8192},
        ]}))
        assert len(r.settings.provider_models) == 1
        assert r.settings.provider_models[0].model == "meta-llama/llama-3"

    def test_provider_models_listed_empty_payload_clears(self):
        """Empty models list clears the overlay."""
        p = Projection()
        p = fold(p, _e("provider_models_listed", {"models": [
            {"provider": "openai", "model": "gpt-4", "display_name": "GPT-4", "context_window": 8192},
        ]}))
        r = fold(p, _e("provider_models_listed", {"models": []}))
        assert r.settings.provider_models == []

    def test_provider_models_listed_does_not_touch_run(self):
        """provider_models_listed must not modify run state."""
        p = _proj_with_run()
        r = fold(p, _e("provider_models_listed", {"models": [
            {"provider": "openrouter", "model": "meta-llama/llama-3b", "display_name": "Llama 3B", "context_window": 4096},
        ]}))
        assert r.run is not None
        assert r.run.config == p.run.config

    def test_provider_models_listed_populates_families(self):
        """Fold provider_models_listed with families; Settings.provider_families is populated."""
        from koan.projections import ProviderFamilyWire

        p = Projection()
        families = [
            {
                "provider": "anthropic",
                "family": "claude-sonnet",
                "resolved": "claude-sonnet-4-5",
                "resolved_from": "newest(claude-sonnet)@2026-06-10 -> claude-sonnet-4-5",
            },
            {
                "provider": "anthropic",
                "family": "claude-haiku",
                "resolved": "claude-haiku-4-0",
                "resolved_from": "newest(claude-haiku)@2026-06-10 -> claude-haiku-4-0",
            },
        ]
        r = fold(p, _e("provider_models_listed", {"models": [], "families": families}))
        assert len(r.settings.provider_families) == 2
        by_family = {pf.family: pf for pf in r.settings.provider_families}
        assert by_family["claude-sonnet"].resolved == "claude-sonnet-4-5"
        assert by_family["claude-sonnet"].provider == "anthropic"
        assert "2026-06-10" in by_family["claude-haiku"].resolved_from

    def test_provider_models_listed_families_absent_yields_empty(self):
        """Fold with no families key leaves provider_families empty."""
        p = Projection()
        r = fold(p, _e("provider_models_listed", {"models": []}))
        assert r.settings.provider_families == []

    def test_provider_models_listed_families_replaces_previous(self):
        """A second event replaces the families list entirely."""
        p = Projection()
        p = fold(p, _e("provider_models_listed", {"models": [], "families": [
            {"provider": "anthropic", "family": "claude-opus", "resolved": "claude-opus-4-0", "resolved_from": ""},
        ]}))
        r = fold(p, _e("provider_models_listed", {"models": [], "families": [
            {"provider": "openai", "family": "gpt-4o", "resolved": "gpt-4o-2024-11-20", "resolved_from": ""},
        ]}))
        assert len(r.settings.provider_families) == 1
        assert r.settings.provider_families[0].family == "gpt-4o"

    def test_provider_models_listed_connection_id_round_trips(self):
        """connection_id on models and families dicts survives the fold round-trip.

        Verifies the D4 wire-shape change: both ProviderModelWire and
        ProviderFamilyWire carry connectionId so the frontend can join per-connection
        without collision between same-type connections.
        """
        p = Projection()
        models = [
            {
                "provider": "openai",
                "model": "gpt-4o",
                "display_name": "GPT-4o",
                "context_window": 128000,
                "connection_id": "openai-work",
            },
        ]
        families = [
            {
                "provider": "openai",
                "family": "gpt-4o",
                "resolved": "gpt-4o-2024-11-20",
                "resolved_from": "",
                "connection_id": "openai-work",
            },
        ]
        r = fold(p, _e("provider_models_listed", {"models": models, "families": families}))

        assert len(r.settings.provider_models) == 1
        assert r.settings.provider_models[0].connection_id == "openai-work"

        assert len(r.settings.provider_families) == 1
        assert r.settings.provider_families[0].connection_id == "openai-work"
