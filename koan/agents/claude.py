# ClaudeSDKAgent -- drives the Claude Agent SDK Python library behind the Agent
# Protocol. Replaces the interim koan/runners/claude.py ClaudeRunner adapter
# introduced in M1. The SDK spawns the Claude Code CLI subprocess internally;
# koan communicates with it via a typed Python message protocol rather than raw
# JSONL parsing.
#
# All claude_agent_sdk imports are lazy (inside run()) to avoid a circular import
# at module load time: koan/runners/__init__.py loads runner classes eagerly, which
# import from koan/agents/base.py, which triggers koan/agents/__init__.py to
# evaluate. A module-level SDK import here would be evaluated during that chain;
# lazy import defers it until the first actual run() call when the full module
# graph is already loaded.

from __future__ import annotations

import json
from typing import TYPE_CHECKING, AsyncIterator, Iterator

from ..logger import get_logger
from ..types import AgentInstallation, ModelInfo
from .base import AgentDiagnostic, AgentError, AgentOptions

if TYPE_CHECKING:
    from ..state import AppState
    from ..runners.base import StreamEvent

log = get_logger("claude_sdk_agent")


# Map internal thinking mode names to SDK effort values.
# xhigh -> max is the opus-only extended-thinking alias (preserved from ClaudeRunner).
_EFFORT_MAP: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
}

# Canonical tool name mappings for Claude's tool vocabulary.
# Migrated verbatim from koan/runners/claude.py.
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
    # Models occasionally emit numeric tool arguments as strings; coerce here
    # to match the leniency that the actual tools accept at call time.
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


def _extract_attachments(content: object) -> list[dict] | None:
    """Extract attachment metadata from a tool_result content field.

    Returns a list of dicts for any EmbeddedResource/ImageContent/file blocks
    found in the content list. Text blocks are excluded. Returns None when there
    are no attachment blocks (not an empty list, so callers can distinguish
    'no attachments' from 'zero attachment blocks after filtering').
    """
    if not isinstance(content, list):
        return None
    result: list[dict] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")
        if item_type not in ("image", "resource", "file"):
            continue
        a: dict = {}
        resource = item.get("resource") or {}
        if isinstance(resource, dict):
            if "mimeType" in resource:
                a["content_type"] = resource["mimeType"]
            uri = resource.get("uri", "")
            if uri:
                a["uri"] = uri
        source = item.get("source") or {}
        if isinstance(source, dict):
            if "media_type" in source and "content_type" not in a:
                a["content_type"] = source["media_type"]
        name = item.get("filename") or item.get("name") or resource.get("name", "")
        if name:
            a["filename"] = name
        if a:
            result.append(a)
    return result if result else None


def _tool_result_text(content: object) -> str:
    """Extract text payload from a tool_result block's content field.

    content is usually a string, but the API occasionally sends a list of
    content blocks. The SDK's ToolResultBlock.content is str | list[dict] | None.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text") or "")
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _parse_read_result(text: str) -> dict | None:
    """Parse Claude's Read tool output for line/byte metrics."""
    if not text:
        return None
    sr_idx = text.find("<system-reminder>")
    if sr_idx != -1:
        text = text[:sr_idx]
    lines = 0
    byte_total = 0
    any_numbered = False
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        tab_idx = stripped.find("\t")
        if tab_idx == -1:
            continue
        prefix = stripped[:tab_idx]
        if not prefix.isdigit():
            continue
        any_numbered = True
        content = stripped[tab_idx + 1:]
        lines += 1
        byte_total += len(content.encode("utf-8"))
    if not any_numbered:
        return None
    return {"lines_read": lines, "bytes_read": byte_total}


