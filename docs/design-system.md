# Koan Design System

The single source of truth for koan's visual design. `src/styles/variables.css` is a mechanical translation of the token tables below. The doc changes first, then the CSS follows.

---

## Tokens

### Background surfaces

| Token             | Hex       | Usage                                                                     |
| ----------------- | --------- | ------------------------------------------------------------------------- |
| `--bg-danger`     | `#fce8e8` | Destructive confirmation backgrounds. Red-family tint.                    |
| `--bg-toggle-off` | `#d3d1c7` | Toggle track off state. Neutral warm gray, lighter than `--border-input`. |

### Text colors

| Token                | Hex       | Usage                                               |
| -------------------- | --------- | --------------------------------------------------- |
| `--text-danger`      | `#791f1f` | Destructive confirmation heading text. Darkest red. |
| `--text-danger-body` | `#a03030` | Destructive confirmation body text.                 |

### Border colors

| Token             | Hex       | Usage                                                         |
| ----------------- | --------- | ------------------------------------------------------------- |
| `--border-danger` | `#e8c8c8` | Danger button borders, destructive confirmation card borders. |
| `--border-teal`   | `#b8d8cc` | Teal-accented button borders (Detect, Explore actions).       |

### Interactive colors

| Token                  | Hex       | Usage                                                                    |
| ---------------------- | --------- | ------------------------------------------------------------------------ |
| `--color-orange-hover` | `#c06a4f` | Hover state for orange interactive elements (ReviewBlock gutter button). |

### Component gaps

| Token                 | Value | Usage                                                                |
| --------------------- | ----- | -------------------------------------------------------------------- |
| `--gap-entity-rows`   | 8px   | Between entity rows within a settings section card.                  |
| `--gap-form-rows`     | 12px  | Between form rows inside an inline form.                             |
| `--gap-form-controls` | 8px   | Between controls in a single form row (e.g., three cascade selects). |

### Component internal padding

| Token                     | Value     | Usage                                                                         |
| ------------------------- | --------- | ----------------------------------------------------------------------------- |
| `--padding-card-settings` | 22px 26px | Settings section cards.                                                       |
| `--padding-entity-row`    | 12px 16px | Entity rows (profile rows, installation rows).                                |
| `--padding-inline-form`   | 22px 26px | Inline edit/create forms. Matches settings card padding for visual alignment. |

### Page-level spacing

| Token                  | Value | Usage                                                             |
| ---------------------- | ----- | ----------------------------------------------------------------- |
| `--settings-nav-width` | 152px | Side navigation column width on the Settings page.                |
| `--settings-max-width` | 960px | Max width for the Settings page layout container (nav + content). |

### Tool family indicator colors

| Token        | Hex       | Usage                                                                                                                                                                                                            |
| ------------ | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--dot-read` | `#5a9a8a` | `StatusDot` `status="read"`. Identifies `read` operations in tool aggregate cards. Aliases `--color-teal`; the alias pattern matches `--status-done`.                                                            |
| `--dot-grep` | `#7ab0a0` | `StatusDot` `status="grep"`. Identifies `grep` operations. Slightly lighter teal than `--dot-read`; distinguishable from `--dot-read` at 8px stat-block size, secondary to the command text at 6px log-row size. |
| `--dot-ls`   | `#4a8878` | `StatusDot` `status="ls"`. Identifies `ls` operations. Slightly darker teal than `--dot-read`.                                                                                                                   |

All three tokens belong to the teal family because all three tools are
read-only exploration operations. Orange is reserved for active state
(`--color-orange`) and must not appear in tool-family indicator colors.

---

## Atoms

### StatusDot

A small colored circle indicating either an operational state or a tool family.

Container: `display: inline-block`, `border-radius: var(--radius-circle)`,
`flex-shrink: 0`. All variants are static — no animation. In-flight activity
indicators in consuming molecules are implemented inline (see `ToolCallRow`'s
`.tcr-running-dot` pattern) rather than through `StatusDot`, so that
`StatusDot` stays a pure visual primitive and adjacent features that already
use `StatusDot` (e.g., `ScoutRow`) are not affected by changes in this area.

**Sizes:**

- `sm`: 6px × 6px. Used inside `ToolLogRow` log rows where vertical density
  matters.
- `md`: 8px × 8px. Default. Used in `ToolStatBlock` stat blocks, scout tables,
  artifact cards, and the header orchestrator indicator.

**Status variants — operational state:**

- `running`: `background: var(--status-running)` (orange). Static.
- `done`: `background: var(--status-done)` (teal). Static.
- `queued`: `background: var(--status-queued)` (neutral warm gray). Static.
- `failed`: `background: var(--status-failed)` (red). Static.

**Status variants — tool family:**

- `read`: `background: var(--dot-read)`. Static.
- `grep`: `background: var(--dot-grep)`. Static.
- `ls`: `background: var(--dot-ls)`. Static.

The tool-family variants share the `status` prop with the operational variants
intentionally — the geometry and usage pattern are identical, and a single
`status` prop keeps consumers' call sites readable.

Type: `Status = 'running' | 'done' | 'queued' | 'failed' | 'read' | 'grep' | 'ls'`,
`Size = 'sm' | 'md'`.

Props: `status: Status`, `size?: Size` (default `'md'`).

### TextInput

Shared text input used in settings forms, NewRunForm textarea, NewRunForm concurrency input, RadioOption/CheckboxOption custom text input, and FeedbackInput textarea.

**Field variant (default):** Background `--bg-base`, `1.5px solid --border-input`, `--radius-lg`. Padding: 8px 12px. Font: `--font-body`, 13px, `--text-primary`. Placeholder: `--text-placeholder`. Focus: border-color `--color-orange`, box-shadow `0 0 0 3px var(--focus-ring)`. Error state: border-color `--status-failed`. Disabled: opacity 0.5.

**Inline variant:** Transparent background, no side/top borders, `border-bottom: 1px solid --border-card`. Padding: 8px 0. Focus: border-bottom-color `--border-input`. Used inside RadioOption and CheckboxOption for the custom "Other" text input.

**Mono modifier:** When `mono` is true, uses `--font-mono` at 13px. For file paths, extra args, and technical identifiers.

**Textarea mode:** When rendered as `<textarea>`, uses field variant styling with `min-height: 80px`, `resize: vertical`. Used in NewRunForm description field and FeedbackInput.

