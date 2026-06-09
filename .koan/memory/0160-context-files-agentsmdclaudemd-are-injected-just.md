---
title: Context files (AGENTS.md/CLAUDE.md) are injected just-in-time as user messages
  on first tool-touch of a subtree, including for subagents
type: decision
created: '2026-06-04T14:14:36Z'
modified: '2026-06-04T14:14:36Z'
related:
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

koan injects project context files into every agent's conversation dynamically and just-in-time (`koan/tools/context_files.py`): the project-directory context file is seeded at loop start, and a subtree's context file is injected the first time the agent touches any path inside that subtree with a tool. `AGENTS.md` takes precedence over `CLAUDE.md` at each directory level; the walk ascends only up to the project root and never above it; `@`-imports inside context files are treated as opaque text and not expanded; and each agent dedupes via its own `injected_context_files` set so a file is injected at most once. Context is delivered as separate `<project_instructions>` USER messages, never folded into the system prompt, so the cacheable prefix stays byte-stable. The same mechanism applies to subagents. Leon's rationale: pay context tokens only for the subtrees an agent actually visits, and keep context out of the system prompt for cache stability. Alternatives rejected: a single global `~/.koan` context file, walking for context files above the project root, expanding `@`-imports, and statically injecting all context at boot.
