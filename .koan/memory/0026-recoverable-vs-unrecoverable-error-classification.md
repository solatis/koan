---
title: Recoverable vs unrecoverable error classification for model tool-call failures;
  recoverable errors return a structured error for self-correction
type: decision
created: '2026-04-16T09:25:58Z'
modified: '2026-06-05T01:55:27Z'
related:
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
- 0002-step-first-workflow-pattern-boot-prompt-is.md
---

koan classifies model-driven tool-call failures into recoverable and unrecoverable -- a two-category rule Leon established -- and only the unrecoverable ones fail fast. Recoverable conditions (malformed tool-call JSON or arguments from the model, tool-argument schema validation failures, and disallowed or unknown tool calls) are returned to the model as a structured tool error so it can self-correct and retry within the same conversation rather than aborting. Unrecoverable conditions (invariant or contract violations such as a missing or malformed `task.json` at subagent startup, states with no safe deterministic next action, and failures with no simple local recovery) fail fast. The rationale: once the agent loses its in-progress conversation it cannot resume mid-step, so keeping the conversation alive and handing the model a correctable error is the only way to preserve continuity for recoverable faults. This governs the in-process koan tool handlers; note that pydantic-ai's `agent.iter()` can swallow exceptions raised inside a tool handler, so a recoverable error is surfaced as a returned structured error rather than a raised exception the loop might silently absorb.
