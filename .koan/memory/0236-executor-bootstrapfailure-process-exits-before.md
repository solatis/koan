---
title: Executor bootstrap_failure (process exits before first koan_complete_step)
  is usually a transient spawn issue; retry once before investigating
type: procedure
created: '2026-06-22T02:15:38Z'
modified: '2026-06-22T02:15:38Z'
---

koan spawns executor and scout subagents as separate processes that must complete a bootstrap handshake -- the agent's first koan_complete_step call -- before doing work; AgentState.first_turn_completed records success and the diagnostic code bootstrap_failure (stage 'handshake') records failure. When an executor exited with bootstrap_failure and the message "Process exited before first koan_complete_step call" (tokens_sent and tokens_received both zero, after roughly three minutes of heartbeats), no implementation work had been done and the working tree was unchanged; re-running the same executor handoff immediately succeeded. The response that worked: on a bootstrap_failure, treat it as a likely-transient subprocess-spawn or MCP-handshake fault rather than a defect in the plan or handoff, confirm the working tree is clean (git status) so no partial edits are stranded, and retry the executor once; investigate the executor backend (subprocess startup, MCP connection, credentials) only if the failure repeats. The zero-token signature distinguishes this from a model or tool failure mid-run, which would show non-zero usage.
