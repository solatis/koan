# ClaudeRunner -- builds claude CLI commands and parses stream-json JSONL.
# MCP injection via --mcp-config file written to the subagent directory.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..lib.partial_json import parse_partial
from ..types import AgentInstallation, ModelInfo, ThinkingMode
from .base import KOAN_MCP_TOOLS, RunnerDiagnostic, RunnerError, StreamEvent


@dataclass
class _ToolUseAccumulator:
    tool_name: str
    raw_name: str
    tool_use_id: str
    buffer: list[str] = field(default_factory=list)
    latest_draft: dict | None = None

# Map internal thinking mode names to Claude CLI --effort values.
_EFFORT_MAP: dict[ThinkingMode, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",  # opus only
}

# Canonical tool name mappings for Claude's tool vocabulary.
_TOOL_NAME_MAP: dict[str, str] = {
    "Read": "read",
    "Write": "write",
    "Edit": "edit",
    "MultiEdit": "edit",
    "Bash": "bash",
    "Glob": "grep",
    "Grep": "grep",
    "LS": "ls",
    "TodoRead": "todo_read",
    "TodoWrite": "todo_write",
    "WebFetch": "web_fetch",
    "WebSearch": "web_search",
}


def _normalize_tool_name(name: str | None) -> str | None:
    if name is None:
        return None
    return _TOOL_NAME_MAP.get(name, name.lower())


def _coerce_int(value: object) -> int | None:
    # Models occasionally emit numeric tool arguments as strings; Read itself
    # accepts both, so we coerce here to match that lenience for display.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _extract_tool_summary(tool: str, args: dict) -> str:
    """Extract human-readable detail from Claude tool arguments."""
    if tool == "read":
        path = args.get("file_path", "")
        offset = _coerce_int(args.get("offset"))
        limit = _coerce_int(args.get("limit"))
        if offset is not None and limit is not None:
            return f"{path}:{offset}-{offset + limit}"
        if offset is not None:
            return f"{path}:{offset}+"
        start = _coerce_int(args.get("start_line"))
        end = _coerce_int(args.get("end_line"))
        if start is not None and end is not None:
            return f"{path}:{start}-{end}"
        return path
    if tool == "bash":
        return args.get("command", "")
    if tool in ("write", "edit"):
        return args.get("file_path", "")
    if tool == "grep":
        return args.get("pattern", "") or args.get("query", "")
    if tool == "ls":
        return args.get("path", "")
    return ""


