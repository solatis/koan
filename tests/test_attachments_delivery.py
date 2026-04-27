# End-to-end attachment delivery tests for M3.
#
# Three scenarios:
#   1. File attached to a chat message reaches koan_yield as an EmbeddedResource
#      block adjacent to the USER MESSAGE text block; tool_completed event carries
#      the attachment manifest.
#   2. Non-Claude runner_type collapses file blocks to a single TextContent notice;
#      manifest is still populated.
#   3. Per-decision attachments on /api/memory/curation reach koan_memory_propose
#      as File blocks in the correct order.

from __future__ import annotations

import asyncio
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from koan.state import AgentState, AppState, UploadState
from koan.phases import PhaseContext
from koan.web.app import create_app
from koan.web.mcp_endpoint import build_mcp_server


# -- Shared helpers ------------------------------------------------------------

def _make_agent(app_state: AppState, tmp_path: Path, runner_type: str = "claude") -> AgentState:
    agent = AgentState(
        agent_id="test-attach-agent",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir=str(tmp_path),
        step=2,
        is_primary=True,
        runner_type=runner_type,
        event_log=AsyncMock(),
        phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
    )
    app_state.agents[agent.agent_id] = agent
    return agent


class FakeContext:
    def __init__(self, agent: AgentState):
        self._agent = agent

    async def get_state(self, key):
        if key == "agent":
            return self._agent
        return None


# -- Scenario 1: Claude runner receives EmbeddedResource block for text file ----

@pytest.mark.anyio
async def test_chat_attachment_reaches_koan_yield_as_embedded_resource(tmp_path):
    """Upload a file, attach it to a chat message, and assert koan_yield returns
    an EmbeddedResource block immediately after the USER MESSAGE text block.
    The tool_completed event must carry the attachment manifest.
    """
    from mcp.types import EmbeddedResource, TextContent
    from koan.web.uploads import init_upload_state

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "intake"
    init_upload_state(app_state.uploads)

    agent = _make_agent(app_state, tmp_path, runner_type="claude")
    _, handlers = build_mcp_server(app_state)

    # Upload a small text file via the upload registry.
    from koan.web.uploads import register_upload, commit_to_run

    class FakeFile:
        filename = "note.txt"
        content_type = "text/plain"
        file = io.BytesIO(b"hello from note")

    record = await register_upload(app_state.uploads, FakeFile())
    uid = record.id

    # Commit the file to run_dir (simulates what api_chat does).
    commit_to_run(app_state.uploads, [uid], tmp_path)

    # Buffer a chat message with the attachment id.
    import time
    from koan.state import ChatMessage
    msg = ChatMessage(
        content="check this file",
        timestamp_ms=int(time.time() * 1000),
        attachments=[uid],
    )
    app_state.interactions.user_message_buffer.append(msg)

    # Resolve the yield future immediately so koan_yield doesn't block.
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    app_state.interactions.yield_future = fut
    # The handler drains user_message_buffer on resolve; we trigger by resolving
    # in the same event loop tick AFTER the handler starts blocking.
    # Strategy: run koan_yield concurrently and resolve the future once it blocks.

    # Actually with pre-buffered messages koan_yield drains immediately without
    # setting yield_future. Messages are already in user_message_buffer.
    result = await handlers.koan_yield(FakeContext(agent), suggestions=None)

    # First block: the USER MESSAGE text block
    assert isinstance(result[0], TextContent)
    assert "USER MESSAGE" in result[0].text
    assert "check this file" in result[0].text

    # Second block: EmbeddedResource for note.txt
    assert isinstance(result[1], EmbeddedResource)

    # M3: verify tool_attachments projection event carries full koan-side fields.
    events = app_state.projection_store.events
    attach_events = [e for e in events if e.event_type == "tool_attachments"]
    assert len(attach_events) >= 1, "expected at least one tool_attachments event"
    manifest = attach_events[-1].payload.get("attachments", [])
    assert len(manifest) == 1
    att = manifest[0]
    assert att["upload_id"] == uid
    assert att["filename"] == "note.txt"
    assert att["path"] != ""  # koan-side path populated


# -- Scenario 2: Non-Claude runner collapses blocks to text notice -------------

