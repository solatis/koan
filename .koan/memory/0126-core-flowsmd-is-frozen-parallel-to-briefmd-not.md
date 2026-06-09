---
title: core-flows.md is frozen, parallel to brief.md, not disposable
type: decision
created: '2026-04-29T06:01:22Z'
modified: '2026-06-02T14:08:37Z'
related:
- 0100-artifact-design-doctrine-distinct-lifetimes.md
- 0101-intake-produces-briefmd-as-a-frozen-handoff.md
- 0103-plan-mnmd-is-disposable-compresses-into.md
---

This entry documents the lifetime decision for the `core-flows.md` artifact produced by the koan `core-flows` phase (`koan/phases/core_flows.py`), added on 2026-04-29. Leon decided on the `frozen` lifetime over a `disposable` default. Leon's stated rationale: the operational-behavior description in core-flows.md is part of the initiative's foundation, parallel to brief.md, and is read by every downstream phase (tech-plan-spec, tech-plan-review, milestone-spec, milestone-review, plan-spec, plan-review, exec-review, plus the executor via handoff in initiative-workflow runs) as authoritative behavioral spec. Rejected alternative: disposable (consumed by tech-plan-spec then superseded), which would have made core-flows.md a transient input only. Implementation consequences carried forward: docs/initiative.md's artifact table marks core-flows.md as frozen at core-flows exit; docs/artifacts.md carries a per-artifact lifecycle row reflecting the same; the core-flows phase module's write guidance instructs marking the artifact frozen in prose (the `status` frontmatter field that originally carried `Final` was removed project-wide on 2026-06-02); downstream phase guidance for tech-plan-spec, milestone-spec, and plan-spec in INITIATIVE_WORKFLOW references core-flows.md alongside brief.md and tech-plan.md as authoritative reading. The frozen lifetime aligns core-flows.md with brief.md -- the why-band and what-experience-band artifacts are both stable foundations; only the what-system band's tech-plan.md and the how-band's plan-milestone-N.md remain disposable in the initiative workflow.
