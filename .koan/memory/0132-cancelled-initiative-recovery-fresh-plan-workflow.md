---
title: Cancelled-initiative recovery -- fresh plan workflow with original run's artifacts
  as inputs
type: procedure
created: '2026-05-02T07:23:22Z'
modified: '2026-05-02T07:23:22Z'
related:
- 0122-brief-contradictions-discovered-downstream-are-resolved-in-the-consumer-artifact-not-by-amending-the-frozen-brief.md
---

The koan workflow engine (`koan/driver.py`, `koan/lib/workflows.py`) has no native primitive for resuming a cancelled `initiative` or `milestones` run mid-flight. Run-state -- the orchestrator's phase counter, `workflow_history`, in-memory `PhaseContext` -- is per-process and is not portable across orchestrator spawns. On 2026-05-02, user encountered a cancelled Claude Agent SDK migration at `~/.koan/runs/1777448300-422e9a02/` (the agent-abstraction and SDK-adapter milestones were complete; the documentation milestone's plan was finalized but never executed) and asked the agent to "plan to complete the work" in a new run. The agent surfaced two recovery paths in intake: re-plan from scratch in a fresh `plan` workflow with the cancelled run's `milestones.md` and `plan-milestone-N.md` as intake inputs, OR execute the already-finalized `plan-milestone-N.md` directly. User directed re-plan-fresh on 2026-05-02. Rationale captured in the new plan's brief: re-planning produced a focused single-purpose plan workflow rooted in the latest codebase state; direct execution risked shipping a plan whose assumptions had drifted since it was written (the SDK-adapter milestone's deletions had landed in the interim). On the same date, user adopted the recovery procedure -- read the cancelled run's `brief.md`, `milestones.md`, and the most-recent `plan-milestone-N.md` as intake inputs; produce a fresh `brief.md` scoping only the leftover work; produce a fresh `plan.md`; execute. The original run's artifacts are inputs, not outputs to amend -- the cancelled run's frozen `brief.md` is read-only, and any contradiction discovered downstream resolves in the consumer artifact (the new plan workflow's `brief.md`).
