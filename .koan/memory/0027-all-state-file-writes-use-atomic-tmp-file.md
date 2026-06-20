---
title: All state file writes use atomic tmp-file + os.rename() to prevent partial
  reads under concurrent access
type: procedure
created: '2026-04-16T09:26:07Z'
modified: '2026-06-20T03:38:21Z'
related:
- 0004-file-boundary-invariant-llms-write-markdown.md
---

The koan driver (`koan/driver.py`) and the in-process orchestrator tool layer (`koan/tools/koan_tools.py`) write state files concurrently with a running web server and SSE subscribers, so all persistent state writes use an atomic pattern: write the payload to a sibling `.tmp` path, then `os.rename()` it onto the target. Rationale: a partial read of a state file caused by mid-write concurrent access produces silent data corruption or spurious errors, and `os.rename()` on the same filesystem is atomic, so a reader sees either the old file or the new one, never a truncation. The pattern is mandatory for every persistent state file koan writes: `run-state.json` in `~/.koan/runs/<run_id>/`, the per-subagent `task.json` written before spawn, and the per-subagent `state.json` in the audit projection. `koan/audit/event_log.py` is the canonical implementation. Violating this -- writing JSON in place -- risks the driver, the web server, or an SSE subscriber observing a truncated file.
