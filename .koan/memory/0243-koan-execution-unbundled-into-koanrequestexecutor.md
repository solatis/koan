---
title: koan execution unbundled into koan_request_executor and made repeatable; koan_set_phase
  is pure routing; the subagent-launch rule
type: decision
created: '2026-06-22T22:50:13Z'
modified: '2026-06-22T22:50:13Z'
related:
- 0241-koan-artifact-lifecycle-living-documents-with.md
---

koan's execution handoff was unbundled. `koan_set_phase` is now pure routing (no `plan_file` parameter, no spawn), and a new `koan_request_executor(plan_file?, instructions?)` tool (`koan/tools/koan_tools.py`, registered for the orchestrator in the execute phase via `koan/tools/tool_policy.py`) launches the blocking executor and returns its deviation report; `instructions` is required when no `plan_file` is given. The same plan may be re-run any number of times; the remediation-successor chain (the `plan-remediation-K` grammar, `next_remediation_name`, `predecessor_chain`) was removed. The execute phase is now Run / Verify / Reconcile: the orchestrator launches the executor, runs authoritative bash verification, records the outcome inline (`## Execution N`), and either advances or re-runs -- re-execution is the orchestrator's own agency (calling `koan_request_executor` again), not a `get_next_step` loop. Leon governed this with the subagent-launch rule: launch a subagent mechanically exactly when its task is fully determined by artifacts already on disk (the reviewer, on `koan_artifact_write`), and via an explicit `koan_request_*` tool when the orchestrator must communicate intent (the executor -- which plan, whether to re-run, what to fix; and scouts). This reverses an earlier koan decision that had rejected a standalone `koan_request_executor` in favor of bundling execution into `koan_set_phase`; Leon stated "I was wrong", because bundling made re-execution unrepresentable (`koan_set_phase` rejects self-transitions, so re-running from within execute was impossible) and hid a communication act inside a routing primitive. Alternatives rejected: keep `set_phase('execute', plan_file=...)` and special-case re-execution (a hack around the self-transition mismatch); make the reviewer explicit for symmetry (it carries no orchestrator intent, so mechanical is correct).
