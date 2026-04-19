# Unit tests for koan.runners -- parse_stream_event, build_command,
# list_models, thinking modes, and extra_args.

import json

import pytest

from koan.runners import ClaudeRunner, CodexRunner, GeminiRunner, RunnerError, StreamEvent
from koan.types import AgentInstallation, ThinkingMode


def _install(name: str, extra_args: list[str] | None = None) -> AgentInstallation:
    return AgentInstallation(
        alias=name, runner_type=name, binary=name, extra_args=extra_args or []
    )


# -- ClaudeRunner: parse_stream_event ------------------------------------------

class TestClaudeRunnerParseStreamEvent:
    def setup_method(self):
        self.runner = ClaudeRunner(subagent_dir="/tmp/test-claude")

    def _msg(self, content: list) -> str:
        """Wrap content blocks in the stream-json message envelope."""
        return json.dumps({"type": "assistant", "message": {"content": content}})

    def test_text_delta(self):
        line = self._msg([{"type": "text", "text": "hello"}])
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="token_delta", content="hello"), StreamEvent(type="assistant_text", content="hello")]

    def test_tool_call(self):
        line = self._msg([{"type": "tool_use", "name": "bash", "input": {"cmd": "ls"}}])
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="tool_call", tool_name="bash", tool_args={"cmd": "ls"}, summary="")]

    def test_thinking_block(self):
        line = self._msg([{"type": "thinking", "text": "hmm"}])
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="thinking", is_thinking=True, content="hmm")]

    def test_thinking_block_thinking_key(self):
        # Real claude stream-json uses "thinking" key, not "text"
        line = self._msg([{"type": "thinking", "thinking": "reasoning here", "signature": "sig"}])
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="thinking", is_thinking=True, content="reasoning here")]

    # -- stream_event (--include-partial-messages) ----------------------------

    def test_stream_event_thinking_delta(self):
        line = json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        })
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="thinking", is_thinking=True, content="hmm")]

    def test_stream_event_text_delta(self):
        line = json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "hello"}},
        })
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="token_delta", content="hello")]

    def test_stream_event_suppresses_assistant_text_and_tool_use(self):
        """Once stream_events are seen, assistant text/thinking/tool_use blocks are skipped."""
        delta_line = json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "hi"}},
        })
        self.runner.parse_stream_event(delta_line)
        msg_line = self._msg([
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "name": "bash", "input": {"cmd": "ls"}},
        ])
        evts = self.runner.parse_stream_event(msg_line)
        # Both text and tool_use are skipped; only assistant_text remains
        assert len(evts) == 1
        assert evts[0].type == "assistant_text"
        assert evts[0].content == "hi"

    def test_result_success(self):
        line = json.dumps({"type": "result", "subtype": "success", "result": "done"})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="turn_complete", content="done")]

    def test_system_event_skipped(self):
        line = json.dumps({"type": "system", "subtype": "init"})
        assert self.runner.parse_stream_event(line) == []

    def test_invalid_json(self):
        assert self.runner.parse_stream_event("not json{") == []

    def test_multi_block_text_and_tool(self):
        line = self._msg([
            {"type": "text", "text": "calling tool"},
            {"type": "tool_use", "name": "read", "input": {"path": "/a"}},
        ])
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 3
        assert evts[0] == StreamEvent(type="token_delta", content="calling tool")
        assert evts[1] == StreamEvent(type="tool_call", tool_name="read", tool_args={"path": "/a"}, summary="")
        assert evts[2] == StreamEvent(type="assistant_text", content="calling tool")

    def test_multi_block_thinking_and_text(self):
        line = self._msg([
            {"type": "thinking", "text": "reasoning"},
            {"type": "text", "text": "answer"},
        ])
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 3
        assert evts[0] == StreamEvent(type="thinking", is_thinking=True, content="reasoning")
        assert evts[1] == StreamEvent(type="token_delta", content="answer")
        assert evts[2] == StreamEvent(type="assistant_text", content="answer")

    def test_multi_block_with_unknown_type_skipped(self):
        line = self._msg([
            {"type": "text", "text": "hello"},
            {"type": "unknown_block"},
            {"type": "tool_use", "name": "bash", "input": {}},
        ])
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 3
        assert evts[0].type == "token_delta"
        assert evts[1].type == "tool_call"
        assert evts[2].type == "assistant_text"

    def test_multi_block_non_dict_block_skipped(self):
        line = self._msg([
            "not a dict",
            {"type": "text", "text": "valid"},
        ])
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="token_delta", content="valid"), StreamEvent(type="assistant_text", content="valid")]


