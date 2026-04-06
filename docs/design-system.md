# Koan Design System

## Overview

This document defines the complete visual language for koan's web UI. Every component must reference these tokens — nothing hardcodes values. The aesthetic is mid-century modern geometric: confident, warm, professional with controlled playfulness. Inspired by Lobotain's navy/orange/teal palette, Kolur's complementary duotones, and Japanese-influenced earthy pastels.

## Color Palette

### Core colors

These are the three identity colors. They appear in the header, accents, status indicators, and interactive elements.

| Token | Hex | Usage |
|---|---|---|
| `--color-navy` | `#2e3a5e` | Header bar, scout bar frame, primary text, artifact icons (dark), logo text |
| `--color-orange` | `#d4775a` | Primary accent, active states, running indicators, progress bars, primary buttons, decision borders, numbered list markers |
| `--color-teal` | `#5a9a8a` | Secondary accent, success/completion states, checkmarks in tool calls, completed progress segments, orchestrator dot, "recommended" badges |

### Background surfaces

These define the layering system. The hierarchy from back to front is: base → surface → card. Each layer must be visually distinguishable from its neighbors.

| Token | Hex | Usage |
|---|---|---|
| `--bg-base` | `#f8f6f2` | Main content area background. Warm-tinted near-white — warm enough to avoid clinical, light enough to avoid brown. |
| `--bg-surface` | `#f3efe8` | Artifacts sidebar background. Slightly warmer and darker than base to create panel distinction. |
| `--bg-card` | `#ffffff` | Prose output cards, form sections, scout table interior, artifact cards, input fields. True white provides the strongest contrast against base. |
| `--bg-tool-row` | `#f0ede6` | Tool call rows (bash, read, edit). Sits between base and surface in warmth. |
| `--bg-thinking` | `#eae5f2` | Thinking/reasoning blocks. Lavender — in the cool family with navy but lighter, creating warm/cool interplay. |
| `--bg-step-guidance` | `#efece6` | Step guidance pill, model badges in scout table, "coming soon" badges. Neutral warm. |
| `--bg-completion` | `#e8f5ee` | Completion/success banners. Teal-family light green. |
| `--bg-selected` | `#fdf8f5` | Selected card state (e.g., selected workflow option). Very faint orange tint. |
| `--bg-card-warm` | `#faf8f4` | Slightly warmer white for artifact cards, scout table interior, and secondary card surfaces distinguishable from prose cards. |

### Text colors

| Token | Hex | Usage |
|---|---|---|
| `--text-primary` | `#2e3a5e` | Headings, prose body text, scout names, form labels. Same as navy — this is intentional, it ties text to the brand. |
| `--text-body` | `#4a4a5a` | Secondary body text within prose cards, list items, codebase findings. |
| `--text-muted` | `#9a8e7e` | Tool call type labels ("bash", "read"), metadata, timestamps, placeholder labels, column headers. |
| `--text-subtle` | `#7a6e60` | Step guidance text, form descriptions, secondary labels. |
| `--text-placeholder` | `#b0a498` | Input placeholder text ("Send feedback..."). |
| `--text-hint` | `#c8baa8` | Hint text below inputs ("Enter to send · Shift+Enter for newline"). |
| `--text-thinking` | `#3a3460` | Text inside thinking blocks. Dark purple for contrast against lavender. |
| `--text-thinking-label` | `#5a5080` | "THINKING" label text. Medium purple. |
| `--text-completion` | `#2a6a4a` | Completion banner text. Dark teal-green. |
| `--text-artifact-time` | `#a89888` | Artifact "modified X ago" timestamps. |

### Text on dark backgrounds (navy header, scout bar frame)

