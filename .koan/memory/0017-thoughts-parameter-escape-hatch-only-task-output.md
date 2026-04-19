---
title: '`thoughts` parameter -- escape hatch only; task output goes to files'
type: procedure
created: '2026-04-16T09:00:44Z'
modified: '2026-04-16T09:00:44Z'
related:
- 0004-file-boundary-invariant-llms-write-markdown.md
- 0002-step-first-workflow-pattern-boot-prompt-is.md
---

The `koan_complete_step` tool in the koan orchestration system accepts a `thoughts` parameter. On 2026-04-16, the architecture documentation in `docs/subagents.md` established that `thoughts` must never be used to capture task output: the `thoughts` parameter is an escape hatch only. The rationale recorded in that document: some models (particularly weaker ones) cannot produce text output and a tool call in the same response turn; `thoughts` gives those models a way to call the tool without exiting the workflow. Task output -- summaries, reports, structured data, findings -- was established to go exclusively to files such as `findings.md`, `landscape.md`, and `plan.md` in the run directory at `~/.koan/runs/<run_id>/`. The driver, which runs in `koan/driver.py`, reads those files after the subagent exits; it does not read `thoughts` content, and `thoughts` values are not preserved in the audit log (`events.jsonl`). Any subagent that extracts output through `thoughts` rather than file writes creates a silent data loss path.
