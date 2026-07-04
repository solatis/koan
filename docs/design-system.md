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

| Token                  | Hex       | Usage                                                                     |
| ---------------------- | --------- | ------------------------------------------------------------------------- |
| `--color-orange-hover` | `#c06a4f` | Hover state for orange interactive elements (ReviewBlock gutter button).  |
| `--color-purple`       | `#8e7ca0` | Memory type indicator color for `procedure`. `MemoryTypeIcon` background. |

### Warning surface

Warning is a recurring semantic (the New-Run config-incomplete notice, the
add-connection backend note) and was previously hardcoded in `Badge` `default`.
These tokens remove the duplication. All role/provider colors elsewhere in this
addendum map to existing core colors, so no other new tokens are introduced.

| Token              | Value     | Use                                              |
| ------------------ | --------- | ------------------------------------------------ |
| `--bg-warning`     | `#fdf2ee` | Warning notice/flag surface (orange-amber tint). |
| `--border-warning` | `#f0d8cc` | Warning notice/flag border.                      |
| `--text-warning`   | `#c06030` | Warning text + icon on a warning surface.        |

Migration follow-up (not blocking): `Badge` `default` (`#fdf2ee` / `#c06030`)
should be repointed at these tokens.

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

| Token        | Hex       | Usage                                                                                       |
| ------------ | --------- | ------------------------------------------------------------------------------------------- |
| `--dot-read` | `#5a9a8a` | `read` operations. Aliases `--color-teal`.                                                  |
| `--dot-grep` | `#7ab0a0` | `grep` operations. Lighter teal.                                                            |
| `--dot-glob` | `#4a8878` | `glob` operations. Darker teal. (Reuses the retired `--dot-ls` hex; `--dot-ls` is removed.) |
| `--dot-bash` | `#8e7ca0` | `bash` operations. Aliases `--color-purple` — execution, not read-only.                     |
| `--dot-web`  | `#7a8fb5` | `web_search` and `web_fetch` operations. Desaturated slate blue — remote retrieval.         |

Teal family = local read-only filesystem exploration. Purple = shell execution.
Slate = network retrieval. Orange stays reserved for active state
(`--color-orange`) and must not appear in tool-family indicator colors.

### Tool component sizing

| Token                  | Value | Usage                                                                                                                                         |
| ---------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `--tool-op-row-height` | 24px  | Fixed row height for `ToolLogRow` and `ToolStatBlock` header/meta lines. The shared rhythm that keeps group-stat and group-ops cells aligned. |

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

- `sm`: 6px × 6px. Used in `ToolStatBlock` header rows and the `ToolCallRow`
  family variant, where vertical density matters.
- `md`: 8px × 8px. Default. Used in scout tables, artifact cards, and the
  header orchestrator indicator.

**Status variants — operational state:**

- `running`: `background: var(--status-running)` (orange). Static.
- `done`: `background: var(--status-done)` (teal). Static.
- `queued`: `background: var(--status-queued)` (neutral warm gray). Static.
- `failed`: `background: var(--status-failed)` (red). Static.

**Status variants — tool family:**

- `read`: `background: var(--dot-read)`. Static.
- `grep`: `background: var(--dot-grep)`. Static.
- `glob`: `background: var(--dot-glob)`. Static.
- `bash`: `background: var(--dot-bash)`. Static.
- `web`: `background: var(--dot-web)`. Static. Shared by `web_search` and
  `web_fetch` — both pass `web`.

The tool-family variants share the `status` prop with the operational variants
intentionally — the geometry and usage pattern are identical, and a single
`status` prop keeps consumers' call sites readable.

Type: `Status = 'running' | 'done' | 'queued' | 'failed' | 'read' | 'grep' | 'glob' | 'bash' | 'web'`,
`Size = 'sm' | 'md'`.

Props: `status: Status`, `size?: Size` (default `'md'`).

### ToolCommandText

Per-family command rendering. One semantic unit — a formatted text primitive —
used identically by `ToolLogRow` (aggregate rows) and `ToolCallRow` (standalone
and single-op fallback rows). Owning the family-specific markup in one atom is
what keeps the three consumers from drifting.

Container: `display: flex`, `align-items: baseline`, `min-width: 0`,
`overflow: hidden`, `white-space: nowrap`, `font-family: var(--font-mono)`,
`font-size: 12px`. The container carries `title` with the untruncated text.

Variants by `family`:

- **`read`** — three spans:
  - Directory prefix: `color: var(--text-muted)`, `overflow: hidden`,
    `text-overflow: ellipsis`, `direction: rtl`, `unicode-bidi: plaintext`,
    `min-width: 0`, `flex-shrink: 1`. Left-truncates so the basename survives.
  - Basename: `color: var(--text-body)`, `flex-shrink: 0`.
  - Range (optional): `:{start}–{end}`, `color: var(--text-muted)`,
    `flex-shrink: 0`. Omitted when the whole file was read.
- **`grep`** — pattern span (`color: var(--text-body)`, right-ellipsis,
  `min-width: 0`) + optional scope span (`color: var(--text-muted)`,
  `flex-shrink: 0`, `padding-left: 8px`). Scope format: `in {path}` and/or the
  glob filter, middot-joined (`in koan/ · *.py`).
- **`glob`** — identical structure to `grep` (pattern + scope).
- **`bash`** — `$` sigil (`color: var(--text-muted)`, `padding-right: 6px`,
  `flex-shrink: 0`) + command (`color: var(--text-body)`, right-ellipsis,
  `min-width: 0`). Multiline commands collapse to their first line for display;
  `title` carries the full command.
- **`web_search`** — query text, `color: var(--text-body)`, right-ellipsis.
- **`web_fetch`** — host (`color: var(--text-body)`, `flex-shrink: 0`) + path
  (`color: var(--text-muted)`, right-ellipsis, `min-width: 0`). Scheme is
  stripped for display.

Running state (`running={true}`): primary spans (`basename`, pattern, command,
query, host) drop to `color: var(--text-subtle)`.

Error state (`error={true}`): primary spans render
`color: var(--status-failed)`.

Props: `family: 'read' | 'grep' | 'glob' | 'bash' | 'web_search' | 'web_fetch'`,
plus family-specific data
(`path?`, `range?`, `pattern?`, `scope?`, `command?`, `query?`, `url?`),
`running?: boolean`, `error?: boolean`.

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

### MemoryTypeBadge

Alias atom over `Badge`. Renders `<Badge variant={type}>` with the type name capitalized as the label: `decision` -> "Decision", `lesson` -> "Lesson", `context` -> "Context", `procedure` -> "Procedure".

Props: `type: 'decision' | 'lesson' | 'context' | 'procedure'`.

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

### RoleMarker

Colored rounded square identifying a model role. Sibling of `MemoryTypeIcon`, but
**no letter** — role identity is carried by color + an adjacent text label, and a
letter would collide (Strong / Standard both start with "S"). Used by `RoleRow`
(Settings) and `RoleCard` (New Run, first-run).

Container: `--radius-lg`, `flex-shrink: 0`. Two sizes:

- `sm` — `34px` × `34px`. Used in `RoleRow`.
- `lg` — `38px` × `38px`. Used in `RoleCard`.

Per-role background color:

| Role       | Background       |
| ---------- | ---------------- |
| `strong`   | `--color-orange` |
| `standard` | `--color-navy`   |
| `cheap`    | `--color-teal`   |
| `memory`   | `--color-purple` |

The `memory` variant marks the Memory section's binding rows (embedding /
memory-llm / reflect-llm) as one family, distinct from the three model roles.

Static. No hover, no content.

Props: `role: 'strong' | 'standard' | 'cheap' | 'memory'`, `size?: 'sm' | 'lg'` (default `'sm'`).

### ProviderBadge

`30px` × `30px` rounded-square icon with a two-letter mono code identifying a
connection's provider type. Used by `ConnectionRow` and (optionally) `ConnectionForm`.

Container: `30px` × `30px`, `--radius-md`, `display: inline-flex`, `align-items: center`, `justify-content: center`, `flex-shrink: 0`.

Label: `--font-mono`, 11px, font-weight 500, `color: white`, `line-height: 1`, uppercase.

Per-type background + code:

| Provider type | Background                        | Code |
| ------------- | --------------------------------- | ---- |
| `anthropic`   | `--color-orange`                  | `AN` |
| `openai`      | `--color-navy`                    | `OA` |
| `google`      | `--color-teal`                    | `GO` |
| `bedrock`     | `--text-subtle`                   | `BE` |
| `openrouter`  | `#8a7e70` (hardcoded, deliberate) | `OR` |
| `voyage`      | `--color-purple`                  | `VO` |