| Token | Hex | Usage |
|---|---|---|
| `--text-on-dark` | `#f0e8d8` | Primary text on navy. Warm off-white, not pure white. |
| `--text-on-dark-muted` | `rgba(240,232,216,0.55)` | Breadcrumb inactive segments, secondary labels on navy. |
| `--text-on-dark-subtle` | `rgba(240,232,216,0.4)` | Timestamps, tertiary info on navy. |
| `--text-on-dark-faint` | `rgba(255,255,255,0.15)` | Dividers, inactive progress segments, icon button borders on navy. |
| `--text-on-dark-scouts-muted` | `rgba(240,232,216,0.45)` | Scout summary labels ("running", "done") on navy. |

### Border colors

| Token | Hex | Usage |
|---|---|---|
| `--border-card` | `#eae6e0` | Card borders (prose cards, artifact cards). Faint warm line. |
| `--border-input` | `#c8c0b4` | Input field borders, text area borders. Distinctly visible against white and base backgrounds. |
| `--border-radio` | `#e0d8cc` | Radio option card borders, form element borders. Between card and input in weight. |
| `--border-divider` | `#e8e2d8` | Artifact sidebar dividers, table row separators, panel borders. |
| `--border-divider-light` | `#f0ebe4` | Scout table internal row separators. Very faint. |

### Semantic status colors

These are used exclusively for scout status indicators and similar operational state.

| Token | Hex | Usage |
|---|---|---|
| `--status-running` | `#d4775a` | Running scout dots, active step labels. Same as orange accent. |
| `--status-done` | `#5a9a8a` | Completed scout dots. Same as teal accent. |
| `--status-queued` | `#b8aca0` | Queued count text. Desaturated warm. |
| `--status-failed` | `#c44` | Failed count text. Standard red — used sparingly. |

### Derived colors

These are derived from core tokens for specific UI effects. Not part of the primary palette.

| Token | Value | Usage |
|---|---|---|
| `--overlay-backdrop` | `rgba(46, 58, 94, 0.45)` | Navy-tinted translucent backdrop for modals and overlays. |
| `--focus-ring` | `rgba(212, 119, 90, 0.12)` | Orange-derived focus ring glow for input fields. |
| `--flash-teal` | `rgba(90, 154, 138, 0.12)` | Teal-derived background flash for result animations. |

## Typography

### Font families

| Token | Value | Usage |
|---|---|---|
| `--font-display` | System serif stack (Georgia, "Times New Roman", serif) | Logo "koan" wordmark only. |
| `--font-body` | System sans-serif stack (-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif) | All UI text, headings, labels, prose, form elements. |
| `--font-mono` | Monospace stack ("SF Mono", "Fira Code", "Cascadia Code", monospace) | File paths, tool call commands, scout names, code inline, timestamps, model names, artifact filenames. |

### Type scale

All weights are 400 (regular) or 500 (medium). Never use 600 or 700.

| Token | Size | Weight | Usage |
|---|---|---|---|
| `--type-page-title` | 26px | 500 | "New Run" page title. Letter-spacing: -0.5px. |
| `--type-logo` | 17px | 500 | "koan" wordmark in header. Uses `--font-display`. Letter-spacing: -0.3px. |
| `--type-section-title` | 17px | 500 | "Gather Summary" and similar section headings within prose cards. |
| `--type-step-header` | 16px | 500 | Step name next to step indicator ("Gather", "Summarize"). |
| `--type-prose` | 15px | 400 | Agent prose output, decision question text, form field values. Line-height: 1.7. |
| `--type-body` | 14px | 400 | Body text within cards (findings, decisions list items, context descriptions). Line-height: 1.65. |
| `--type-step-indicator` | 14px | 500 | "step 1/3", "step 3/3" colored labels. |
| `--type-breadcrumb` | 13px | 400/500 | Header breadcrumb segments (400 for inactive, 500 for active). |
| `--type-tool-type` | 12px | 400 | Tool call type label ("bash", "read", "edit"). Uses `--text-muted`. |
| `--type-tool-path` | 12px | 400 | Tool call file paths. Uses `--font-mono`. |
| `--type-label` | 11px | 500 | Section labels ("ARTIFACTS", "CONTEXT", "DECISION", "SCOUTS", "THINKING"). Uppercase, letter-spacing: 1px. |
| `--type-badge` | 10px | 500 | "coming soon", "recommended", model badges, scout column headers. |
| `--type-timestamp` | 10px | 400 | "modified 2m ago" artifact timestamps. |

