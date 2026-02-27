# Planning Widget Refresh

## Context
The planning widget now follows the design-deck contract selected on Feb 25 2026:

- **Canvas direction:** Stacked Modular Cards
- **Navigation direction:** Vertical Timeline Rail
- **Header strategy:** Full-width top border + metadata header row (active phase in header, no tabs strip)
- **Log strategy:** Declarative shape-table serialization + dense two-column layout
- **QR strategy:** Inline integrated section (not a detached sub-card)

The goal is to keep a long-running (1-2h) planning session readable in real time while preserving high-signal audit telemetry.

## Decisions & Rationale

### 1) Deterministic log serialization (hybrid detail)
- Keep **tool name** as the primary scan anchor.
- Use a declarative per-tool formatter table for known `koan_*` tools.
- Unknown tools fall back to tool-name-only output.
- Field order is deterministic and curated (e.g., IDs first), not alphabetical.

**Rationale:** Users scan continuously during execution; stable order makes visual parsing faster and reduces cognitive churn between updates.

### 2) Selective detail by field type
- Arrays render as **first item + count** (`[first] +N`).
- Free-form fields (`diff`, `doc_diff`, `comments`, large narrative strings) render as **size metadata only** (`184L/9.2k`), never full body.
- Getter tools (`koan_get_*`) show target identifiers plus response size metadata (`resp:42L/3.1k`).

**Rationale:** Maintains observability without blowing out vertical space or flooding with low-value text.

### 3) Latest log as dense two-column grid
- Left column: tool name (bold accent anchor).
- Right column: compact deterministic summary.
- Column widths adapt to available terminal width + observed tool-name lengths (protecting right-column readability).
- High-value rows may wrap to 2 lines; if overflow exceeds 2 lines, the second line is re-compacted with ellipsis.
- Repeated events remain separate rows (no dedup/collapse).

**Rationale:** Preserves temporal fidelity while increasing information density and keeping the "what just happened" answer immediate, even under constrained widths.

### 4) QR is a first-class workflow section
- QR renders inline in detail pane with divider rule (no detached mini-card border).
- Visible for Plan design (and contractually for Plan execution), hidden only for Context gathering.
- QR starts directly in the **`execute`** stage for iteration 1 (non-fix mode); fix iterations reuse the same stage model.
- QR block is normalized to a fixed structure: header, phase rail, counters, divider.
- Metadata is budgeted to **64 visible chars max** and progressively compacted (`phase/iter/mode` -> `iN/M`, `d/p/f/t`) when width is constrained.
- Counter line emphasizes severity: `fail` is error-colored; `pass` is accent; others remain muted/dim.

**Rationale:** QR is not optional side telemetry; it is the acceptance loop for the plan. The UI should communicate that structural importance while remaining legible and shape-stable at smaller widths.

### 5) Header-first metadata, tabs removed
- Keep a full top border and put active workflow context directly in the header row.
- Header format is phase-first: `Planning · <active phase> · <phase status>` on the left, elapsed timer right-aligned.
- Remove the separate phase-tabs strip entirely; it is redundant once active context is in the header.
- Keep timeline rows in the body (left rail) because they provide progression context and status history, unlike tabs.

**Rationale:** The previous title treatment felt detached from the frame and duplicated information with the tabs row. Consolidating context into the header yields a cleaner hierarchy and better information density in TUI constraints.

## Layout Overview
```
┌────────────────────────────────────────────────────────────────────────────────┐
│ Planning · Context gathering · CURRENT                                  12m 22s │
│                                                                                │
│ ● Context gathering            Current step                                    │
│ │   DONE                       Step 2/6: Codebase Exploration                  │
│ │                              read internal/rules/CLAUDE.md · 17L/1.2k       │
│ ● Plan design                 QR | phase:execute · iter 1/6 initial            │
│ │   CURRENT                    Execute → QR decompose → QR verify              │
│ ○ Plan code                   done:0/- pass:0 fail:0 todo:-                    │
│ │   UPCOMING                   Subagents queued:0 active:1 done:0              │
│ ○ Plan docs                   Plan ID    : <plan-id>                           │
│     UPCOMING                  Agent      : architect                            │
│                               Model      : openai-codex/gpt-5.3-codex          │
│────────────────────────────────────────────────────────────────────────────────│
│ Latest log                                                                     │
│ koan_set_milestone_tests   id=M-002 · tests:["covers retries"] +7             │
│ koan_get_milestone         id=M-002 · resp:42L/3.1k                            │
│ koan_add_intent            milestone=M-002 · file=src/planner/ui/widget.ts     │
│ koan_set_change_diff       id=CC-M-001-002 · diff:184L/9.2k                    │
│ koan_qr_assign_group       phase=plan-design · ids:[QR-001] +11                │
└────────────────────────────────────────────────────────────────────────────────┘
```

