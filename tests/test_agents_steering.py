# Unit tests for koan.agents.steering -- drain_for_primary, render_text,
# render_blocks. Pure-function tests that exercise the three callables
# without spawning any agent subprocess.

from __future__ import annotations

from koan.agents.steering import drain_for_primary, render_blocks, render_text
from koan.state import AgentState, AppState, ChatMessage


def _app_state_with_messages(*contents: str) -> AppState:
    """Construct an AppState with the given strings queued as steering messages."""
    app_state = AppState()
    for i, content in enumerate(contents):
        app_state.interactions.steering_queue.append(
            ChatMessage(content=content, timestamp_ms=(1_000_000 + i * 1000))
        )
    return app_state


def _primary_agent() -> AgentState:
    return AgentState(agent_id="test-primary", role="orchestrator", subagent_dir="/tmp", is_primary=True)


def _secondary_agent() -> AgentState:
    return AgentState(agent_id="test-secondary", role="executor", subagent_dir="/tmp", is_primary=False)


# -- drain_for_primary ---------------------------------------------------------

class TestDrainForPrimary:

    def test_returns_empty_when_agent_is_none(self):
        app_state = _app_state_with_messages("hello")
        result = drain_for_primary(app_state, agent=None)
        assert result == []
        # Queue preserved -- no drain happened.
        assert len(app_state.interactions.steering_queue) == 1

    def test_returns_empty_when_agent_is_not_primary(self):
        app_state = _app_state_with_messages("hello")
        result = drain_for_primary(app_state, agent=_secondary_agent())
        assert result == []
        # Queue preserved.
        assert len(app_state.interactions.steering_queue) == 1

    def test_returns_messages_and_clears_queue_for_primary(self):
        app_state = _app_state_with_messages("first", "second")
        result = drain_for_primary(app_state, agent=_primary_agent())
        assert len(result) == 2
        assert result[0].content == "first"
        assert result[1].content == "second"
        # Queue atomically cleared after drain.
        assert app_state.interactions.steering_queue == []

    def test_drain_is_idempotent_on_empty_queue(self):
        app_state = AppState()
        result = drain_for_primary(app_state, agent=_primary_agent())
        assert result == []


# -- render_text ---------------------------------------------------------------

class TestRenderText:

    def test_returns_empty_string_for_empty_list(self):
        assert render_text([]) == ""

    def test_produces_envelope_and_message_lines(self):
        msg = ChatMessage(content="do the thing", timestamp_ms=1_000_000)
        text = render_text([msg])
        assert "<steering>" in text
        assert "</steering>" in text
        assert "do the thing" in text

    def test_two_messages_both_present(self):
        messages = [
            ChatMessage(content="first msg", timestamp_ms=1_000_000),
            ChatMessage(content="second msg", timestamp_ms=1_001_000),
        ]
        text = render_text(messages)
        assert "first msg" in text
        assert "second msg" in text

    def test_artifact_path_prefixed(self):
        msg = ChatMessage(content="comment", timestamp_ms=1_000_000, artifact_path="plan.md")
        text = render_text([msg])
        assert "[artifact: plan.md]" in text
        assert "comment" in text


# -- render_blocks -------------------------------------------------------------

class TestRenderBlocks:

    def test_returns_empty_tuple_for_empty_list(self):
        app_state = AppState()
        blocks, manifest = render_blocks([], app_state, agent=None)
        assert blocks == []
        assert manifest == []

    def test_produces_envelope_open_message_close(self):
        app_state = AppState()
        messages = [ChatMessage(content="steer me", timestamp_ms=1_000_000)]
        blocks, manifest = render_blocks(messages, app_state, agent=None)
        # At minimum: envelope-open, one message block, envelope-close.
        assert len(blocks) >= 3
        # First block is the envelope opener (contains steering header text).
        first_text = getattr(blocks[0], "text", "")
        assert "<steering>" in first_text
        # Last block is the envelope closer.
        last_text = getattr(blocks[-1], "text", "")
        assert "</steering>" in last_text
        # Manifest is empty when no attachments are present.
        assert manifest == []

    def test_message_content_in_blocks(self):
        app_state = AppState()
        messages = [ChatMessage(content="pay attention", timestamp_ms=1_000_000)]
        blocks, _ = render_blocks(messages, app_state, agent=None)
        all_text = " ".join(getattr(b, "text", "") for b in blocks)
        assert "pay attention" in all_text
