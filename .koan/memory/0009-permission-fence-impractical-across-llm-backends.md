---
title: Permission fence impractical across LLM backends; planned for removal
type: lesson
created: '2026-04-16T08:34:06Z'
modified: '2026-04-16T08:34:06Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The permission fence in koan (`koan/lib/permissions.py`) was initially designed as a load-bearing default-deny gate enforced on every MCP tool call. On 2026-02-10, Leon established it as Invariant 4 in `docs/architecture.md`, describing it as a load-bearing rule that blocked unknown roles and tools. By approximately 2026-04-08, Leon reversed this assessment, stating in a Claude Code project memory note that the fence is "probably not worth maintaining" because many coding agents do not support accurately disabling tool features, making the gate impractical to enforce reliably across different LLM backends. Leon identified the root cause: enforcement does not work reliably across LLM backends, and the maintenance cost outweighs the benefit. Leon directed that no effort should be invested in extending or hardening the permission fence and that it may be completely removed in a future update. The fence still exists in the codebase as of 2026-04-16, but is deprioritized; the architecture documentation was not updated to reflect this direction change and still describes it as load-bearing.
