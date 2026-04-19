---
title: 'Three active workflows: plan, milestones (stub), curation'
type: context
created: '2026-04-16T08:37:42Z'
modified: '2026-04-16T08:37:42Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The koan workflow registry (`koan/lib/workflows.py`) defined three workflows as of 2026-04-16: `plan` (the primary active pipeline), `milestones` (a stub), and `curation` (standalone memory maintenance). Leon added the `curation` workflow when implementing the koan memory system, giving it its own `Workflow` dataclass in the `WORKFLOWS` dict in `koan/lib/workflows.py`. The `plan` workflow runs: intake -> plan-spec -> plan-review -> execute -> curation (postmortem). The `milestones` workflow ran intake only and was a stub as of 2026-04-16, intended for broad multi-subsystem initiatives but not yet implemented beyond the intake phase. The `curation` workflow runs a single curation phase using the `_STANDALONE_DIRECTIVE` string defined in `koan/lib/workflows.py` and is invoked when the user wants to maintain project memory outside of a development workflow run. Note: an earlier Claude Code project memory entry (written approximately 2026-04-08) listed only two workflows (plan and milestones); the curation workflow was added after that entry was written.
