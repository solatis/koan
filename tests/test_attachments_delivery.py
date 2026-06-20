# Attachment delivery tests (M3, updated for M1 MCP-transport removal).
#
# Scenarios:
#   1. A chat-message attachment surfaces in the loop's resume prompt as a text
#      notice (in-process path; koan_yield removed in M5).
#   2. A binary EmbeddedResource (runner_type "claude") cannot ride the single-
#      string resume prompt -- documents the text-only delivery limitation.
#
# Scenario 3 (per-decision attachments via _render_curation_payload) was
# removed in M7: the koan_memory_propose approval gate is retired, so
# _render_curation_payload and its test no longer exist.
#
# Scenarios 4 and 5 (start-run attachment delivery on the first koan_complete_step)
# tested the HTTP MCP handler wrapper path which was removed in M1. That attachment
# delivery path is MCP-transport-only; the in-process advance_step core does not
# replicate it. These scenarios are deleted with the transport.

from __future__ import annotations

import io

import pytest

from koan.state import AppState


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


