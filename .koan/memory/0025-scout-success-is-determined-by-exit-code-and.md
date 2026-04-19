---
title: Scout success is determined by exit code and final_response, not by file existence
type: procedure
created: '2026-04-16T09:25:55Z'
modified: '2026-04-16T09:25:55Z'
related:
- 0006-directory-as-contract-taskjson-over-cli-flags-for.md
---

Koan scouts are spawned via `koan_request_scouts` in `koan/web/mcp_endpoint.py` and each produces a `findings.md` output file in their subagent directory under `~/.koan/runs/<run_id>/subagents/`. On 2026-04-16, the architecture documentation in `docs/architecture.md` established that scout success must be derived from the subagent's exit code and final response, not from checking whether `findings.md` exists. The maintainer recorded the rationale: a scout can write a partial `findings.md` and then crash -- file existence is not proof of completion. The documented success check in `koan/web/mcp_endpoint.py` was: `succeeded = result.exit_code == 0; findings = result.final_response or None`. Failed scouts (non-zero exit code) return `None` from the scout runner and are omitted from the concatenated findings returned to the parent orchestrator. The maintainer established that scout failures must be non-fatal -- a failed scout does not abort the parent's workflow; its task ID is reported in the `failures` array and its findings are simply omitted.
