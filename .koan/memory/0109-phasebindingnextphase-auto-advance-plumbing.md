---
title: Per-binding auto-advance via PhaseBinding.next_phase replaces format_phase_complete
  trampoline
type: decision
created: '2026-04-26T09:32:34Z'
modified: '2026-06-19T12:20:43Z'
---

On 2026-04-26, Leon shifted koan's workflow control flow (`koan/lib/workflows.py`, `koan/phases/format_step.py`) from phase-end-trampoline yields to per-binding auto-advance. The change: `PhaseBinding` gained an optional `next_phase: str | None = None` field; `PhaseContext` gained `next_phase` and `suggested_phases` populated at the step-handshake site. A pure helper `terminal_invoke(next_phase, suggested_phases)` in `koan/phases/format_step.py` renders the last-step `invoke_after` directive: `koan_set_phase("X")` (auto-advance) when bound, `koan_yield(suggestions=[...])` (full yield) when None, including an explicit override clause ('If exceptional circumstances warrant user direction, call koan_yield instead'). The `format_phase_complete` trampoline was deleted. Auto-advance is GUIDANCE not enforcement -- the orchestrator may yield instead when warranted (documented in `docs/guided-transitions.md`); the yolo/`directed_phases` short-circuit is independent.

**Update (feat/epoch refactor):** the specific bindings are superseded by the new phase set {intake, core-flows, tech-plan, milestone, plan, execute, curation, frame} -- the *-review phases were removed, and the execute phase carries next_phase=None because the inline post-execution review outcome (clean vs remediation) determines the path. The per-binding auto-advance MECHANISM (PhaseBinding.next_phase plus the terminal_invoke helper rendering koan_set_phase auto-advance when bound vs koan_yield when None) is unchanged.
