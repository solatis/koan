---
title: koan_yield removed; the terminal-text turn is the hand-back, with suggestions
  from koan_suggest_next or build_phase_suggestions
type: decision
created: '2026-06-04T14:14:18Z'
modified: '2026-06-05T13:06:21Z'
related:
- 0016-steering-vs-phase-boundary-message-routing-dual.md
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

The orchestrator hands control back to the user not by calling a tool but by ending a turn in assistant text with no outstanding tool call; `koan/agents/loop.py:run_agent_loop` treats that terminal-text turn at a phase boundary as the hand-back, parks the primary loop on a loop-owned `yield_future` (resolved by the chat endpoint), and resumes with the user's next message as the following turn's prompt. The `koan_yield` tool is removed. `koan_set_phase` remains the explicit phase transition and `koan_set_phase("done")` the workflow tombstone. The structured next-phase suggestions on the hand-back card come from one of two sources: the orchestrator can author them by calling `koan_suggest_next` (added by the control-loop change on 2026-06-05), which records them on `InteractionState.next_suggestions`; the loop consumes and clears that record at the hand-back, falling back to the deterministic, workflow-transition-derived `build_phase_suggestions` when the orchestrator authored none. Leon's rationale: ending a turn is already an observable signal, so a dedicated hand-back tool cost one model turn per yield for nothing; `koan_suggest_next` restores authored suggestions without making the hand-back itself a tool call. The cost of removing `koan_yield` -- it had silently carried more than control flow -- is recorded as a separate lesson.
