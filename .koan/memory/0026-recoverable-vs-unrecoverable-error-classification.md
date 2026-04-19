---
title: Recoverable vs unrecoverable error classification for model-output failures
  in the MCP endpoint
type: decision
created: '2026-04-16T09:25:58Z'
modified: '2026-04-16T09:25:58Z'
related:
- 0002-step-first-workflow-pattern-boot-prompt-is.md
---

The koan MCP endpoint in `koan/web/mcp_endpoint.py` handles tool calls from LLM subagents. On 2026-04-16, the architecture documentation in `docs/architecture.md` established a two-category error classification. The maintainer recorded the rule: fail-fast is scoped to unrecoverable conditions only. Unrecoverable conditions were defined as: invariant/contract violations (e.g., missing or malformed `task.json` at subagent startup), unexpected states where there is no safe deterministic next action, and failures with no simple local recovery path. Recoverable conditions were defined as: malformed tool-call JSON or arguments from the LLM, tool argument schema validation failures, and disallowed or unknown tool calls. The documented handling for recoverable errors was: return a structured tool error so the model can self-correct and retry in the same subagent process. The maintainer noted the rationale: once an LLM subagent process exits due to a parse error, the workflow cannot resume from mid-step -- keeping the process alive for recoverable errors is the only way to maintain continuity.