# -- ClaudeRunner: streaming tool_use events -----------------------------------

class TestClaudeRunnerStreamingToolUse:
    def setup_method(self):
        self.runner = ClaudeRunner(subagent_dir="/tmp/test")

    def _stream_event(self, inner: dict) -> str:
        return json.dumps({"type": "stream_event", "event": inner})

    def test_content_block_start_tool_use_emits_tool_start(self):
        line = self._stream_event({
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "Write", "input": {}},
        })
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 1
        assert evts[0].type == "tool_start"
        assert evts[0].tool_name == "write"
        assert evts[0].tool_use_id == "toolu_01"
        assert evts[0].block_index == 1

    def test_input_json_delta_emits_tool_input_delta(self):
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "Write", "input": {}},
        }))
        line = self._stream_event({
            "type": "content_block_delta", "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"file_pa'},
        })
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 1
        assert evts[0].type == "tool_input_delta"
        assert evts[0].content == '{"file_pa'
        assert evts[0].block_index == 1

    def test_content_block_stop_emits_tool_stop_with_assembled_args(self):
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "Bash", "input": {}},
        }))
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_delta", "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"command":'},
        }))
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_delta", "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '"ls -la"}'},
        }))
        evts = self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_stop", "index": 1,
        }))
        assert len(evts) == 1
        assert evts[0].type == "tool_stop"
        assert evts[0].tool_name == "bash"
        assert evts[0].tool_args == {"command": "ls -la"}
        assert evts[0].summary == "ls -la"

    def test_streaming_suppresses_assistant_tool_use(self):
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "Bash", "input": {}},
        }))
        msg_line = json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                {"type": "text", "text": "done"},
            ]},
        })
        evts = self.runner.parse_stream_event(msg_line)
        types = [e.type for e in evts]
        assert "tool_call" not in types
        assert "assistant_text" in types

    def test_message_start_resets_accumulators(self):
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "Write", "input": {}},
        }))
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_delta", "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"file'},
        }))
        self.runner.parse_stream_event(self._stream_event({"type": "message_start"}))
        stop_evts = self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_stop", "index": 1,
        }))
        assert len(stop_evts) == 0

    def test_koan_tools_not_filtered_in_streaming(self):
        line = self._stream_event({
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_02", "name": "koan_yield", "input": {}},
        })
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 1
        assert evts[0].type == "tool_start"
        assert evts[0].tool_name == "koan_yield"

    def test_parallel_tool_blocks(self):
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_a", "name": "Read", "input": {}},
        }))
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_start", "index": 2,
            "content_block": {"type": "tool_use", "id": "toolu_b", "name": "Bash", "input": {}},
        }))
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_delta", "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"file_path":"/a.txt"}'},
        }))
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_delta", "index": 2,
            "delta": {"type": "input_json_delta", "partial_json": '{"command":"pwd"}'},
        }))
        stop1 = self.runner.parse_stream_event(self._stream_event({"type": "content_block_stop", "index": 1}))
        stop2 = self.runner.parse_stream_event(self._stream_event({"type": "content_block_stop", "index": 2}))
        assert stop1[0].tool_name == "read"
        assert stop1[0].tool_args == {"file_path": "/a.txt"}
        assert stop2[0].tool_name == "bash"
        assert stop2[0].tool_args == {"command": "pwd"}

    def test_malformed_json_uses_lenient_fallback(self):
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_x", "name": "Write", "input": {}},
        }))
        self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"file_path": "/tmp/x.html", "content": "<html'},
        }))
        evts = self.runner.parse_stream_event(self._stream_event({
            "type": "content_block_stop", "index": 0,
        }))
        assert len(evts) == 1
        assert evts[0].type == "tool_stop"
        assert evts[0].tool_args.get("file_path") == "/tmp/x.html"


