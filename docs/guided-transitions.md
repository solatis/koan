# Guided phase transitions

## Overview

Each `PhaseBinding` in a workflow carries an optional `next_phase: str | None`
field that controls how the orchestrator exits the phase:

- **`next_phase = "some-phase"`** -- auto-advance. The orchestrator calls
  `koan_set_phase("some-phase")` directly after summarizing what was accomplished.
  No hand-back is needed; the workflow advances without user input.

- **`next_phase = None`** -- hand back to the user. The orchestrator calls
  `koan_suggest_next(suggestions=[...])` to record the suggested options, then
  ends its turn in terminal text. The loop parks and awaits the user's reply
  before the orchestrator can call `koan_set_phase`.

Auto-advance is guidance, not enforcement. The orchestrator may hand back
instead of calling `koan_set_phase` directly when exceptional circumstances
warrant user direction (see Override discipline below). The default promotes
smooth forward progress on the happy path; overrides surface when findings
demand it.

## Per-workflow transition tables

### Plan workflow

| Phase      | `next_phase` | Behaviour                                                                                      |
| ---------- | ------------ | ---------------------------------------------------------------------------------------------- |
| `intake`   | `plan`       | auto-advance                                                                                   |
| `plan`     | `None`       | hand back -- orchestrator calls `koan_set_phase("execute")` after reconciling                  |
| `execute`  | `None`       | hand back -- orchestrator picks `curation` (conforming) or re-runs via `koan_request_executor` |
| `curation` | `None`       | terminal hand-back -- workflow ends here                                                       |

Note: `plan` hands back (not auto-advances) because the orchestrator must yield
to the user after reconciling reviewer findings before committing to execution.
The producer's terminal step instructs it to call `koan_set_phase("execute")`.

### Milestones workflow

| Phase       | `next_phase` | Behaviour                                                                        |
| ----------- | ------------ | -------------------------------------------------------------------------------- |
| `intake`    | `milestone`  | auto-advance                                                                     |
| `milestone` | `None`       | hand back -- orchestrator advances to `plan` once reconcile is complete          |
| `plan`      | `None`       | hand back -- orchestrator calls `koan_set_phase("execute")` after reconciling    |
| `execute`   | `None`       | hand back -- orchestrator picks `plan` (next milestone) or `curation` (all done) |
| `curation`  | `None`       | terminal hand-back -- workflow ends here                                         |

## Step progression history

**Pre-M3:** when `get_next_step` returned `None`, the `koan_complete_step` handler
called `format_phase_complete(phase, suggested_phases, descriptions)`. This rendered
a "Phase Complete" banner telling the orchestrator to summarize and call `koan_yield`.
The orchestrator then called `koan_yield` and the user directed the next phase.

**Post-M3 / pre-M6:** the directive moved into each phase module's last-step
`step_guidance()` return value, carried in the `invoke_after` field of
`StepGuidance`. Each last step calls:

```python
invoke_after=terminal_invoke(ctx.next_phase, ctx.suggested_phases)
```

The `terminal_invoke(next_phase, suggested_phases) -> str` helper (in
`koan/phases/format_step.py`) renders either the auto-advance directive or the
hand-back directive depending on whether `next_phase` is bound. The directive
lands at the recency position (end of step text) via `format_step()`.

**Post-M6 (current):** `koan_complete_step` is removed. The turn-outcome
resolver (`resolve_turn_outcome` in `koan/agents/loop.py`) drives step
progression at each end-of-turn. The phase-boundary case is: steps exhausted
for a primary agent means hand back to the user. The orchestrator's last step
instructs it to call `koan_suggest_next` with structured suggestions and then
end its turn in terminal text; the resolver detects the step exhaustion and
parks the loop awaiting the user. `format_step()` still formats step guidance
with the directive last for recency reinforcement, but no tool call is required
to advance -- ending the turn is the signal.

## Override discipline

The orchestrator may hand back to the user instead of calling `koan_set_phase`
directly (even when `next_phase` is bound) when any of the following apply:

1. An exceptional finding has surfaced that the user must direct (e.g.,
   inline conformance review reveals a fundamental flaw requiring a scope
   change beyond the current plan).
2. The phase outcome does not match any single bound `next_phase` (e.g.,
   milestone completed all milestones on the first pass and curation
   is the right target, not plan).
3. The user asked mid-phase to redirect the workflow.

This is intentionally soft -- prompt discipline rather than vocabulary
enforcement. All phases are `next_phase=None` in the current model (since M6
collapsed the `*-review` phases into the mechanical reviewer and inline execute
review), so every phase boundary is a hand-back where the orchestrator picks the
next step based on findings and outcome.

## The `directed_phases` interaction

`directed_phases` (yolo mode, set by the eval harness) short-circuits the
phase-boundary hand-back to a fixed phase sequence so eval runs do not pause
for user input. It is independent of `next_phase`:

- A phase with `next_phase` bound calls `koan_set_phase` directly -- the
  resolver auto-advances and `directed_phases` has no effect.
- A phase with `next_phase=None` reaches a hand-back; the loop's yolo handler
  reads `directed_phases` and builds an auto-response rather than parking.

Both regimes work correctly with the other present.

## Eval fixture acknowledgement

`evals/fixtures/koan-1/repo/` is a pinned snapshot of the koan codebase at an
earlier point. It retains the old `format_phase_complete` symbol in its copy of
`koan/phases/format_step.py`. This is expected and correct: the eval runner
spawns koan as a subprocess from the fixture submodule, so the fixture is
self-contained and unaffected by changes in the live tree. Do NOT edit the eval
fixture to remove the old symbol -- it would break the snapshot's pin.