### Inline code

Code tokens within prose use: `background: var(--bg-tool-row); padding: 1px 5px; border-radius: 3px; font-size: one step below surrounding text; color: var(--text-primary); font-family: var(--font-mono)`.

## Spacing

### Page-level spacing

| Token | Value | Usage |
|---|---|---|
| `--page-padding` | 28px 32px | Main content area padding. |
| `--sidebar-padding` | 20px 16px | Artifacts sidebar padding. |
| `--header-height` | 50px | Header bar fixed height. |
| `--form-max-width` | 640px | Max width for standalone form pages ("New Run"). Centered. |
| `--form-page-padding` | 40px 24px | Padding around centered form content. |

### Component gaps

| Token | Value | Usage |
|---|---|---|
| `--gap-content` | 20px | Between major content blocks in the stream (thinking → prose → tools → thinking). |
| `--gap-tool-rows` | 3px | Between individual tool call rows within a group. |
| `--gap-artifact-cards` | 10px | Between artifact cards in the sidebar. |
| `--gap-form-sections` | 28px | Between form card sections on the "New Run" page. |
| `--gap-radio-options` | 10px | Between radio option cards in elicitation. |
| `--gap-scout-summary` | 16px | Between scout summary count groups. |
| `--gap-progress-segments` | 3px | Between progress bar segments in header. |

### Component internal padding

| Token | Value | Usage |
|---|---|---|
| `--padding-card` | 14px 20px | Prose output cards. |
| `--padding-card-form` | 20px 24px | Form section cards, context/decision panels. |
| `--padding-tool-row` | 7px 14px | Individual tool call rows. |
| `--padding-step-guidance` | 8px 16px | Step guidance pill. |
| `--padding-artifact` | 10px 12px | Artifact cards in sidebar. |
| `--padding-scout-bar` | 14px 24px | Scout bar outer padding. |
| `--padding-scout-row` | 8px 14px | Scout table rows. |
| `--padding-input` | 14px 18px | Feedback input area. |
| `--padding-radio` | 12px 14px | Radio option cards. |

## Border Radius

| Token | Value | Usage |
|---|---|---|
| `--radius-sm` | 3px | Inline code tags, model badges. |
| `--radius-md` | 6px | Tool call rows, progress bar segments, small buttons. |
| `--radius-lg` | 8px | Artifact cards, scout table, step guidance pill, input fields, form dropdowns. |
| `--radius-xl` | 10px | Prose cards, thinking blocks, feedback input, completion banner, radio options. |
| `--radius-2xl` | 12px | Form section cards, context/decision panels, page-level container. |
| `--radius-pill` | 20px | Pill-shaped badges ("coming soon", "recommended"). |
| `--radius-circle` | 50% | Status dots, radio buttons, logo circles, orchestrator dot. |

## Component Specifications

### Header bar

The header is a fixed 50px bar with `--color-navy` background. It contains the logo, breadcrumb navigation, progress segments, orchestrator info, elapsed time, and settings button. It spans the full width of the viewport.

The logo is the "koan" wordmark in `--font-display` at 17px/500, colored `--text-on-dark`. To the left of the wordmark are two overlapping circles: a 16px circle in `--color-orange` (top-left) and a 10px circle in `--color-teal` (bottom-right). This geometric motif is the brand mark.

A 1px vertical divider at `rgba(255,255,255,0.15)` separates the logo from the breadcrumb. The breadcrumb shows phase and step as `Phase > Step` with a small chevron. The inactive segment uses `--text-on-dark-muted`, the active segment uses `--text-on-dark` at weight 500.

Progress segments are 24px wide, 4px tall, with `--radius-md`. Completed segments use `--color-teal`, the active segment uses `--color-orange`, and future segments use `--text-on-dark-faint`. Gap between segments: 3px.

