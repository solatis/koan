"""End-to-end streaming test for tool aggregation.

Covers the pipeline from raw Claude CLI stream-json JSONL lines through
ClaudeRunner.parse_stream_event, the subagent's streaming event-handling
branches, and the projection fold. Regression guard for the bug where
exploration tools (read/grep/ls) were emitted as ToolGenericEntry because
the streaming path routed them through tool_started/tool_stopped instead
of the typed tool_read/tool_grep/tool_ls events.
"""
from __future__ import annotations

import json
import uuid

from koan.events import (
    build_tool_completed,
    build_tool_grep,
    build_tool_ls,
    build_tool_read,
    build_tool_result_captured,
    build_tool_started,
    build_tool_stopped,
)
from koan.projections import (
    AggregateReadChild,
    ProjectionStore,
    ToolAggregateEntry,
    VersionedEvent,
    fold,
)
from koan.runners.base import StreamEvent
from koan.runners.claude import ClaudeRunner


# ---------------------------------------------------------------------------
# Streaming event-handling harness — replicates the relevant branches of
# stream_stdout()'s loop. This intentionally mirrors the production code so
# the test would have caught the original bug; if the subagent ever grows
# extra streaming logic for these tools, this harness must grow with it.
# ---------------------------------------------------------------------------

class _StreamingHarness:
    def __init__(self, store: ProjectionStore, agent_id: str) -> None:
        self.store = store
        self.agent_id = agent_id
        self.streaming_call_ids: dict[int, tuple[str, str]] = {}
        self.call_id_by_tool_use_id: dict[str, str] = {}
        # Deterministic call_id generator so assertions are stable.
        self._next_id = 0

    def _new_call_id(self) -> str:
        self._next_id += 1
        return f"call-{self._next_id}"

    def dispatch(self, ev: StreamEvent, now_ms: int = 1000) -> None:
        if ev.type == "tool_start":
            call_id = self._new_call_id()
            tool_name = ev.tool_name or "tool"
            block_idx = ev.block_index if ev.block_index is not None else -1
            self.streaming_call_ids[block_idx] = (call_id, tool_name)
            if tool_name in ("read", "grep", "ls"):
                if ev.tool_use_id:
                    self.call_id_by_tool_use_id[ev.tool_use_id] = call_id
            else:
                self.store.push_event(
                    "tool_started",
                    build_tool_started(call_id, tool_name),
                    agent_id=self.agent_id,
                )
        elif ev.type == "tool_stop":
            block_idx = ev.block_index if ev.block_index is not None else -1
            pair = self.streaming_call_ids.pop(block_idx, None)
            if pair is None:
                return
            call_id, tool_name = pair
            summary = ev.summary or ""
            if tool_name in ("read", "grep", "ls"):
                if tool_name == "read":
                    file_part, lines_part = summary, ""
                    if ":" in summary:
                        head, tail = summary.rsplit(":", 1)
                        if tail and (tail[0].isdigit() or "-" in tail):
                            file_part, lines_part = head, tail
                    self.store.push_event(
                        "tool_read",
                        build_tool_read(call_id, file_part, lines_part, ts_ms=now_ms),
                        agent_id=self.agent_id,
                    )
                elif tool_name == "grep":
                    self.store.push_event(
                        "tool_grep",
                        build_tool_grep(call_id, summary, ts_ms=now_ms),
                        agent_id=self.agent_id,
                    )
                else:  # ls
                    self.store.push_event(
                        "tool_ls",
                        build_tool_ls(call_id, summary, ts_ms=now_ms),
                        agent_id=self.agent_id,
                    )
                self.store.push_event(
                    "tool_completed",
                    build_tool_completed(call_id, tool_name, ts_ms=now_ms),
                    agent_id=self.agent_id,
                )
            else:
                self.store.push_event(
                    "tool_stopped",
                    build_tool_stopped(call_id, tool_name, summary),
                    agent_id=self.agent_id,
                )
        elif ev.type == "tool_result":
            tool_use_id = ev.tool_use_id or ""
            cid = self.call_id_by_tool_use_id.get(tool_use_id)
            if cid is not None:
                self.store.push_event(
                    "tool_result_captured",
                    build_tool_result_captured(cid, ev.tool_name or "", metrics=ev.metrics),
                    agent_id=self.agent_id,
                )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _wrap_stream_event(inner: dict) -> str:
    return json.dumps({"type": "stream_event", "event": inner})


def _read_block_lines(block_idx: int, tool_use_id: str, file_path: str) -> list[str]:
    """Produce the raw JSONL lines for one streaming Read tool use."""
    return [
        _wrap_stream_event({
            "type": "content_block_start",
            "index": block_idx,
            "content_block": {
                "type": "tool_use",
                "id": tool_use_id,
                "name": "Read",
                "input": {},
            },
        }),
        _wrap_stream_event({
            "type": "content_block_delta",
            "index": block_idx,
            "delta": {
                "type": "input_json_delta",
                "partial_json": json.dumps({"file_path": file_path}),
            },
        }),
        _wrap_stream_event({
            "type": "content_block_stop",
            "index": block_idx,
        }),
    ]


