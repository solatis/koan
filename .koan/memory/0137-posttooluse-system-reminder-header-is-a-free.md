---
title: PostToolUse:* system-reminder header is a free diagnostic for steering tool-boundary
  triggers
type: procedure
created: '2026-05-04T07:56:10Z'
modified: '2026-05-04T07:56:10Z'
related:
- 0130-agent-abstraction-in-koanagents-replaces-runner.md
---

This entry documents an observability technique for steering delivery in koan's Claude Agent SDK integration (`koan/agents/claude.py post_tool_use_hook`). On 2026-05-04, during a live audit verification of the SDK steering hook implementation, the agent observed that the `<system-reminder>` block emitted by the SDK when the PostToolUse hook returns `additionalContext` includes a header line of the form `PostToolUse:{tool_name}` (e.g. `PostToolUse:Bash`, `PostToolUse:mcp__koan__koan_complete_step`, `PostToolUse:Read`). The header names the specific tool whose completion triggered the drain.

This is a free diagnostic: no debug logs are required to determine which tool boundary delivered a steering message. The header is part of the system-reminder source the LLM receives. For operators investigating steering delivery, this means the system-reminder's first line distinguishes "drained on a built-in tool boundary" (e.g. Bash, Read) from "drained on a koan MCP tool boundary" (e.g. mcp__koan__koan_complete_step). The distinction is the operational deliverable of the SDK migration -- pre-SDK Claude could only drain at koan MCP boundaries.

Future agents debugging steering delivery in Claude runs should look at the system-reminder source directly, not only the `<steering>` content. The header tells which tool boundary fired the hook. This complements the existing log line `steering delivered via PostToolUse hook | ...` in `koan/agents/claude.py`, which logs the drain but not the originating tool name.
