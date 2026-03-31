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

    def test_text_delta(self):
        line = json.dumps({"type": "assistant", "content": [{"type": "text", "text": "hello"}]})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="token_delta", content="hello")]

    def test_tool_call(self):
        line = json.dumps({
            "type": "assistant",
            "content": [{"type": "tool_use", "name": "bash", "input": {"cmd": "ls"}}],
        })
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="tool_call", tool_name="bash", tool_args={"cmd": "ls"})]

    def test_thinking_block(self):
        line = json.dumps({"type": "assistant", "content": [{"type": "thinking", "text": "hmm"}]})
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="thinking", is_thinking=True, content="hmm")]

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
        line = json.dumps({
            "type": "assistant",
            "content": [
                {"type": "text", "text": "calling tool"},
                {"type": "tool_use", "name": "read", "input": {"path": "/a"}},
            ],
        })
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 2
        assert evts[0] == StreamEvent(type="token_delta", content="calling tool")
        assert evts[1] == StreamEvent(type="tool_call", tool_name="read", tool_args={"path": "/a"})

    def test_multi_block_thinking_and_text(self):
        line = json.dumps({
            "type": "assistant",
            "content": [
                {"type": "thinking", "text": "reasoning"},
                {"type": "text", "text": "answer"},
            ],
        })
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 2
        assert evts[0] == StreamEvent(type="thinking", is_thinking=True, content="reasoning")
        assert evts[1] == StreamEvent(type="token_delta", content="answer")

    def test_multi_block_with_unknown_type_skipped(self):
        line = json.dumps({
            "type": "assistant",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "unknown_block"},
                {"type": "tool_use", "name": "bash", "input": {}},
            ],
        })
        evts = self.runner.parse_stream_event(line)
        assert len(evts) == 2
        assert evts[0].type == "token_delta"
        assert evts[1].type == "tool_call"

    def test_multi_block_non_dict_block_skipped(self):
        line = json.dumps({
            "type": "assistant",
            "content": [
                "not a dict",
                {"type": "text", "text": "valid"},
            ],
        })
        evts = self.runner.parse_stream_event(line)
        assert evts == [StreamEvent(type="token_delta", content="valid")]


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
        assert evts == [StreamEvent(type="tool_call", tool_name="read", tool_args={"path": "/a"})]

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
        assert haiku.thinking_modes == frozenset({"disabled", "low"})

    def test_opus_all_thinking_modes(self):
        runner = ClaudeRunner(subagent_dir="/tmp/x")
        models = runner.list_models("claude")
        opus = [m for m in models if m.alias == "opus"][0]
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


