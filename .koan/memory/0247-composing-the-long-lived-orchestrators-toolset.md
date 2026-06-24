---
title: Composing the long-lived orchestrator's toolset once at run start froze phase-conditional
  tools at the initial phase, so koan_request_executor was never available in execute
type: lesson
created: '2026-06-23T02:23:26Z'
modified: '2026-06-23T02:23:26Z'
related:
- 0157-tool-vocabulary-is-restricted-at-toolset.md
- 0243-koan-execution-unbundled-into-koanrequestexecutor.md
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The in-process orchestrator builds its PydanticAI toolset exactly once, at run() start, from the workflow's initial phase. When the tool vocabulary was phase-conditional at construction time (compose_toolset keyed on (role, phase)), that single build froze the vocabulary at the initial phase -- intake for the plan workflow -- and no later phase change recomposed it. koan_request_executor is allowed only in the execute phase, so it never entered the orchestrator's vocabulary; on reaching execute the orchestrator could not launch the executor and instead attempted to write the implementation itself. Root cause: compose_toolset was designed as if it ran per phase, but the long-lived orchestrator spans every phase on a single toolset build -- unlike one-shot scouts and executors, which legitimately compose once for their only phase. The defect was masked for koan_request_scouts because scouts are allowed in the initial phase (intake), so that tool stayed available throughout. The fix composes the orchestrator's vocabulary per role (static, full) and enforces phase-appropriateness at call time, so the once-per-run build no longer determines which phase-conditional tools are reachable.
