---
title: PhaseContext resets on koan_set_phase -- orchestrator loop state must live
  in artifact files
type: decision
created: '2026-04-23T13:24:55Z'
modified: '2026-06-20T04:13:05Z'
related:
- 0004-file-boundary-invariant-llms-write-markdown-driver.md
---

The milestones workflow orchestrator loop in koan (`koan/lib/workflows.py`, `koan/phases/milestone_spec.py`) relies on `milestones.md` as its persistent cross-phase state store. The rule: `PhaseContext` (defined in `koan/phases/__init__.py`) is reset on every `koan_set_phase()` transition. The milestone loop -- the milestone phase once to decompose, then a repeating `plan -> execute` per milestone -- spans many `koan_set_phase` transitions, so any in-memory tracking of the current milestone number or status would be lost between phases. The design decision: `milestones.md` in the run directory (`~/.koan/runs/<id>/milestones.md`) is the single source of truth for milestone state, using status markers `[pending]`, `[in-progress]`, `[done]`, `[skipped]`; the orchestrator reads it fresh at each phase entry to find the current milestone. Alternatives rejected: a `current_milestone` field on `PhaseContext` (survives within a phase only, lost on transition); milestone state in `run-state.json` (violates the file boundary invariant -- LLMs do not write JSON).
