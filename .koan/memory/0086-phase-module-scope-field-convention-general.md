---
title: 'Phase module SCOPE field convention: general = reusable, workflow-name = specific'
type: decision
created: '2026-04-23T13:24:49Z'
modified: '2026-04-23T13:24:49Z'
---

The koan phase module system (`koan/phases/`) uses the `SCOPE` field on each module to indicate its reuse policy across workflows. On 2026-04-23, as part of the milestones workflow implementation, Leon confirmed the convention: `SCOPE="general"` means the module is reusable by any workflow via a `PhaseBinding` in `koan/lib/workflows.py`; `SCOPE="<workflow_name>"` (e.g., `SCOPE="milestones"`) means the module is specific to that workflow only. As part of this work, `plan_spec.py` and `plan_review.py` were changed from `SCOPE="plan"` to `SCOPE="general"` so they could serve both the plan and milestones workflows without duplication. Workflow-specific framing (artifact filename, review target, etc.) is injected at runtime via `PhaseBinding.guidance`, not hardcoded in the module body. Leon's rationale: workflows should compose from shared phase building blocks; duplicating phase logic per workflow creates divergence over time. Modules with `SCOPE="milestones"` as of 2026-04-23: `milestone_spec.py`, `milestone_review.py`. Modules with `SCOPE="general"`: `intake.py`, `plan_spec.py`, `plan_review.py`, `execute.py`, `executor.py`, `exec_review.py`, `curation.py`.
