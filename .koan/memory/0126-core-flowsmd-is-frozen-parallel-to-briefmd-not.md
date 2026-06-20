---
title: core-flows.md is frozen, parallel to brief.md, not disposable
type: decision
created: '2026-04-29T06:01:22Z'
modified: '2026-06-20T04:28:35Z'
related:
- 0100-artifact-design-doctrine-distinct-lifetimes.md
- 0101-intake-produces-briefmd-as-a-frozen-handoff.md
- 0103-plan-mnmd-is-disposable-compresses-into.md
---

The `core-flows.md` artifact produced by koan's `core-flows` phase (`koan/phases/core_flows.py`) has a `frozen` lifetime, a decision Leon made over a `disposable` default. Rationale: the operational-behavior description in core-flows.md is part of the initiative's foundation, parallel to brief.md, and is read as authoritative behavioral spec by every downstream initiative phase -- tech-plan, milestone, plan, execute -- plus the executor via handoff. Rejected alternative: disposable (consumed by tech-plan then superseded), which would have made core-flows.md a transient input only. Implementation consequences: docs/initiative.md's artifact table marks core-flows.md frozen at core-flows exit; docs/artifacts.md carries the matching per-artifact lifecycle row; the core-flows phase module's write guidance instructs marking the artifact frozen in prose (koan removed the `status` frontmatter field that once carried `Final`); and the tech-plan, milestone, and plan phase guidance in INITIATIVE_WORKFLOW references core-flows.md alongside brief.md and tech-plan.md as authoritative reading. The frozen lifetime aligns core-flows.md with brief.md -- the why-band and what-experience-band artifacts are both stable foundations; only the what-system band's tech-plan.md and the how-band's plan-milestone-N.md remain disposable in the initiative workflow.
