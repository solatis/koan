---
title: Phase guidance (workflow scope framing) is injected at the top of step 1, before
  procedural instructions
type: decision
created: '2026-04-16T09:03:03Z'
modified: '2026-04-16T09:03:03Z'
related:
- 0002-step-first-workflow-pattern-boot-prompt-is.md
- 0015-three-active-workflows-plan-milestones-stub.md
---

The koan orchestration system injects per-workflow scope framing into each phase transition via the `phase_guidance` dict in `koan/lib/workflows.py`. On 2026-04-03, the workflow redesign plan (`plans/2026-04-03-workflow-types-and-plan-mode.md`) established Decision D8: the `phase_guidance` injection must appear at the TOP of step 1 guidance, before procedural instructions, not appended at the bottom. The maintainer recorded the rationale: scope framing is the strongest lever for controlling LLM posture -- "this is a focused change" produces fundamentally different behavior than "this is a broad initiative." If the LLM reads procedural instructions before scope framing, it begins reasoning from the wrong posture and receives the correction too late. The injection contract established by the maintainer specified five required sections per `phase_guidance` entry: Scope, Downstream consumer, Investigation posture, Question posture, and User override (always present, always last). In `koan/web/mcp_endpoint.py`, the `koan_set_phase` handler was designed to store `workflow.phase_guidance.get(phase, "")` in `PhaseContext.phase_instructions`, which step 1 of each phase module renders at the top of the returned guidance string.
