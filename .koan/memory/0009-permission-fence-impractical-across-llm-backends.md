---
title: Permission fence impractical across LLM backends; replaced by construction-time
  toolset composition
type: lesson
created: '2026-04-16T08:34:06Z'
modified: '2026-06-04T14:26:17Z'
related:
- 0157-tool-vocabulary-is-restricted-at-toolset.md
---

The permission fence in koan (`koan/lib/permissions.py`) was first designed as a load-bearing default-deny gate (`check_permission`) enforced on every MCP tool call, documented as a load-bearing invariant in `docs/architecture.md`. Leon later reversed that assessment: the gate is impractical to enforce reliably across different LLM backends because many coding agents do not support accurately disabling tool features, so the maintenance cost outweighs the benefit. Root cause: runtime per-call enforcement does not work uniformly across backends. The resolution is now in place on the agent path: tool vocabulary is restricted at toolset-construction time -- `compose_toolset` in `koan/tools/tool_policy.py` composes the exact tool set per (role, phase) so a disallowed tool is never registered into the model's context -- rather than gated on each call. The allowlist data survives as a `ToolPolicy`; only the call-time gate is retired. The lesson that generalizes: enforce capability restrictions by construction (never offering the capability) rather than by a runtime gate that depends on backend cooperation.
