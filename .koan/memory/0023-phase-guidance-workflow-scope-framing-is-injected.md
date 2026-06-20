---
title: Phase guidance (workflow scope framing) is injected at the top of step 1, before
  procedural instructions
type: decision
created: '2026-04-16T09:03:03Z'
modified: '2026-06-20T03:26:03Z'
related:
- 0002-step-first-workflow-pattern-boot-prompt-is.md
- 0015-three-active-workflows-plan-milestones-stub.md
---

koan injects per-workflow scope framing into each phase transition via the `phase_guidance` dict in `koan/lib/workflows.py`. Leon's decision: this framing must render at the TOP of step 1 guidance, before procedural instructions -- not appended at the bottom. Rationale: scope framing is the strongest lever for controlling LLM posture -- a focused-change framing produces fundamentally different behavior than a broad-initiative framing; if the LLM reads procedural instructions before scope framing, it begins reasoning from the wrong posture and receives the correction too late. Each `phase_guidance` entry is authored as a small set of fixed sections (scope, investigation and question posture, downstream consumer) with a user-override clause kept always-last so the user can deviate from any preset. Mechanically, the `koan_set_phase` handler (`apply_set_phase` in `koan/tools/koan_tools.py`) stores the phase's `phase_guidance` text (empty when the phase has none) into `PhaseContext.phase_instructions`, which each phase module's step 1 renders at the top of its returned guidance string.