@pytest.mark.anyio
async def test_non_claude_runner_gets_text_notice_not_file_block(tmp_path):
    """Same upload flow with runner_type='codex' should produce a single
    TextContent notice block, not an EmbeddedResource. Manifest still populated.
    """
    from mcp.types import EmbeddedResource, TextContent
    from koan.web.uploads import init_upload_state, register_upload, commit_to_run

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "intake"
    init_upload_state(app_state.uploads)

    agent = _make_agent(app_state, tmp_path, runner_type="codex")
    _, handlers = build_mcp_server(app_state)

    class FakeFile:
        filename = "data.csv"
        content_type = "text/csv"
        file = io.BytesIO(b"a,b,c")

    record = await register_upload(app_state.uploads, FakeFile())
    commit_to_run(app_state.uploads, [record.id], tmp_path)

    import time
    from koan.state import ChatMessage
    msg = ChatMessage(
        content="see attached",
        timestamp_ms=int(time.time() * 1000),
        attachments=[record.id],
    )
    app_state.interactions.user_message_buffer.append(msg)

    result = await handlers.koan_yield(FakeContext(agent), suggestions=None)

    # First block: the USER MESSAGE text block
    assert isinstance(result[0], TextContent)
    assert "USER MESSAGE" in result[0].text

    # Second block: the text notice (NOT an EmbeddedResource)
    assert isinstance(result[1], TextContent)
    assert "attachment(s) omitted" in result[1].text
    assert "data.csv" in result[1].text
    assert not any(isinstance(b, EmbeddedResource) for b in result)

    # M3: even for non-Claude runners the tool_attachments event must fire with
    # full koan-side fields (manifest is always populated regardless of runner).
    events = app_state.projection_store.events
    attach_events = [e for e in events if e.event_type == "tool_attachments"]
    assert len(attach_events) >= 1
    manifest = attach_events[-1].payload.get("attachments", [])
    assert len(manifest) == 1
    assert manifest[0]["upload_id"] == record.id
    assert manifest[0]["filename"] == "data.csv"
    assert manifest[0]["path"] != ""


# -- Scenario 3: Per-decision attachments in koan_memory_propose ---------------

@pytest.mark.anyio
async def test_memory_curation_per_decision_attachments(tmp_path):
    """POST /api/memory/curation with per-decision attachments; koan_memory_propose
    emits per-decision File blocks in order after the JSON blob.
    """
    from mcp.types import EmbeddedResource, TextContent
    from koan.web.uploads import init_upload_state, register_upload, commit_to_run
    from koan.projections import ActiveCurationBatch, Proposal
    from koan.web.app import create_app
    from starlette.testclient import TestClient

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "curation"
    init_upload_state(app_state.uploads)

    agent = _make_agent(app_state, tmp_path, runner_type="claude")
    _, handlers = build_mcp_server(app_state)

    # Upload a file and commit it (simulating api_memory_curation_submit).
    class FakeFile:
        filename = "evidence.md"
        content_type = "text/plain"
        file = io.BytesIO(b"# Evidence")

    record = await register_upload(app_state.uploads, FakeFile())
    commit_to_run(app_state.uploads, [record.id], tmp_path)

    # Build a curation batch with one proposal and push projection events.
    proposal = Proposal(
        id="p1", op="add", seq="", type="context",
        title="Test entry", body="Some body", rationale="test",
    )
    batch = ActiveCurationBatch(
        proposals=[proposal], batch_id="batch-test-1", context_note="",
    )
    from koan.events import build_memory_curation_started
    app_state.projection_store.push_event(
        "memory_curation_started",
        build_memory_curation_started(batch.to_wire()),
        agent_id=agent.agent_id,
    )

    # Schedule koan_memory_propose concurrently; it will block on the future.
    propose_task = asyncio.create_task(
        handlers.koan_memory_propose(FakeContext(agent), proposals=[proposal.model_dump()])
    )

    # Give the task time to reach the await point.
    await asyncio.sleep(0.01)

    # Resolve via direct future manipulation (mirrors what api_memory_curation_submit does).
    future = app_state.interactions.memory_propose_future
    assert future is not None

    decisions = [
        {
            "proposal_id": "p1",
            "decision": "approved",
            "feedback": "",
            "attachments": [record.id],
        }
    ]
    future.set_result(decisions)

    result = await asyncio.wait_for(propose_task, timeout=2.0)

    # Block 0: the JSON blob (json.loads(result[0].text) must work)
    assert isinstance(result[0], TextContent)
    parsed = json.loads(result[0].text)
    # batch_id is generated by the handler; just verify it's a non-empty string
    assert isinstance(parsed.get("batch_id"), str) and parsed["batch_id"]

    # Block 1: the label separator
    assert isinstance(result[1], TextContent)
    assert "Attachments for proposal p1" in result[1].text

    # Block 2: the EmbeddedResource for evidence.md
    assert isinstance(result[2], EmbeddedResource)


# -- Scenario 4: start-run attachment delivered on first koan_complete_step ----