# -- CodexRunner: parse_stream_event -------------------------------------------

class TestCodexRunnerParseStreamEvent:
    def setup_method(self):
        self.runner = CodexRunner()

    def test_turn_started(self):
        line = json.dumps({"type": "turn.started"})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="thinking", is_thinking=True)]

    def test_turn_completed(self):
        line = json.dumps({"type": "turn.completed"})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="turn_complete", is_thinking=True)]

    def test_turn_failed(self):
        line = json.dumps({"type": "turn.failed"})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="turn_complete", is_thinking=True)]

    def test_item_event_skipped(self):
        line = json.dumps({"type": "item.created"})
        assert self.runner.parse_stream_event(line) == []

    def test_invalid_json(self):
        assert self.runner.parse_stream_event("<<<not json>>>") == []


# -- GeminiRunner: parse_stream_event ------------------------------------------

class TestGeminiRunnerParseStreamEvent:
    def setup_method(self):
        self.runner = GeminiRunner(subagent_dir="/tmp/test-gemini")

    def test_message_delta(self):
        line = json.dumps({"type": "message", "content": "hello"})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="token_delta", content="hello")]

    def test_tool_use(self):
        line = json.dumps({"type": "tool_use", "name": "read", "input": {"path": "/a"}})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="tool_call", tool_name="read", tool_args={"path": "/a"}, summary="/a")]

    def test_result_event(self):
        line = json.dumps({"type": "result"})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="turn_complete")]

    def test_init_skipped(self):
        line = json.dumps({"type": "init"})
        assert self.runner.parse_stream_event(line) == []

    def test_invalid_json(self):
        assert self.runner.parse_stream_event("nope") == []


# -- ClaudeRunner: build_command -----------------------------------------------

class TestClaudeRunnerBuildCommand:
    def test_writes_mcp_config_and_returns_command(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "do stuff", "http://localhost:9000/mcp",
            _install("claude"), "claude-sonnet-4-5", "disabled",
        )

        config_path = tmp_path / "mcp-config.json"
        assert config_path.exists()
        written = json.loads(config_path.read_text("utf-8"))
        assert written["mcpServers"]["koan"]["url"] == "http://localhost:9000/mcp"
        assert written["mcpServers"]["koan"]["type"] == "http"

        assert "--mcp-config" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert cmd[0] == "claude"

    def test_model_always_appended(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "do stuff", "http://localhost:9000/mcp",
            _install("claude"), "claude-sonnet-4-5", "disabled",
        )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-5"


# -- CodexRunner: build_command ------------------------------------------------

class TestCodexRunnerBuildCommand:
    def test_command_contains_mcp_override(self):
        runner = CodexRunner()
        cmd = runner.build_command(
            "do stuff", "http://localhost:9000/mcp",
            _install("codex"), "gpt-5", "disabled",
        )
        assert "-c" in cmd
        idx = cmd.index("-c")
        assert cmd[idx + 1] == "mcp_servers.koan.url=http://localhost:9000/mcp"
        assert cmd[0] == "codex"


# -- GeminiRunner: build_command -----------------------------------------------