Colors are decorative anchors; the two-letter code disambiguates. `google`
reuses an existing color value that is otherwise semantic -- acceptable, since a
badge is not a status read-out. The `openrouter` background is a hardcoded deep
warm gray rather than `--status-queued`: the status token (`#b8aca0`) was too
light on the warm card surfaces -- the badge read as disabled and white text fell
below comfortable contrast. A decorative badge color, not a status read-out.

Props: `type: ProviderType`.

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

- `/plan write an implementation plan` -> `The user wishes to transition to phase \`plan\` with instruction: write an implementation plan`
- `/plan` (no instruction) -> `The user wishes to transition to phase \`plan\`.`

Props: `placeholder?: string`, `onSend?: (text: string, attachments?: string[]) => void`, `disabled?: boolean`, `availableCommands?: PhaseCommand[]`, `onPaletteToggle?: (open: boolean) => void`.

#### ToolCallRow

A single horizontal row representing a standalone tool call. Used for
mutations (`write`, `edit`), which keep their individual visual weight outside
aggregate cards, and — via the family variant below — for the single-op
aggregate fallback (a run of exactly one exploration operation).

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

**Family variant** — used for (a) the single-op aggregate fallback and (b) any
future standalone exploration rendering. `write`/`edit` rows are unchanged
(status indicator + type label). When `family` is set:

- The 13px status-indicator column renders `StatusDot size="sm"
status={family}` instead of the check; for a running op it renders the pulsing
  orange dot; for an error, the `✕`.
- The command slot renders `ToolCommandText` instead of a plain string.
- Type label and metric behave as before (metric formats from the `ToolLogRow`
  table).

Props: `tool: string`, `command: string`, `status?: 'done' | 'running' | 'error'`
(default `'done'`), `metric?: string`, `family?: ExplorationFamily`, plus
command data forwarded to `ToolCommandText` when `family` is set. When `family`
is absent the row renders exactly as specced above (string `command`).

#### ToolLogRow

One operation line inside a `ToolAggregateCard` group-ops cell. No leading
family dot — family identity lives on the group's stat block, not per row. The
only leading indicator is the pulsing orange dot on an in-flight row.

Container: `height: var(--tool-op-row-height)`, `display: flex`,
`align-items: center`, `gap: 10px`, `min-width: 0`,
`font-family: var(--font-mono)`, `font-size: 12px`.

Content: `ToolCommandText` (`flex: 1`, `min-width: 0`) + metric span
(`flex-shrink: 0`, `font-size: 11px`, `color: var(--text-muted)`,
`padding-left: 12px`).

Metric formats by family:

| Family       | Completed metric                      | Notes                                                        |
| ------------ | ------------------------------------- | ------------------------------------------------------------ |
| `read`       | `{n} lines · {kb} KB`                 |                                                              |
| `grep`       | `{m} matches · {l} lines · {f} files` | Zero matches: `0 matches`, italic, `--text-muted` — not red. |
| `glob`       | `{f} files`                           |                                                              |
| `bash`       | `exit {code} · {l} lines`             | Non-zero exit: metric `color: var(--status-failed)`.         |
| `web_search` | `{n} results`                         |                                                              |
| `web_fetch`  | `{kb} KB`                             |                                                              |

