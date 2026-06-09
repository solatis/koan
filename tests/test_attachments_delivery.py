# Attachment delivery tests (M3, updated for M1 MCP-transport removal).
#
# Scenarios:
#   1. A chat-message attachment surfaces in the loop's resume prompt as a text
#      notice (in-process path; koan_yield removed in M5).
#   2. A binary EmbeddedResource (runner_type "claude") cannot ride the single-
#      string resume prompt -- documents the text-only delivery limitation.
#   3. Per-decision attachments on /api/memory/curation reach _render_curation_payload
#      as File blocks in the correct order (unit-tests the relocated function).
#
# Scenarios 4 and 5 (start-run attachment delivery on the first koan_complete_step)
# tested the HTTP MCP handler wrapper path which was removed in M1. That attachment
# delivery path is MCP-transport-only; the in-process advance_step core does not
# replicate it. These scenarios are deleted with the transport.

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


# -- Scenario 1: in-process resume delivers attachment text notice to the next turn ---
#
# M4: upload_ids_to_blocks always returns a text notice regardless of runner_type;
# binary/image delivery to multimodal models is out of scope (brief).
# The notice includes the filename so the orchestrator knows what was attached.

@pytest.mark.anyio
async def test_resume_prompt_includes_attachment_text_notice(tmp_path):
    """A buffered message with an attachment yields a resume prompt carrying the
    USER MESSAGE text plus the upload text-notice (all runner types).
    """
    from koan.web.uploads import init_upload_state, register_upload, commit_to_run
    from koan.state import drain_user_messages
    from koan.agents.loop import assemble_resume_prompt

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "intake"
    init_upload_state(app_state.uploads)

    class FakeFile:
        filename = "note.txt"
        content_type = "text/plain"
        file = io.BytesIO(b"hello from note")

    record = await register_upload(app_state.uploads, FakeFile())
    uid = record.id
    commit_to_run(app_state.uploads, [uid], tmp_path)

    import time
    from koan.state import ChatMessage
    app_state.interactions.user_message_buffer.append(ChatMessage(
        content="check this file",
        timestamp_ms=int(time.time() * 1000),
        attachments=[uid],
    ))

    messages = drain_user_messages(app_state)
    prompt, manifest = assemble_resume_prompt(messages, app_state, runner_type="pydantic_ai")

    assert "USER MESSAGE" in prompt
    assert "check this file" in prompt
    assert "note.txt" in prompt
    # M4: text notice replaces binary delivery; message confirms out-of-scope status.
    assert "binary content delivery is out of scope" in prompt
    assert len(manifest) == 1
    assert manifest[0]["filename"] == "note.txt"
    assert manifest[0]["upload_id"] == uid


# -- Scenario 2: all runner_types receive the text notice (no binary delivery) ---
#
# M4: the runner_type=="claude" binary-delivery branch was removed from
# upload_ids_to_blocks. All paths now return a text notice with the filename.

@pytest.mark.anyio
async def test_resume_prompt_all_runners_receive_text_notice(tmp_path):
    """All runner types (including 'claude') receive the text-notice block.

    M4: binary delivery path removed; upload_ids_to_blocks is runner-type-agnostic.
    Binary/image delivery to multimodal models remains out of scope (brief).
    """
    from koan.web.uploads import init_upload_state, register_upload, commit_to_run
    from koan.state import drain_user_messages
    from koan.agents.loop import assemble_resume_prompt

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "intake"
    init_upload_state(app_state.uploads)

    class FakeFile:
        filename = "data.csv"
        content_type = "text/csv"
        file = io.BytesIO(b"a,b,c")

    record = await register_upload(app_state.uploads, FakeFile())
    commit_to_run(app_state.uploads, [record.id], tmp_path)

    import time
    from koan.state import ChatMessage
    app_state.interactions.user_message_buffer.append(ChatMessage(
        content="see attached",
        timestamp_ms=int(time.time() * 1000),
        attachments=[record.id],
    ))

    messages = drain_user_messages(app_state)
    # runner_type="claude" used to produce a binary EmbeddedResource; now text notice.
    prompt, manifest = assemble_resume_prompt(messages, app_state, runner_type="claude")

    assert "USER MESSAGE" in prompt
    assert "see attached" in prompt
    # Filename IS now present in the text notice (all runners get the notice).
    assert "data.csv" in prompt
    assert "binary content delivery is out of scope" in prompt
    assert len(manifest) == 1
    assert manifest[0]["filename"] == "data.csv"


# -- Scenario 3: Per-decision attachments via _render_curation_payload ----------
#
# This unit-tests the relocated _render_curation_payload function directly.
# propose_memory_core discards the attachment blocks (returns only the JSON text),
# so the attachment interleaving logic must be tested on the function itself.

@pytest.mark.anyio
async def test_memory_curation_per_decision_attachments(tmp_path):
    """_render_curation_payload emits per-decision text-notice blocks after the JSON blob.

    M4: EmbeddedResource delivery removed; upload_ids_to_blocks always returns
    a TextContent notice (binary delivery is out of scope, brief).
    """
    from mcp.types import TextContent
    from koan.web.uploads import init_upload_state, register_upload, commit_to_run, _render_curation_payload
    from koan.projections import ActiveCurationBatch, Proposal

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.phase = "curation"
    init_upload_state(app_state.uploads)

    # Upload a file and commit it (simulating api_memory_curation_submit).
    class FakeFile:
        filename = "evidence.md"
        content_type = "text/plain"
        file = io.BytesIO(b"# Evidence")

    record = await register_upload(app_state.uploads, FakeFile())
    commit_to_run(app_state.uploads, [record.id], tmp_path)

    # Build a curation batch with one proposal.
    proposal = Proposal(
        id="p1", op="add", seq="", type="context",
        title="Test entry", body="Some body", rationale="test",
    )
    batch = ActiveCurationBatch(
        proposals=[proposal], batch_id="batch-test-1", context_note="",
    )

    decisions = [
        {
            "proposal_id": "p1",
            "decision": "approved",
            "feedback": "",
            "attachments": [record.id],
        }
    ]

    # Call _render_curation_payload directly -- the unit under test.
    result, manifest = _render_curation_payload(
        batch, decisions, app_state.uploads, str(tmp_path), runner_type="claude"
    )

    # Block 0: the JSON blob (json.loads(result[0].text) must work)
    assert isinstance(result[0], TextContent)
    parsed = json.loads(result[0].text)
    assert parsed.get("batch_id") == "batch-test-1"

    # Block 1: the label separator
    assert isinstance(result[1], TextContent)
    assert "Attachments for proposal p1" in result[1].text

    # Block 2: the text notice for evidence.md (EmbeddedResource removed in M4)
    assert isinstance(result[2], TextContent)
    assert "evidence.md" in result[2].text