Props: `value`, `onChange`, `placeholder`, `variant?: 'field' | 'inline'`, `mono?: boolean`, `error?: boolean`, `disabled?: boolean`, `as?: 'input' | 'textarea'`.

### Select

Shared dropdown select used in settings profile/installation forms, NewRunForm profile and installation dropdowns, and standalone preference selects.

Background `--bg-base`, `1.5px solid --border-input`, `--radius-lg`. Padding: 8px 28px 8px 12px. Font: `--font-body`, 13px, `--text-primary`. When `mono` is true, uses `--font-mono` at 13px. Used for selects displaying technical identifiers (runner types in installation forms). Custom chevron: 10×6px SVG arrow, stroke `--text-muted`, positioned via `background-image` at `right 10px center`. `-webkit-appearance: none; appearance: none`. Focus: border-color `--color-orange`. Disabled: opacity 0.5. Placeholder option (no value selected): `--text-placeholder`.

Props: `value`, `onChange`, `options: { value: string, label: string }[]`, `placeholder?: string`, `disabled?: boolean`, `mono?: boolean`.

### Toggle

A boolean switch for auto-saving preferences (auto-open artifacts, sandbox execution, verbose debug output).

Track: 36px wide, 20px tall, `--radius-pill`. Off state: `--bg-toggle-off`. On state: `--color-teal`. Thumb: 16px diameter, `--bg-card` (white), `--radius-circle`. Off position: `left: 2px`. On position: `left: 18px`. Transition: background and left, `--duration-fast`. Disabled: opacity 0.5.

Auto-saves on click. The parent component handles the API call — no explicit save UI.

Props: `checked: boolean`, `onChange: (checked: boolean) => void`, `disabled?: boolean`.

### NumberInput

A compact numeric input for scalar configuration values (scout concurrency, limits).

Width: 48px. Center-aligned text. Font: `--font-mono`, 13px. Otherwise identical to TextInput field variant (`--bg-base`, `1.5px solid --border-input`, `--radius-lg`, padding 8px 0). Focus: border-color `--color-orange`.

Auto-saves on blur. The parent component handles the API call — no explicit save UI.

Props: `value: number`, `onChange: (value: number) => void`, `min?: number`, `max?: number`, `disabled?: boolean`.

### Buttons — sizes and variants

**Sizes:**

- `xs`: padding 2px 10px, font-size 12px, `--radius-md`. Used for compact inline actions on entity rows (Edit, Delete, Explore).
- `sm`: padding 5px 16px, font-size 13px, `--radius-md`. Used for form-level actions (Cancel, Save in InlineForm) and utility actions inside form rows (Detect).
- `md`: padding 10px 28px, font-size 15px, `--radius-lg`. Used for page-level actions (Start Run, Submit, Next).

**Danger variant:** At `xs` and `sm` sizes: `--status-failed` text, `1px solid --border-danger`, `--radius-md`. Used for Delete actions on entity rows (`xs`) and form-level destructive actions (`sm`). At `md` size: `--status-failed` background, white text, `--radius-lg`. Used in destructive confirmation dialogs.

**Teal variant:** `--color-teal` text, `1px solid --border-teal`, `--radius-md`. Available at `xs` and `sm` sizes. Used for utility actions: Detect (find binary path), Explore (view session).

**Text variant:** `--color-orange` text, font-weight 500, no border, no background, no padding. Used for add triggers ("+ New profile", "+ Add claude installation").

Type: `Variant = 'primary' | 'secondary' | 'danger' | 'teal' | 'text'`, `Size = 'xs' | 'sm' | 'md'`.

### Badges

Variant type: `'neutral' | 'success' | 'accent' | 'model' | 'default' | 'error'`.

**Default variant:** text `#c06030` (darkened orange), background `#fdf2ee` (orange-tinted). Used for "default" installation labels.

**Error variant:** text `--status-failed`, background `--bg-danger`. Used for "unavailable" status.

---

## Molecules

### Stream Molecules

#### RadioOption

A selectable option card for elicitation questions (single-select mode).

Container: `--padding-radio` (12px 14px), `--radius-lg`, `1.5px solid --border-radio`. Cursor: pointer. Transition: border-color and background, `--duration-fast`.

Selected state: `border-color: --color-orange`, `background: --bg-selected`.

Recommended state: `border-left: 3px solid --color-orange`, `background: --bg-selected`. No padding adjustment — the 1.5px content shift from the thicker border is sub-pixel. When recommended and selected simultaneously, selected wins: `border-left-width` resets to `1.5px` for a uniform orange border.

Contains a radio circle (18px, `2px solid --border-input`, selected: `--color-orange` with 8px inner dot), label text (`--type-body`, `--text-primary`), and optional custom text input (inline variant TextInput, visible when `isCustom && selected`).

Props: `label`, `selected?: boolean`, `recommended?: boolean`, `isCustom?: boolean`, `customText?: string`, `onCustomTextChange?: (text: string) => void`, `onClick?: () => void`.

#### CheckboxOption

A selectable option card for elicitation questions (multi-select mode). Identical to RadioOption except: square checkbox (18px, `--radius-sm`, `2px solid --border-input`, selected: `--color-orange` fill with white checkmark SVG).

Same recommended treatment as RadioOption: `border-left: 3px solid --color-orange`, `background: --bg-selected`. Selected+recommended resets `border-left-width` to `1.5px`.

Props: same as RadioOption.

#### YieldPanel

A self-contained command panel rendered in the content stream when the orchestrator yields for a phase transition decision.

Container: `--bg-card`, `0.5px solid --border-card`, `--radius-2xl` (12px), `overflow: hidden`.

Header: `padding: var(--padding-card)` (14px 20px), `border-bottom: 1px solid --border-divider-light`. Prompt text: `--font-body`, `--type-body` (14px), font-weight 500, `--text-primary`, `line-height: 1.4`. The orchestrator provides the prompt text (e.g., "Intake is complete. What would you like to do next?").

Body: `padding: 2px 0`.

Command row: `display: flex; align-items: flex-start; gap: 14px; padding: 11px 20px`. Cursor: pointer. Hover: `background: var(--bg-card-warm)`. Transition: `background var(--duration-fast) var(--ease-default)`. Adjacent rows separated by `border-top: 0.5px solid --border-divider-light`. Clicking a row sets `chatDraft` to `/${suggestion.id} ` (slash, phase ID, trailing space).