Running state: inline pulsing orange dot (6px, local `@keyframes`, same pattern
as `ToolCallRow`'s `.tcr-running-dot` — independent of `StatusDot`),
`ToolCommandText running`, metric shows the in-progress verb (`reading…`,
`grepping…`, `globbing…`, `running…`, `searching…`, `fetching…`) in
`color: var(--color-orange)`.

Error state: `ToolCommandText error`, metric in `color: var(--status-failed)`
(e.g. `not found` for a failed read).

Props: `family`, command data (forwarded to `ToolCommandText`),
`metric?: string`, `status?: 'done' | 'running' | 'error'` (default `'done'`).

#### ToolStatBlock

The navy stat cell for one family group in `ToolAggregateCard`. Renders **on
`--color-navy`** — all text uses the on-dark palette.

Container: `background: var(--color-navy)`, `padding: 9px 16px`,
`font-family: var(--font-mono)`, `font-size: 12px`. Adjacent group-stat cells
separated by `border-top: 1px solid rgba(240,232,216,0.10)` (navy-specific,
hardcoded with comment; first cell has none).

Header row: `height: var(--tool-op-row-height)`, `display: flex`,
`align-items: center`, `gap: 8px`. Contains `StatusDot size="sm"
status={family}` (web tools pass `web`), family name
(`color: var(--text-on-dark)`, `font-weight: 500`), op count
(`margin-left: auto`, `font-size: 11px`, `color: var(--text-on-dark-muted)`,
e.g. `4 ops`).

Meta lines: `padding-left: 14px`, `font-size: 11px`,
`color: var(--text-on-dark-muted)`, `line-height: var(--tool-op-row-height)`.
Rollup content by family:

| Family       | Rollup lines                                                                                         |
| ------------ | ---------------------------------------------------------------------------------------------------- |
| `read`       | `{Σlines} lines · {ΣKB} KB`; `{distinct} files`; `{k} failed` (line only when k>0, `color: #e8a0a0`) |
| `grep`       | `{Σmatches} matches · {Σlines} lines` (no file counts — see rationale)                               |
| `glob`       | `{Σfiles} files`                                                                                     |
| `bash`       | `{k} failed` (only when k>0, `#e8a0a0`)                                                              |
| `web_search` | `{Σresults} results`                                                                                 |
| `web_fetch`  | `{ΣKB} KB`                                                                                           |

Single-op groups render the header row only — no meta lines (the row's own
metric already carries the numbers; restating them is noise).

Active variant: family name `color: var(--color-orange)` when the in-flight op
belongs to this group. Only one `ToolStatBlock` in a card can be active at a
time. `#e8a0a0` is the on-navy failure red (`--status-failed` lacks contrast
on navy); hardcoded with comment, navy-specific.

Props: `family`, `opCount: number`, `metaLines: string[]`, `active?: boolean`,
`failedCount?: number`.

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

#### ConnectionRow

A two-line list item for a provider connection. Parallels `EntityRow` but adds a
leading `ProviderBadge`. Used in the Settings -> Connections section.

Container: `--padding-entity-row` (12px 16px), `--radius-lg`, `0.5px solid --border-card`, `background: --bg-card-warm`. Margin-bottom: `--gap-entity-rows` (8px). `display: flex; align-items: center; gap: 12px`.

Leading: `ProviderBadge`.

Text block (`min-width: 0`): connection id in `--font-mono`, 13px, font-weight 500, `--text-primary`. Sub-line in `--font-mono`, `--type-label` (11px), `--text-muted`, `margin-top: 2px` — shows `type · key set`, `type · region us-east-1`, etc.

Then a `flex: 1` spacer, a status `Badge`, and an Edit `Button` (`secondary`, `xs`).

**Status badge:** `Badge` `success` ("configured") when a credential / required
config is present; `Badge` `error` ("not set") when the connection exists but its
credential is missing.

Props: `type: ProviderType`, `id: string`, `meta: string`, `status: 'configured' | 'not-set'`, `onEdit: () => void`.

#### ConnectionForm

A provider-add / -edit form. Specialization of `InlineForm` (appears inline under
the Connections list or under the row being edited; same `1.5px solid --color-orange`
container). Fields are **conditional on provider type**.

Always-present `FormRow`s:

- **Provider** — `Select` (`mono`). On add, switching the provider re-renders the conditional fields below. On edit, read-only.
- **Name** — `TextInput` (`mono`). The connection id.

Conditional `FormRow`s by provider type:

| Provider     | API key                  | Region         | Endpoint            | Test |
| ------------ | ------------------------ | -------------- | ------------------- | ---- |
| `anthropic`  | TextInput mono           | --             | TextInput mono, opt | yes  |
| `openai`     | TextInput mono           | --             | TextInput mono, opt | yes  |
| `google`     | TextInput mono           | --             | --                  | yes  |
| `bedrock`    | — (AWS credential chain) | TextInput, req | TextInput mono, opt | no   |
| `openrouter` | TextInput mono           | --             | -- (library-fixed)  | yes  |
| `voyage`     | TextInput mono           | --             | --                  | no   |

- Optional fields append "(OPT)" to the FormRow label string -- FormRow's label is a plain string, so a styled tag span is not available without modifying FormRow.
- A `FormRow`-aligned helper line (`--type-label`, `--text-muted`, indented to the controls column) explains the absences: Bedrock -> "uses your AWS credential chain"; OpenRouter -> no endpoint field because the library fixes `https://openrouter.ai/api/v1` internally; Voyage -> "embedding provider; models entered by id".

**Edit mode:** the API key field shows a placeholder "configured -- enter to replace" and is left blank (the stored secret is never echoed). A `Button` `danger` (`sm`) "Delete connection" appears in the actions row.

**Test connection** (listing-capable providers only -- `anthropic`, `openai`, `google`, `openrouter`): a `Button` `teal` (`sm`) in the actions row. Result surfaces as a `Badge` next to it -- `success` ("N models") or `error` (message). `bedrock` and `voyage` have no Test (no list endpoint). Test is save-then-list: no pre-save test endpoint exists, so Test persists the draft via the connection endpoint and then calls list-models, surfacing the count or the error. A Test click therefore saves the connection.

Actions render as two stacked rows: a utility row with Test connection (`teal`,
`sm`) and its result Badge, plus Delete connection (`danger`, `sm`) pushed right
in edit mode; then the InlineForm-standard [Cancel] [Save] row. InlineForm's
action slot cannot host the extra buttons, and modifying InlineForm for one
consumer was rejected; the two-row split also keeps Delete visually apart from
Save.

Props: `mode: 'add' | 'edit'`, `type: ProviderType`, `values: ConnectionDraft`, `onChange`, `onSave`, `onCancel`, `onDelete?`, `onTest?`, `testState?: 'idle' | 'pending' | { ok: number } | { error: string }`, `saving?: boolean`.

#### ModelPicker

A custom combobox for choosing a model id for a connection. **Not the `Select`
atom** — it filters, groups, offers free-text entry, and reloads its options
when the connection changes. The heaviest new molecule. Used as the model control
in `RoleRow` and `RoleCard`.

**Trigger:** a `Select`-shaped box (mono, `--type-breadcrumb`, `1px solid --border-input`, `--radius-md`, custom chevron). Shows the current model id, or a placeholder when none. When the picker is open the border is `--color-orange`. **Disabled** (no connection chosen yet): `--bg-surface`, `--border-divider`, `--text-hint`, not interactive (see cascade in `RoleRow`).

**Dropdown panel:** `position: absolute`, `width: 380px` (wider than the trigger so ids never wrap), `top: calc(100% + 6px)`, `z-index: 5`, `1px solid --border-input`, `--radius-lg`, `background: --bg-card`, `box-shadow: 0 10px 30px rgba(46,58,94,.13)`, `overflow: hidden`. Internal list scrolls past a max height.

Panel regions, top to bottom:

1. **Filter** — a borderless mono input with a search glyph (`--text-muted`), `border-bottom: 1px solid --border-divider-light`. Filters the list as you type.
2. **Newest in family** group (listing-capable only) — group label "Newest in family · pins a version" (`--bg-surface`, 9px uppercase `--text-muted`). Each row: family name (`--font-mono`, 13px, 500) + the resolved pinned id (`--font-mono`, 11px, `--text-muted`, e.g. `→ claude-opus-4`). Selecting one writes the resolved pinned id. This is the config-time "newest" convenience; it never stores the alias, only the resolved version.
3. **All models** group — label "All models · {connection}". Flat list of model ids (`--font-mono`, 13px, `--text-primary`), one per row (`padding: 8px 14px`, `white-space: nowrap`). Row states: hover and keyboard highlight use `--bg-tool-row`; the keyboard-highlighted row additionally carries `box-shadow: inset 2px 0 0 --color-orange` (an inset, not a border, so row geometry never shifts as the highlight moves). The row matching the current value uses `--bg-selected`. The highlight rule is declared after the selected rule so the keyboard cursor visibly overrides the selected tint when walking across the current value. **Flat — no family/tier nesting.** No capability annotations (context/caching/tools are inferred, not selection criteria).
4. **Free-text** — `border-top: 1px solid --border-divider-light`. Label "Or enter a model id" + a mono input (`--bg-surface`). Always available, so unlisted ids can be entered.

**States:**

- **Loading** — replaces groups 2-3 with a spinner row ("Loading models from {connection}...") + 2-3 skeleton bars. Free-text stays available. Shown while the per-connection model list fetches (on open, and whenever the connection changes).
- **Non-listing** (`bedrock`, `voyage`) — no live groups. Free-text id input first, then a "Suggestions · koan catalog" group (curated ids from the registry), then a note: "{provider} can't list models over its runtime API — enter the id or pick from koan's catalog." Capabilities resolve once the id is set.
- **Disabled** — trigger only (no connection chosen). Cannot open.

Props: `connectionId: string | null`, `value: string | null`, `onChange: (modelId: string) => void`, `models: string[]`, `families?: { family: string, resolved: string }[]`, `loading?: boolean`, `listingCapable: boolean`, `catalogSuggestions?: string[]`, `disabled?: boolean`.

Keyboard: with the trigger focused, Enter / Space / ArrowDown open the panel
(focus moves to the filter input, or the free-text input for non-listing
providers). ArrowDown / ArrowUp move the highlight through the visible rows in
DOM order, clamped at the ends; typing in the filter narrows the list, hides the
pin group, and resets the highlight. Enter selects the highlighted row, or
commits a non-empty free-text id when nothing is highlighted. Escape closes
without committing and returns focus to the trigger; outside mousedown closes.
The highlight is component state, not DOM focus.

The free-text footer label ("Or enter a model id" / "Model id") uses the
group-label typography (9px uppercase) without the `--bg-surface` tinted strip —
it sits inside the already-padded footer, where a nested tinted box reads wrong.
The panel also pins `text-align: left` on itself so it is immune to ancestor text
alignment (it renders inside centered containers).

#### RoleRow

The configuration row for one model role (Settings -> Model roles) or one memory
binding (Settings -> Memory). A role/binding is described by **connection + model +
thinking + optional context-window override**. The context-window override is
secondary and optional; the cascade (connection -> model -> thinking) is unchanged.

Container: `0.5px solid --border-card`, `--radius-xl`, `background: --bg-card-warm`, `padding: 15px 18px`, `display: flex; align-items: center; gap: --gap-form-controls` (8px).

Layout, left to right (dependency order):

1. `RoleMarker` (`sm`).
2. Meta block, `width: 150px`, `flex-shrink: 0`: role name (14px/500 `--text-primary`) + description (`--type-label`, `--text-muted`, `margin-top: 2px`). Strong -> "Planning & reviews"; Standard -> "Writing code"; Cheap -> "Exploration sub-agents". Memory rows: Embedding / Memory LLM / Reflect LLM with their descriptions.
3. **Connection** `Select` (`mono`), `flex: 0 0 ~180px`.
4. **Model** `ModelPicker`, `flex: 1`.
5. **Thinking** `Select`, `flex: 0 0 ~112px`.
6. **Context window** plain text input (`mono`, `--type-breadcrumb`, `width: ~90px`, `flex-shrink: 0`), shown below the main row as a secondary label+input pair. Shown only in the `default` variant (not `compact`). Placeholder shows the capability-derived window (e.g. "131072") when no override is set. A positive integer sets the explicit override on the ConfiguredModel; clearing it removes the override. Auto-saves on blur. Logic stays in the connected parent (App.tsx `onRoleChange('context_window', value)`); the control is purely presentational.

The Memory **Embedding** binding omits the thinking `Select` (embeddings have no
thinking); its `ModelPicker` simply extends to where thinking would sit.

**Variant `compact`** (`variant?: 'default' | 'compact'`, default `'default'` --
the Settings rows above are the default and are pixel-identical with or without
the variant prop). Used by `NewRunForm`'s per-run override, where the row must fit
the 640px form column. Differences from default:

- Row padding `11px 14px` (vs `15px 18px`); gap `6px` (vs `--gap-form-controls`).
- `RoleMarker` rendered at `26px` x `26px` (CSS override inside the compact row).
- Meta block `width: 84px` (vs 150px), **name only** -- the description line is
  not rendered.
- Columns: connection `flex: 0 0 142px`; model `flex: 1`; thinking `flex: 0 0 80px`.
  Sized to the longest real values ("anthropic-main", "medium") so the model
  column gets ~150px at form width -- enough for a 15-char mono id.
- Controls compacted via descendant overrides (mono, `--type-breadcrumb`,
  `padding: 6px 22px 6px 8px`, chevron at `right 7px`, `width: 100%`,
  ellipsized values).
- All states (assigned / unassigned cascade / broken / no-thinking) work
  unchanged; the broken helper line indents to the compact meta width (~130px).
- Context-window input is **not rendered** in `compact` variant (per-run
  overrides do not expose per-model context windows).

**States:**

- **Assigned** -- all three set.
- **Unassigned (cascade)** -- connection `Select` shows a placeholder ("-- select connection --", `--text-placeholder`); the model `ModelPicker` is **disabled** until a connection is chosen; the thinking `Select` is **disabled** until a model is chosen. Choosing a connection enables + loads the picker; choosing a model enables thinking. This cascade applies to every RoleRow, not only empty ones.
- **Broken** -- the slot points at a configured model whose connection was removed. `background: --bg-danger`; the connection `Select` renders in error state (border `--status-failed`) showing the dead id, followed by a `Badge` `error` ("removed"); thinking is disabled. A helper line sits below the row (`--type-label`, `--text-danger-body`): "Connection removed -- choose another." The role counts as **not-runnable** (see New Run gate). Re-picking a connection clears it.
- **No thinking support** -- when the chosen model resolves to no thinking capability, the thinking `Select` stays present but **disabled**, showing `--`. Keeping it present (vs hiding) preserves column alignment across the three rows. When the model does support thinking, the options are `off` + the supported subset only.

**Save:** the controls auto-save individually on change (no Save button -- see
`InlineForm` / "Save model" rationale). On a backend reject, the control reverts
and an error `Notification` toast appears (rationale "Auto-save error surfacing").

Props: `role: RoleSlot | 'embedding' | 'memory-llm' | 'reflect-llm'`, `connectionId`, `modelId`, `thinking`, `contextWindow: number | null`, `capabilityContextWindow?: number`, `state: 'assigned' | 'unassigned' | 'broken' | 'no-thinking'`, `connections`, `models`, `modelsLoading`, `thinkingOptions`, `onChange(field, value)`, `showThinking?: boolean` (default true; false for embedding). Logic for `context_window` field changes stays in the App.tsx connected parent.

#### RoleCard

The vertical, "playful" placeholder card for the first-run gate
(`NoProvidersBlock`). Shares the `RoleMarker` visual language with `RoleRow` so
the surfaces read as one family.

> The former `override` variant (three labelled controls per card) was removed:
> it required >=245px per card and could not fit the 640px New Run column. The
> per-run override now uses `RoleRow` `variant="compact"` (see rationale
> "Override layout at form width").

Container: `flex: 1`, `--radius-xl`, `padding: 16px 14px 14px`, `text-align: center`,
`1px dashed --border-input`, `background: --bg-surface`.

Contents: `RoleMarker` (`lg`, centered, `margin: 0 auto 10px`, reduced opacity
`0.55`) + role name (14px/500 `--text-primary`) + a status line below the name
("not set", `--type-badge`, uppercase, `--text-hint`). No controls.

Props: `role: WorkflowRole`, `variant: 'not-set'`.

#### InlineNotice

A one-line warning strip. Used by the New Run config-incomplete gate and the
add-connection backend note. Reusable.

Container: `background: --bg-warning`, `1px solid --border-warning`, `--radius-lg`, `padding: 12px 16px`, `display: flex; align-items: center; gap: 10px`.

Leading: a 16px warning glyph, `stroke: --text-warning`. Text: `--type-breadcrumb`, `--text-warning`. Optional trailing link (`margin-left: auto`): `--color-orange`, font-weight 500, `--type-breadcrumb`, no underline.

Props: `message: ReactNode`, `action?: { label: string, onClick: () => void }`.

---

## Organisms

### SettingsPage

> Supersedes the earlier two-column `NavItem` layout and the `Profiles` /
> `Agents` sections. The live UI is single-column stacked cards; this spec
> matches it. The redesign is built around the
> **connection -> configured model -> role slot** model the backend ships (M5/M6).

Full-page settings view via "Settings" in the header. **Single column**, centered
container (`--settings-max-width`, `margin: 0 auto`), `--form-page-padding`-style
top/side padding. Page title (26px/500 `--text-primary`) then a vertical stack of
section cards (`--gap-content` between them).

Section cards: `--bg-card`, `--radius-2xl`, `0.5px solid --border-card`,
`--padding-card-settings` (22px 26px). Each card: a card title (17px/500
`--text-primary`) with an optional right-aligned hint (`--type-breadcrumb`,
`--text-muted`), an optional description line, then content.

**Sections, in order:**

1. **Connections** — `ConnectionRow` per connection, the active row's `ConnectionForm` inline below it, and a `Button` `text` ("+ Add connection") that opens an add `ConnectionForm`. Empty state: just the add trigger.
2. **Model roles** — three `RoleRow`s (strong, standard, cheap). Description: "koan uses three roles across every workflow. Pick a connection, then a model, then a thinking level." Right hint: "Any model can fill any role."
3. **Memory** — three `RoleRow`s (embedding [no thinking], memory-llm, reflect-llm). Description: "Models used by the memory subsystem."
4. **Runtime** — a `SettingRow` with `NumberInput` for scout concurrency ("Maximum number of parallel scout agents").

Connections sits first because Model roles and Memory both reference connections;
ordering the dependency before its consumers reads top-down.

### NewRunForm

The New Run page. A workflow selector and a description field, plus a per-run model
override and two config-gating states. The workflow selector and description field
are unchanged from the prior design.

**Run-readiness:** a run is startable when all three role slots (strong / standard
/ cheap) resolve to a valid configured model **and** at least one connection
exists. Memory bindings do **not** gate run start.

Three render states:

1. **Ready** (config complete): below Description, a **Models** section card —
   header `seclabel` "Models" + right hint "Defaults from Settings · changes apply
   to this run only" — containing a column-header line (a flex row mirroring the
   compact row geometry: a spacer over marker+meta, then PROVIDER / MODEL /
   THINKING labels — 9px/500, uppercase, letter-spacing .6px, `--text-muted`)
   above three `RoleRow`s (`variant="compact"`, strong / standard / cheap, 8px
   gap). Then `Button` `primary` (`md`) "Start Run", enabled.