def _parse_grep_result(text: str) -> dict | None:
    """Parse Claude's Grep tool output for match/file metrics."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    sr_idx = text.find("<system-reminder>")
    if sr_idx != -1:
        text = text[:sr_idx].rstrip()
        if not text:
            return None
    first_line = text.splitlines()[0] if text else ""
    if first_line.lower().startswith("found "):
        import re
        m = re.search(r"found\s+(\d+)\s+matches?(?:\s+in\s+(\d+)\s+files?)?", first_line, re.IGNORECASE)
        if m:
            matches = int(m.group(1))
            files = int(m.group(2)) if m.group(2) else None
            result: dict = {"matches": matches}
            if files is not None:
                result["files_matched"] = files
            return result
        m = re.search(r"found\s+(\d+)\s+files?", first_line, re.IGNORECASE)
        if m:
            return {"matches": int(m.group(1)), "files_matched": int(m.group(1))}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    if all(":" in ln and ln.rsplit(":", 1)[-1].strip().isdigit() for ln in lines):
        total = sum(int(ln.rsplit(":", 1)[-1].strip()) for ln in lines)
        return {"matches": total, "files_matched": len(lines)}
    content_mode = True
    files_seen: set[str] = set()
    match_count = 0
    for ln in lines:
        parts = ln.split(":", 2)
        if len(parts) >= 3 and parts[1].strip().isdigit():
            files_seen.add(parts[0])
            match_count += 1
        else:
            content_mode = False
            break
    if content_mode and match_count > 0:
        return {"matches": match_count, "files_matched": len(files_seen)}
    if all(":" not in ln or not ln.split(":", 1)[-1][:1].isdigit() for ln in lines):
        n = len(lines)
        return {"matches": n, "files_matched": n}
    return None


def _parse_ls_result(text: str) -> dict | None:
    """Parse Claude's LS tool output for entry/directory metrics."""
    if not text:
        return None
    sr_idx = text.find("<system-reminder>")
    if sr_idx != -1:
        text = text[:sr_idx]
    entries = 0
    directories = 0
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if not stripped.startswith("- "):
            continue
        if indent == 0:
            continue
        name = stripped[2:].strip()
        if not name:
            continue
        entries += 1
        if name.endswith("/"):
            directories += 1
    if entries == 0:
        return None
    return {"entries": entries, "directories": directories}