Command name column: `--font-mono`, `--type-breadcrumb` (13px), font-weight 500, `--text-primary`, `white-space: nowrap`, `flex-shrink: 0`, `min-width: 100px`. The `/` prefix rendered as `<span>` with `color: --color-orange`.

Description column: `--font-body`, `--type-breadcrumb` (13px), `--text-muted`, `line-height: 1.4`, `flex: 1`, `min-width: 0`.

Recommended row: `border-left: 3px solid --color-orange`, `padding-left: 17px` (20px minus 3px border), `background: --bg-selected`. Command name color: `--color-orange`. At most one recommended row per panel.

Props: `prompt: string`, `suggestions: Suggestion[]`, `onSelect: (suggestion: Suggestion) => void`.

#### CommandPalette

A floating dropdown anchored above FeedbackInput, triggered when the user types `/` as the first character during a yield point. Shows all available phases in the current workflow, filterable as the user types.

Availability: only when `run.isYielded` is `true`. Gated by `availableCommands` prop on FeedbackInput — when undefined or empty, `/` is regular text.

Positioning: `position: absolute`, `bottom: 100%`, `left: 0`, `right: 0`, `margin-bottom: 6px`. FeedbackInput's `.fi` container provides `position: relative`.

Container: `--bg-card`, `0.5px solid --border-card`, `--radius-2xl` (12px), `overflow: hidden`. Box-shadow: `0 4px 16px rgba(46,58,94,0.10)` (hardcoded, candidate for future `--shadow-dropdown` token). `z-index: 10`.

Backdrop: content stream receives `opacity: 0.35` when the palette is open. Dismissed by Escape, clicking outside, or deleting the `/`.

Hint bar: `padding: 10px 16px`, `background: var(--bg-base)`, `border-bottom: 1px solid --border-divider-light`. Info icon (14px circle, `1.5px solid --border-input`, "i" in `--text-muted`, 9px) + hint text: `--type-tool-type` (12px), `--text-muted`. Text: "Select a command or keep typing to filter".

Palette items: `padding: 10px 16px`. Hover / keyboard-active: `background: var(--bg-tool-row)`. Transition: `background var(--duration-fast) var(--ease-default)`. Adjacent items separated by `border-top: 0.5px solid --border-divider-light`. Max visible before scrolling: 5.

Item command name: `--font-mono`, `--type-breadcrumb` (13px), font-weight 500, `--text-primary`, `margin-bottom: 2px`. `/` prefix: `color: --color-orange`.

Item description: `--type-tool-type` (12px), `--text-muted`, `line-height: 1.3`.

Keyboard: `↑`/`↓` navigate, `Enter` selects, `Escape` closes and clears the `/`. Filtering by prefix match on command name. Empty state: "No matching commands" centered in `--text-muted`.

Selection inserts `/${command.id} ` into FeedbackInput. Cursor placed after trailing space.

Props: `commands: PhaseCommand[]`, `filter: string`, `activeIndex: number`, `onSelect`, `onNavigate`, `onDismiss`.

Component ownership: molecule rendered by FeedbackInput. Palette state is local to FeedbackInput.

#### PhaseMarker

An event divider rendered in the content stream when a phase transition occurs. The teal dot sits on a horizontal rule, acting as a timeline node. The phase label and description flow to the right on the same line.

Container: `padding: 20px 0`, `position: relative`.

Horizontal rule: `position: absolute`, `left: 0`, `right: 0`, `top: 50%`, `transform: translateY(-50%)`, `height: 1px`, `background: var(--border-divider)`. Spans the full content width behind the content group.

Content overlay: `position: relative`, `display: flex`, `align-items: center`, `gap: 10px`, `background: var(--bg-base)`, `padding-right: 16px`. The background creates a visual break in the rule behind the content.

Teal dot: 10px diameter, `background: var(--color-teal)`, `var(--radius-circle)`, `flex-shrink: 0`.

"Phase:" label: `--type-label` (11px), `text-transform: uppercase`, `letter-spacing: 1px`, font-weight 500, `--text-muted`.

Phase name: `--type-breadcrumb` (13px), font-weight 500, `--color-teal`.

Separator: "·" in `--text-muted`.

Description: `--font-body`, `--type-breadcrumb` (13px), `--text-muted`.

Props: `name: string`, `description: string`.

#### ReviewEvent

An event divider rendered in the content stream when the user submits an artifact review. Uses the same dot-on-divider pattern as PhaseMarker, but with an orange dot (user action) instead of teal (system event).

Container: `padding: 20px 0`, `position: relative`. Same layout structure as PhaseMarker.

Horizontal rule: identical to PhaseMarker (`position: absolute`, full width, `1px`, `--border-divider`).

Content overlay: `position: relative`, `display: flex`, `align-items: center`, `gap: 10px`, `background: var(--bg-base)`, `padding-right: 16px`.

Orange dot: 10px diameter, `background: var(--color-orange)`, `var(--radius-circle)`, `flex-shrink: 0`.

"Review:" label: `--type-label` (11px), `text-transform: uppercase`, `letter-spacing: 1px`, font-weight 500, `--text-muted`.

File name: `--font-mono`, `--type-breadcrumb` (13px), font-weight 500, `--color-orange`.

Separator: "·" in `--text-muted`.

Summary: `--font-body`, `--type-breadcrumb` (13px), `--text-muted`. Shows comment count (e.g., "2 comments submitted").

Props: `path: string`, `commentCount: number`.

#### ReviewBlock

A wrapper around a single rendered markdown block (paragraph, heading, list, code block) inside the ReviewPanel organism. The entire block is a click target for opening a comment input. A small "+" button in the left gutter appears on hover as a visual hint.

Container: `display: flex`, `align-items: center`, `gap: 10px`, `padding: 4px 12px`, `margin: 0 -12px`, `border-radius: var(--radius-lg)`, `cursor: pointer`. Transition: `background var(--duration-fast) var(--ease-default)`.

Hover state: `background: var(--bg-selected)`. The gutter button becomes visible.

Active state (comment input open): `background: var(--bg-selected)`, `border-left: 3px solid --color-orange`, `padding-left: 9px`, `margin-left: -15px`. The gutter button is persistently visible.

Gutter button: flex child, `flex-shrink: 0`, `width: 18px`, `height: 18px`, `--radius-circle`. Background `--color-orange`, white "+" text, 12px. `opacity: 0` by default, `opacity: 1` on block hover or active state. Transition: `opacity var(--duration-fast) var(--ease-default)`. Hover: `background: var(--color-orange-hover)`. The button occupies its 18px width even when invisible (opacity: 0), keeping content indented consistently with no layout shift on hover.

