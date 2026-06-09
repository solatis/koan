---
title: Step progression is driven by an end-of-turn turn-outcome resolver; koan_complete_step
  removed
type: decision
created: '2026-04-16T07:13:50Z'
modified: '2026-06-05T13:05:54Z'
related:
- 0013-single-cognitive-goal-per-step-prevents-simulated.md
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
- 0158-koanyield-removed-the-agent-loops-terminal-text.md
---

Step progression for koan's in-process agent loop is driven by the loop itself, not by a tool call. On 2026-06-05, Leon's control-loop change removed the `koan_complete_step` tool and its `advance_step` core; `koan/agents/loop.py:run_agent_loop` now runs one turn per step, and a position-based turn-outcome resolver (`resolve_turn_outcome`) runs at each end-of-turn. The resolver advances to the next step while steps remain, re-injects the same step when `validate_step_completion` returns an error, hands a primary agent (the orchestrator) back to the user when the phase's steps are exhausted, and terminates a non-primary agent (scout or executor) at exhaustion. The loop injects the first step's guidance -- carrying the phase role context and the mechanical memory injection, via the retained `_step_phase_handshake_core` -- as the very first turn prompt, so there is no boot prompt. The first-tool-call handshake (`AgentState.handshake_observed`) is replaced by a first-turn-completed signal (`AgentState.first_turn_completed`, set once the first turn reaches the loop's End node); the haiku-class failure that originally motivated the one-sentence boot prompt (weaker models emitting text and exiting before entering the tool loop) is now mitigated by giving the model real first-step work on turn one. End-of-turn is position-based: the model never signals "advance" versus "hand back"; the resolver decides from the step position. Leon's rationale: `koan_complete_step` was a workaround for the Agent-SDK single-prompt limit, and once koan owned the loop in-process, ending a turn became the natural advancement signal -- a dedicated step tool cost a model turn per step for nothing. Alternatives rejected: a new advance-versus-hand-back disambiguation tool (it reintroduces the very tool being removed); dissolving the per-step concept and delivering a whole phase's guidance in one turn (it loses the single-cognitive-goal-per-step isolation, so the resolver still injects exactly one step's guidance per turn). Hand-back suggestions are recorded by the `koan_suggest_next` tool, with the deterministic workflow-derived `build_phase_suggestions` as fallback.
