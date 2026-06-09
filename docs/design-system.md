# Koan Design System

The single source of truth for koan's visual design. `src/styles/variables.css` is a mechanical translation of the token tables below. The doc changes first, then the CSS follows.

---

## Tokens

### Background surfaces

| Token              | Hex       | Usage                                                                                 |
| ------------------ | --------- | ------------------------------------------------------------------------------------- |
| `--bg-danger`      | `#fce8e8` | Destructive confirmation backgrounds. Red-family tint.                                |
| `--bg-toggle-off`  | `#d3d1c7` | Toggle track off state. Neutral warm gray, lighter than `--border-input`.             |
| `--bg-diff-before` | `#fbf6f6` | DiffPane "Current" column background. Quiet red-family tint.                          |
| `--bg-diff-after`  | `#e6f2ec` | DiffPane "Proposed" column background. Quiet green-family tint.                       |
| `--diff-hl-add-bg` | `#c6e6d5` | Inline addition highlight background in `DiffPane`. Stronger than `--bg-diff-after`.  |
| `--diff-hl-del-bg` | `#f2d0d0` | Inline deletion highlight background in `DiffPane`. Stronger than `--bg-diff-before`. |

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

| Token                  | Hex       | Usage                                                                     |
| ---------------------- | --------- | ------------------------------------------------------------------------- |
| `--color-orange-hover` | `#c06a4f` | Hover state for orange interactive elements (ReviewBlock gutter button).  |
| `--color-purple`       | `#8e7ca0` | Memory type indicator color for `procedure`. `MemoryTypeIcon` background. |

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

Variant type: `'neutral' | 'success' | 'accent' | 'model' | 'default' | 'error' | 'decision' | 'lesson' | 'context' | 'procedure' | 'add' | 'update' | 'deprecate'`.

**Default variant:** text `#c06030` (darkened orange), background `#fdf2ee` (orange-tinted). Used for "default" installation labels.

**Error variant:** text `--status-failed`, background `--bg-danger`. Used for "unavailable" status.

**Memory type variants** (`decision`, `lesson`, `context`, `procedure`): all render with `--bg-tool-row` background and `--text-subtle` text. All 4 memory-type variants currently render identically because their color encoding lives in `MemoryTypeIcon` rather than in the badge. Variants remain separate so they can diverge without breaking consumers of `MemoryTypeBadge`.

**Operation variants:**

| Variant     | Background        | Text color          |
| ----------- | ----------------- | ------------------- |
| `add`       | `--bg-completion` | `--text-completion` |
| `update`    | `#fdf2ee`         | `#c06030`           |
| `deprecate` | `--bg-danger`     | `--text-danger`     |

Consumers go through the `OperationBadge` alias atom.

### MemoryTypeBadge

Alias atom over `Badge`. Renders `<Badge variant={type}>` with the type name capitalized as the label: `decision` -> "Decision", `lesson` -> "Lesson", `context` -> "Context", `procedure` -> "Procedure".

Props: `type: 'decision' | 'lesson' | 'context' | 'procedure'`.

### OperationBadge

Alias atom over `Badge`. Renders `<Badge variant={op}>` with a prefix glyph + capitalized operation as the label:

| Op          | Label         |
| ----------- | ------------- |
| `add`       | `+ Add`       |
| `update`    | `~ Update`    |
| `deprecate` | `- Deprecate` |

The `deprecate` prefix is U+2212 MINUS SIGN. The prefix glyph is part of the label text, not separately styled.

Props: `op: 'add' | 'update' | 'deprecate'`.

### MemoryTypeIcon

28x28 colored rounded-square icon with a single-letter label identifying memory type. Used by `MemoryCard` and composition previews.

Container: `28px` x `28px`, `--radius-md`, `display: inline-flex`, `align-items: center`, `justify-content: center`, `flex-shrink: 0`.

Per-type background color and letter:

| Type        | Background       | Letter |
| ----------- | ---------------- | ------ |
| `decision`  | `--color-navy`   | `D`    |
| `lesson`    | `--color-orange` | `L`    |
| `context`   | `--color-teal`   | `C`    |
| `procedure` | `--color-purple` | `P`    |

Letter styling: `--font-mono`, 11px, font-weight 700, `color: white`, `line-height: 1`.

Props: `type: 'decision' | 'lesson' | 'context' | 'procedure'`.

### CiteChip

Inline reference chip rendered within prose. Used by briefing text in `MemoryReflectPage` and entry bodies in `MemoryDetailPage` to link to other memory entries by sequence number.

Container: `display: inline-block`, `vertical-align: baseline`. Padding: `0 6px`. Border-radius: `3px` (hardcoded; candidate for a future `--radius-sm` token). Background: `var(--bg-selected)`. Border: `0.5px solid rgba(212, 119, 90, 0.3)` (`--color-orange` at 30% alpha). Margin: `0 1px`. Cursor: `pointer`. No underline.

Text: `--font-mono`, 11px, font-weight 500, `line-height: 1`, `color: var(--color-orange)`.

Hover: background `rgba(212, 119, 90, 0.12)` (`--color-orange` at 12% alpha), border-color `var(--color-orange)` (opaque). Transition: background and border-color, `--duration-fast`.

Focus: `:focus-visible` outline: 2px `var(--color-orange)` at 2px offset.

CiteChip's 3px radius is deliberately tighter than Badge's pill radius. Inline chips live inside running prose; a pill-shaped chip would disrupt the reading baseline more than a rounded-rectangle chip. The chip's job is to feel like a recognizable token without turning into a button.

Props: `seq: string` (sequence number to display, e.g., `"0065"`), `onClick?: () => void`.

### QueueStateIndicator

22x22 circle shown in the curation queue, one per proposal. Communicates whether each proposal has been decided.

Container (all states): `width: 22px`, `height: 22px`, `--radius-circle`, `display: inline-flex`, `align-items: center`, `justify-content: center`, `flex-shrink: 0`.

**pending:** transparent background, `1.5px dashed var(--border-input)`. Content: 1-indexed position number. Text: `--font-mono`, 11px, font-weight 700, `--text-muted`, `line-height: 1`.

**approved:** background `var(--color-teal)`, no border. Content: checkmark (U+2713). Text: 11px, font-weight 700, white, `line-height: 1`.

**rejected:** background `var(--status-failed)`, no border. Content: multiplication x (U+2715). Text: 11px, font-weight 700, white, `line-height: 1`.

Static. No hover, no animation. The indicator is a status read-out, not an interactive control.

The `pending` state uses a dashed border rather than a solid one to signal "awaiting input" without competing visually with the solid-filled decided states. The 22px size is larger than StatusDot (6-8px) because QueueStateIndicator carries content (a digit or glyph), where StatusDot is a pure primitive.

Props: `state: 'pending' | 'approved' | 'rejected'`, `index: number` (always required; rendered only when `state === 'pending'`).

