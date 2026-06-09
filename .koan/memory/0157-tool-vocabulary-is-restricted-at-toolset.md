---
title: Tool vocabulary is restricted at toolset-construction time (compose_toolset),
  not by a runtime permission fence
type: decision
created: '2026-06-04T14:14:07Z'
modified: '2026-06-04T14:14:07Z'
related:
- 0009-permission-fence-impractical-across-llm-backends.md
- 0053-new-read-only-memory-tools-must-be-added-to.md
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

koan restricts which tools an agent can call by composing the exact tool set per (role, phase) when the agent's toolset is built -- `compose_toolset(policy, role, phase)` in `koan/tools/tool_policy.py` -- so a disallowed tool never enters the model's context in the first place. This replaces the runtime `check_permission` gate (`koan/lib/permissions.py`), which validated every tool call as it happened. The allowlist DATA survives as a `ToolPolicy` dataclass; only the call-time GATE is removed. Composition is per (role, phase) and NOT per step, deliberately: holding the tool set byte-stable across the steps of a phase keeps the tool-definition prefix cache-stable (a step-granular toolset would invalidate the cache at every step boundary). Leon's rationale: in-process toolsets make construction-time vocabulary control free, and the runtime fence was impractical to enforce across LLM backends -- so withhold tools by never registering them rather than gating them on call. Rejected: keeping the runtime fence. A consequence: the one legacy step-level gate (a brief-generation read step) is dropped, having no active-workflow consumer.