Content wrapper: `flex: 1`, `min-width: 0`. First child margin zeroed via `.rb-content > :first-child { margin-top: 0 }` to align content flush with the gutter button.

Click behavior: clicking anywhere on the block opens the comment input. Text selection is preserved — the click handler checks `window.getSelection()` and skips if text was selected via drag. The gutter button click calls `stopPropagation` to prevent double-firing.

Props: `hasComments: boolean`, `isActive: boolean`, `onClickGutter: () => void`, `children: ReactNode`.

#### ReviewComment

A read-only comment card displayed below its anchor ReviewBlock. Gray left accent on the white card surface (user-content convention, matching UserBubble). A delete button appears on hover.

Container: `border-left: 3px solid --text-muted`, `padding: 6px 12px`, `margin-bottom: 4px`. No background (inherits `--bg-card` from ReviewPanel). Uses the gray left-border convention for user-authored content, matching UserBubble.

Header row: `display: flex`, `align-items: center`, `justify-content: space-between`.

Meta line: `--type-badge` (10px), `--text-muted`, `text-transform: uppercase`, `letter-spacing: 0.5px`, font-weight 500. Shows "You · just now" (timestamps are cosmetic in review context).

Delete button: `×` character, 14px, `--text-muted`, `opacity: 0` by default. Appears on `.rc-comment:hover` via `opacity: 1`. On button hover: `color: --status-failed` (red). Transition: opacity and color, `--duration-fast`. Click calls `onDelete` and stops propagation to prevent ReviewBlock toggle.

Comment text: `--type-breadcrumb` (13px), `line-height: 1.5`, `--text-body`.

Props: `text: string`, `onDelete?: () => void`.

#### ReviewCommentInput

An inline comment input form that appears below a ReviewBlock when the user clicks the gutter "+" button.

Container: `background: var(--bg-card)`, `border: 1.5px solid --color-orange`, `border-radius: var(--radius-lg)`, `padding: 10px 12px`, `margin: 6px 0 12px 0`. Focus ring appears only when the textarea is focused: `:focus-within` adds `box-shadow: 0 0 0 3px var(--focus-ring)`.

Textarea: `--font-body`, `--type-breadcrumb` (13px), `line-height: 1.5`, `--text-body`. No border, transparent background. `min-height: 44px`, `resize: vertical`. Placeholder: `--text-placeholder`, text "Add a comment on this block...".

Actions row: `display: flex`, `justify-content: flex-end`, `gap: 8px`, `margin-top: 6px`. Contains Cancel (Button secondary `xs`) and Add comment (Button primary `xs`).

On "Add comment": the input closes, a ReviewComment card appears in its place, and the block's `hasComment` state becomes true (orange dot indicator visible).

Props: `onAdd: (text: string) => void`, `onCancel: () => void`.

#### FeedbackInput

Text input for sending messages to the orchestrator. Sits at the bottom of the content stream.

Container: `--bg-card`, `1.5px solid --border-input`, `--radius-xl` (10px), `var(--padding-input)` (14px 18px). `position: relative` (provides positioning context for CommandPalette).

Focused state (palette open): `border-color: var(--color-orange)`, `box-shadow: 0 0 0 3px var(--focus-ring)`.

Textarea: `--font-body`, `--type-body` (14px), `--text-primary`. Placeholder: `--text-placeholder`. No border, transparent background.

Footer: flex row. Left: hint text in `--type-label` (11px), `--text-hint`. Default: "Enter to send · Shift+Enter for newline". Palette open: "↑↓ navigate · Enter select · Esc dismiss". Right: Button primary `sm`.

**`/`-command support:** When the input value starts with `/` and `availableCommands` is provided, the CommandPalette renders above the input. When a `/`-command message is sent, FeedbackInput transforms it before calling `onSend`:

- `/plan-spec write an implementation plan` → `The user wishes to transition to phase \`plan-spec\` with instruction: write an implementation plan`
- `/plan-spec` (no instruction) → `The user wishes to transition to phase \`plan-spec\`.`

Props: `placeholder?: string`, `onSend?: (text: string) => void`, `disabled?: boolean`, `availableCommands?: PhaseCommand[]`, `onPaletteToggle?: (open: boolean) => void`.

#### ToolCallRow

A single horizontal row representing a standalone tool call. Used for
non-exploration tools (`bash`, `write`, `edit`) that keep their individual
visual weight outside aggregate cards.

Container: `display: flex`, `align-items: center`, `gap: 10px`,
`background: var(--bg-tool-row)`, `border-radius: var(--radius-md)`,
`padding: var(--padding-tool-row)` (7px 14px).

Status indicator column (`width: 13px`, `flex-shrink: 0`) — existing markup,
not routed through `StatusDot`:

- `done`: teal check SVG (`stroke: var(--color-teal)`, 13×13, 2.5 stroke
  width).
- `running`: 6px orange dot rendered as an inline `span.tcr-running-dot`,
  animated by the local `@keyframes tcr-pulse` at 1.5s ease-in-out infinite.
- `error`: `✕` character, `color: var(--status-failed)`, 11px.

Type label (`min-width: 36px`, `flex-shrink: 0`):
`--type-tool-type` (12px), `--text-muted`. Examples: "bash", "write", "edit".

Command / path (`flex: 1`, `min-width: 0`):
`--font-mono`, `--type-tool-path` (12px), `--text-body`, `white-space: nowrap`,
`overflow: hidden`, `text-overflow: ellipsis`. The actual path or shell
command.

Metric (optional, `flex-shrink: 0`, `padding-left: 12px`):
`--font-mono`, `--type-tool-path` (12px), `--text-muted`. Right-aligned.
Added in this spec; absent in the original `ToolCallRow`. Examples:
`"22.8 KB · new"`, `"2.4s · 140 B out"`, `"3 hunks · ±24 lines"`.

Error state: container background `#f6e8e8` (hardcoded, candidate for
`--bg-tool-row-error` in a future token pass), command and metric text
`color: var(--text-danger-body)`.

Running state: container `opacity: 0.8`.

Props: `tool: string`, `command: string`, `status?: 'done' | 'running' | 'error'`
(default `'done'`), `metric?: string`.

#### ToolLogRow

A compact, no-background log row used inside the right pane of
`ToolAggregateCard`. Visually lighter than `ToolCallRow` — no background fill,
no explicit type label (the colored dot encodes the tool family instead).

