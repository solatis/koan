---
title: Surface cascading doc-amendment scope as an explicit user question in intake
type: procedure
created: '2026-04-29T06:00:46Z'
modified: '2026-04-29T06:00:46Z'
related:
- 0089-proactively-capture-memory-updates-for.md
---

This entry records a procedural pattern that emerged during the 2026-04-29 koan initiative+discovery workflow-presets intake. After Leon answered the first round of questions ("convention-only acceptance gate", "core-flows.md frozen", "discovery single-phase"), the orchestrator identified that those choices cascaded into doc-amendment scope expansion not named in the original task prompt: docs/initiative.md (Approved-gate language and core-flows lifetime row), docs/workflow-phases.md (tech-plan-review section and producer-and-acceptance summary), and docs/artifacts.md (stale Write-tools section plus missing core-flows.md / tech-plan.md rows). Rather than burying these as unstated assumptions in brief.md, the orchestrator surfaced a follow-up koan_ask_question with three scope options (full / targeted / minimum), and Leon chose full. Without that explicit surfacing, the implementation would have shipped with multiple docs disagreeing with the live behavior at land time. Procedure for future intake runs: when intake-stage decisions visibly invalidate passages in docs that the original task prompt did NOT name, do not treat the doc-amendment scope as inferred -- ask the user with an explicit option set (full / targeted / minimum) so the trade-off is on the record. Pairs naturally with the proactive-capture-of-inconsistencies-outside-current-task-scope rule (recorded separately) but is intake-time-specific: this is the surface-as-question moment, not the curation-time write moment.