2. **Config incomplete** (>=1 connection, but a role slot is unassigned or broken):
   workflow + description render normally; the **Models section is hidden** (there
   is no complete config to override — the durable fix is in Settings, not a
   per-run patch). An `InlineNotice` ("Assign a model to all three roles before
   starting a run." + "Open Settings ->") sits where the Start button group is, and
   "Start Run" is disabled.
3. **No providers** (zero connections): the `NoProvidersBlock` organism (below)
   replaces the form body.

### NoProvidersBlock

The first-run / cold-start gate. Full-width block inside the New Run content area.

Container: `--bg-card`, `0.5px solid --border-card`, `--radius-2xl`, `padding: ~40px`, `text-align: center`.

Contents: a 46px danger circle (`background: --bg-danger`, a warning glyph
`stroke: --text-danger-body`), a heading (20px/500 `--text-primary`, "No providers
configured"), a body line (`--type-body`, `--text-body`, max-width ~400px,
"koan needs at least one connection before it can run. Add a provider, then assign
models to the three roles."), a row of three `RoleCard`s (`variant="not-set"`),
and a `Button` `primary` (`md`) "Go to Settings".

Distinct from NewRunForm state 2: zero connections is a full takeover (nothing to
do here yet); incomplete config keeps the real page and surfaces the specific gap.

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

- Top section: Overall feedback textarea (label + `TextInput` in textarea mode with file-attach gutter button). Label: "Overall feedback (optional)". Placeholder: "Summarize your overall feedback on this document, or leave empty to submit only inline comments."
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

### ToolAggregateCard

Container: `background: var(--bg-card)`, `0.5px solid var(--border-card)`,
`border-radius: var(--radius-xl)`, `overflow: hidden`. **No orange left
border** — the navy header band carries the card's identity; doubling it with
the content-source accent over-decorated the card. (Deliberate deviation from
"left border = content source"; the navy band is a stronger, unambiguous marker
of agent tool activity.)

Header band: `background: var(--color-navy)`, `display: flex`,
`align-items: baseline`, `gap: 10px`, `padding: 10px 18px 9px`. Contains:

1. Label "explore": `font-size: 11px`, `color: var(--text-on-dark-muted)`,
   `letter-spacing: 1px`, uppercase.
2. Op count: `font-size: 14px`, `color: var(--text-on-dark)`,
   `font-weight: 500`. E.g. "10 operations".
3. Spacer (`flex: 1`).
4. Running indicator (when in-flight): pulsing orange dot + label,
   `--font-mono`, 11px, `color: var(--color-orange)` — unchanged semantics.
5. Elapsed: `--font-mono`, 11px, `color: var(--text-on-dark-subtle)`,
   `padding-left: 8px`. Computed from the first child's `started_at_ms` (which
   the backend must stamp correctly — see the backend data contract).

Body: `display: grid`, `grid-template-columns: 208px 1fr`. One **pair of grid
cells per family group**, in first-occurrence order:

- Group-stat cell: a `ToolStatBlock`. The navy column is formed by the stacked
  stat cells — there is no separate pane element.
- Group-ops cell: `padding: 9px 18px`, `min-width: 0`; a stack of
  `ToolLogRow`s in chronological order within the family. Adjacent group-ops
  cells separated by `border-top: 1px solid var(--border-divider-light)`
  (first has none).

Because stat cell and ops cell are cells of the same grid row, the stat header
top-aligns with the group's first op row by construction.

Active state: unchanged three-signal rationale — header running indicator,
owning `ToolStatBlock` `active`, in-flight `ToolLogRow` `running`.

Props: `groups: FamilyGroup[]` (ordered; each `{ family, ops, metaLines }`),
`operationCount: number`, `runningLabel?: string`, `elapsed?: string`. The
grouping utility (`groupExplorationOps`) folds chronological `ExplorationOp[]`
into `FamilyGroup[]`, keeping the organism pure layout.

#### Rendering rule (stream level)

- Run of 2+ consecutive exploration ops → `ToolAggregateCard`.
- Run of exactly 1 exploration op → `ToolCallRow` family variant.
- `write`/`edit` → standalone `ToolCallRow` (status variant), breaks runs.
- Thinking, prose, user messages, step/phase boundaries break runs (unchanged).

---

## Header Bar

The header bar operates in two modes:

**Navigation mode:** Used on the New Run, Sessions, Memory, and Settings pages. The zone right of the logo divider shows top-level navigation links: "New run", "Sessions", "Memory", "Settings". Each link: `--type-breadcrumb` (13px), `--font-body`. Active page: `--text-on-dark`, font-weight 500. Inactive pages: `--text-on-dark-muted`, font-weight 400. Links separated by 6px gap.

**Sub-page breadcrumb (navigation mode):** When rendered inside a sub-page of a primary nav section, `BreadcrumbNav` is shown left of the logo divider, showing the current nav section name plus sub-page identifier. Pattern: `Memory > #0048`, `Memory > Reflect > "..."`. This is structurally distinct from workflow-mode breadcrumb, which encodes phase/step and includes `ProgressSegment`s.

**Workflow mode:** Used during an active workflow run. The zone right of the logo divider shows the phase/step breadcrumb and progress segments. Navigation links are not shown.

Settings is accessed via the "Settings" navigation link. There is no separate settings icon in the header.

---

## Layout: Settings View

Used for the Settings page. Single-column layout: a centered container holding a
vertical stack of section cards. (Supersedes the earlier two-column side-nav
layout; the live UI is single-column stacked cards.)

```
Structure:
  Flex column (100vh, overflow: hidden):
  ├─ HeaderBar (flex-shrink: 0, full viewport width, navigation mode)
  └─ Centered container (flex: 1, min-height: 0, --settings-max-width,
                         margin: 0 auto, --form-page-padding top/side padding,
                         overflow-y: auto)
        ├─ Page title (26px/500, --text-primary)
        └─ Stack of section cards (--gap-content between them)
           (--bg-card, --radius-2xl, 0.5px solid --border-card,
            --padding-card-settings)
              └─ Card title (17px/500) [+ optional right hint]
                 [+ optional description] + content
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

FeedbackInput rewrites `/plan ...` into natural language before sending to the backend. The `/` prefix is a UI convention only -- the orchestrator receives a clear, structured instruction without requiring backend slash-command parsing.

### Internal tool call suppression

Koan orchestration tools (`koan_yield`, `koan_complete_step`, `koan_set_phase`) are internal to the workflow engine. Their effects are visible through the molecules they trigger (YieldPanel, StepHeader, PhaseMarker). They do not render as ToolCallRows in the content stream.

### Orange dot-on-divider = user event

The dot-on-divider pattern is extended with color semantics. A **teal dot** signals a system event (PhaseMarker — the workflow engine changed phase). An **orange dot** signals a user event (ReviewEvent — the user submitted artifact feedback). Both use identical layout; only the dot color differs. This preserves the "events happen between content" principle while distinguishing system-initiated from user-initiated transitions.

### Review card pattern

The ReviewPanel card uses `border-top: 3px solid --color-orange`, the same "panel-level attention" signal as ElicitationPanel's decision panel. Both are organisms that yield the conversation and require user action to proceed. The visual consistency communicates this shared interaction pattern: the workflow is paused, waiting for you.

### Family-grouped panes over chronological two-pane

The prior `ToolAggregateCard` put family stats in a fixed left pane and a
chronological log in the right pane. The two panes had independent vertical
rhythm, so their lines never aligned. The redesign groups the log **by tool
family**: each family is one grid row whose left cell is that family's stat
block and whose right cell is that family's operations. Alignment is
structural — the stat block is the row header of its group and cannot drift
from it. Chronological order is preserved _within_ each family; family order
is first-occurrence order in the run.

Cross-family chronology inside one card is sacrificed. This is acceptable
because aggregates are bounded by thinking blocks, prose, and mutations —
consecutive exploration runs are short, and the stream-level ordering (card →
thinking → card) carries the narrative. Cards are summaries, not transcripts.

### Single-op fallback

An aggregate containing exactly **one** operation renders as a compact
`ToolCallRow` (family variant), not as the card. Two or more operations render
the full card. Thinking blocks break aggregate runs, and the agent thinks
between most calls, so single-op aggregates are the dominant case in practice —
a full card (navy stat block restating one row under a full header) is absurd
at n=1. The threshold is op count, not family count: a 6-family / 6-op card
(one op each) still renders as a card.

### Exploration family set

`read`, `grep`, `glob`, `bash`, `web_search`, `web_fetch`. These are the
builtin tools an agent uses to gather context. `write` and `edit` are
mutations — individually significant, never aggregated, and they break an
aggregate run. Koan orchestration tools remain suppressed (existing rationale).
`ls` is not registered as a builtin; no fold case, store union member, or
`StatusDot` variant exists for it.

`bash` joins the aggregate unconditionally — no read-only heuristic. Bash has
semantic variance (explore vs mutate), but classifying commands by intent is
guesswork, and a wrong "mutation" guess would eject an `ls -la` to a standalone
row while a wrong "exploration" guess would bury a `git commit`. The exit-code
metric and the `$` sigil keep bash rows self-describing inside the card.

### Family indicator colors

Filesystem read-only tools stay in the teal family (`read`, `grep`, `glob`).
`bash` is execution, not read-only — it takes the purple already established as
a decorative anchor (`--color-purple`). Web tools are remote retrieval and get
a desaturated slate blue, distinct from both teal (local reads) and navy
(surface). Orange remains reserved for active state and never appears as a
family color.

### Secondary text weight on white

Directory prefixes, line ranges, grep scopes, and the `$` sigil render in
`--text-muted` (#9a8e7e), **not** `--text-hint` (#c8baa8). Hint-weight text on
`--bg-card` white fails comfortable readability for content the user actually
scans (which directory was that file in?). `--text-hint` remains correct for
genuinely ignorable chrome (elapsed timestamps) but not for command content.

### Tool command overflow

Truncate + native `title` tooltip. No click-to-expand, no row caps. Read paths
truncate from the **left** (directory side) so the basename always survives;
patterns, commands, queries, and URL paths truncate from the right. Every
truncating element carries `title` with the full text.

### Grep rollup omits file counts

Summing `files_matched` across greps double-counts files that matched multiple
patterns. Distinct-file counting requires the backend to report _which_ files
matched, which it does not. The grep group rollup therefore shows
`matches · lines` only. Per-op rows still show that op's file count — a single
op's count is exact.

### Tool aggregation active state

Active state on `ToolAggregateCard` is communicated through three in-card
signals, not through a border color change. When an operation inside the
card is in-flight:

1. The card header renders a pulsing orange dot plus a short label
   (e.g., "reading projections.py").
2. The stat block for the tool type that owns the in-flight operation
   renders with `active={true}`, turning its tool name orange.
3. The in-flight log row in its group-ops cell renders with
   `status="running"`, gaining a pulsing orange dot and dimming its command
   text.

The card's outer chrome does not change with activity — the navy header band
is constant (the card carries no content-source left border; see the
`ToolAggregateCard` spec). Keeping the chrome static avoids conflating "this
is agent content" with "this is happening right now." The three in-card
signals are enough: the user always has a clear "something is still
happening" indicator without ambiguity in the outer chrome.

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

`ToolCallRow` for `write` and `edit` shows size/line-count metrics without
duration. `bash` now aggregates (see "Exploration family set") and follows the
per-op metric table — exit code and output lines, no duration.

### Model configuration is three fields

A configured model is exactly **provider (connection) + model id + thinking /
effort**. Context-window variant, prompt caching, and tool selection are inferred
and managed by koan, not user-configured — the backend resolves them per
`(provider, model)` capability. Exposing them as controls invited per-model
fiddling with settings the user shouldn't have to reason about. The thinking
control is a single unified scale (`off` / `low` / `medium` / `high`, or the
model's supported subset); koan maps it to each provider's native shape (budget /
effort / adaptive). This keeps the role rows and override cards to three controls.

### Picker dependency order

Connection, model, and thinking are arranged in dependency order everywhere
(`RoleRow` left-to-right, in both its default and compact variants — the compact
variant's shared PROVIDER/MODEL/THINKING column header on New Run carries the
labels): the connection scopes
which models are listable, and the chosen model scopes which thinking levels exist.
The model `ModelPicker` is disabled until a connection is set; the thinking `Select`
is disabled until a model is set. This is the locked override layout (chosen over a
model-first arrangement) because it matches the data dependency and avoids invalid
intermediate states.

### Override layout at form width

The New Run per-run override originally used three `RoleCard`s side by side
(labelled controls stacked per card). That layout needed >=245px per card for a
14-15 character mono model id to stay readable, but the New Run column is 640px
(`--form-max-width`), which yields 173px cards — geometrically unworkable, no
amount of padding-trimming closes the gap. The override therefore uses compact
`RoleRow`s with a single shared column-header line (PROVIDER / MODEL / THINKING),
which gives the model column the full row width and also unifies New Run with
Settings' row language. Lesson: mockups and harnesses for width-sensitive
components must render at the true container width — the card layout looked fine
in a 920px review harness and failed only on the real page.

### ModelPicker is a combobox, not a Select

The model control filters, groups ("newest in family" pins vs the flat list),
accepts free-text ids, shows a loading state, and degrades to free-text + catalog
for non-listing providers. A native `Select` can't do this. The list is **flat** —
no family/tier tree — because tiering is a koan concept (the three role slots), not
a property the user navigates when picking a specific model. The picker reloads its
options whenever the connection changes; the Settings page fetches a connection's
models live on render where the provider supports it.

### Run-readiness and the two empty states

Zero connections and incomplete-but-nonempty config are different situations and
look different. Zero connections (`NoProvidersBlock`) is a full-page takeover —
there is nothing useful to do on New Run yet. Incomplete config (a slot unassigned
or broken while connections exist) keeps the real New Run page, hides the override
section, disables Start, and points to Settings. The override is only for tweaking a
working configuration; you finish setup in Settings, where the active config is the
source of truth — patching an empty slot per-run would force a re-pick every run.

### Broken assignment

A slot can point at a configured model whose connection was later removed. Rather
than fail silently, the `RoleRow` flags it: danger-tinted row, the dead connection
shown in field-error state with a "removed" badge, and a helper line. The role
counts as not-runnable, so it trips the New Run gate. Re-picking a connection
repairs it. The signal lives at the field (the connection is what vanished), not as
a generic row error.

### Capability-gated controls

The UI never offers a control for a capability the chosen `(provider, model)` does
not have. Concretely: a model with no thinking support shows the thinking `Select`
disabled (`—`) rather than offering levels that would error. Capabilities are
resolved, never asked. This makes backend `422`s on unsupported settings rare; the
auto-save error toast is the safety net, not the primary path.

### Auto-save error surfacing

The role / memory `Select`s and `ModelPicker`s auto-save individually (per the
"Save model" rule — every control has a valid state at every moment). They have no
Save button to attach an inline error to, so a failed save shows a transient error
`Notification` toast and **reverts the control to its last-good value**.
`ConnectionForm` keeps its inline error instead — it is an `InlineForm` with Save /
Cancel, so the error belongs in the form.

### OpenAI-compatible endpoints

xAI/Grok, Together, Groq and similar OpenAI-compatible APIs are reached
by creating an `openai` connection with a custom endpoint (e.g.
`https://api.x.ai/v1`), not by adding a provider type. `ProviderType` is
`google | anthropic | openai | bedrock | openrouter | voyage`.
`openrouter` is a first-class provider type (key-required, library-fixed endpoint
`https://openrouter.ai/api/v1`); other OpenAI-compatible services use the `openai`
type with a custom endpoint override instead. Adding another first-class type is
a backend change (capability table + adapter entry) and is out of scope for the UI.

### RoleMarker vs MemoryTypeIcon

Both are colored rounded squares. `MemoryTypeIcon` carries a single letter (D/L/C/P)
because its four types are otherwise only distinguished by color. `RoleMarker` omits
the letter: roles always sit beside a text label, and "Strong"/"Standard" would both
reduce to "S". The marker is a color anchor, not a glyph.

### Perceptibility of state-change colors

Interactive state changes (hover, keyboard highlight, selection) must use a
surface at least one perceptual step from the background they sit on: on
`--bg-card` (white), that means `--bg-surface` or `--bg-tool-row`, never
`--bg-card-warm`. The original ModelPicker highlight used `--bg-card-warm`
(#faf8f4) on white — a few RGB points of difference — and keyboard navigation
appeared broken while working correctly: the state changed, the pixels didn't.
Related: a Badge whose background matches its row surface (e.g. `--bg-danger`
pill on a `--bg-danger` broken row) degrades to plain colored text; acceptable
when the text carries the meaning, but choose a contrasting surface when the pill
shape matters.

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

### Zustand state shape

| Field           | Type                 | Purpose                                                                              |
| --------------- | -------------------- | ------------------------------------------------------------------------------------ |
| `memory`        | `MemoryState`        | Project-scoped entry summaries and summary text; persists across workflow boundaries |
| `reflect`       | `ReflectRun \| null` | Project-scoped reflect session; null when no session is active                       |
| `memorySidebar` | `{search, filter}`   | Shared search/filter state across all three memory browsing pages                    |

### SSE events consumed

The following event types are produced by the backend and consumed by the
frontend SSE fold to update the projection:

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

---

## Timeline Rail & Phase Transition

Addendum for the phase transition redesign (Direction C: Timeline Rail). Covers
all new components, tokens, store types, and layout changes.

### Design Rationale

#### Why a timeline rail

Phase transitions reset the orchestrator's context window. Artifacts are the only
state that crosses phase boundaries. The current single-scroll content stream
gives users the false impression that the agent retains all previous
conversation. The timeline rail solves this by:

1. Making phases spatially separate — each phase's content occupies the full
   content area; old content is not scrolled past.
2. Showing handoff artifacts explicitly on the timeline, between the phases they
   connect.
3. Supporting variable-length workflows (milestones) and skipped phases without
   layout changes.

#### Phase viewing vs. phase active

"Active" means the orchestrator is currently running in that phase. "Viewing"
means the user is looking at a phase's historical content. These are independent:
you can view Intake while Plan Spec is active. The timeline always shows truth
about what's active (orange dot + glow). The content area shows what's being
viewed.

#### Milestone grouping

Milestones contain sub-phases (Plan, Execute) that are real context-window
resets. Visually, milestones are grouped to avoid timeline bloat. Sub-phases use
smaller dots and indentation. Sub-phase artifacts use smaller badges. The
milestone header uses a numbered circle instead of a plain dot.

#### Retired components

`PhaseMarker` (molecule) is retired. Phase boundaries are no longer inline
content events — they are structural, represented by the timeline rail + content
area replacement. The `BreadcrumbNav` molecule's phase/step display is superseded
by the timeline rail; the header simplifies.

### Timeline tokens

#### Page-level spacing

| Token                         | Value | Usage                                                                                  |
| ----------------------------- | ----- | -------------------------------------------------------------------------------------- |
| `--timeline-width`            | 200px | Timeline rail width for simple workflows.                                              |
| `--timeline-width-milestones` | 220px | Timeline rail width when milestone groups are present (wider for indented sub-phases). |

No other new tokens required. Timeline-internal colors (connecting lines, text on
navy) reuse existing `--color-navy`, `--color-teal`, `--color-orange`,
`--text-on-dark` family, and `--text-on-dark-muted` / `--text-on-dark-subtle`.
Specific rgba values for connecting lines and future-state elements are hardcoded
in component CSS with comments, since they are navy-background-specific and not
reusable elsewhere.

### Timeline atoms

#### TimelineDot

A status dot used on the timeline rail for top-level phase nodes. Four states:
done, active, future, skipped.

Size: 12px diameter, `border-radius: 50%`, `flex-shrink: 0`. Positioned with
`position: relative; z-index: 1` to sit above the connecting line.

- **done:** `background: var(--color-teal)`.
- **active:** `background: var(--color-orange)`, `box-shadow: 0 0 0 4px rgba(212, 119, 90, 0.25)` (orange glow ring).
- **future:** `background: transparent`, `border: 2px solid rgba(255, 255, 255, 0.15)`.
- **skipped:** `background: transparent`, `border: 2px solid rgba(255, 255, 255, 0.08)`. A diagonal strike-through via `::after` pseudo-element: `position: absolute`, `left: 1px`, `right: 1px`, `top: 50%`, `height: 1.5px`, `background: rgba(255, 255, 255, 0.2)`, `transform: rotate(-45deg)`.

Props: `status: 'done' | 'active' | 'future' | 'skipped'`.

#### MilestoneNumber

A numbered circle used as the milestone group header node. Three states: done,
active, future.

Size: 20px diameter, `border-radius: 50%`, `display: flex`, `align-items: center`,
`justify-content: center`. Font: `var(--font-mono)`, 10px, font-weight 500.
Positioned with `position: relative; z-index: 1`.

- **done:** `background: var(--color-teal)`, `color: var(--text-on-dark)`.
- **active:** `background: var(--color-orange)`, `color: var(--text-on-dark)`, `box-shadow: 0 0 0 3px rgba(212, 119, 90, 0.2)`.
- **future:** `background: transparent`, `border: 2px solid rgba(255, 255, 255, 0.15)`, `color: rgba(255, 255, 255, 0.25)`.

Props: `number: number`, `status: 'done' | 'active' | 'future'`.

### Timeline molecules

#### TimelinePhaseNode

A clickable phase entry in the timeline rail. Renders a TimelineDot, phase name,
and optional metadata (elapsed time, step info).

Container: `position: relative`, `padding: 0 16px`, `cursor: pointer`. The
`::before` pseudo-element draws the vertical connecting line: `position: absolute`,
`left: 27px`, `top: 0`, `bottom: 0`, `width: 2px`,
`background: rgba(255, 255, 255, 0.08)`. First child: `top: 50%`. Last child:
`bottom: 50%`.

Inner row: `display: flex`, `align-items: center`, `gap: 10px`,
`padding: 10px 0`.

Phase name: `font-size: 13px`, `font-weight: 500`. Color by status — active:
`var(--text-on-dark)`, done: `var(--text-on-dark-muted)`, future:
`rgba(255, 255, 255, 0.22)`, skipped: `rgba(255, 255, 255, 0.15)` with
`text-decoration: line-through`, `text-decoration-color: rgba(255, 255, 255, 0.2)`.

Meta line (optional): `font-size: 10px`, `var(--font-mono)`, `color: var(--text-on-dark-subtle)`, `margin-top: 1px`. Shows elapsed time for done phases, "step N/M · StepName" for active phases, "skipped" for skipped phases.

**Viewing state:** When the user is viewing this phase's historical content (but
it is not the active phase), the container gets
`background: rgba(255, 255, 255, 0.06)`, `border-radius: var(--radius-md)`,
`margin: 0 4px`, `padding: 0 12px`. The name color upgrades to
`var(--text-on-dark)` regardless of status.

Props: `name: string`, `status: 'done' | 'active' | 'future' | 'skipped'`, `meta?: string`, `viewing?: boolean`, `onClick?: () => void`.

Composes: TimelineDot.

#### TimelineHandoff

An artifact badge rendered between top-level phases on the timeline, representing
the handoff artifact that connects them.

Container: `display: flex`, `align-items: center`, `gap: 5px`,
`margin: -4px 0 -4px 39px` (aligns with the connecting line, overlapping the
vertical spacing slightly), `padding: 3px 8px`,
`background: rgba(90, 154, 138, 0.15)` (teal-derived),
`border-radius: var(--radius-md)`, `position: relative`, `z-index: 1`.

Artifact name: `var(--font-mono)`, `font-size: 10px`, `color: var(--color-teal)`,
`font-weight: 500`.

Props: `name: string`, `onClick?: () => void`.

#### TimelineSubPhaseNode

A smaller phase node for sub-phases within a milestone group (Plan, Execute). Uses
a smaller dot and tighter spacing.

Container: `display: flex`, `align-items: center`, `gap: 8px`, `padding: 4px 0`,
`position: relative`.

Dot: 7px diameter, `border-radius: 50%`, `position: relative`, `z-index: 1`.
States — done: `background: var(--color-teal)`, `opacity: 0.7`. Active:
`background: var(--color-orange)`, `box-shadow: 0 0 0 3px rgba(212, 119, 90, 0.2)`.
Future: `border: 1.5px solid rgba(255, 255, 255, 0.12)`, `background: transparent`.

Name: `font-size: 11px`. Colors — done: `rgba(240, 232, 216, 0.4)`, active:
`var(--text-on-dark)`, `font-weight: 500`, future: `rgba(255, 255, 255, 0.18)`.

Props: `name: string`, `status: 'done' | 'active' | 'future'`.

#### TimelineSubArtifact

A smaller artifact badge between sub-phases within a milestone group. Visually
subordinate to TimelineHandoff.

Container: `display: flex`, `align-items: center`, `gap: 4px`,
`margin: -2px 0 -2px 7px` (indented less than top-level handoffs),
`padding: 2px 6px`, `background: rgba(90, 154, 138, 0.1)` (lighter teal than
TimelineHandoff), `border-radius: 3px`, `position: relative`, `z-index: 1`.

Artifact name: `var(--font-mono)`, `font-size: 9px`,
`color: rgba(90, 154, 138, 0.8)`, `font-weight: 500`.

Props: `name: string`.

#### TimelinePlaceholder

A three-dot placeholder for variable-count future phases (milestones).
Communicates "something goes here, count unknown."

Container: same `::before` connecting line as TimelinePhaseNode. Inner:
`display: flex`, `align-items: center`, `gap: 10px`, `padding: 10px 0`.

Dots column: `display: flex`, `flex-direction: column`, `gap: 4px`,
`align-items: center`, `width: 12px` (matches TimelineDot width). Three dots:
each 4px diameter, `background: rgba(255, 255, 255, 0.15)`, `border-radius: 50%`.

Label: `font-size: 11px`, `color: rgba(255, 255, 255, 0.18)`,
`font-style: italic`, `font-family: var(--font-body)`.

Props: `label: string`.

#### ContextCard

A handoff card rendered at the top of each phase's content, showing which
artifacts the agent received from the previous phase. Not shown for the first
phase (Intake has no handoff).

Container: `background: var(--bg-card)`, `border: 1px solid var(--border-card)`,
`border-left: 3px solid var(--color-teal)`,
`border-radius: 0 var(--radius-lg) var(--radius-lg) 0`, `padding: 10px 16px`.

Label: `font-size: 11px`, `text-transform: uppercase`, `letter-spacing: 1px`,
`color: var(--text-muted)`, `font-weight: 500`, `margin-bottom: 4px`. Text:
"Handoff from {PhaseName}" or "Handoff from {PhaseName} ({SkippedPhase} skipped)"
when phases were skipped.

File entries: `display: flex`, `gap: 12px`, `flex-wrap: wrap`. Each entry —
filename: `var(--font-mono)`, `font-size: 12px`, `color: var(--color-orange)`,
`font-weight: 500`. Optional role label below: `font-size: 11px`,
`color: var(--text-muted)`, `font-weight: 400`, `font-family: var(--font-body)`.

Props: `fromPhase: string`, `artifacts: { name: string, role?: string }[]`, `skippedPhases?: string[]`.

#### PhaseTitleBar

A title bar rendered at the top of the content area identifying the current phase.
Different styling for active vs. historical viewing.

Container: `display: flex`, `align-items: center`, `gap: 10px`,
`padding-bottom: 8px`, `border-bottom: 1px solid var(--border-divider)`,
`margin-bottom: 4px`.

Dot: 10px diameter, `border-radius: 50%`. Active phase:
`background: var(--color-orange)`. Completed phase (viewing history):
`background: var(--color-teal)`.

Title: `font-size: 18px`, `font-weight: 500`, `color: var(--text-primary)`. For
milestone sub-phases: "Milestone N · SubPhase" format (e.g., "Milestone 2 · Execute").

Subtitle (right-aligned): `font-size: 12px`, `color: var(--text-muted)`,
`margin-left: auto`, `font-family: var(--font-mono)`. Shows "from {artifact}" for
active phases, milestone name for milestone sub-phases.

Badge (historical only): `font-size: 10px`, `color: var(--text-muted)`,
`border: 1px solid var(--border-card)`, `padding: 2px 8px`,
`border-radius: 3px`, `margin-left: auto`. Text: "completed · {elapsed}".

Props: `name: string`, `status: 'active' | 'completed'`, `subtitle?: string`, `elapsed?: string`.

#### ReturnBanner

A clickable banner shown at the top of the content area when viewing a completed
phase's history while another phase is active. Provides one-click navigation back
to the active phase.

Container: `display: flex`, `align-items: center`, `gap: 10px`,
`padding: 8px 16px`, `background: var(--bg-card)`,
`border: 1px solid var(--border-card)`, `border-radius: var(--radius-lg)`,
`cursor: pointer`. Hover: `background: var(--bg-tool-row)`. Transition:
`background var(--duration-fast) var(--ease-default)`.

Dot: 8px diameter, `background: var(--color-orange)`, `border-radius: 50%`.
Pulsing animation: `animation: pulse 2s ease-in-out infinite`
(opacity 1 -> 0.5 -> 1).

Text: `font-size: 13px`, `color: var(--text-muted)`. Phase name within:
`color: var(--color-orange)`, `font-weight: 500`. Format:
"Active: {PhaseName} is running".

Arrow: `margin-left: auto`, `color: var(--text-placeholder)`, `font-size: 14px`.
Text: "->".

Props: `activePhase: string`, `onClick: () => void`.

### Timeline organisms

#### TimelineRail

The full left sidebar showing the phase timeline. Renders all phases, handoffs,
milestone groups, and placeholders.

Container: `width: var(--timeline-width)` (or
`var(--timeline-width-milestones)` when milestones are present),
`flex-shrink: 0`, `background: var(--color-navy)`, `padding: 16px 0`,
`display: flex`, `flex-direction: column`, `overflow-y: auto`.

Optional section label (e.g., "milestones"): `padding: 4px 16px 6px`,
`font-size: 9px`, `text-transform: uppercase`, `letter-spacing: 1.5px`,
`color: rgba(255, 255, 255, 0.2)`.

Optional section separator: `height: 1px`,
`background: rgba(255, 255, 255, 0.06)`, `margin: 6px 16px`.

**Milestone group container:** `position: relative`, `padding: 0 16px`. Same
`::before` connecting line as TimelinePhaseNode. Header: MilestoneNumber + title.
Sub-phases wrapper: `padding-left: 20px`. Inner connecting line for sub-phases:
`position: absolute`, `left: 22px`, `width: 1px`,
`background: rgba(255, 255, 255, 0.06)`.

Future milestones show only the numbered header — no sub-phase detail.

**Scrolling:** The rail scrolls independently when milestone count exceeds
viewport height. Standard `overflow-y: auto` with koan's existing scrollbar
styling.

**Data model:** The rail renders from the workflow definition (phases list) plus
run state (phase statuses, produced artifacts, milestone definitions). When
milestones are not yet defined (early in the workflow), a TimelinePlaceholder
renders in their position.

Composes: TimelinePhaseNode, TimelineHandoff, TimelineSubPhaseNode,
TimelineSubArtifact, TimelinePlaceholder, MilestoneNumber.

Props: `phases: PhaseNodeData[]`, `milestones?: MilestoneGroupData[]`, `activePhaseId: string`, `viewingPhaseId: string | null`, `onPhaseClick: (phaseId: string) => void`.

### Modified organisms

#### HeaderBar

The breadcrumb nav (`BreadcrumbNav` molecule) no longer needs to show phase and
step — the timeline rail handles this. The header simplifies: the breadcrumb area
shows only the run title (e.g., "--home flag implementation"). The progress
segments are removed — progress is visible on the timeline.

The right side (model indicator, usage gauge, elapsed, settings gear) is
unchanged.

#### ContentStream

Phase boundaries are no longer rendered as inline `PhaseMarker` entries. Instead:

1. On phase transition, the content stream clears and shows only the new phase's
   conversation entries.
2. `PhaseTitleBar` renders above the Virtuoso list (not inside it) as a fixed
   header within the content column.
3. `ContextCard` renders as the first element inside the content column, below
   PhaseTitleBar, above the Virtuoso list.
4. `ReturnBanner` renders above PhaseTitleBar when viewing a completed phase.
5. When viewing a historical phase, the feedback input is hidden and content
   renders at `opacity: 0.75`. Historical prose cards use
   `border-left: 3px solid var(--color-teal)` instead of `var(--color-orange)`.
6. Historical YieldPanels render in a non-interactive "selected" state: the
   chosen option highlighted with teal accent, other options removed.
7. Step headers in completed phases use `color: var(--color-teal)` for the step
   label instead of `color: var(--color-orange)`.

#### Workspace Layout

The workspace layout changes from a two-column (content + artifacts sidebar) to a
three-column layout:

```
Flex row (flex: 1, min-height: 0):
+- TimelineRail (flex-shrink: 0, width: var(--timeline-width))
+- workspace-main (flex: 1, min-width: 0)
|  `- content-column (flex: 1, overflow-y: auto)
|     +- ReturnBanner (conditional)
|     +- PhaseTitleBar
|     +- ContextCard (conditional)
|     `- Virtuoso list + StreamingLeaf + FeedbackFooter
`- artifacts-sidebar (existing, unchanged)
```

### Timeline store changes

#### PhaseNodeData (new type)

```typescript
interface PhaseNodeData {
  id: string;
  name: string;
  status: "done" | "active" | "future" | "skipped";
  elapsed?: number; // ms, for completed phases
  currentStep?: number; // for active phase
  totalSteps?: number; // for active phase
  stepName?: string; // for active phase
  producedArtifacts?: string[]; // artifact filenames produced by this phase
}
```

#### MilestoneGroupData (new type)

```typescript
interface MilestoneGroupData {
  number: number;
  title: string;
  status: "done" | "active" | "future";
  subPhases: {
    name: string; // "Plan" | "Execute"
    status: "done" | "active" | "future";
    producedArtifact?: string; // e.g., "plan-ms-2.md"
  }[];
}
```

#### KoanState additions

```typescript
// Add to KoanState:
viewingPhaseId: string | null // null = viewing active phase
setViewingPhaseId: (id: string | null) => void
```

#### Run additions

```typescript
// Extend Run:
phaseHistory: PhaseNodeData[] // ordered list of all phases in the workflow
milestones?: MilestoneGroupData[] // populated after tech-plan phase
```

---

## Exploration Aggregate: Backend Data Contract

The tool-aggregate renderers consume fields the projection fold produces.
All items are implemented:

1. **Args on children.** `tool_request` creates entries with empty
   command fields, filled by `tool_input_delta` for all six families
   (read, grep, glob, bash, web_search, web_fetch). Providers that send
   complete args at tool_start (e.g. Anthropic) populate fields immediately
   via the `args` payload key.
2. **Timestamps.** `tool_request` carries real epoch-ms `ts_ms`; children
   and the aggregate entry carry real timestamps.
3. **Read ranges.** The display range is derived from `offset`/`limit` in
   `tool_input`; whole-file reads (no explicit limit) carry no range.
4. **Grep line counts.** The `matched_lines` metric is reported alongside
   match and file counts.
5. **Bash metrics.** `exit_code` and `output_lines` are computed natively
   by the tool function.
6. **Web metrics.** web_search `result_count`; web_fetch `content_size_bytes`.
7. **Store union.** Frontend `ExplorationChild` includes all six families
   (`read`, `grep`, `glob`, `bash`, `web_search`, `web_fetch`); `ls` is
   not present anywhere.
8. **Aggregation scope.** The fold's exploration set is
   `{read, grep, glob, bash, web_search, web_fetch}`; bash renders as a
   `ToolCallRow` family variant when standalone and as an aggregate child
   when inside a run.