Container: `display: flex`, `align-items: center`, `gap: 10px`,
`padding: 3px 0`, `font-family: var(--font-mono)`, `font-size: 12px`,
`line-height: 1.5`.

Status indicator: one of

- `StatusDot size="sm" status={type}` where `type` is `read`, `grep`, or `ls`,
  for completed operations. Static teal-family dot.
- An inline pulsing orange dot (6px, same pattern as `ToolCallRow`'s
  `.tcr-running-dot` — local `@keyframes` on the molecule, independent of
  `StatusDot`) for the in-flight operation.

Command (`flex: 1`, `min-width: 0`): `--font-mono`, `font-size: 12px`,
`--text-body`, `white-space: nowrap`, `overflow: hidden`,
`text-overflow: ellipsis`. Typically a compact path or pattern
(e.g., `"plan.md:160-560"`, `"^from|^import"`).

Metric (optional, `flex-shrink: 0`, `padding-left: 12px`):
`font-size: 11px`, `--text-muted`. Right-aligned. Examples:
`"400 lines · 16.1 KB"`, `"46 matches · 6 files"`.

Running state: command text color becomes `--text-subtle`, metric text color
becomes `--color-orange`. This muted-text + orange-metric treatment fires
whenever the row is in its `running` status — there is no separate boolean
prop for it. A completed read renders with a `--dot-read` StatusDot, normal
command text, and a `--text-muted` metric; an in-flight read renders with a
pulsing orange dot, `--text-subtle` command text, and a `--color-orange`
metric text like "reading…".

Props: `status: 'read' | 'grep' | 'ls' | 'running'`, `command: string`,
`metric?: string`.

The single `status` prop covers both the dot's visual and the row's running-
state styling. For an in-flight operation, callers pass `status="running"`
and get both the pulsing orange dot and the dimmed text; for a completed
operation, callers pass the tool-family variant and get both the static
teal-family dot and normal text. The two states always move together, so
collapsing them into one prop keeps the API honest.

#### ToolStatBlock

A single per-tool-type statistics block in the left pane of
`ToolAggregateCard`. Presents aggregated scope information — operation count,
bytes, lines, matches, files touched — for one tool family.

Container: `display: flex`, `flex-direction: column`, `gap: 3px`. Multiple
blocks within a pane are separated by `gap: 12px` via the parent.

Header row: `display: flex`, `align-items: center`, `gap: 8px`. Contains:

- `StatusDot size="md" status={type}` where `type` is `read`, `grep`, or `ls`.
- Tool name: `--font-mono`, `font-size: 12px`, `--text-primary`,
  `font-weight: 500`. E.g., "read", "grep", "ls".
- Op count: `--font-mono`, `font-size: 11px`, `--text-muted`,
  `margin-left: auto` (right-aligned). E.g., "4 ops".

Meta lines (`padding-left: 16px` to align under the tool name, past the dot):
`--font-mono`, `font-size: 11px`, `--text-muted`, `line-height: 1.4`.
Multiple lines rendered via `<br>` or separate elements. Examples:
`"612 lines · 24.7 KB"`, `"3 files touched"`, `"76 matches"`.

Active variant: when the currently-running operation in the aggregate belongs
to this tool type, the tool name becomes `color: var(--color-orange)`,
font-weight 500. The StatusDot and op count are unchanged. Only one
`ToolStatBlock` in a card can be active at a time.

Props: `type: 'read' | 'grep' | 'ls'`, `name: string`, `opCount: string`
(formatted, e.g., `"4 ops"`), `metaLines: string[]`, `active?: boolean`.

#### ToolAggregateCard

A card that groups consecutive exploration tool calls (`read`, `grep`, `ls`)
into a single two-pane visual unit. Always rendered fully expanded — there is
no collapsed state. Replaces the run of individual `ToolCallRow` rows that
would otherwise wall the content stream.

Container: `--bg-card`, `0.5px solid var(--border-card)`,
`border-left: 3px solid var(--color-orange)`, `--radius-xl` (10px),
`overflow: hidden`. The 3px orange left border follows the existing
"left border = content source" convention — tool calls are agent output, so
the card inherits the same source accent as `ProseCard`. The border color
does NOT change when the card is in its active state.

Active state — signaled only in the header and in the inner components, not
in the outer border. When any child operation is in-flight:

1. The header renders a pulsing orange dot plus a short label
   (e.g., "reading projections.py"). This is the primary signal — visible
   at a glance, persistent through the entire active period.
2. The `ToolStatBlock` for the tool type that owns the in-flight operation
   renders with `active={true}`, turning its tool name orange.
3. The in-flight `ToolLogRow` in the right pane renders with
   `status="running"`, replacing its dot with a pulsing orange dot and
   dimming its command text.

When no child operation is in-flight, the header does not render the running
indicator and no stat block or log row is in the active/running state.

Header: `display: flex`, `align-items: baseline`, `gap: 10px`,
`padding: 10px 18px 9px 18px`, `border-bottom: 1px solid var(--border-divider-light)`.
Contains, in order:

1. Aggregate label: `--type-tool-type` (12px), `--text-muted`,
   `letter-spacing: 0.3px`. Always the literal string "explore".
2. Operation count: `--type-body` (14px), `--text-primary`, `font-weight: 500`.
   E.g., "8 operations".
