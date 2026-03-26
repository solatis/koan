# Planning Widget

## Context

The planning widget follows the stacked-card + timeline-rail layout and optimizes for long-running sessions (30-120 minutes).

The runtime pane is designed around one principle:

- show where the active subagent is **inside its workflow** (`step number + step title`),
- not the orchestrator's internal QR fix-loop iteration counter.

## Design Goals

1. **Immediate progress readability**
   - The user should answer “how far along are we?” in one glance.
2. **Active worker clarity**
   - The widget should show who is running now and pool load (`queued/active/done`).
3. **Meaningful output accounting**
   - Show entity modifications as `+delta (total)`.
4. **Stable visual scan path**
   - Header + timeline + runtime + latest log remain in fixed positions.

## Runtime Information Hierarchy

From highest to lowest priority:

1. `step` (`current/total · title`)
2. step-based progress bar
3. active subagents block (role/model/load/mode)
4. modifications block (`Δ / total`)
5. latest log (auditable tail)

## Layout Overview

```
┌──────────────────────────────────── Runtime ──────────────────────────────────── 33m 14s ┐
│ step     : 2/6 · Codebase Exploration                                              │
│ progress : ███████░░░░░░░░░░ 33%                                                   │
│──────────────────────────────────────────┬──────────────────────────────────────────│
│ active subagents                         │ modifications (Δ / total)                │
│ role   : architect                       │ milestones : +2 (6)                      │
│ model  : anthropic/claude-opus-4-6       │ decisions  : +1 (9)                      │
│ load   : queued 0   active 1   done 0    │ intents    : +4 (18)                     │
│ mode   : single                          │ changes    : +0 (3)                      │
└──────────────────────────────────────────┴──────────────────────────────────────────┘
```

Elapsed time remains right-aligned in the top row.

## Phase-Specific Modifications Panel

### A) Plan design / plan code / plan docs / execution

Show plan-modification counters:

- `milestones : +Δ (total)`
- `decisions  : +Δ (total)`
- `intents    : +Δ (total)`
- `changes    : +Δ (total)`

### B) QR decompose

Show QR decomposition counters:

- `qr items added   : +Δ (total)`
- `qr items updated : +Δ (total)`
- `groups assigned  : +Δ (total)`

### C) QR verify

Show explicit placeholder (by design):

- `[placeholder]`
- `qr-verify counters not instrumented yet`

This placeholder is intentional and must be rendered explicitly rather than silently omitting the panel.

## Rendering Contract

1. **Header row**
   - Left: `Planning · <active phase> · <status>`
   - Right: elapsed timer
   - Keep deterministic compaction when width is constrained.

2. **Timeline rail (left column)**
   - Keep phase icons/status semantics (`pending/running/completed/failed`).

3. **Runtime detail (right column)**
   - First two lines are always step + progress bar.
   - Then split into two panes:
     - left: `active subagents`
     - right: `modifications`

4. **Latest log**
   - Keep current deterministic two-column rendering and tool-shape serialization.

## Progress Semantics

- Primary progress is based on active subagent workflow steps.
- The progress bar denominator is the subagent’s step total.
- For `qr-verify`, where reviewer execution is pooled, progress uses grouped verification progress (`done/total groups`) as the step/progress source.
- QR fix-loop cycle counters are internal orchestration state and are not part of the primary runtime progress display.

## Active Subagents Semantics

Runtime subagent block renders aggregate execution state:

- `role`
- `model`
- `load` (`queued`, `active`, `done`)
- `mode` (`single` or `pool ×N`)

`x<N>` denotes configured pool capacity (target parallelism), not current active count.

## Modifications Counter Semantics

Formatting rule:

- `+2 (6)` means **delta +2**, **current total 6**.

General rules:

- Delta is scoped to the currently running phase block.
- Total is the current persisted artifact count at render time.
- Missing counters should render explicit placeholders (never blank rows).

## Data Contract Notes

- Header metadata: active phase label/status + elapsed time.
- Step/progress data: step index, step total, step title (or grouped verify progress fallback).
- Subagent telemetry: role, model, parallel count, queued/active/done.
- Log lines: deterministic `tool + summary` rows.
- Modification counters:
  - plan phases: milestones/decisions/intents/changes (delta + total)
  - qr-decompose: added/updated/grouped (delta + total)
  - qr-verify: explicit placeholder.

## Rationale Summary

- Step-first progress reduces ambiguity during long runs.
- Aggregate subagent telemetry keeps runtime compact while still explaining throughput.
- `Δ / total` counters answer both “what changed recently?” and “how much exists now?”.
- Explicit placeholders prevent silent uncertainty during uninstrumented phases.
- Stable layout preserves user orientation while high-frequency updates stream in.