def _make_start_run_agent(app_state: AppState, tmp_path: Path, runner_type: str = "claude") -> AgentState:
    """Build a step-0 primary orchestrator agent with a minimal phase module."""
    from unittest.mock import AsyncMock, MagicMock
    from koan.phases import StepGuidance

    phase_mod = MagicMock()
    phase_mod.ROLE = "intake"
    phase_mod.TOTAL_STEPS = 3
    phase_mod.PHASE_ROLE_CONTEXT = ""
    phase_mod.STEP_NAMES = {1: "Gather"}
    phase_mod.validate_step_completion = MagicMock(return_value=None)
    phase_mod.get_next_step = MagicMock(return_value=2)
    phase_mod.step_guidance = MagicMock(return_value=StepGuidance(
        title="Gather",
        instructions=["Read the task description."],
    ))
    phase_mod.on_loop_back = AsyncMock()

    event_log = AsyncMock()
    event_log.emit_step_transition = AsyncMock()

    agent = AgentState(
        agent_id="test-startrun-agent",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir=str(tmp_path),
        step=0,
        is_primary=True,
        runner_type=runner_type,
        phase_module=phase_mod,
        phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
        event_log=event_log,
    )
    app_state.agents[agent.agent_id] = agent
    return agent


@pytest.mark.anyio
async def test_start_run_attachment_delivered_on_first_complete_step(tmp_path):
    """Upload a file at start-run time, set start_attachments, and assert that
    the first koan_complete_step call returns an EmbeddedResource block for the
    file after the step-1 guidance text. Assert start_attachments is cleared
    after delivery so phase re-entries do not re-emit.
    """
    from mcp.types import EmbeddedResource, TextContent
    from koan.web.uploads import init_upload_state, register_upload, commit_to_run

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "intake"
    init_upload_state(app_state.uploads)

    agent = _make_start_run_agent(app_state, tmp_path, runner_type="claude")
    _, handlers = build_mcp_server(app_state)

    # Upload a small text file and commit it into the run dir (mirrors what
    # api_start_run does immediately after creating the run directory).
    class FakeFile:
        filename = "brief.txt"
        content_type = "text/plain"
        file = io.BytesIO(b"project brief content")

    record = await register_upload(app_state.uploads, FakeFile())
    uid = record.id
    commit_to_run(app_state.uploads, [uid], tmp_path)

    # Simulate the in-memory state set by api_start_run.
    app_state.run.start_attachments = [uid]

    result = await handlers.koan_complete_step(FakeContext(agent), thoughts="")

    # Block 0: the step-1 guidance TextContent
    assert isinstance(result[0], TextContent)
    assert "Gather" in result[0].text or "Read" in result[0].text

    # Block 1: EmbeddedResource for brief.txt
    assert isinstance(result[1], EmbeddedResource)

    # start_attachments must be cleared so re-entry does not re-emit.
    assert app_state.run.start_attachments == []

    # M3: tool_attachments event should carry the full koan-side manifest.
    events = app_state.projection_store.events
    attach_events = [e for e in events if e.event_type == "tool_attachments"]
    assert len(attach_events) >= 1
    manifest = attach_events[-1].payload.get("attachments", [])
    assert len(manifest) == 1
    assert manifest[0]["upload_id"] == uid
    assert manifest[0]["filename"] == "brief.txt"
    assert manifest[0]["path"] != ""

    # Second call (agent.step is now 1): no File block emitted because
    # start_attachments was cleared and this path is normal within-phase.
    result2 = await handlers.koan_complete_step(FakeContext(agent), thoughts="")
    assert all(isinstance(b, TextContent) for b in result2)


@pytest.mark.anyio
async def test_start_run_attachment_non_claude_gets_text_notice(tmp_path):
    """Same start-run upload flow with runner_type='codex': expect a TextContent
    notice block (not an EmbeddedResource) after the step-1 guidance. The audit
    manifest must still carry the file record.
    """
    from mcp.types import EmbeddedResource, TextContent
    from koan.web.uploads import init_upload_state, register_upload, commit_to_run

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "intake"
    init_upload_state(app_state.uploads)

    agent = _make_start_run_agent(app_state, tmp_path, runner_type="codex")
    _, handlers = build_mcp_server(app_state)

    class FakeFile:
        filename = "spec.md"
        content_type = "text/plain"
        file = io.BytesIO(b"# Spec")

    record = await register_upload(app_state.uploads, FakeFile())
    uid = record.id
    commit_to_run(app_state.uploads, [uid], tmp_path)

    app_state.run.start_attachments = [uid]

    result = await handlers.koan_complete_step(FakeContext(agent), thoughts="")

    # Block 0: step-1 guidance
    assert isinstance(result[0], TextContent)

    # Block 1: text notice (not an EmbeddedResource)
    assert isinstance(result[1], TextContent)
    assert "attachment(s) omitted" in result[1].text
    assert "spec.md" in result[1].text
    assert not any(isinstance(b, EmbeddedResource) for b in result)

    # M3: tool_attachments event fires with full koan-side fields even for non-Claude.
    events = app_state.projection_store.events
    attach_events = [e for e in events if e.event_type == "tool_attachments"]
    assert len(attach_events) >= 1
    manifest = attach_events[-1].payload.get("attachments", [])
    assert len(manifest) == 1
    assert manifest[0]["upload_id"] == uid
    assert manifest[0]["filename"] == "spec.md"
    assert manifest[0]["path"] != ""