The settings button is a 30px square with `--radius-lg`, 1px border in `--text-on-dark-faint`, containing a 14px gear SVG icon stroked at `rgba(240,232,216,0.6)`.

### Prose output card

White card (`--bg-card`) with `--radius-xl`, `0.5px solid --border-card` on all sides, plus a 3px `--color-orange` left border. Padding: `--padding-card`. Text is `--type-prose` in `--text-primary`. These cards contain the agent's spoken output — everything the agent says directly to the user (as opposed to thinking or tool calls).

### Thinking block

Lavender block (`--bg-thinking`) with `--radius-xl`. Padding: 16px 20px. Contains a label row with a small 14px navy circle (with a 6px `#b8b0d0` inner circle) followed by "THINKING" in `--type-label` at `--text-thinking-label`. Body text is `--type-body` in `--text-thinking`.

### Tool call row

Background `--bg-tool-row`, `--radius-md`, padding `--padding-tool-row`. Contains a 13px teal checkmark SVG, a tool type label ("bash", "read", "edit") in `--type-tool-type` and `--text-muted` with min-width 36px, and the command/path in `--type-tool-path` and `--font-mono` colored `var(--text-body)`. Rows within a group are spaced `--gap-tool-rows` apart.

### Step guidance pill

Inline-flex element with `--bg-step-guidance`, `--radius-lg`, padding `--padding-step-guidance`. Contains an 8px circle in `--color-orange` (or `--color-teal` when step is complete), label text in `--text-subtle` at 13px/500, and a 10px chevron-down SVG. Aligns to `flex-start` (left-aligned, not full-width).

### Artifact card

Background `--bg-card-warm` (`#faf8f4` — slightly warmer than pure white to distinguish from prose cards), `--radius-lg`, `0.5px solid --border-divider`, padding `--padding-artifact`. Contains a 28px square icon with `--radius-lg`: navy background with a lavender file SVG for recently modified artifacts, or teal background with a light-teal file SVG for older/stable artifacts. Next to the icon: filename in `--font-mono` at 12px/500 in `--text-primary`, and timestamp in `--type-timestamp` at `--text-artifact-time`.

### Scout bar

Navy frame (`--color-navy`) with padding `--padding-scout-bar`. The summary line sits directly on navy: an 8px orange dot, "SCOUTS" label in `--text-on-dark-muted` at `--type-label`, then count groups (e.g., "3 running") where the number uses the appropriate status color and the label uses `--text-on-dark-scouts-muted`.

Below the summary, a white table card (`--bg-card-warm`) with `--radius-lg` and no outer border. The table has a header row with column labels in `--type-badge` / `--text-muted`, uppercase, with a `0.5px solid --border-divider` bottom border. Data rows use `--padding-scout-row` with `0.5px solid --border-divider-light` separators (no border on the last row).

Table columns: status dot (20px col, 6px dot in status color), name (flex, `--font-mono` 12px/500 in `--text-primary`), model (60px, `--text-muted` 11px), tools (60px, `--text-muted`), elapsed (70px, `--text-muted`), status (flex, `--color-orange` for active steps).

### Feedback input

White card (`--bg-card`), `--radius-xl`, `1.5px solid --border-input` (this is intentionally darker than card borders for definition). Padding `--padding-input`. Placeholder text in `--text-placeholder`. Below: hint text in `--text-hint` at 11px left-aligned, and a "Send" button right-aligned with `--color-orange` background, white text, `--radius-md`, padding 5px 16px, 13px/500.

### Completion banner

Background `--bg-completion`, `--radius-xl`, padding 14px, text centered in `--text-completion` at 14px.

### Form cards (New Run page)

White card (`--bg-card`), `--radius-2xl`, `0.5px solid --border-card`, padding `--padding-card-form`. Section label in `--type-label` / `--text-muted` at the top. Form inputs use `background: --bg-base`, `1.5px solid --border-input`, `--radius-lg`, padding 10px 14px.

### Workflow selection cards (New Run page)

