---
title: Slim a protocol in the same change that deletes its last non-trivial implementor
  -- not before, not after
type: procedure
created: '2026-06-04T14:20:36Z'
modified: '2026-06-04T14:20:36Z'
related:
- 0025-scout-success-is-determined-by-exit-code-and.md
- 0154-koan-workflow-tools-and-subagents-run-in-process.md
---

When removing members from a shared protocol whose only real implementors are themselves slated for deletion, do the slim in the same change that deletes those implementors. In koan's `Agent` protocol, `register_process`, `exit_code`, and `stderr_output` were kept until the legacy CLI-runner agents were deleted, because `spawn_subagent` still derived a subagent's result from them and only those to-be-deleted agents implemented them meaningfully; removing them earlier would have stranded `spawn_subagent` with no result source, and removing them later would have carried dead protocol surface and dead `spawn_subagent` branches. Once the legacy agents are gone, `spawn_subagent` derives success or failure from a raised `AgentError` versus a clean completion plus the handshake check, not from a process exit code. The rule: sequence a protocol slim with the deletion of its last meaningful implementor -- earlier strands the callers that still depend on the members, later leaves dead surface.