### FileChip

A removable pill showing an attached file's name and size. Used inside any composer surface that supports file attachment. Same visual family as Badge (mono font, pill radius, compact padding) but purpose-built for the dismiss + metadata layout that Badge does not support.

Container: `display: inline-flex`, `align-items: center`, `gap: 4px`, `padding: 2px 6px 2px 8px`, `background: var(--bg-tool-row)`, `border-radius: var(--radius-pill)`, `white-space: nowrap`.

Filename: `--font-mono`, 11px, `--text-subtle`. `overflow: hidden`, `text-overflow: ellipsis`, `max-width: 160px`.

Size label: `--font-mono`, 10px, `--text-hint`. `flex-shrink: 0`. Formatted compact (e.g., "2.1K", "340K", "1.2M").

Dismiss button: `background: none`, `border: none`, `padding: 1px`, `cursor: pointer`, `color: var(--text-hint)`, `display: flex`, `align-items: center`. Contains an 8x8 X SVG (`stroke: currentColor`, `strokeWidth: 2`, `strokeLinecap: round`). Hover: `color: var(--text-subtle)`.

Uploading state: filename replaced by "Uploading...", size label hidden, dismiss button hidden. `opacity: 0.6`.

Error state: `background: var(--bg-danger)`, filename `color: var(--text-danger)`. Dismiss button visible.

Props: `name: string`, `size: string`, `state?: 'ready' | 'uploading' | 'error'` (default `'ready'`), `onRemove?: () => void`.

### StatCell

Single labeled numeric value. Composition unit for `StatStrip`; not used standalone in product UIs.