Two cards side by side in a 2-column grid with 12px gap. The selected card has `2px solid --color-orange` border, `--bg-selected` background, and a filled radio circle (16px outer circle with 2px orange border, 8px filled orange inner). The unselected/disabled card has `1.5px solid --border-radio` border, opacity 0.6 for disabled state.

### Elicitation panels (Deepen view)

Two-panel 1fr/1fr grid with 20px gap. Each panel is a white card (`--bg-card`) with `--radius-2xl` and `0.5px solid --border-card`. The Context panel has a 3px `--color-teal` top border. The Decision panel has a 3px `--color-orange` top border. Panel labels use the respective accent color for text.

### Radio option cards (Deepen view)

Each option is a label element with `--radius-lg`, `1.5px solid --border-radio`, padding `--padding-radio`. Contains an 18px circle with `2px solid --border-input` (unfilled state) or `2px solid --color-orange` with 8px filled inner (selected state). The "recommended" badge uses `background: --bg-completion; color: --text-completion` (teal-green family), `--radius-pill`, `--type-badge`.

When `isCustom` is true and selected, a text input appears below the label (8px top margin, full-width, transparent background, bottom-border-only: --border-card default, --border-input on focus, placeholder "Type your response..." in --text-placeholder). Hidden when not selected.

### Buttons

Primary: `--color-orange` background, white text, `--radius-lg` (8px for larger buttons, 6px for small), 13-15px/500. Used for "Start Run", "Next", "Send".

Secondary/outline: `1.5px solid --border-input`, `--text-subtle`, `--radius-lg`. Used for "Use Defaults".

## Layout

### Page frame

The page is a flex column filling `100vh`. Three direct children:

1. **HeaderBar** — `flex-shrink: 0`, full viewport width, `--color-navy` background.
2. **Centered container** — `flex: 1`, `min-height: 0`, `max-width: 1400px`, `margin: 0 auto`, `width: 100%`. Contains the content+sidebar grid.
3. **ScoutBar** (conditional) — `flex-shrink: 0`, full viewport width, `--color-navy` background. Omitted when no scouts are active.

The HeaderBar and ScoutBar span the full viewport width. The centered container constrains the content grid to 1400px. On wide screens, the space beyond the container edges is `--bg-base` background. No pseudo-elements. No `overflow-x: hidden`.

### Two-column workflow view

Used during active workflow phases (Gather, Deepen, Summarize). The centered container is a CSS grid with `grid-template-columns: minmax(0, 1fr) 260px`, filling the height between header and scout bar. The content column (left) scrolls vertically (`overflow-y: auto`, `padding: 28px 32px`) and is at most ~1140px wide — a comfortable reading width without needing further constraint. The artifacts sidebar (right) is 260px with `--bg-surface` background and a 1px `--border-divider` left border. Both columns stretch to fill the full grid height. The sidebar does not touch the right viewport edge on wide screens — this is intentional.

### Centered form view

Used for the "New Run" page. Single centered column with `--form-max-width` (640px), no sidebar, no scout bar. Content sections are stacked with `--gap-form-sections`.

### Scout bar (conditional)

Appears at the bottom of the viewport only during phases where scouts are active. Full-viewport-width frame element at the same level as the HeaderBar. Contains the summary line and white table card. Not present on the New Run page or completion views where scouts aren't running.

## Logo

The koan logo consists of two elements: a geometric mark and a wordmark.

The geometric mark is two overlapping circles. The larger circle (16px diameter) is `--color-orange`, positioned top-left. The smaller circle (10px diameter) is `--color-teal`, positioned bottom-right, partially overlapping the orange circle. Total mark footprint: approximately 20x20px.

The wordmark "koan" is set in `--font-display` (serif) at 17px/500, colored `--text-on-dark` when on navy, or `--text-primary` when on light backgrounds. Letter-spacing: -0.3px.

The mark and wordmark are separated by 8px. On the header bar, a 1px vertical divider at `--text-on-dark-faint` separates the logo group from the navigation breadcrumb with 16px gap on each side.