class TestGeminiRunnerBuildCommand:
    def test_writes_settings_json(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "do stuff", "http://localhost:9000/mcp",
            _install("gemini"), "gemini-pro", "disabled",
        )

        settings = tmp_path / ".gemini" / "settings.json"
        assert settings.exists()
        written = json.loads(settings.read_text("utf-8"))
        assert written["mcpServers"]["koan"]["httpUrl"] == "http://localhost:9000/mcp"

        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert cmd[0] == "gemini"

    def test_merge_conflict_raises_runner_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({
            "mcpServers": {"koan": {"httpUrl": "http://other:1234/mcp"}},
        }))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(RunnerError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        assert exc_info.value.diagnostic.code == "mcp_inject_failed"

    def test_non_object_toplevel_raises_runner_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps([1, 2, 3]))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(RunnerError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        diag = exc_info.value.diagnostic
        assert diag.code == "mcp_inject_failed"
        assert diag.runner == "gemini"
        assert "list" in diag.message

    def test_non_dict_mcp_servers_raises_runner_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": "not-a-dict"}))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(RunnerError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        diag = exc_info.value.diagnostic
        assert diag.code == "mcp_inject_failed"
        assert "mcpServers" in diag.message

    def test_non_dict_koan_entry_raises_runner_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"koan": "a-string"}}))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(RunnerError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        diag = exc_info.value.diagnostic
        assert diag.code == "mcp_inject_failed"
        assert "mcpServers.koan" in diag.message


# -- ClaudeRunner: thinking modes ---------------------------------------------

class TestClaudeRunnerThinkingMode:
    def test_disabled_no_thinking_flag(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("claude"), "opus", "disabled",
        )
        assert "--effort" not in cmd

    def test_effort_low(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("claude"), "opus", "low",
        )
        idx = cmd.index("--effort")
        assert cmd[idx + 1] == "low"

    def test_effort_medium(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("claude"), "opus", "medium",
        )
        idx = cmd.index("--effort")
        assert cmd[idx + 1] == "medium"

    def test_effort_high(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("claude"), "opus", "high",
        )
        idx = cmd.index("--effort")
        assert cmd[idx + 1] == "high"

    def test_effort_max_opus(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("claude"), "opus", "xhigh",
        )
        idx = cmd.index("--effort")
        assert cmd[idx + 1] == "max"


# -- ClaudeRunner: opus thinking-display --------------------------------------

class TestClaudeRunnerOpusThinkingDisplay:
    def test_opus_alias_injects_thinking_display(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command("p", "http://x/mcp", _install("claude"), "opus", "disabled")
        assert "--thinking-display" in cmd
        idx = cmd.index("--thinking-display")
        assert cmd[idx + 1] == "summarized"

    def test_opus_with_suffix_still_matches(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command("p", "http://x/mcp", _install("claude"), "opus[1m]", "disabled")
        assert "--thinking-display" in cmd
        idx = cmd.index("--thinking-display")
        assert cmd[idx + 1] == "summarized"

    def test_case_insensitive_match(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command("p", "http://x/mcp", _install("claude"), "OPUS", "disabled")
        assert "--thinking-display" in cmd

    def test_non_opus_model_has_no_thinking_display(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        for model in ("sonnet", "haiku"):
            cmd = runner.build_command("p", "http://x/mcp", _install("claude"), model, "disabled")
            assert "--thinking-display" not in cmd

    def test_thinking_display_before_extra_args(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        inst = AgentInstallation(
            alias="claude", runner_type="claude", binary="claude",
            extra_args=["--verbose"],
        )
        cmd = runner.build_command("p", "http://x/mcp", inst, "opus", "disabled")
        # extra_args must remain last
        assert cmd[-1] == "--verbose"
        assert "--thinking-display" in cmd
        td_idx = cmd.index("--thinking-display")
        # Compare against the LAST --verbose (from extra_args), not the
        # built-in --verbose that the runner hardcodes earlier in the command.
        verbose_idx = len(cmd) - 1 - cmd[::-1].index("--verbose")
        assert td_idx < verbose_idx


# -- ClaudeRunner: list_models -------------------------------------------------

class TestClaudeRunnerListModels:
    def test_returns_three_models(self):
        runner = ClaudeRunner(subagent_dir="/tmp/x")
        models = runner.list_models("claude")
        assert len(models) == 3

    def test_haiku_limited_thinking(self):
        runner = ClaudeRunner(subagent_dir="/tmp/x")
        models = runner.list_models("claude")
        haiku = [m for m in models if m.alias == "haiku"][0]
        assert haiku.thinking_modes == frozenset({"disabled", "low", "medium", "high"})

    def test_opus_all_thinking_modes(self):
        runner = ClaudeRunner(subagent_dir="/tmp/x")
        models = runner.list_models("claude")
        opus = [m for m in models if m.alias == "opus[1m]"][0]
        assert opus.thinking_modes == frozenset({"disabled", "low", "medium", "high", "xhigh"})

    def test_sonnet_all_thinking_modes(self):
        runner = ClaudeRunner(subagent_dir="/tmp/x")
        models = runner.list_models("claude")
        sonnet = [m for m in models if m.alias == "sonnet"][0]
        assert sonnet.thinking_modes == frozenset({"disabled", "low", "medium", "high"})


# -- ClaudeRunner: extra_args --------------------------------------------------

class TestClaudeRunnerExtraArgs:
    def test_extra_args_at_end(self, tmp_path):
        runner = ClaudeRunner(subagent_dir=str(tmp_path))
        inst = AgentInstallation(
            alias="claude", runner_type="claude", binary="claude",
            extra_args=["--verbose"],
        )
        cmd = runner.build_command("p", "http://x/mcp", inst, "opus", "disabled")
        assert cmd[-1] == "--verbose"


# -- CodexRunner: thinking modes -----------------------------------------------

class TestCodexRunnerThinkingMode:
    def test_disabled_succeeds(self):
        runner = CodexRunner()
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("codex"), "gpt-5", "disabled",
        )
        assert "codex" == cmd[0]

    def test_low_raises_runner_error(self):
        runner = CodexRunner()
        with pytest.raises(RunnerError) as exc_info:
            runner.build_command(
                "p", "http://x/mcp", _install("codex"), "gpt-5", "low",
            )
        assert exc_info.value.diagnostic.code == "unsupported_thinking_mode"


# -- CodexRunner: list_models --------------------------------------------------

class TestCodexRunnerListModels:
    def test_returns_two_models(self):
        runner = CodexRunner()
        models = runner.list_models("codex")
        assert len(models) == 2

    def test_both_disabled_only(self):
        runner = CodexRunner()
        for m in runner.list_models("codex"):
            assert m.thinking_modes == frozenset({"disabled"})


# -- CodexRunner: extra_args ---------------------------------------------------

class TestCodexRunnerExtraArgs:
    def test_extra_args_at_end(self):
        runner = CodexRunner()
        inst = AgentInstallation(
            alias="codex", runner_type="codex", binary="codex",
            extra_args=["--verbose"],
        )
        cmd = runner.build_command("p", "http://x/mcp", inst, "gpt-5", "disabled")
        assert cmd[-1] == "--verbose"


# -- GeminiRunner: thinking modes ----------------------------------------------

class TestGeminiRunnerThinkingMode:
    def test_disabled_no_thinking_flag(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "disabled",
        )
        assert "--thinking-mode" not in cmd

    def test_low_thinking(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "low",
        )
        idx = cmd.index("--thinking-mode")
        assert cmd[idx + 1] == "low"

    def test_medium_thinking(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "medium",
        )
        idx = cmd.index("--thinking-mode")
        assert cmd[idx + 1] == "medium"

    def test_high_thinking(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "high",
        )
        idx = cmd.index("--thinking-mode")
        assert cmd[idx + 1] == "high"

    def test_xhigh_raises_runner_error(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(RunnerError) as exc_info:
            runner.build_command(
                "p", "http://x/mcp", _install("gemini"), "gemini-pro", "xhigh",
            )
        assert exc_info.value.diagnostic.code == "unsupported_thinking_mode"


# -- GeminiRunner: list_models -------------------------------------------------

class TestGeminiRunnerListModels:
    def test_returns_two_models(self):
        runner = GeminiRunner(subagent_dir="/tmp/x")
        models = runner.list_models("gemini")
        assert len(models) == 2

    def test_flash_limited_thinking(self):
        runner = GeminiRunner(subagent_dir="/tmp/x")
        models = runner.list_models("gemini")
        flash = [m for m in models if m.alias == "gemini-flash"][0]
        assert flash.thinking_modes == frozenset({"disabled", "low"})


# -- GeminiRunner: extra_args --------------------------------------------------

class TestGeminiRunnerExtraArgs:
    def test_extra_args_at_end(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        inst = AgentInstallation(
            alias="gemini", runner_type="gemini", binary="gemini",
            extra_args=["--verbose"],
        )
        cmd = runner.build_command("p", "http://x/mcp", inst, "gemini-pro", "disabled")
        assert cmd[-1] == "--verbose"




# -- Summary extraction --------------------------------------------------------

class TestClaudeSummaryExtraction:
    def setup_method(self):
        self.runner = ClaudeRunner(subagent_dir="/tmp/test-claude")

    def _msg(self, content):
        import json
        return json.dumps({"type": "assistant", "message": {"content": content}})

    def test_read_summary(self):
        line = self._msg([{"type": "tool_use", "name": "Read", "input": {"file_path": "/src/foo.ts"}}])
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/src/foo.ts"

    def test_read_summary_with_offset_limit(self):
        line = self._msg([{"type": "tool_use", "name": "Read", "input": {"file_path": "/src/foo.ts", "offset": 10, "limit": 50}}])
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/src/foo.ts:10-60"

    def test_bash_summary(self):
        line = self._msg([{"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}])
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "ls -la"

    def test_write_summary(self):
        line = self._msg([{"type": "tool_use", "name": "Write", "input": {"file_path": "/src/new.ts"}}])
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/src/new.ts"

    def test_grep_summary(self):
        line = self._msg([{"type": "tool_use", "name": "Grep", "input": {"pattern": "def foo"}}])
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "def foo"

    def test_ls_summary(self):
        line = self._msg([{"type": "tool_use", "name": "LS", "input": {"path": "/src"}}])
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/src"

    def test_unknown_tool_empty_summary(self):
        line = self._msg([{"type": "tool_use", "name": "WebFetch", "input": {"url": "http://example.com"}}])
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == ""


class TestCodexSummaryExtraction:
    def setup_method(self):
        self.runner = CodexRunner()

    def _item(self, name, args_dict):
        import json
        return json.dumps({"type": "item.completed", "item": {
            "type": "function_call", "name": name, "arguments": json.dumps(args_dict)
        }})

    def test_read_summary(self):
        line = self._item("read_file", {"path": "/src/foo.ts"})
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/src/foo.ts"

    def test_bash_summary(self):
        line = self._item("shell", {"command": "npm test"})
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "npm test"

    def test_write_summary(self):
        line = self._item("write_file", {"path": "/out/result.ts"})
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/out/result.ts"

    def test_no_function_call_output_event(self):
        """function_call_output should no longer produce a tool_call event."""
        import json
        line = json.dumps({"type": "item.completed", "item": {
            "type": "function_call_output", "output": "some result"
        }})
        evts = self.runner.parse_stream_event(line)
        assert evts == []


class TestGeminiSummaryExtraction:
    def setup_method(self):
        self.runner = GeminiRunner(subagent_dir="/tmp/test-gemini")

    def _tool(self, name, input_dict):
        import json
        return json.dumps({"type": "tool_use", "name": name, "input": input_dict})

    def test_read_summary(self):
        line = self._tool("read_file", {"file_path": "/src/bar.go"})
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/src/bar.go"

    def test_bash_summary(self):
        line = self._tool("run_bash_command", {"command": "go build"})
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "go build"

    def test_ls_summary(self):
        line = self._tool("list_directory", {"path": "/src"})
        evts = self.runner.parse_stream_event(line)
        assert evts[0].summary == "/src"