**Size `lg`** (default -- used on `MemoryOverviewPage`'s stats strip): flex row, `align-items: baseline`, `gap: 8px`. Value: `--font-display`, 22px, font-weight 400, `letter-spacing: -0.3px`, `--text-primary`. Label: `var(--type-breadcrumb)` (13px), `--text-muted`.

**Size `sm`** (used on `MemoryReflectPage` done-meta strip): flex row, `align-items: baseline`, `gap: 5px`. Value: `--font-mono`, `var(--type-breadcrumb)` (13px), font-weight 500, `--text-primary`. Label: `--font-body`, `var(--type-breadcrumb)` (13px), `--text-muted`.

The two sizes use different font families intentionally: `lg` uses the display serif to match page-level stat headers (overview, entry counts), while `sm` uses the monospace to match in-stream meta readouts (elapsed time, iteration count). The sizes are not interchangeable -- they encode different reading contexts.

Props: `value: string` (pre-formatted, e.g., `"28s"`, `"~290"`), `label: string`, `size?: 'lg' | 'sm'` (default `'lg'`).

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

An inline comment input form that appears below a ReviewBlock when the user clicks the gutter "+" button. Supports file attachment via gutter icon, drag-and-drop, and clipboard paste.

Container: `background: var(--bg-card)`, `border: 1.5px solid --color-orange`, `border-radius: var(--radius-lg)`, `padding: 10px 12px`, `margin: 6px 0 12px 0`. Focus ring appears only when the textarea is focused: `:focus-within` adds `box-shadow: 0 0 0 3px var(--focus-ring)`.

Drag-over state: same overlay treatment as FeedbackInput, scaled to the smaller container.

Textarea wrapper: `position: relative`. Contains the textarea and gutter attach button.

Textarea: `--font-body`, `--type-breadcrumb` (13px), `line-height: 1.5`, `--text-body`. No border, transparent background. `min-height: 44px`, `resize: vertical`, `padding-right: 24px`. Placeholder: `--text-placeholder`, text "Add a comment on this block...".

Gutter attach button: `position: absolute`, `right: 0`, `bottom: 2px`. Paperclip SVG icon (11px, `stroke: var(--text-hint)`). `opacity: 0.5`. Hover: `opacity: 1`.

File chips row: rendered between textarea wrapper and actions row when files are attached. `display: flex`, `flex-wrap: wrap`, `gap: 4px`, `margin-top: 4px`. Contains `FileChip` atoms.

Actions row: `display: flex`, `justify-content: flex-end`, `gap: 8px`, `margin-top: 6px`. Contains Cancel (Button secondary `xs`) and Add comment (Button primary `xs`).

On "Add comment": the input closes, a ReviewComment card appears in its place, and the block's `hasComment` state becomes true (orange dot indicator visible).

Props: `onAdd: (text: string, attachments?: string[]) => void`, `onCancel: () => void`.

#### FeedbackInput

Text input for sending messages to the orchestrator. Sits at the bottom of the content stream. Supports file attachment via gutter icon, drag-and-drop, and clipboard paste.

Container: `--bg-card`, `1.5px solid --border-input`, `--radius-xl` (10px), `var(--padding-input)` (14px 18px). `position: relative` (provides positioning context for CommandPalette).

Focused state (palette open): `border-color: var(--color-orange)`, `box-shadow: 0 0 0 3px var(--focus-ring)`.

Drag-over state: `border-color: var(--color-orange)`, `box-shadow: 0 0 0 3px var(--focus-ring)`. An overlay covers the composer area: `background: rgba(255,255,255,0.92)`, centered upload icon (20px, `stroke: var(--color-orange)`) and "Drop to attach" label (`--font-body`, 13px, font-weight 500, `--color-orange`).

Textarea wrapper: `position: relative`. Contains the textarea and a gutter attach button.

Textarea: `--font-body`, `--type-body` (14px), `--text-primary`. Placeholder: `--text-placeholder`. No border, transparent background. `padding-right: 28px` to clear the gutter button.

Gutter attach button: `position: absolute`, `right: 0`, `bottom: 4px`. Paperclip SVG icon (13px, `stroke: var(--text-hint)`). `opacity: 0.6`. Hover: `opacity: 1`. Click opens hidden `<input type="file" multiple>`.

File chips row: rendered between textarea wrapper and footer when `files.length > 0`. `display: flex`, `flex-wrap: wrap`, `gap: 4px`, `margin-top: 6px`. Contains `FileChip` atoms.

Footer: flex row. Left: hint text in `--type-label` (11px), `--text-hint`. Default: "Enter to send -- Shift+Enter for newline". Palette open: "up/down navigate -- Enter select -- Esc dismiss". Right: Button primary `sm`.

**File attachment:** Files are uploaded immediately on drop/paste/select via `POST /api/upload` (multipart/form-data). Each upload returns `{ id, filename, size, content_type }`. FileChip shows uploading state during upload. On send, the payload includes `attachments: string[]` (file IDs) alongside the text.

**`/`-command support:** When the input value starts with `/` and `availableCommands` is provided, the CommandPalette renders above the input. When a `/`-command message is sent, FeedbackInput transforms it before calling `onSend`:

- `/plan-spec write an implementation plan` -> `The user wishes to transition to phase \`plan-spec\` with instruction: write an implementation plan`
- `/plan-spec` (no instruction) -> `The user wishes to transition to phase \`plan-spec\`.`

Props: `placeholder?: string`, `onSend?: (text: string, attachments?: string[]) => void`, `disabled?: boolean`, `availableCommands?: PhaseCommand[]`, `onPaletteToggle?: (open: boolean) => void`.

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

### Memory Molecules

#### RelationsCard

Shared molecule for rendering entry relations and citations. Promoted from
`MemoryDetailPage` (its first consumer) when `MemoryReflectPage` added a
second consumer (citations). Two consumers is the promotion threshold per
the design-system rule.

File: `frontend/src/components/molecules/RelationsCard.tsx` + colocated
`.css`.

Card chrome: `--bg-card`, `0.5px solid --border-card`, `--radius-2xl`,
`padding: 22px 30px 26px`.

Head row: eyebrow (`--color-teal`, `var(--type-label)`, uppercase,
font-weight 500). Optional counts pushed right (`margin-left: auto`):
`--font-mono`, 12px, `--text-muted`, number in `--text-body` weight 500.

**Props:**

- `outgoing: RelationEntry[]` -- entries this record points to (always
  rendered).
- `incoming?: RelationEntry[]` -- entries pointing here (default `[]`).
- `eyebrow?: string` -- card label, default `"Relations"`.
- `counts?: boolean` -- show count summary in the head row, default `true`.
- `layout?: 'split' | 'single'` -- `'split'` (default) renders both
  columns with a `grid-template-columns: 1fr 1fr` grid; `'single'` renders
  only the outgoing column at full width (used for citations on
  `MemoryReflectPage`).

**Current consumers:**

1. `MemoryDetailPage` -- relations (split layout, eyebrow "Relations").
2. `MemoryReflectPage` -- citations (single layout, eyebrow "Citations").

#### MemoryCard

Repeating unit for listing memory entries. Used by `MemorySidebar`, the curation queue, the relations section on `MemoryDetailPage`, and any future memory list. Composes `MemoryTypeIcon`.

Container: `display: grid`, `grid-template-columns: 28px 1fr`, `gap: 10px`, `align-items: start`. Padding: `10px 8px`. Border-radius: `--radius-md`. Cursor: pointer. Background: transparent. Hover: `background: var(--bg-selected)`. Transition: background, `--duration-fast`. No outer border, no outline.

**Current-entry variant** (`current={true}`): background `var(--bg-selected)`, `border-left: 3px solid var(--color-orange)`. Padding changes to `10px 8px 10px 5px` -- the 3px border is offset by reducing left padding from 8px to 5px so the 28px icon column stays pixel-aligned with non-current cards in the same list. Without the compensation, icon columns jitter by 3px on navigation, which is unacceptable in sidebar lists. Hover on current: background stays `--bg-selected`, no further darkening.

Icon slot: renders `<MemoryTypeIcon type={type} />` directly. No wrapper.

Body slot (second grid column): `display: flex`, `flex-direction: column`, `gap: 2px`, `min-width: 0`.

Head row: `display: flex`, `align-items: center`, `gap: 6px`. Sequence number: `--font-mono`, 10px, `--text-hint`. Type label: 9px, font-weight 500, `text-transform: uppercase`, `letter-spacing: 0.6px`, `--text-subtle`.

Title: 12px, `--text-primary`, `line-height: 1.35`, font-weight 500. Clamped to 2 lines: `display: -webkit-box`, `-webkit-line-clamp: 2`, `line-clamp: 2`, `-webkit-box-orient: vertical`, `overflow: hidden`.

Root element: `<button type="button">` when `onClick` is provided, else `<div>`. Button resets default browser styles. `:focus-visible` outline 2px `var(--color-orange)` at 2px offset. No `:focus` rule.

`MemoryCard` uses a dashed/solid outline pattern on its `MemoryTypeIcon` when rendered inside a context-aware list (e.g., reflect's sidebar highlighting cited entries, entry detail's sidebar highlighting related entries). Those outline states live on the consuming organism, not on `MemoryCard` itself -- the card stays context-free and the sidebar applies a wrapper class. Keeps the molecule reusable across contexts with different highlight semantics.

Props: `type: 'decision' | 'lesson' | 'context' | 'procedure'`, `seq: string`, `title: string`, `current?: boolean` (default false), `onClick?: () => void`.

#### MemoryFilterChips

Single-select chip row for filtering a memory list by type. Used in `MemorySidebar`. Controlled -- parent owns the state.

Container: `display: flex`, `gap: 6px`, `flex-wrap: wrap`. `role="group"`, `aria-label="Filter by memory type"`.

Each chip -- `<button type="button">`: `--font-mono`, 10px, font-weight 500, `text-transform: uppercase`, `letter-spacing: 0.6px`, `line-height: 1`. Padding: `3px 8px`, `--radius-pill`. No border. Cursor: pointer. Transition: background, color, `--duration-fast`. `aria-pressed={active}`.

Inactive chip: background `var(--bg-tool-row)`, color `var(--text-subtle)`. Hover: color `var(--text-body)`, background unchanged.

Active chip: background `var(--color-navy)`, color `var(--text-on-dark)`. No hover change.

Focus: `:focus-visible` outline 2px `var(--color-orange)` at 2px offset.

Chip order (fixed): `all`, `decision`, `lesson`, `context`, `procedure`. Labels rendered lowercase; CSS uppercases via `text-transform`.

MemoryFilterChips uses `<button>` elements with `aria-pressed` rather than a `role="radiogroup"` / `role="radio"` pattern. Radios imply exclusive choice among meaningful peers; filter chips are a weaker affordance where `all` is a privileged default rather than a peer option. Button + `aria-pressed` matches the actual interaction model and is consistent with `TabBar`'s treatment.

Props: `value: 'all' | 'decision' | 'lesson' | 'context' | 'procedure'`, `onChange: (value: typeof value) => void`.

#### DiffPane

Two-column side-by-side diff. Left column shows current content (red-tinted); right shows the proposed replacement (green-tinted). Inline changes are marked with `DiffAdd` (addition highlight) and `DiffDel` (deletion highlight), both co-exported from the same file.

Container: `display: grid`, `grid-template-columns: 1fr 1fr`, `gap: 12px`. Border: `0.5px solid var(--border-divider-light)`, `--radius-lg`, `overflow: hidden`.

Each column: `padding: 16px 20px`, `font-size: var(--type-body)` (14px), `line-height: 1.65`.

Before column (left): background `var(--bg-diff-before)`, right border `1px solid var(--border-danger)`, label color `var(--text-danger-body)`.

After column (right): background `var(--bg-diff-after)`, label color `var(--text-completion)`.

Label (first element in each column): `var(--type-label)` (11px), `text-transform: uppercase`, `letter-spacing: 0.8px`, font-weight 500, `margin-bottom: 10px`. Fixed text: "Current" (before), "Proposed" (after).

Prose content: paragraphs `margin: 0 0 10px`, last-child `margin-bottom: 0`. Inline `<code>`: `--font-mono`, 12px, `background: rgba(255,255,255,0.6)`, `padding: 1px 5px`, `border-radius: 3px`.

`DiffAdd`: inline `<span>`, `background: var(--diff-hl-add-bg)`, `padding: 0 2px`, `border-radius: 2px`. Inherits text styling.

`DiffDel`: inline `<span>`, `background: var(--diff-hl-del-bg)`, `padding: 0 2px`, `border-radius: 2px`, `text-decoration: line-through`, `text-decoration-color: #a03030`.

`DiffPane` does not compute the diff -- callers pass pre-marked JSX. The molecule's job is layout and color, not text analysis. Highlighting is scoped to inline `DiffAdd`/`DiffDel` spans rather than entire lines because koan memory entries are prose, not code, and meaningful changes are usually sub-sentence (a clause added, a qualifier tightened). Line-level diff granularity would under-serve the medium. Column backgrounds use dedicated `--bg-diff-before` / `--bg-diff-after` tokens rather than `--bg-danger` / `--bg-completion` because the two palettes serve different scales: the diff columns host paragraphs of prose, while the confirmation/completion backgrounds are sized for small alert surfaces and carry a stronger tint.

Props: `before: ReactNode`, `after: ReactNode`.

#### RationaleBlock

Lavender-background block rendering the orchestrator's justification for a proposed memory mutation.

Container: `padding: 12px 16px`, `--radius-lg`. Background: `var(--bg-thinking)`. Color: `var(--text-body)`. `var(--type-breadcrumb)` (13px), `line-height: 1.6`.

Label (first child, always rendered): text "Rationale" (fixed). `var(--type-label)` (11px), `text-transform: uppercase`, `letter-spacing: 0.8px`, font-weight 500, `color: var(--text-thinking)`, `margin-bottom: 6px`. `display: flex`, `align-items: center`, `gap: 6px`. Prepended with a `::before` pseudo-element: 6x6 circle, `background: var(--text-thinking)`, `--radius-circle`. Meta-commentary dot signaling model authorship.

Body: upright (not italic). Explicitly upright to distinguish from `ThinkingBlock`'s italic body. Inline `<code>`: `--font-mono`, 11px, no special background.

`RationaleBlock` shares `--bg-thinking` with `ThinkingBlock` because both are model meta-commentary, but their body treatment diverges: `ThinkingBlock` renders italic to mark transient reasoning, `RationaleBlock` renders upright to mark a committed statement the user evaluates. The lavender palette unifies "meta-commentary from the model"; the italic/upright axis separates "in-flight thought" from "submitted justification."

Props: `children: ReactNode`.

#### DecisionPill

Small pill rendered in a proposal's `OperationProposalHead` after the user has decided. Two states: `approved`, `rejected`.

Container: `display: inline-flex`, `align-items: center`, `gap: 6px`. Padding: `3px 10px`, `--radius-pill`. `var(--type-label)` (11px), `text-transform: uppercase`, `letter-spacing: 0.8px`, font-weight 500. Border: `0.5px solid`.

First child: `<StatusDot size="sm" />`. `approved` -> `status="done"` (teal), `rejected` -> `status="failed"` (red).

Second child: label text. `approved` -> "Approved", `rejected` -> "Rejected".

Approved: background `var(--bg-completion)`, color `var(--text-completion)`, border-color `var(--border-teal)`.

Rejected: background `var(--bg-danger)`, color `var(--text-danger)`, border-color `var(--border-danger)`.

`DecisionPill` intentionally has only two states. Earlier iterations included a `feedback` third state (for "revise and re-propose"), but the interaction model consolidated: user feedback is handled via the `OverallFeedback` textarea alongside the decision, not via a third decision outcome. A rejection with accompanying feedback text carries the revise-request intent; the pill still just says `Rejected`. The textarea content is where the nuance lives.

Props: `state: 'approved' | 'rejected'`.

#### ActivityRow

Display-only two-column row for the activity timeline on `MemoryOverviewPage`. Not interactive at the row level -- interactivity lives in any inline elements (e.g., `CiteChip`) inside the body.

Container: `display: grid`, `grid-template-columns: 60px 1fr`, `gap: 14px`, `align-items: baseline`. No background, no padding. The parent list controls vertical rhythm with `gap` between rows.

Time column: `--font-mono`, 11px, `--text-hint`, `white-space: nowrap`.

Body column: `var(--type-breadcrumb)` (13px), `line-height: 1.5`, `--text-body`. Accepts inline elements as children. Provides CSS for common inline elements: `strong`/`b` -> `--text-primary`, font-weight 500; `code` -> `--font-mono`, 11px, `--bg-tool-row`, `padding: 1px 5px`, `border-radius: 3px`.

`ActivityRow`'s body slot accepts ReactNode rather than a string so callers can embed `CiteChip`, `<strong>` highlights, or `<code>` inline without styling gymnastics. The molecule ships styles for `strong`/`b` and `code` as a courtesy -- callers pass plain JSX, the row handles the rest. `time` stays a string because its formats are too open-ended to pre-commit to a formatter here.

Props: `time: string`, `body: React.ReactNode`.

#### ProgressStrip

Horizontal strip anchored at the top of the reflect page during an in-progress run. Pure composition of existing atoms -- no new styling except the container's layout and middot separator color.

Container: `display: flex`, `align-items: center`, `gap: 18px`, `flex-wrap: wrap`. Padding: `12px 0 16px`. Border-bottom: `0.5px solid var(--border-divider-light)`.

Children in order: Turn block (`StatCell size="sm"`, label "Turn", value `"{turn} / {maxTurns}"`), ProgressSegment bar (flex row, `gap: 3px`, renders `maxTurns` segments: done / active / pending), middot separator (`color: var(--border-input)`), Elapsed block (`StatCell size="sm"`), middot separator, Model block (`StatCell size="sm"`), spacer (`flex: 1`), Cancel button (`Button variant="danger" size="sm"`).

The separator is rendered as a text node rather than a component because it is a single decorative character shared between two layout contexts; promoting it to an atom would not pay for itself.

Props: `turn: number` (1-indexed), `maxTurns: number`, `elapsed: string`, `model: string`, `onCancel: () => void`.

#### StatStrip

Horizontal row of `StatCell`s with optional dividers. Two sizes: `lg` (overview stats strip, with dividers) and `sm` (reflect done-meta row, no dividers).

Container: `display: flex`, `align-items: center`. Size `lg`: `gap: 32px`. Size `sm`: `gap: 18px`.

Dividers (only when `size="lg"` AND `dividers` is truthy): vertical line between adjacent cells, `width: 1px`, `height: 24px`, `background: var(--border-divider)`, `flex-shrink: 0`. Rendered as React elements between cells, not via pseudo-elements. Not rendered before first cell or after last.

`StatStrip` renders dividers as sibling React elements between cells rather than per-cell pseudo-elements, so cell widths and the divider positions stay decoupled. The `dividers` flag is a boolean rather than part of `size` because the divider choice is contextual: overview stats want visual separation to read as discrete metrics; reflect done-meta cells flow as a single tight inline readout and would be harmed by dividers. The two intents can diverge without exploding the size enum.

Props: `cells: { value: string; label: string }[]`, `size?: 'lg' | 'sm'` (default `'lg'`), `dividers?: boolean` (default `false`; silently ignored when `size="sm"`).

#### OperationProposalHead

Composed header block for a proposal. Used at the top of both the curation queue item and the proposal detail pane.

Row 1 -- meta row: `display: flex`, `align-items: center`, `gap: 10px`, `flex-wrap: wrap`. Contains in order: `<OperationBadge op={op} />`, `<MemoryTypeBadge type={type} />`, sequence label (`--font-mono`, `var(--type-tool-type)` 12px, `--text-hint`, `letter-spacing: 0.5px`), and optionally `<DecisionPill state={decision} />` with `margin-left: auto`.

Row 2 -- title: `margin-top: 8px`. `--font-display`, 22px, font-weight 400, `letter-spacing: -0.3px`, `line-height: 1.25`, `--text-primary`. Rendered as `<h2>`.

No outer border, no padding. Caller provides enclosing context.

`OperationProposalHead` composes atoms and one molecule (`DecisionPill`) into a structural header. The `decision` prop is optional rather than a separate component because a proposal header with a decision pill is the same header with one more slot filled -- treating decided and pending as two separate components would double the organism-level surface area and break the shared layout.

Props: `op: 'add' | 'update' | 'deprecate'`, `type: 'decision' | 'lesson' | 'context' | 'procedure'`, `seq: string`, `title: string`, `decision?: 'approved' | 'rejected'`.

#### OverallFeedback

Label + textarea with file attachment support. Promoted from the `ReviewPanel` footer so `ReviewPanel` and the curation detail pane share one implementation. Controlled -- parent owns the value.

Container: `display: flex`, `flex-direction: column`, `gap: 6px`.

Label: `var(--type-label)` (11px), font-weight 500, `text-transform: uppercase`, `letter-spacing: 0.5px`, `--text-muted`. Default text: "Overall feedback (optional)", overridable via `label` prop.

Textarea wrapper: `position: relative`. Contains `TextInput` atom in textarea mode (`as="textarea"`, field variant) with `padding-right: 28px`, and a gutter attach button. Default placeholder: "Summarize your overall feedback on this document, or leave empty to submit only inline comments."

Gutter attach button: same treatment as FeedbackInput (paperclip 13px, `opacity: 0.6`, positioned `right: 12px`, `bottom: 12px` inside the TextInput's border). Drag-and-drop supported on the textarea.

File chips row: rendered below the textarea when files are attached. `display: flex`, `flex-wrap: wrap`, `gap: 4px`, `margin-top: 4px`. Contains `FileChip` atoms.

`OverallFeedback` does not own its state. Both `ReviewPanel` and the curation detail pane need to include this text in submission payloads whose shape is organism-specific, so hoisting the value into the parent is the only honest arrangement. The molecule is pure layout + typography over `TextInput`.

Props: `value: string`, `onChange: (value: string) => void`, `attachments?: UploadedFile[]`, `onAttachmentsChange?: (files: UploadedFile[]) => void`, `label?: string`, `placeholder?: string`, `disabled?: boolean`.

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

- Top section: Contains an `OverallFeedback` molecule. See the `OverallFeedback` spec for label text, textarea sizing, and placeholder.
- Bottom section (`margin-top: 12px`): `display: flex`, `align-items: center`, `gap: 12px`. Left: hint text (`--type-label` 11px, `--text-hint`) showing "N inline comments will be submitted" or "No comments yet — click + on any block above". Right (pushed via flex spacer): "Close without submitting" (Button secondary `sm`) and "Submit review" (Button primary `sm`).

**Submit payload:** When the user clicks "Submit review", the frontend collects:

1. Per-block comments: each comment paired with the first 200 characters of its anchor block's text content (for the agent to locate the block in the markdown source).
2. The overall feedback summary text (may be empty).

These are sent to the backend as a single structured message. A ReviewEvent molecule is inserted into the content stream, and the content column returns to the normal stream view.

**Close without submitting:** discards all draft comments and closes the review. No ReviewEvent is inserted. The content column returns to the stream. The artifact can be reopened from the sidebar.

**Switching artifacts:** clicking a different artifact in the ArtifactsSidebar while reviewing swaps the ReviewPanel body to show the new artifact. Draft comments are preserved per-artifact in component-local state — switching back restores them.

### MemorySidebar

340px right-column organism. Consumes a list of entries, filter state, search state, and optional per-entry outline decorations. Controlled -- parent owns all state.

Container: `position: sticky`, `top: 26px`, `background: var(--bg-card)`, `border: 0.5px solid var(--border-card)`, `--radius-2xl`, `padding: 18px 16px`, `max-height: calc(100vh - 120px)`, `overflow: auto`. Width is parent-controlled (typically 340px grid column).

Header row: `display: flex`, `align-items: center`, `justify-content: space-between`, `padding: 0 4px 12px`. Title: "Memory" (fixed), `var(--type-breadcrumb)` (13px), font-weight 500, `--text-primary`. Count: `--font-mono`, 11px, `--text-muted`, format `"{n} entries"`.

Search input: `TextInput` atom, field variant, 100% width, `margin-bottom: 10px`. Placeholder: "Search memories..." (U+2026 ellipsis). Controlled.

Filter chips row: `<MemoryFilterChips>`, wrapping div `padding: 0 4px 12px`.

Entry list: `display: flex`, `flex-direction: column`. Divider between cards: `height: 0.5px`, `background: var(--border-divider-light)`, `margin: 6px 4px`. Not before first or after last.

**Outline variants** -- context-dependent icon decorations applied via a wrapper div around each `<MemoryCard>`:

| Outline      | Icon outline                            | Wrapper bg           | Animation                                 |
| ------------ | --------------------------------------- | -------------------- | ----------------------------------------- |
| `cited`      | solid 2px `--color-orange`, 2px offset  | `var(--bg-selected)` | none                                      |
| `retrieving` | dashed 2px `--color-orange`, 2px offset | none                 | `ms-retrieve-pulse` 1.2s ease-in-out loop |
| `outgoing`   | solid 2px `--color-orange`, 2px offset  | `var(--bg-selected)` | none                                      |
| `incoming`   | dashed 2px `--color-orange`, 2px offset | `var(--bg-selected)` | none                                      |

`cited` and `outgoing` render identically (solid orange). `retrieving` and `incoming` differ only in that `retrieving` animates. Outlines are applied via `.ms-entry--{outline} .atom-memory-type-icon` descendant selectors.

Empty state: centered block, `padding: 32px 8px`. Primary: 13px, `--text-muted`, "No memories match." (when search/filter non-default) or "No memories yet." (default). Optional hint below: 11px, `--text-hint`.

`MemorySidebar` is structurally parallel to `ArtifactsSidebar` but not unified. The planned future unification would extract a shared right-sidebar shell handling the common container, header row, search input, and scroll behavior. Unification is deferred until a third sidebar emerges or the two start diverging in ways that make the parallel implementation expensive -- whichever comes first. Until then, both sidebars maintain their own molecules to avoid a premature abstraction.

The outline states (`cited`, `retrieving`, `outgoing`, `incoming`) collectively form the "this entry is contextually relevant right now" layer, but the rendering distinguishes only two visual modes: solid vs. dashed. The semantic split between `cited`/`outgoing` (both solid) and `retrieving`/`incoming` (both dashed) is preserved in the API so the sidebar's consumers can pass the exact state they know about, but collapsing both solid states into one enum value would lose the traceability -- when debugging why an icon is outlined, the state label is the starting point.

The outline styles reach into `MemoryCard`'s internal `.atom-memory-type-icon` class. This is a documented violation of strict encapsulation, justified by the `MemoryCard` spec's design note that consuming organisms own the highlight semantics. When `MemoryCard` unifies with `ArtifactCard`, the icon selector becomes part of the unified card's stable contract.

Props: `count: number`, `search: string`, `onSearchChange: (value: string) => void`, `filter: 'all' | 'decision' | 'lesson' | 'context' | 'procedure'`, `onFilterChange: (value: typeof filter) => void`, `entries: SidebarEntry[]`, `emptyHint?: string`.

### MemoryOverviewPage

Landing page for the Memory nav section. Two-column page: main content + `MemorySidebar` on the right.

Outer layout: `max-width: 1400px`, `margin: 0 auto`, `padding: 26px 24px 40px`. `display: grid`, `grid-template-columns: 1fr 340px`, `gap: 24px`, `align-items: start`.

**Page head:** `display: flex`, `align-items: baseline`, `gap: 16px`, `margin-bottom: 14px`, `padding: 0 4px`. Title: `<h1>`, "Memory" (fixed), `--font-display`, `var(--type-page-title)` (26px), font-weight 400, `--text-primary`, `letter-spacing: -0.4px`. Count meta: `--font-mono`, 12px, `--text-muted`, format `"{n} entries - {n} decisions - {n} lessons"`.

**Split-top grid:** `display: grid`, `grid-template-columns: 1.38fr 1fr`, `gap: 16px`, `align-items: start`, `margin-bottom: 16px`.

**SummaryPanel** (left, local to page): card chrome (`--bg-card`, `0.5px solid --border-card`, `--radius-2xl`, `padding: 22px 26px`, `min-height: 360px`). Eyebrow: "Summary", `var(--type-label)` 11px, uppercase, `letter-spacing: 1px`, `--color-teal`, font-weight 500. Optional subtitle `<h2>`: `--font-display`, 20px, font-weight 400, `--text-primary`. Prose body: 14px, `line-height: 1.75`, `--text-body`. Inline `<code>`: `--font-mono`, 12px, `--bg-tool-row`. Inline `<strong>`: `--text-primary`, font-weight 500. Content via `children: ReactNode`.

**ReflectStarterPanel** (right, local to page): same card chrome PLUS `border-top: 3px solid var(--color-orange)`. `display: flex`, `flex-direction: column`, `min-height: 360px`. Eyebrow: "Reflect", `--color-orange`. Lead text: `--font-display`, 17px, `--text-primary`, `line-height: 1.45`. Spacer (`flex: 1`). Composer: `TextInput` textarea, placeholder configurable. Actions row: Button primary sm "Ask ->".

**Stats card strip:** card chrome, `padding: 18px 24px`, `margin-bottom: 16px`. Renders `<StatStrip cells={...} size="lg" dividers />`.

**Activity card:** card chrome, `padding: 20px 26px`. Head row: section label "Recent activity" in teal, "See all ->" text button on the right. List: flex column, `gap: 10px`, `<ActivityRow>` elements. Empty state: centered "No recent activity." in `--text-muted`.

Right column: `<MemorySidebar>` with all props forwarded.

`SummaryPanel` and `ReflectStarterPanel` live inside `MemoryOverviewPage` as local components rather than promoted molecules. Neither has a second consumer today. Promotion is deferred until one emerges -- this follows the same rule we applied to `MemoryCard`/`ArtifactCard` unification: resist the abstraction until you have two or more real consumers to shape it around.

The stats strip and the page-head count meta deliberately restate similar information. The meta line is a quick at-a-glance read for people landing on the page; the strip is the organized scannable display. They serve different reading positions and are not redundant in a harmful way.

The reflect starter's 3px orange top border matches the `ElicitationPanel` and `ReviewPanel` treatment -- all three are "user input expected" surfaces at the organism level. The orange top border pattern is a strong signal across the product: the page below is asking you for something.

Props: `counts: { entries, decisions, lessons, context, procedures }`, `summarySubtitle?: string`, `summary: ReactNode`, `reflect: { lead?, placeholder?, value, onChange, onAsk }`, `activity: { time, body }[]`, `onSeeAllActivity?: () => void`, `sidebar: MemorySidebarProps`.

### MemoryDetailPage

Single-entry detail view. Two-column page: main content (entry detail card + relations card) + `MemorySidebar` on the right.

Outer layout: identical to `MemoryOverviewPage` -- `max-width: 1400px`, `margin: 0 auto`, `padding: 26px 24px 40px`, `display: grid`, `grid-template-columns: 1fr 340px`, `gap: 24px`, `align-items: start`.

Main column: `display: flex`, `flex-direction: column`, `gap: 18px`.

**EntryDetailCard** (local to page): card chrome (`--bg-card`, `0.5px solid --border-card`, `--radius-2xl`, `padding: 28px 40px 32px`).

Head row: `display: flex`, `align-items: center`, `gap: 10px`, `flex-wrap: wrap`, `margin-bottom: 10px`. Contains `<MemoryTypeBadge type={type} />` + sequence span (`--font-mono`, 12px, `--text-hint`, `letter-spacing: 0.5px`).

Title: `<h1>`, `--font-display`, 26px, font-weight 400, `--text-primary`, `letter-spacing: -0.3px`, `line-height: 1.25`, `margin: 8px 0 10px`.

Dates grid: `display: grid`, `grid-template-columns: repeat(3, auto)`, `gap: 32px`, `padding: 14px 0 18px`, `margin-bottom: 22px`, `border-bottom: 0.5px solid --border-divider-light`. Each cell: label (`var(--type-label)`, uppercase, `--text-muted`) + value (`--font-mono`, `var(--type-body)`, `--text-primary`, `font-variant-numeric: tabular-nums`) + sub (`--font-mono`, 11px, `--text-hint`). Cells: Created (date + age), Last modified (date + sub), Size (value + sub).

Prose body: `max-width: 720px`, 15px, `line-height: 1.75`, `--text-body`. Inline `<code>`: `--font-mono`, 13px, `--bg-tool-row`. Inline `<strong>`: `--text-primary`, font-weight 500. Inline `<em>`: italic, `--text-subtle`.

Filename: `--font-mono`, 11px, `--text-hint`, `margin-top: 18px`.

Actions footer: `margin-top: 28px`, `padding-top: 20px`, `border-top: 0.5px solid --border-divider-light`. Left: edit meta (`--font-mono`, 12px, `--text-muted`). Right: "Copy link" + "View raw" (Button secondary sm).

**RelationsCard** (promoted molecule, imported from
`../molecules/RelationsCard`): renders the entry's relations in the split
layout (outgoing + incoming). See the RelationsCard section under Memory
Molecules for the full spec.

`EntryDetailCard` is still local to `MemoryDetailPage` (no second consumer
yet). If it gains a consumer (e.g., a historical-revision detail view), it
gets promoted then.

The dates grid is a first-class structural element -- each memory entry is a living document with a history, and "when was this last touched" is a first-class question. The grid sits between the title and the prose to assert this.

Relations are rendered as a separate card below the entry rather than as a sidebar section or inline list. The separate card signals that relations are a structural property of the entry rather than trivia: they are part of what the entry means in the graph. This is the direction we chose explicitly during the entry-detail design review (option B, "relations as first-class section").

The sidebar on `MemoryDetailPage` uses no outline decorations. Relations are communicated in the main column via the relations card; piping them into the sidebar too would double-signal and compete with the section's authority.

Props: `entry: { type, seq, title, meta, body: ReactNode, onCopyLink?, onViewRaw? }`, `relations: { outgoing: RelationEntry[], incoming: RelationEntry[] }`, `sidebar: MemorySidebarProps`.

### MemoryCurationPage

Full-page curation takeover. No `MemorySidebar`. Two-column grid: 340px queue (left) + 1fr detail (right). Inverted from other memory pages -- during curation there's no browsing, only deciding. The queue IS the navigation; navigation goes left.

Outer layout: `max-width: 1400px`, `margin: 0 auto`, `padding: 22px 24px 22px`, `display: grid`, `grid-template-columns: 340px 1fr`, `gap: 20px`, `align-items: start`, `height: calc(100vh - var(--header-height))`, `overflow: hidden`.

The curation page is viewport-height bound: the outer document does not scroll. Both columns have their own internal scroll regions. The queue's list section and the detail pane's card body each own their own `overflow: auto`. This is distinct from the other memory pages (overview/detail/reflect), which have document-length scrolling with a sticky right sidebar. The intent is different: browsing pages are document-style; curation is a bounded workspace.

**CurationQueue** (local, left column): sticky (`top: 22px`), flex column, `gap: 14px`. Contains two cards:

Card 1 (queue card): card chrome + `border-top: 3px solid --color-orange`, `overflow: hidden`, `flex: 1`, `min-height: 0`, `display: flex`, `flex-direction: column`. Head section: eyebrow (default "Memory curation - post-mortem"), title ("{n} proposals"), optional subtitle. Tally row: `--bg-card-warm`, `--font-mono` 12px counts ("N approved - N rejected - N pending"). Always shows pending even at zero; hides other counts at zero. List section: `flex: 1`, `min-height: 0`, `overflow: auto` -- scrolls internally when the queue is long. Head and tally stay fixed above the scrollable list. `<QueueItem>` elements, no dividers.

Card 2 (submit card): card chrome. Submit note (pending-aware text) + Cancel (secondary sm) + Submit batch (primary sm, disabled when pending > 0).

**QueueItem** (local): `<button>`, grid `22px 1fr 18px`. `QueueStateIndicator` + body (op-mini badge + seq + 2-line title) + arrow. Active: `--bg-selected` + orange left border + orange arrow. Op-mini badge: 9px uppercase, reuses Badge variant colors at smaller geometry.

**ProposalDetailPane** (local, right column): card chrome. Top row: position "Proposal N of M" right-aligned. `<OperationProposalHead>` with optional `DecisionPill`. Meta line. `<RationaleBlock>`. Op-discriminated body: update -> `<DiffPane>`, add -> teal-bordered prose, deprecate -> red-tinted struck-through prose. `<OverallFeedback label="Your feedback">`. Action row: optional Change Decision (secondary) + Reject (secondary) + Approve (primary).

`MemoryCurationPage` inverts the column layout of the other memory pages. Overview/detail/reflect pages have a focused main column with a browse sidebar on the right; curation has a queue on the left (primary navigation for this session) and a focused detail pane on the right (the current proposal being worked on). The inversion is deliberate: during curation there's no browsing, only deciding. The queue IS the navigation, and navigation goes left.

`QueueItem` uses a local op-mini badge rather than the full `OperationBadge` atom because OperationBadge's 10px uppercase padding is too tall for a 2-line-clamp compact row. Both variants share CSS color tokens -- the op-mini class family reuses the `add`/`update`/`deprecate` Badge variant colors -- so visual drift is minimized even though the geometries differ.

The detail pane renders the content body in one of three shapes depending on the op, enforced via a TypeScript discriminated union. Callers passing `op: 'add'` are forced to provide `addBody` and cannot provide `updateBefore`. The compile-time constraint prevents a class of bugs where a proposal has both update-diff and add-prose data.

The decision model is two-button (Approve + Reject) plus an OverallFeedback textarea. A rejection with empty feedback is a dismissal; a rejection with feedback text is a revision request. The distinction is read downstream from the textarea content rather than from a third button. `DecisionPill` remains two-state (Approved/Rejected) for the same reason.

Props: `eyebrow?: string`, `subtitle?: string | ReactNode`, `proposals: Proposal[]`, `selectedIndex: number`, `onSelectIndex`, `onApprove`, `onReject`, `onChangeDecision`, `onFeedbackChange`, `onCancel`, `onSubmit`.

### MemoryReflectPage

Reflect page with two states: in-progress (streaming retrieval + thinking)
and done (briefing + citations). Two-column page: main ReflectPane +
`MemorySidebar`.

Outer layout: same shell as overview/detail -- `max-width: 1400px`,
`margin: 0 auto`, `padding: 26px 24px 40px`, `display: grid`,
`grid-template-columns: 1fr 340px`, `gap: 24px`, `align-items: start`.

**ReflectPane** (local to page): card chrome (`--bg-card`,
`0.5px solid --border-card`, `--radius-2xl`, `padding: 28px 34px 26px`,
`min-height: 600px`) PLUS `border-top: 3px solid var(--color-orange)`.
Same "panel-level attention" signal as ElicitationPanel / ReviewPanel /
ReflectStarterPanel.

**Back-to-memory link** (both states): rendered at the very top of the
`.rfl` container, above the eyebrow. Uses `Button variant="text" size="sm"`
navigating to `/memory`. Ensures the user can abandon a slow run without
hunting for nav.

Head (both states): eyebrow (`var(--type-label)`, uppercase,
`--color-orange`): in-progress shows "Reflection - in progress", done shows
"Reflection". Question `<h1>`: `--font-display`, 24px, font-weight 400,
`--text-primary`, `line-height: 1.35`, `letter-spacing: -0.3px`.

**In-progress body:** `<ProgressStrip>` below the question. Ordered
`entries: ReflectTraceRender[]` stream rendered after the strip: thinking
entries as `<ThinkingBlock>`, text entries as inline prose
(`.rfl-text-delta`), search entries as `<ToolCallRow tool="search">`. All
entries render in arrival order, interleaved as the model produces them.
No follow-up composer.

**Done body:** done-meta strip (`margin-top: 10px`, `margin-bottom: 22px`,
`padding-bottom: 18px`, `border-bottom: 0.5px solid --border-divider-light`):
`<StatStrip size="sm">` (iterations, searches, elapsed, cited). Ordered
`entries` stream (same `ReflectTraceRender[]`, same rendering). Briefing
prose: 15px, `line-height: 1.75`, `--text-body`, `max-width: 720px`.
Citations card: `<RelationsCard eyebrow="Citations" layout="single"
outgoing={citations} incoming={[]} />` rendered below the briefing
(`margin-top: 28px`). No follow-up composer.

Sidebar: `<MemorySidebar>` with all props forwarded. During in-progress,
entries matching retrieval get `outline: "retrieving"`. During done, entries
cited in the briefing get `outline: "cited"`. Outline state is decided by
the caller, not the page.

ReflectPane uses a discriminated union for its state: in-progress and done
have genuinely different data shapes (no `turn` in done, no `iterations`
in-progress). The unified `entries: ReflectTraceRender[]` field replaces the
prior split of `tools: ReflectToolCall[]` + `thinking?: string` so both states
share the same arrival-ordered rendering.

Props: `question: string`, `state: InProgressProps | DoneProps` (discriminated
union on `status`), `sidebar: MemorySidebarProps`.

---

## Header Bar

The header bar operates in two modes:

**Navigation mode:** Used on the New Run, Sessions, Memory, and Settings pages. The zone right of the logo divider shows top-level navigation links: "New run", "Sessions", "Memory", "Settings". Each link: `--type-breadcrumb` (13px), `--font-body`. Active page: `--text-on-dark`, font-weight 500. Inactive pages: `--text-on-dark-muted`, font-weight 400. Links separated by 6px gap.

**Sub-page breadcrumb (navigation mode):** When rendered inside a sub-page of a primary nav section, `BreadcrumbNav` is shown left of the logo divider, showing the current nav section name plus sub-page identifier. Pattern: `Memory > #0048`, `Memory > Reflect > "..."`. This is structurally distinct from workflow-mode breadcrumb, which encodes phase/step and includes `ProgressSegment`s.

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

## Memory section

### Routes

| URL pattern       | Page organism        | Notes                                               |
| ----------------- | -------------------- | --------------------------------------------------- |
| `/memory`         | `MemoryOverviewPage` | Entry list, summary, reflect starter, activity feed |
| `/memory/:seq`    | `MemoryDetailPage`   | Single entry body, outgoing/incoming relations      |
| `/memory/reflect` | `MemoryReflectPage`  | In-progress or completed reflect session            |

`/memory/reflect` redirects to `/memory` when `projection.reflect` is null
(no active session). All three routes are mounted by `MemoryRoutes` which is
rendered by `App.tsx` when `page === 'memory'`.

### Curation takeover

When `run.activeCurationBatch` is non-null the App renders `CurationTakeover`
in place of all other run-scoped views, including the content stream,
completion, artifact review, and elicitation panels. The takeover mounts
`MemoryCurationPage` and submits decisions to `/api/memory/curation`.

Per-proposal decision and feedback draft lives in the Zustand store slice
`memoryCurationDraft`. This draft is intentionally lost on page refresh
(accept-loss decision from intake). The batch data itself is server-backed
via `run.activeCurationBatch` and survives a refresh.

### Zustand state shape

| Field                     | Type                                    | Purpose                                                                                 |
| ------------------------- | --------------------------------------- | --------------------------------------------------------------------------------------- |
| `memory`                  | `MemoryState`                           | Project-scoped entry summaries and summary text; persists across workflow boundaries    |
| `reflect`                 | `ReflectRun \| null`                    | Project-scoped reflect session; null when no session is active                          |
| `run.activeCurationBatch` | `ActiveCurationBatch \| null`           | Non-null while orchestrator is blocked in `koan_memory_propose`                         |
| `memoryCurationDraft`     | `Record<string, {decision?, feedback}>` | Store-only; seeded by `resetMemoryCurationDraft` on batch mount, cleared on batch clear |
| `memorySidebar`           | `{search, filter}`                      | Shared search/filter state across all three memory browsing pages                       |

### SSE events consumed

The following event types are produced by the backend and consumed by the
frontend SSE fold to update the projection:

- `memory_curation_started` -- batch lands in `run.activeCurationBatch`
- `memory_curation_cleared` -- batch cleared from `run.activeCurationBatch`
- `memory_entry_created` -- new entry upserted into `memory.entries`
- `memory_entry_updated` -- existing entry replaced in `memory.entries`
- `memory_entry_deleted` -- entry removed from `memory.entries`
- `memory_summary_updated` -- `memory.summary` text replaced
- `reflect_started` -- `reflect` field set to new in-progress session
- `reflect_trace` -- trace appended to `reflect.traces`, iteration counter updated
- `reflect_done` -- `reflect.status` set to done with answer and citations
- `reflect_cancelled` -- `reflect.status` set to cancelled
- `reflect_failed` -- `reflect.status` set to failed with error message
- `reflect_cleared` -- `reflect` field set to null

### Known limitation

The activity timeline on `MemoryOverviewPage` is derived from entry timestamps
(`modifiedMs`) and does NOT show deletions. Deleted entries are gone from disk
and from `memory.entries`; there is no separate backend event log for activity.
This is intentional per the intake decision -- no new backend event log was added.