class ClaudeRunner:
    name = "claude"
    supported_thinking_modes: frozenset[ThinkingMode] = frozenset(
        {"disabled", "low", "medium", "high", "xhigh"}
    )

    def __init__(self, *, subagent_dir: str) -> None:
        self.subagent_dir = subagent_dir
        self._saw_stream_events = False
        self._tool_accumulators: dict[int, _ToolUseAccumulator] = {}

    def list_models(self, binary: str) -> list[ModelInfo]:
        return [
            ModelInfo(
                alias="opus[1m]", display_name="Opus",
                thinking_modes=frozenset({"disabled", "low", "medium", "high", "xhigh"}),
                tier_hint="strong",
            ),
            ModelInfo(
                alias="sonnet", display_name="Sonnet",
                thinking_modes=frozenset({"disabled", "low", "medium", "high"}),
                tier_hint="standard",
            ),
            ModelInfo(
                alias="haiku", display_name="Haiku",
                thinking_modes=frozenset({"disabled", "low", "medium", "high"}),
                tier_hint="cheap",
            ),
        ]

    def build_command(
        self,
        boot_prompt: str,
        mcp_url: str,
        installation: AgentInstallation,
        model: str,
        thinking: ThinkingMode,
        system_prompt: str = "",
    ) -> list[str]:
        if thinking not in self.supported_thinking_modes:
            raise RunnerError(RunnerDiagnostic(
                code="unsupported_thinking_mode",
                runner="claude",
                stage="build_command",
                message=f"Thinking mode '{thinking}' is not supported by claude",
            ))

        config_dir = Path(self.subagent_dir)
        config_path = config_dir / "mcp-config.json"
        config_data = {"mcpServers": {"koan": {"type": "http", "url": mcp_url}}}

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            tmp = config_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(config_data, indent=2) + "\n", "utf-8")
            tmp.rename(config_path)
        except OSError as e:
            raise RunnerError(RunnerDiagnostic(
                code="mcp_inject_failed",
                runner="claude",
                stage="build_command",
                message=f"Failed to write MCP config: {e}",
            )) from e

        cmd = [
            installation.binary, "-p", boot_prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--mcp-config", str(config_path),
        ]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
        if thinking != "disabled":
            cmd.extend(["--effort", _EFFORT_MAP[thinking]])
        cmd.extend(["--model", model])
        cmd.extend(installation.extra_args)
        return cmd

    def parse_stream_event(self, line: str) -> list[StreamEvent]:
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return []

        if not isinstance(data, dict):
            return []

        evt_type = data.get("type")

        if evt_type == "stream_event":
            return self._parse_stream_event(data)
        if evt_type == "assistant":
            return self._parse_assistant(data)
        if evt_type == "result":
            evt = self._parse_result(data)
            return [evt] if evt is not None else []
        return []

    # -- Private helpers -------------------------------------------------------

    def _parse_stream_event(self, data: dict) -> list[StreamEvent]:
        """Handle incremental stream_event deltas from --include-partial-messages."""
        inner = data.get("event")
        if not isinstance(inner, dict):
            return []
        inner_type = inner.get("type")

        if inner_type == "message_start":
            self._saw_stream_events = False
            self._tool_accumulators = {}
            return []

        if inner_type == "content_block_start":
            block = inner.get("content_block", {})
            if block.get("type") == "tool_use":
                idx = inner.get("index", -1)
                raw_name = block.get("name", "")
                canonical = _normalize_tool_name(raw_name)
                tool_use_id = block.get("id", "")
                self._tool_accumulators[idx] = _ToolUseAccumulator(
                    tool_name=canonical or raw_name,
                    raw_name=raw_name,
                    tool_use_id=tool_use_id,
                )
                self._saw_stream_events = True
                return [StreamEvent(
                    type="tool_start",
                    tool_name=canonical,
                    tool_use_id=tool_use_id,
                    block_index=idx,
                )]
            return []

        if inner_type == "content_block_delta":
            self._saw_stream_events = True
            delta = inner.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "thinking_delta":
                return [StreamEvent(type="thinking", is_thinking=True, content=delta.get("thinking", ""))]
            if delta_type == "text_delta":
                return [StreamEvent(type="token_delta", content=delta.get("text", ""))]
            if delta_type == "input_json_delta":
                idx = inner.get("index", -1)
                partial = delta.get("partial_json", "")
                acc = self._tool_accumulators.get(idx)
                if acc is not None:
                    acc.buffer.append(partial)
                    acc.latest_draft = parse_partial("".join(acc.buffer))
                return [StreamEvent(
                    type="tool_input_delta",
                    content=partial,
                    tool_args=acc.latest_draft if acc else None,
                    block_index=idx,
                )]
            return []

        if inner_type == "content_block_stop":
            idx = inner.get("index", -1)
            acc = self._tool_accumulators.pop(idx, None)
            if acc is not None:
                full_json = "".join(acc.buffer)
                try:
                    args = json.loads(full_json) if full_json else {}
                except json.JSONDecodeError:
                    args = acc.latest_draft or {}
                summary = _extract_tool_summary(acc.tool_name, args)
                return [StreamEvent(
                    type="tool_stop",
                    tool_name=acc.tool_name,
                    tool_args=args,
                    summary=summary,
                    tool_use_id=acc.tool_use_id,
                    block_index=idx,
                )]
            return []

        return []

    def _parse_assistant(self, data: dict) -> list[StreamEvent]:
        # stream-json wraps content inside a "message" envelope
        msg = data.get("message")
        if isinstance(msg, dict):
            blocks = msg.get("content")
        else:
            blocks = data.get("content")
        if not isinstance(blocks, list) or len(blocks) == 0:
            return []

        events: list[StreamEvent] = []
        text_parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                if self._saw_stream_events:
                    continue
                raw_name = block.get("name")
                canonical = _normalize_tool_name(raw_name)
                if canonical in KOAN_MCP_TOOLS:
                    continue
                args = block.get("input") or {}
                events.append(StreamEvent(
                    type="tool_call",
                    tool_name=canonical,
                    tool_args=args,
                    summary=_extract_tool_summary(canonical or "", args),
                ))
            # text and thinking blocks are streamed incrementally via
            # stream_event deltas (--include-partial-messages). Only
            # emit them from assistant messages as a fallback when no
            # stream_events were seen (e.g. partial-messages disabled).
            elif block_type == "text":
                text = block.get("text", "")
                text_parts.append(text)
                if not self._saw_stream_events:
                    events.append(StreamEvent(type="token_delta", content=text))
            elif block_type == "thinking" and not self._saw_stream_events:
                events.append(StreamEvent(
                    type="thinking",
                    is_thinking=True,
                    content=block.get("thinking") or block.get("text"),
                ))
        if text_parts:
            events.append(StreamEvent(type="assistant_text", content="".join(text_parts)))
        return events

    def _parse_result(self, data: dict) -> StreamEvent | None:
        subtype = data.get("subtype")
        if subtype == "success":
            return StreamEvent(type="turn_complete", content=data.get("result"))
        return StreamEvent(type="turn_complete")
