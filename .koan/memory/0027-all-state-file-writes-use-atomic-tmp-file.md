---
title: All state file writes use atomic tmp-file + os.rename() to prevent partial
  reads under concurrent access
type: procedure
created: '2026-04-16T09:26:07Z'
modified: '2026-04-16T09:26:07Z'
related:
- 0004-file-boundary-invariant-llms-write-markdown.md
---

The koan driver in `koan/driver.py` and orchestrator tools in `koan/web/mcp_endpoint.py` write state files concurrently with a running web server and SSE subscribers. On 2026-04-16, the architecture documentation in `docs/architecture.md` established the atomic write pattern for all persistent state writes: write to a `.tmp` file, then call `os.rename()` to atomically replace the target. The maintainer recorded the rationale: a partial read of `state.json` caused by a mid-write concurrent access causes silent data corruption or spurious errors. The documented pattern was: `tmp = f"{file_path}.tmp"; json.dump(data, open(tmp, "w")); os.rename(tmp, file_path)`. This pattern was established as mandatory for: `run-state.json` in `~/.koan/runs/<run_id>/`, per-story `state.json` and `status.md` in `stories/{story_id}/`, per-subagent `task.json` written before spawn, and per-subagent `state.json` in the audit projection. The `koan/audit/event_log.py` module was documented as the canonical implementation of this pattern.