class ClaudeSDKAgent:
    """SDK-driven Claude implementation behind the Agent Protocol.

    Wraps claude_agent_sdk.ClaudeSDKClient. Translates SDK Message types into
    koan StreamEvents inside the run() async iterator. Registers a PostToolUse
    hook at run time that drains the steering queue after every tool call and
    delivers steering text via additionalContext. HTTP MCP transport is used
    (same as CommandLineAgent) per brief decision 2.

    Lifecycle: one instance per subagent spawn. run(options) is called once;
    the caller iterates until the iterator terminates after a ResultMessage.
    interrupt() delegates to ClaudeSDKClient.interrupt(). compact() raises
    NotImplementedError per brief decision 3. register_process() is a no-op
    because the SDK manages its CLI subprocess internally.
    """

    name: str = "claude"

    def __init__(self, *, subagent_dir: str, app_state: AppState) -> None:
        """Create a ClaudeSDKAgent for one subagent spawn.

        app_state is stored for the PostToolUse hook closure, which needs
        access to the steering queue and the agent registry. subagent_dir is
        kept for interface consistency with CommandLineAgent (not used by the
        SDK directly; the SDK uses cwd from AgentOptions).
        """
        self._subagent_dir = subagent_dir
        self._app_state = app_state

        # Populated during run(); read after run() completes.
        self._client = None
        self._exit_code: int | None = None
        self._stderr_lines: list[str] = []
        # Maps tool_use_id -> canonical tool_name. Populated for every ToolUseBlock
        # except koan MCP tools; drained by the corresponding ToolResultBlock.
        self._tool_by_id: dict[str, str] = {}

    async def run(self, options: AgentOptions) -> AsyncIterator[StreamEvent]:
        """Run the agent and stream StreamEvents until the terminal ResultMessage.

        This is an async generator. The caller must iterate it to completion so
        cleanup (SDK disconnect) runs via the async-with context manager.

        PostToolUse hook is built as a closure capturing options.agent_id at
        run() call time so it is tied to this specific invocation rather than
        the Agent instance, which could in principle be reused.

        SDK errors are mapped to AgentError per the diagnostic mapping table
        in tech-plan.md: CLINotFoundError->binary_not_found,
        CLIConnectionError->sdk_connect_failed, ProcessError->agent_process_failed,
        CLIJSONDecodeError->protocol_decode_failed. bootstrap_failure is
        detected by spawn_subagent's handshake check after run() returns.
        """
        # Lazy SDK import: avoids the circular import that arises when this
        # module is evaluated during koan/agents/__init__.py initialization,
        # which happens early in the koan/runners/__init__.py chain.
        from claude_agent_sdk import (
            ClaudeAgentOptions,
            ClaudeSDKClient,
            CLIConnectionError,
            CLIJSONDecodeError,
            CLINotFoundError,
            HookMatcher,
            ProcessError,
            ResultMessage,
            UserMessage,
            AssistantMessage,
        )
        from ..runners.base import KOAN_MCP_TOOLS

        app_state = self._app_state
        agent_id = options.agent_id

        async def post_tool_use_hook(input, tool_use_id, context):
            """Drain the steering queue after every tool call.

            Registered as a PostToolUse hook on ClaudeAgentOptions so it fires
            after both built-in tools (Bash, Read, etc.) and koan MCP tools.
            This is the sole steering drain entry for Claude agents -- the
            MCP-handler path bypasses the queue for claude runner_type per the
            gate in mcp_endpoint.py:_drain_and_append_steering (Step 7).
            """
            agent_state = app_state.agents.get(agent_id)
            from .steering import drain_for_primary, render_text
            messages = drain_for_primary(app_state, agent_state)
            if not messages:
                return {}
            text = render_text(messages)
            previews = [m.content[:80] for m in messages]
            log.info(
                "steering delivered via PostToolUse hook | %d message(s): %s",
                len(messages), previews,
            )
            from ..events import build_steering_delivered
            app_state.projection_store.push_event(
                "steering_delivered",
                build_steering_delivered(len(messages)),
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": text,
                }
            }

        # Map AgentOptions.thinking to the SDK effort field.
        # When thinking is 'disabled' or None, omit effort entirely (None means
        # the SDK default, not the string "none"). Other values map directly.
        thinking = options.thinking
        effort = _EFFORT_MAP.get(thinking) if thinking and thinking != "disabled" else None

        stderr_callback = self._stderr_lines.append

        # Build add_dirs from project_dir, run_dir, and any additional dirs.
        # The SDK's add_dirs has the same per-tool directory-scoping semantics
        # as the CLI's --add-dir flag; empty strings are excluded.
        add_dirs = [
            d for d in (
                options.project_dir,
                options.run_dir,
                *options.additional_dirs,
            )
            if d
        ]

        # available_tools from AgentOptions maps to SDK 'tools' (the visible
        # tool vocabulary). allowed_tools maps to SDK 'allowed_tools' (the
        # auto-approved subset). Both are preserved to maintain today's
        # permission semantics: tools restricts what Claude sees; allowed_tools
        # restricts what runs without interactive approval.
        claude_options = ClaudeAgentOptions(
            model=options.model,
            system_prompt=options.system_prompt or None,
            mcp_servers={"koan": {"type": "http", "url": options.mcp_url}},
            tools=options.available_tools or None,
            allowed_tools=options.allowed_tools or [],
            add_dirs=add_dirs,
            cwd=options.cwd or None,
            permission_mode=options.permission_mode or None,
            hooks={"PostToolUse": [HookMatcher(matcher=None, hooks=[post_tool_use_hook])]},
            include_partial_messages=True,
            cli_path=options.installation.binary if options.installation else None,
            effort=effort,
            stderr=stderr_callback,
        )

        try:
            self._client = ClaudeSDKClient(options=claude_options)
            async with self._client:
                await self._client.connect(prompt=options.boot_prompt)
                async for msg in self._client.receive_messages():
                    for ev in self._translate_message(msg, KOAN_MCP_TOOLS, AssistantMessage, UserMessage, ResultMessage):
                        yield ev
                    if isinstance(msg, ResultMessage):
                        break
        except CLINotFoundError as e:
            raise AgentError(AgentDiagnostic(
                code="binary_not_found", agent="claude", stage="connect",
                message=str(e),
            )) from e
        except CLIConnectionError as e:
            raise AgentError(AgentDiagnostic(
                code="sdk_connect_failed", agent="claude", stage="connect",
                message=str(e),
            )) from e
        except ProcessError as e:
            raise AgentError(AgentDiagnostic(
                code="agent_process_failed", agent="claude", stage="stream",
                message=str(e),
            )) from e
        except CLIJSONDecodeError as e:
            raise AgentError(AgentDiagnostic(
                code="protocol_decode_failed", agent="claude", stage="stream",
                message=str(e),
            )) from e

    def _translate_message(
        self,
        msg: object,
        koan_mcp_tools: frozenset,
        AssistantMessage: type,
        UserMessage: type,
        ResultMessage: type,
    ) -> Iterator[StreamEvent]:
        """Translate one SDK Message into zero or more koan StreamEvents.

        AssistantMessage, UserMessage, and ResultMessage are passed as parameters
        (not imported at method level) to avoid re-importing inside every call;
        they are bound once inside run() and forwarded here. SDK StreamEvent
        objects (partial deltas from include_partial_messages) and RateLimitEvent
        are ignored -- we emit one big token_delta per TextBlock from the
        complete AssistantMessage rather than incremental deltas.
        """
        from ..runners.base import StreamEvent

        if isinstance(msg, AssistantMessage):
            # Translate the complete assistant turn into koan stream events.
            # ToolUseBlocks for koan MCP tools are skipped entirely (neither
            # tracked nor emitted) to avoid noise in the tool event stream.
            text_parts: list[str] = []
            for block in msg.content:
                block_type = type(block).__name__
                if block_type == "TextBlock":
                    text_parts.append(block.text)
                    yield StreamEvent(type="token_delta", content=block.text)
                elif block_type == "ThinkingBlock":
                    yield StreamEvent(
                        type="thinking",
                        is_thinking=True,
                        content=block.thinking,
                    )
                elif block_type == "ToolUseBlock":
                    canonical = _normalize_tool_name(block.name)
                    if canonical in koan_mcp_tools:
                        # Koan MCP tool calls are handled via HTTP MCP; do not
                        # surface them as tool stream events or track their IDs.
                        continue
                    self._tool_by_id[block.id] = canonical or block.name
                    args = block.input or {}
                    summary = _extract_tool_summary(canonical or block.name, args)
                    yield StreamEvent(
                        type="tool_start",
                        tool_name=canonical,
                        tool_use_id=block.id,
                    )
                    yield StreamEvent(
                        type="tool_input_delta",
                        tool_name=canonical,
                        tool_args=args,
                        content=json.dumps(args) if args else "",
                        tool_use_id=block.id,
                        summary=summary,
                    )
            if text_parts:
                yield StreamEvent(type="assistant_text", content="".join(text_parts))

        elif isinstance(msg, UserMessage):
            # Tool results arrive in UserMessage content as ToolResultBlock objects.
            # Emit one tool_result StreamEvent per tracked (non-MCP) tool result.
            content = msg.content
            if not isinstance(content, list):
                return
            for block in content:
                if type(block).__name__ != "ToolResultBlock":
                    continue
                tool_use_id = block.tool_use_id
                tool_name = self._tool_by_id.pop(tool_use_id, None)
                if tool_name is None:
                    # Not tracked -- koan MCP tool result or unknown; skip.
                    continue
                raw_content = block.content
                text = _tool_result_text(raw_content)
                if tool_name == "read":
                    metrics = _parse_read_result(text)
                elif tool_name == "grep":
                    metrics = _parse_grep_result(text)
                elif tool_name == "ls":
                    metrics = _parse_ls_result(text)
                else:
                    metrics = None
                attachments = _extract_attachments(raw_content)
                yield StreamEvent(
                    type="tool_result",
                    tool_name=tool_name,
                    tool_use_id=tool_use_id,
                    content=text,
                    metrics=metrics,
                    attachments=attachments,
                )

        elif isinstance(msg, ResultMessage):
            # Terminal signal. Set exit_code based on success/error.
            self._exit_code = 0 if msg.subtype == "success" else 1
            yield StreamEvent(
                type="turn_complete",
                content=msg.result if msg.subtype == "success" else None,
            )

        # SDK StreamEvent (partial delta), RateLimitEvent, SystemMessage, and any
        # other message types are intentionally ignored. We rely on the complete
        # AssistantMessage/UserMessage/ResultMessage for all stream events.

    async def interrupt(self) -> None:
        """Interrupt the current generation by calling ClaudeSDKClient.interrupt().

        No caller is wired in M2 per brief decision 10; the method exists for
        future integration without a Protocol contract change.
        """
        if self._client is not None:
            await self._client.interrupt()

    async def compact(self) -> None:
        """Not supported -- the Claude Agent SDK does not expose programmatic compaction."""
        raise NotImplementedError(
            "Claude Agent SDK does not expose programmatic compaction."
        )

    def register_process(self, registry: dict, agent_id: str) -> None:
        """No-op: the SDK manages its own CLI subprocess internally.

        The shutdown path that consults app_state._active_processes finds no
        entry for this agent; cancellation is deferred to a future interrupt()
        integration per brief decision 10.
        """

    @property
    def exit_code(self) -> int | None:
        """Exit code derived from ResultMessage.subtype. None until run() completes."""
        return self._exit_code

    @property
    def stderr_output(self) -> str:
        """Accumulated stderr lines from the SDK's stderr callback."""
        return "".join(self._stderr_lines)

    @classmethod
    def list_models(cls, installation: AgentInstallation) -> list[ModelInfo]:
        """Return the hardcoded Opus/Sonnet/Haiku model list.

        The model list is static; no SDK call is needed. The installation
        parameter is accepted for Protocol conformance but not used. The alias
        'opus[1m]' is preserved verbatim -- registry profiles and tests reference it.
        """
        return [
            ModelInfo(
                alias="opus[1m]",
                display_name="Opus",
                thinking_modes=frozenset({"disabled", "low", "medium", "high", "xhigh"}),
                tier_hint="strong",
            ),
            ModelInfo(
                alias="sonnet",
                display_name="Sonnet",
                thinking_modes=frozenset({"disabled", "low", "medium", "high"}),
                tier_hint="standard",
            ),
            ModelInfo(
                alias="haiku",
                display_name="Haiku",
                thinking_modes=frozenset({"disabled", "low", "medium", "high"}),
                tier_hint="cheap",
            ),
        ]
