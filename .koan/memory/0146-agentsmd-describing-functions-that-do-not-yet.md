---
title: AGENTS.md describing functions that do not yet exist creates implicit pressure
  for executor agents to fulfil the claim outside plan scope
type: lesson
created: '2026-05-08T07:31:31Z'
modified: '2026-05-08T07:31:31Z'
related:
- 0123-llm-generated-task-prompts-can-assert-deleted.md
- 0089-proactively-capture-memory-updates-for-discovered.md
- 0140-tools-and-allowedtools-mirror-each-other-for.md
---

This entry records a scope-creep observation during a koan plan workflow on 2026-05-08 addressing maximization of Claude thinking visibility. The plan in plan.md was scoped strictly to Claude thinking/effort configuration: pyproject.toml pin, `koan/types.py` ThinkingMode and ROLE_EFFORT, `koan/agents/claude.py` rewire and per-model accuracy, `koan/agents/registry.py` branching and clamping, plus tests and `docs/agent-protocol.md`. The plan did not touch `koan/subagent.py`, `koan/agents/command_line.py`, AGENTS.md, or `docs/subagents.md`.

The executor delivered all plan-targeted changes correctly and in addition refactored the Claude tool whitelists: `CLAUDE_TOOL_WHITELISTS` in `koan/subagent.py` was migrated from CSV strings to lists, a new helper `_build_claude_tool_lists(role)` was added, the `Task*` family was removed from the executor whitelist, and dead `_claude_post_build_args` was pruned from `koan/agents/command_line.py`. AGENTS.md and `docs/subagents.md` were updated to match. All 712 tests passed. exec-review classified the deviation as "Minor" because the changes were memory-aligned (pre-existing memory entries dated 2026-05-05 already documented the tool-whitelist design) and risk-free.

Root cause: AGENTS.md text already read, "The same per-role list is passed as both Claude's `--tools` (visible vocabulary) and `--allowedTools` (auto-approved subset); the two fields are kept identical by design ... See `_build_claude_tool_lists` in `koan/subagent.py`." The function `_build_claude_tool_lists` did NOT exist in `koan/subagent.py`; AGENTS.md described code that had not yet landed. The executor, reading AGENTS.md as authoritative project context, "fulfilled" the documentation by creating the missing helper -- expanding the diff scope by roughly five files beyond plan.md targets.

Lesson: when AGENTS.md, memory entries, or docs/ describe code patterns that have not yet landed, executor agents may treat implementation as implicit in-scope and expand the diff. The mirror failure mode (LLM prompts asserting deleted code as still live) is captured separately; both directions trace to the same root drift between docs and code. Two procedural mitigations: (a) AGENTS.md and docs/ should be updated alongside the code that supports their claims, never ahead of it; (b) plan-spec scoping decisions should explicitly include or exclude memory- and AGENTS.md-derived adjacent concerns, especially when the plan touches files those concerns reference.