## Rendering Guide
1. **Canvas** – Keep using `canvasLine()` so widget content remains full-width over `toolPendingBg`.
2. **Main card** – Keep one solid outer border + a full top rule. No cutout title and no detached title badge.
3. **Header row** – Render `Planning · <active phase> · <status>` on the left and elapsed timer right-aligned on the same row.
4. **No tabs strip** – Do not render a separate phase-tabs row under the header. Active phase context now lives in header metadata.
5. **Timeline rail** – Maintain status icon/color semantics (`active=accent`, `done=dim`, `failed=error`).
6. **Detail pane** – Render in this order:
   - a dim section label (`Current step`) to create hierarchy
   - step title + optional activity
   - QR integrated section (if visible)
   - subagent counters (`queued/active/done`) when available
   - identity table (`Plan ID`, `Agent`/`Agent pool`, `Model`) pinned low in pane
7. **QR section** – Use inline header + phase rail + metadata line + divider. Avoid nested border style to keep it visually native to the right pane. Keep line geometry stable (fixed 3-line payload + divider) and enforce a 64-char metadata budget before clamping to pane width.
8. **Latest log section** – Keep it inside the same outer card, separated by a horizontal divider. Reuse the same left/right column split (`timelineWidth` / `detailWidth`) and gap as the planning body so vertical alignment stays consistent.

## Header + Alignment Contract

### Header composition
- Inner card width is `W` (visible cells, excluding borders).
- Timer token is right-aligned and reserved first (`T` visible cells).
- Left header budget is `W - T - 1` (one spacer between left and right chunks).
- Base left chunk: `Planning · <active phase> · <status>`.

### Progressive compaction (left header)
Apply in order until it fits:
1. `CURRENT` -> `CUR`, `UPCOMING` -> `UP`, `DONE` unchanged.
2. Drop status chunk (keep `Planning · <active phase>`).
3. Abbreviate known phases (`Context gathering` -> `Ctx gather`, `Plan design` -> `Design`, `Plan code` -> `Code`, `Plan docs` -> `Docs`).
4. Ellipsize active phase tail (`Planning · <phase…>`).

### Metadata table alignment
- Keys are fixed labels: `Plan ID`, `Agent` or `Agent pool`, `Model`.
- Compute key column width from max visible key length in the rendered set.
- Use a fixed `" : "` separator.
- Values are right-column free text, truncated with ellipsis when overflowing pane width.

### Latest-log alignment
- Keep deterministic two-column geometry shared with body split.
- Left column width is based on observed max tool name (capped); right column gets remaining width.
- High-value rows may wrap to two lines max; second line must still obey right-column width budget.

## Data Contract Notes
- Header metadata state includes:
  - `activePhaseLabel`, `activePhaseStatus`, `elapsed`
- `LogLine` now carries:
  - `tool` (left column)
  - `summary` (right column)
  - `highValue` (whether 2-line wrap is allowed)
- QR state in widget includes:
  - `qrIteration`, `qrIterationsMax`, `qrMode`, `qrPhase`
  - `qrDone`, `qrTotal`, `qrPass`, `qrFail`, `qrTodo`

## Future Work (contracted, not yet implemented)
- Plan execution phase should reuse the same QR integrated section semantics.
- Optional compact mode for very narrow terminals can reduce metadata verbosity while preserving deterministic ordering.

## Update: Runtime Domains + Subagent Identity (2026-02-26)

This update captures follow-up decisions for showing subagent model information
and clarifying QR vs. parallel subagent semantics.

### Domain split (do not merge)
- **QR section** tracks quality state: `todo`, `pass`, `fail`.
- **Subagents section** tracks execution state: `queued`, `active`, `done`.
- These are sibling runtime views. They are related in workflow, but not
  collapsed into one metric family.

### `x<N>` meaning in parallel mode
- `x<N>` means configured pool capacity (target parallelism), not active count.
- Active movement remains in `queued/active/done` counters.

### Footer identity table standard
Use a unified key/value footer block:

- `Plan ID       : <plan-id>`
- `Agent         : <role>` (single subagent)
- `Agent pool    : <role> x<N>` (parallel mode)
- `Model         : <provider/model>`

### Generic rendering rule
The widget should remain role-agnostic and render identity from generic metadata
only:
- `role`
- `parallelCount`
- `model`

Label/value rule:
- `parallelCount > 1` -> `Agent pool : <role> x<parallelCount>`
- otherwise -> `Agent : <role>`

### View-composition pattern
Use section-level selectors/renderers (React-view-like composition without
React) so QR, subagent status, and identity/footer blocks are independently
composable and testable.

### Decision hygiene
A separate "layout pattern" decision was deemed redundant once the domain split
was chosen; track it as derived behavior, not as a distinct product decision.