3. Spacer (`flex: 1`).
4. Running indicator (only when `runningLabel` prop is set): inline-flex
   group — a 6px orange pulsing dot (inline span with local `@keyframes`,
   same pattern as `ToolCallRow`'s `.tcr-running-dot`, not `StatusDot`)
   plus a short label in `--font-mono`, `font-size: 11px`, `--color-orange`.
   The label is a human-readable fragment like "reading projections.py" or
   "grepping" — supplied by the caller; the card does not compute it.
   Padding: gap 5px between dot and label.
5. Elapsed (optional): `--font-mono`, `font-size: 11px`, `--text-hint`,
   `padding-left: 8px`. A formatted duration string like "3m 24s". Shown for
   both completed and active cards. This is the aggregate's total wall-clock
   duration — per-operation durations are intentionally NOT shown anywhere,
   because exploration tools return near-instantly and per-op duration is
   noise. See the design rationale section on duration vs scope metrics.

Body: `display: grid`, `grid-template-columns: 240px 1fr`. Two panes with a
vertical divider between them.

Left pane (stats): `background: var(--bg-card-warm)`,
`border-right: 1px solid var(--border-divider-light)`, `padding: 14px 16px`,
`display: flex`, `flex-direction: column`, `gap: 12px`. Contains a stack of
`ToolStatBlock` molecules, one per tool family present in the aggregate. Tool
families with zero operations are not rendered. Ordering: `read`, `grep`,
`ls` (alphabetical-by-convention; the caller orders).

Right pane (log): `padding: 11px 18px 11px 16px`, `display: flex`,
`flex-direction: column`, `gap: 0`. Contains a stack of `ToolLogRow`
molecules in strict chronological order. The currently-running row, if any,
is rendered last.

The two panes carry orthogonal information. The left pane is enduring
summary — operations fold into their type's totals. The right pane is the
chronological event stream. The left pane is meant to land the eye; the
right pane is meant to scroll past.

Props: `operationCount: number`, `runningLabel?: string`
(when set, card is in active state and the running indicator renders),
`elapsed?: string`, `statsPane: ReactNode` (typically a list of
`ToolStatBlock` elements), `logPane: ReactNode` (typically a list of
`ToolLogRow` elements).

The card uses slot-based composition rather than prescribed data arrays,
because the grouping logic that produces the stats and log rows lives
outside the card (in a utility function consumed by `App.tsx`). Keeping
the card slot-based keeps it pure layout and lets the molecules it contains
stay independently usable.

### Settings Molecules

#### FormRow

Label + control(s) horizontal layout. Used inside InlineForm.

Container: `display: flex; align-items: center`. Rows separated by `--gap-form-rows` (12px) via margin-bottom.

Label: `--type-label` (11px), font-weight 500, `--text-muted`, uppercase, letter-spacing 0.5px. Width: 82px, `text-align: right`, `padding-right: 16px`, `flex-shrink: 0`.

Controls container: `flex: 1; display: flex; gap: var(--gap-form-controls)` (8px). Contains one or more TextInput or Select atoms.

Props: `label: string`, `children: ReactNode`.

#### EntityRow

A two-line list item for configuration entities: profiles, agent installations.

Container: `--padding-entity-row` (12px 16px), `--radius-lg`, `0.5px solid --border-card`. Margin-bottom: `--gap-entity-rows` (8px).

Line 1: `display: flex; align-items: center; gap: 8px`. Entity name: 14px/500 `--text-primary`. For technical identifiers (installation aliases): 13px/500 `--font-mono`. Badges sit inline after the name. Action buttons pushed right via `flex: 1` spacer before them.

Line 2: 12px `--text-muted`, `margin-top: 5px`. Uses `--font-mono` for tier summaries and file paths.

Active state (entity is being edited): border changes to `1.5px solid --color-orange`, visually connecting the row to the InlineForm below it.

Props: `name: string`, `mono?: boolean`, `badges?: BadgeProps[]`, `meta?: string`, `actions?: ReactNode`, `active?: boolean`.

#### TabBar

Horizontal category switcher. Used for agent installation runner types.

Container: `display: flex; gap: 20px; border-bottom: 1px solid --border-divider; margin-bottom: 18px`.

Each tab: `--font-body`, 13px, `padding-bottom: 8px; border-bottom: 2px solid transparent; margin-bottom: -1px` (overlaps container border). Cursor: pointer. No background, no side padding, no border-radius.

Active tab: `--text-primary`, font-weight 500, `border-bottom-color: --color-orange`.
Inactive tab: `--text-muted`, font-weight 400.

Props: `tabs: string[]`, `activeTab: string`, `onChange: (tab: string) => void`.

#### SettingRow

A horizontal layout for individual auto-saving preference controls: label + description on the left, compact control on the right.

Container: `display: flex; align-items: flex-start; gap: 16px; padding: 14px 0`. Adjacent SettingRows are separated by a `0.5px solid --border-card` top border.

Left side (`flex: 1`): Label in 14px/500 `--text-primary`. Description in 12px `--text-muted`, `margin-top: 3px`, `line-height: 1.4`.

Right side (`flex-shrink: 0`, `margin-top: 2px`): any compact control — Toggle, Select, or similar. The 2px top margin aligns the control with the label baseline.

Props: `label: string`, `description?: string`, `children: ReactNode`.

#### InlineForm

An expandable edit/create region that appears inline below entity rows within a settings section card.

Container: `1.5px solid --color-orange`, `--radius-xl` (10px), `--padding-inline-form` (22px 26px), `--bg-card`. The orange border signals "user input expected here."

Contains FormRow children and a form actions row. Form actions: `display: flex; gap: 8px; margin-top: 20px; padding-left: 82px` (aligns with the left edge of form controls). Contains Cancel (Button secondary) and Save (Button primary).

InlineForm is the only place where explicit Save buttons appear in configuration UI. All standalone controls (Toggle, NumberInput, standalone Select in SettingRow) auto-save on interaction.

Props: `children: ReactNode`, `onSave: () => void`, `onCancel: () => void`, `saving?: boolean`.

#### NavItem

A side navigation item for the Settings page.

`display: block; font-size: 13px; --font-body; padding: 6px 16px; border-left: 2px solid transparent; cursor: pointer; margin-bottom: 1px`.

Active: `font-weight: 500; color: --text-primary; border-left-color: --color-orange`.
Inactive: `font-weight: 400; color: --text-muted`.
Hover (inactive): `color: --text-subtle`.

No background on any state. No border-radius.

Props: `label: string`, `active: boolean`, `onClick: () => void`.

---

## Organisms

### SettingsPage

Full-page settings view accessible via "Settings" in the header navigation.

Two-column flex layout within a centered container (`--settings-max-width`, 960px, `margin: 0 auto`). Left column: stack of NavItem elements (`--settings-nav-width`, 152px, `padding: 36px 0`, `flex-shrink: 0`). Right column: content area (`flex: 1`, `padding: 36px 0 36px 28px`, `min-width: 0`, `overflow-y: auto`).

Content area shows: section title (20px/500 `--text-primary`, letter-spacing -0.3px, margin-bottom 6px), section description (13px `--text-muted`, margin-bottom 22px), then one or more section cards.

Section cards: `--bg-card`, `--radius-2xl` (12px), `0.5px solid --border-card`, `--padding-card-settings` (22px 26px).

Only the active section renders. Side nav controls which section is visible.

**Sections:**

- **Profiles:** EntityRows + InlineForm for create/edit + Button text trigger. All inside a section card.
- **Agents:** TabBar for runner types + EntityRows for installations + InlineForm for create/edit. All inside a section card.
- **Runtime:** NumberInput for scout concurrency (with heading above), then SettingRows with Toggle/Select controls. Hairline `0.5px solid --border-card` divider separates the scalar controls from the SettingRow list. All inside a section card.
- **Workflow:** SettingRow with Toggle for "Auto-open new or changed artifacts" (default: on). Description: "Automatically open artifacts for review when they are created or modified." Additional SettingRows for future workflow preferences. Inside a section card.
- **Preferences, Debug, About:** future sections using the same patterns.

### ReviewPanel

Full-width artifact review surface that takes over the content column when an artifact is opened for review. Renders a markdown document with per-block inline commenting. The ArtifactsSidebar remains visible — the user can switch between artifacts during review.

**Trigger:** auto-opens when a new or modified artifact is detected (gated by the "Auto-open artifacts" setting, default: on). Also opens when the user clicks an artifact in the ArtifactsSidebar.

**Yield behavior:** opening a ReviewPanel yields the conversation (same mechanism as AskQuestion). The orchestrator is blocked until the user submits or closes the review. The FeedbackInput is not rendered while ReviewPanel is active.

Card container: `--bg-card`, `--radius-2xl` (12px), `0.5px solid --border-card`, `border-top: 3px solid --color-orange`. Same card treatment as ElicitationPanel decision panel.

**Header:** `display: flex`, `align-items: center`, `gap: 12px`, `padding: 16px 24px`, `border-bottom: 0.5px solid --border-divider-light`.

- "REVIEW" label: `--type-label` (11px), font-weight 500, uppercase, `letter-spacing: 1px`, `--color-orange`. Same treatment as SectionLabel with color="orange".
- File path: `--font-mono`, `--type-tool-type` (12px), `--text-muted`.
- Right side: comment count badge — `--type-badge` (10px), `--text-muted`, `padding: 2px 10px`, `background: var(--bg-tool-row)`, `--radius-pill`. Shows "N comments" or "new" badge (`--type-badge`, `--color-orange`, font-weight 500, `padding: 2px 8px`, `background: var(--bg-selected)`, `0.5px solid --color-orange`, `--radius-pill`) when the artifact has not been reviewed yet.

**Body:** `padding: 20px 24px 12px 24px`. Contains a stack of ReviewBlock elements, each wrapping a rendered markdown AST node (paragraph, heading, list, code block, horizontal rule). The markdown is rendered using the existing Md component. Each top-level AST node is wrapped in a ReviewBlock.

**Footer:** `border-top: 0.5px solid --border-divider-light`, `padding: 16px 24px`.

- Top section: "OVERALL FEEDBACK (OPTIONAL)" label (`--type-label`, 11px, font-weight 500, uppercase, `letter-spacing: 0.5px`, `--text-muted`, `margin-bottom: 6px`). Below it, a textarea (`1.5px solid --border-input`, `--radius-lg`, `padding: 10px 14px`, `--font-body`, `--type-breadcrumb` 13px, `--text-body`, `background: var(--bg-card)`, `min-height: 52px`, `resize: vertical`). Focus: `border-color: --color-orange`, `box-shadow: 0 0 0 3px var(--focus-ring)`. Placeholder: "Summarize your review — e.g. 'Looks good, just clarify the channel types and add PagerDuty'".
- Bottom section (`margin-top: 12px`): `display: flex`, `align-items: center`, `gap: 12px`. Left: hint text (`--type-label` 11px, `--text-hint`) showing "N inline comments will be submitted" or "No comments yet — click + on any block above". Right (pushed via flex spacer): "Close without submitting" (Button secondary `sm`) and "Submit review" (Button primary `sm`).

**Submit payload:** When the user clicks "Submit review", the frontend collects:

1. Per-block comments: each comment paired with the first 200 characters of its anchor block's text content (for the agent to locate the block in the markdown source).
2. The overall feedback summary text (may be empty).

These are sent to the backend as a single structured message. A ReviewEvent molecule is inserted into the content stream, and the content column returns to the normal stream view.

**Close without submitting:** discards all draft comments and closes the review. No ReviewEvent is inserted. The content column returns to the stream. The artifact can be reopened from the sidebar.

**Switching artifacts:** clicking a different artifact in the ArtifactsSidebar while reviewing swaps the ReviewPanel body to show the new artifact. Draft comments are preserved per-artifact in component-local state — switching back restores them.

---

## Header Bar

The header bar operates in two modes:

**Navigation mode:** Used on the New Run, Sessions, and Settings pages. The zone right of the logo divider shows top-level navigation links: "New run", "Sessions", "Settings". Each link: `--type-breadcrumb` (13px), `--font-body`. Active page: `--text-on-dark`, font-weight 500. Inactive pages: `--text-on-dark-muted`, font-weight 400. Links separated by 6px gap.

**Workflow mode:** Used during an active workflow run. The zone right of the logo divider shows the phase/step breadcrumb and progress segments. Navigation links are not shown.

Settings is accessed via the "Settings" navigation link. There is no separate settings icon in the header.

---

## Layout: Settings View

Used for the Settings page. Two-column layout: side navigation + scrollable content area.

```
Structure:
  Flex column (100vh, overflow: hidden):
  ├─ HeaderBar (flex-shrink: 0, full viewport width, navigation mode)
  └─ Centered container (flex: 1, min-height: 0, max-width: 960px, margin: 0 auto)
     ├─ Side nav (width: 152px, padding: 36px 0, flex-shrink: 0)
     │  └─ Stack of NavItem elements
     └─ Content area (flex: 1, padding: 36px 0 36px 28px, min-width: 0,
                       overflow-y: auto)
        ├─ Section title (20px/500, --text-primary, letter-spacing: -0.3px)
        ├─ Section description (13px, --text-muted, margin-bottom: 22px)
        └─ Section card(s) (--bg-card, --radius-2xl, --padding-card-settings)
           └─ Section-specific content
```

No ArtifactsSidebar. No ScoutBar. Header in navigation mode.

---

## Design Rationale

### Border weight rules

Two border weight tiers:

- **`0.5px solid`** — cards, panels, dividers. Used for ProseCard, UserBubble, ElicitationPanel, YieldPanel, CommandPalette, EntityRow, section cards. These are passive containers.
- **`1.5px solid`** — input fields and active editing regions. Used for TextInput, Select, FeedbackInput, InlineForm (with `--color-orange`), EntityRow active state. These are interactive input surfaces.

The `1.5px` weight is never used for cards or panels. The `0.5px` weight is never used for input fields.

### Orange semantics

Orange is used at three weight tiers, each with a distinct meaning:

- **`3px solid` left accent** — "suggested default." Applied to the recommended option in RadioOption/CheckboxOption and the recommended command row in YieldPanel. Draws the eye without demanding action. Paired with `--bg-selected` background tint. This is the weakest orange signal.
- **`1.5px solid` full border** — "user input expected." Applied to selected RadioOption/CheckboxOption cards and InlineForm active regions. Signals an active editing surface. When an option is both recommended and selected, the `1.5px` full border takes precedence over the `3px` left accent (uniform border wins).
- **`3px solid` top accent** — "panel-level attention." Applied to ElicitationPanel decision panel. The strongest orange signal, used at the organism level.

### Teal for system events

`--color-teal` is used for system-level indicators: status dots (done/running), CompletionBanner, PhaseMarker labels, teal-variant buttons for utility actions. Phase transitions are system events — the teal PhaseMarker label distinguishes it from agent content (orange accent) and user content (gray left border).

### Dot-on-divider = event

A teal dot sitting on a horizontal rule signals a system event — something structural happened in the workflow. PhaseMarker uses this pattern for phase transitions. The dot interrupts the divider line and anchors the event label to its right. This pattern is distinct from content cards (which have borders and padding) and section labels (which sit above content). Events happen between content; cards contain content.

### Left border = content source

Left-border color on stream cards encodes content origin:

- **Orange** — agent prose (ProseCard).
- **Gray (`--text-muted`)** — user content: messages (UserBubble), review comments (ReviewComment).
- **Teal** — system events (PhaseMarker label uses teal text rather than a border, but the principle holds).

### Save model

Explicit Cancel/Save appears only inside InlineForm. All standalone controls (Toggle, NumberInput, Select outside InlineForm) auto-save on interaction. The distinction: if a control always has a valid state at every moment, it auto-saves. If a multi-field form can have invalid intermediate states (e.g., profile with runner set but model blank), it requires explicit save.

### Font usage in form controls

All form controls use `--font-body`. The `mono` prop on TextInput is for values that are technical identifiers (file paths, binary paths, extra args). Select always uses `--font-body` even when displaying technical values like runner or model names. CommandPalette and YieldPanel use `--font-mono` for `/command` names since these are technical identifiers.

### Section cards in settings vs stream content

The content stream uses individual molecules (ProseCard, ToolCallRow, YieldPanel) floating on `--bg-base`. Settings uses white section cards grouping related entity rows. The stream is a timeline where each item is independent. Settings is a form where items within a section are related. The card boundary communicates "these things belong together."

### `/`-command transformation

FeedbackInput rewrites `/plan-spec ...` into natural language before sending to the backend. The `/` prefix is a UI convention only — the orchestrator receives a clear, structured instruction without requiring backend slash-command parsing.

### Internal tool call suppression

Koan orchestration tools (`koan_yield`, `koan_complete_step`, `koan_set_phase`) are internal to the workflow engine. Their effects are visible through the molecules they trigger (YieldPanel, StepHeader, PhaseMarker). They do not render as ToolCallRows in the content stream.

### Orange dot-on-divider = user event

The dot-on-divider pattern is extended with color semantics. A **teal dot** signals a system event (PhaseMarker — the workflow engine changed phase). An **orange dot** signals a user event (ReviewEvent — the user submitted artifact feedback). Both use identical layout; only the dot color differs. This preserves the "events happen between content" principle while distinguishing system-initiated from user-initiated transitions.

### Review card pattern

The ReviewPanel card uses `border-top: 3px solid --color-orange`, the same "panel-level attention" signal as ElicitationPanel's decision panel. Both are organisms that yield the conversation and require user action to proceed. The visual consistency communicates this shared interaction pattern: the workflow is paused, waiting for you.

### Tool aggregation scope

Exploration tools (`read`, `grep`, `ls`) are aggregated into
`ToolAggregateCard` when two or more appear consecutively in the conversation
stream without any other entry type between them (prose, thinking, user
message, step boundary, phase marker, `bash`, `write`, `edit`, or any other
tool). A lone `read` renders as a standalone `ToolCallRow`. A run of two or
more consecutive reads/greps/ls's collapses into one card.

`bash`, `write`, and `edit` are never aggregated. `bash` has too much
semantic variance — it can be a one-line formatter, a heavy test run, or an
arbitrary script — and compressing disparate bash calls into a summary
obscures rather than clarifies. `write` and `edit` are mutations; each is
individually significant. All three render as standalone `ToolCallRow`s.

### Tool aggregation active state

Active state on `ToolAggregateCard` is communicated through three in-card
signals, not through a border color change. When an operation inside the
card is in-flight:

1. The card header renders a pulsing orange dot plus a short label
   (e.g., "reading projections.py").
2. The stat block for the tool type that owns the in-flight operation
   renders with `active={true}`, turning its tool name orange.
3. The in-flight log row in the right pane renders with `status="running"`,
   replacing its dot with a pulsing orange dot and dimming its command
   text.

The card's left border stays orange throughout (see "Left border = content
source"). Not changing the border preserves the content-source convention
without conflating "this is agent content" with "this is happening right
now." The three in-card signals are enough: the user always has a clear
"something is still happening" indicator without ambiguity in the outer
chrome.

The signal is qualitative and textual (label + pulsing dot) rather than
quantitative and spatial (a progress bar), because the total number of
operations is not known in advance. A horizontal progress bar would falsely
imply a completion endpoint; a pulsing dot next to a label does not.

### Duration vs scope metrics

`ToolAggregateCard` and `ToolLogRow` show per-operation scope metrics —
bytes read, lines read, matches found, files touched, hunks edited — and
deliberately omit per-operation duration. Exploration tools return in
milliseconds in practice, so per-op duration is noise that competes for
attention with the signal.

Per-aggregate duration is shown once, in the card header, because the
total wall-clock time across a run of exploration ops is legitimately
useful — it tells the user whether the agent is thinking slowly, spawning
many ops, or encountering a tool that happened to be genuinely slow. The
distinction is scale: individual ops are fast, aggregates are not.

`ToolCallRow` (standalone) does show a metric that may include duration for
`bash` specifically, because bash duration is frequently meaningful.
`ToolCallRow` for `write` and `edit` shows size/line-count metrics without
duration.
