---
title: Scout success is determined by clean completion and final_response, not by
  findings.md existence
type: procedure
created: '2026-04-16T09:25:55Z'
modified: '2026-06-04T14:27:02Z'
related:
- 0170-slim-a-protocol-in-the-same-change-that-deletes.md
- 0006-directory-as-contract-taskjson-over-cli-flags-for.md
---

koan scouts are spawned via `koan_request_scouts` and each writes a `findings.md` in its subagent directory, but a scout's success is determined by whether it completed cleanly and returned a final response -- not by whether `findings.md` exists. The rationale: a scout can write a partial `findings.md` and then fail, so file existence is not proof of completion. With subagents running in-process, `spawn_subagent` derives success from a clean run versus a raised `AgentError` (an `AgentError` means failure) and takes the scout's findings from its final response; a scout that fails contributes no findings. Scout failures are non-fatal to the parent: a failed scout does not abort the orchestrator's workflow -- its task id is reported in the failures list and its findings are simply omitted from the concatenation returned to the parent. The wrong approach is to gate on `findings.md` existence; it conflates a partial write with a completed investigation.