def _user_tool_result(tool_use_id: str, content: str) -> str:
    return json.dumps({
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                }
            ]
        },
    })


def _seed_store() -> tuple[ProjectionStore, str]:
    store = ProjectionStore()
    agent_id = "a1"
    store.push_event("run_started", {
        "profile": "balanced",
        "installations": {},
        "scout_concurrency": 8,
    })
    store.push_event(
        "agent_spawned",
        {
            "agent_id": agent_id,
            "role": "intake",
            "label": "",
            "model": "opus",
            "is_primary": True,
            "started_at_ms": 1,
        },
        agent_id=agent_id,
    )
    return store, agent_id


# ---------------------------------------------------------------------------
# The actual tests
# ---------------------------------------------------------------------------

def test_two_streaming_reads_form_one_aggregate_with_two_children():
    """Regression guard: consecutive streaming reads must aggregate.

    Before the fix, the subagent routed every tool_start/tool_stop through
    tool_started/tool_stopped → ToolGenericEntry, so two reads landed as two
    separate generic entries with no aggregate wrapper. The fix routes
    exploration tools through the typed tool_read/tool_grep/tool_ls +
    tool_completed events so the aggregate fold creates a ToolAggregateEntry
    whose children are AggregateReadChild instances.
    """
    store, agent_id = _seed_store()
    runner = ClaudeRunner(subagent_dir="/tmp/does-not-matter")
    harness = _StreamingHarness(store, agent_id)

    raw_lines: list[str] = []
    raw_lines.extend(_read_block_lines(block_idx=1, tool_use_id="toolu_1", file_path="/repo/a.py"))
    raw_lines.extend(_read_block_lines(block_idx=2, tool_use_id="toolu_2", file_path="/repo/b.py"))

    for i, line in enumerate(raw_lines):
        for ev in runner.parse_stream_event(line):
            harness.dispatch(ev, now_ms=100 + i)

    entries = store.projection.run.agents[agent_id].conversation.entries
    assert len(entries) == 1, f"expected exactly one top-level entry, got {[e.type for e in entries]}"
    agg = entries[0]
    assert isinstance(agg, ToolAggregateEntry)
    assert len(agg.children) == 2
    assert all(isinstance(c, AggregateReadChild) for c in agg.children)
    # Both children completed — the streaming path fires tool_completed
    # immediately after the typed tool_read event.
    assert all(c.in_flight is False for c in agg.children)
    assert all(c.completed_at_ms is not None for c in agg.children)
    # Paths preserved through the full pipeline.
    paths = [c.file for c in agg.children if isinstance(c, AggregateReadChild)]
    assert paths == ["/repo/a.py", "/repo/b.py"]
    # tool_use_id mapping populated for both — verifies the streaming path's
    # tool_result_captured correlation is wired.
    assert set(harness.call_id_by_tool_use_id.keys()) == {"toolu_1", "toolu_2"}


def test_streaming_read_then_tool_result_attaches_metrics():
    """After a streaming read, a matching tool_result user message must populate
    the aggregate child's lines_read and bytes_read metrics.

    This exercises the tool_use_id → call_id mapping captured at tool_start
    in the streaming path; if that wiring is missing, tool_result_captured
    would be emitted with the wrong call_id (or not at all) and the child's
    metric fields would stay None.
    """
    store, agent_id = _seed_store()
    runner = ClaudeRunner(subagent_dir="/tmp/does-not-matter")
    harness = _StreamingHarness(store, agent_id)

    # 1. Stream the Read tool_use block.
    for line in _read_block_lines(block_idx=1, tool_use_id="toolu_abc", file_path="/r/x.py"):
        for ev in runner.parse_stream_event(line):
            harness.dispatch(ev, now_ms=200)

    # 2. Deliver a matching tool_result in the user message.
    result_body = "     1\talpha\n     2\tbeta\n     3\tgamma\n"
    user_line = _user_tool_result("toolu_abc", result_body)
    for ev in runner.parse_stream_event(user_line):
        harness.dispatch(ev, now_ms=300)

    entries = store.projection.run.agents[agent_id].conversation.entries
    assert len(entries) == 1
    agg = entries[0]
    assert isinstance(agg, ToolAggregateEntry)
    assert len(agg.children) == 1
    child = agg.children[0]
    assert isinstance(child, AggregateReadChild)
    assert child.file == "/r/x.py"
    assert child.in_flight is False
    assert child.lines_read == 3
    # The numbered-line payload has three rows of pure lowercase ASCII.
    assert child.bytes_read == len(b"alphabetagamma")
