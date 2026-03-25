# Koan Design System

The definitive reference for Koan's visual language. Every UI decision — from
token values to component construction to layout patterns — is derived from
this document. When implementing or reviewing UI code, verify against these
specifications.

---

## 1. Design Principles

Six principles, ordered by priority. When principles conflict, higher wins.

### 1.1 Warm Workshop

Koan feels like a well-made craft tool — wood, leather, paper. Earth tones,
natural textures, nothing clinical or cold. If a design choice feels
"tech-startup" or "developer-dark-mode," it's wrong.

### 1.2 Breathing Space

Generous whitespace. Things float, they don't crowd. Accept showing less at
once in exchange for calm clarity. Padding is never too much; cramming is
always wrong.

### 1.3 Paper on Paper

Flat design. No drop shadows, no gradients, no glassmorphism. Containment
comes from thin warm borders — like sheets of paper laid on a wooden desk.
Depth is implied by background color tiers, not by visual effects.

### 1.4 Color is Earned

Most of the interface is neutral (cream, white, warm browns). Saturated color
appears only where it carries meaning: status indicators, active states,
errors. If everything is colorful, nothing is.

### 1.5 Weight, Not Decoration

Typography hierarchy comes from font weight and size, never from underlines,
all-caps body text, or decorative flourishes. The type system is a single
sans-serif family differentiated by weight. Mono is reserved strictly for
data, paths, and code.

### 1.6 Gentle Motion

Animation is subtle and purposeful. Fade-ins for appearing content, smooth
transitions for state changes, a quiet pulse for "thinking." No bouncing,
no sliding panels, no attention-grabbing motion. The UI should feel still.

---

## 2. Design Tokens

All visual values. CSS custom properties live in `variables.css`. Every
component references tokens — never raw color codes or pixel values.

### 2.1 Color Palette

#### Backgrounds

| Token           | Value     | Usage                                               |
| --------------- | --------- | --------------------------------------------------- |
| `--bg`          | `#FEFAE0` | Cornsilk base — the "desk"                          |
| `--bg-surface`  | `#E0D8C8` | Stone — sidebars, panels, monitor                   |
| `--bg-elevated` | `#FFFFFF` | Cards, overlays — "paper on paper"                  |
| `--bg-inset`    | `#D4CCB8` | Pressed/inset areas                                 |

#### Text

| Token           | Value     | Name         | Usage                                |
| --------------- | --------- | ------------ | ------------------------------------ |
| `--text`        | `#4A4428` | Olive-brown  | Default body text                    |
| `--text-strong` | `#283618` | Black Forest | Headings, names, emphasis            |
| `--text-muted`  | `#7A7450` | Dried sage   | Metadata, timestamps, secondary info |
| `--text-ghost`  | `#A09A6E` | Faded straw  | Placeholders, disabled states        |

#### Borders

| Token             | Value     | Usage                      |
| ----------------- | --------- | -------------------------- |
| `--border`        | `#C8C0A8` | Default card/panel borders |
| `--border-strong` | `#B8B098` | Dividers, emphasis borders |

#### Status — The Pigment Palette

Based on the Olive Garden Feast palette. Use sparingly.

| Token              | Value     | Name    | Meaning                         |
| ------------------ | --------- | ------- | ------------------------------- |
| `--green`          | `#606C38` | Olive   | Done, success, complete         |
| `--green-bg`       | `#EEF2E4` | —       | Success background tint         |
| `--green-border`   | `#606C38` | —       | Success border accent           |
| `--copper`         | `#BC6C25` | Copper  | Active, running, primary action |
| `--copper-bg`      | `#FDF3E4` | —       | Active background tint          |
| `--copper-border`  | `#BC6C25` | —       | Active border accent            |
| `--caramel`        | `#DDA15E` | Caramel | Pulsing dots, secondary accent  |
| `--caramel-bg`     | `#FEF7E8` | —       | Caramel background tint         |
| `--caramel-border` | `#DDA15E` | —       | Caramel border accent           |
| `--red`            | `#9A3412` | Ember   | Error, failed, destructive      |
| `--red-bg`         | `#FEF0E8` | —       | Error background tint           |
| `--red-border`     | `#9A3412` | —       | Error border accent             |
| `--ochre`          | `#92810A` | Ochre   | Warning, caution                |
| `--ochre-bg`       | `#FEFCE8` | —       | Warning background tint         |
| `--ochre-border`   | `#92810A` | —       | Warning border accent           |
| `--plum`           | `#606C38` | Olive   | Thinking, AI-internal states    |
| `--plum-bg`        | `#EEF2E4` | —       | Thinking background tint        |

#### Status Color Usage Rules

- **Backgrounds:** Status tints (`*-bg`) are used on cards/badges to signal
  state. They are very low saturation — barely tinted cream.
- **Text:** Status colors are used directly as text color on their tinted
  backgrounds. Never use status colors on the base `--bg` background for text
  — contrast is insufficient.
- **Borders:** `border-left: 3px solid` accent borders on cards to signal
  state. Only left borders get colored — top/right/bottom remain `--border`.
- **No other hues exist.** If you need a new semantic color, it must fit the
  earth-pigment family. No blues, no cyans, no neon greens.

### 2.2 Typography

#### Font Stacks

| Token         | Value                                                                  | Usage                          |
| ------------- | ---------------------------------------------------------------------- | ------------------------------ |
| `--font-sans` | `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`            | All UI text                    |
| `--font-mono` | `'SF Mono', 'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace` | Data, paths, code, model names |

#### Type Scale

| Token                 | Value  | Usage                         |
| --------------------- | ------ | ----------------------------- |
| `--font-size-xs`      | `11px` | Micro labels, ghost text      |
| `--font-size-sm`      | `13px` | Metadata, captions, secondary |
| `--font-size-md`      | `15px` | Body text (default)           |
| `--font-size-lg`      | `17px` | Section headings, card titles |
| `--font-size-xl`      | `22px` | Phase headings, page titles   |
| `--font-size-display` | `28px` | Logo, hero text               |

#### Weight Rules

| Weight | Token                   | Usage                                |
| ------ | ----------------------- | ------------------------------------ |
| `400`  | —                       | Body text, descriptions              |
| `500`  | —                       | Sidebar values, emphasis within body |
| `600`  | `--font-weight-heading` | Section headings, card titles        |
| `700`  | `--font-weight-strong`  | Page headings, agent names, logo     |
| `800`  | `--font-weight-display` | Display/hero text only               |

#### Typography Decision Tree

- **Is it a heading?** → `--font-sans`, `--text-strong`, weight 600-800
- **Is it body text?** → `--font-sans`, `--text`, weight 400
- **Is it metadata (time, count, model)?** → `--font-mono`, `--text-muted`, weight 400
- **Is it an agent/file name?** → `--font-mono`, `--text` or status color, weight 600
- **Is it a label (uppercase)?** → `--font-sans`, `--text-muted`, weight 700, `letter-spacing: .1em`, `text-transform: uppercase`, `--font-size-xs`

### 2.3 Spacing

Base unit: `4px`. Scale follows: 4, 8, 16, 24, 32, 48, 64.

| Token        | Value  | Usage                                        |
| ------------ | ------ | -------------------------------------------- |
| `--space-1`  | `4px`  | Tight gaps (between badge and text)          |
| `--space-2`  | `8px`  | Small gaps (between related items)           |
| `--space-4`  | `16px` | Default gap (between sections within a card) |
| `--space-6`  | `24px` | Card padding, section spacing                |
| `--space-8`  | `32px` | Between cards, panel padding                 |
| `--space-12` | `48px` | Major section breaks                         |
| `--space-16` | `64px` | Page-level padding, hero spacing             |

#### Spacing Decision Tree

- **Inside a card:** `--space-6` padding. `--space-4` between internal sections.
- **Between cards:** `--space-8` gap.
- **Between a label and its content:** `--space-2`.
- **Between inline items (badges, buttons):** `--space-2` to `--space-4`.
- **Page margins:** `--space-8` to `--space-12`.

### 2.4 Shape

| Token         | Value  | Usage                                    |
| ------------- | ------ | ---------------------------------------- |
| `--radius-sm` | `6px`  | Buttons, inputs, badges, inline controls |
| `--radius-md` | `10px` | Badges, pills, tags                      |
| `--radius-lg` | `14px` | Cards, panels, overlays                  |

#### Shape Rules

- **Cards, panels, overlays:** `--radius-lg` (14px) — soft, cushioned.
- **Buttons, inputs, selects:** `--radius-sm` (6px) — crisp, interactive.
- **Badges, pills:** `--radius-md` (10px) — rounded but not pill-shaped.
- **Status accent borders:** `border-left: 3px solid` with `border-radius: 0` on left, `--radius-lg` on right.
- **Never use `border-radius: 50%`** except for avatar circles (if added later).
- **Never use `border-radius: 9999px`** (full pill). Nothing is fully rounded.

### 2.5 Motion

| Token               | Value      | Usage                        |
| ------------------- | ---------- | ---------------------------- |
| `--duration-fast`   | `150ms`    | Hover states, button presses |
| `--duration-normal` | `250ms`    | Content fade-in, transitions |
| `--duration-slow`   | `400ms`    | Notification fade-out        |
| `--ease-default`    | `ease-out` | All transitions              |

#### Allowed Animations

| Name             | Properties                      | Usage                            |
| ---------------- | ------------------------------- | -------------------------------- |
| `fade-in`        | opacity 0→1                     | Content appearing                |
| `fade-out`       | opacity 1→0 + translateY(0→8px) | Notifications dismissing         |
| `thinking-pulse` | opacity 0.3→1→0.3               | Pulsing dot for "thinking" state |
| `cursor-blink`   | opacity 1→0→1, step-end         | Streaming text cursor            |

#### Forbidden Motion

- No `transform: scale()` — nothing grows/shrinks.
- No `translateX/Y` for layout shifts — things don't slide in.
- No `bounce` or spring easings.
- No `animation-iteration-count: infinite` except `thinking-pulse` and `cursor-blink`.

---

## 3. Primitives

Base-level elements. Every component is built from these.

### 3.1 Text Styles

```
.text-display    → --font-size-display, --font-weight-display, --text-strong, letter-spacing: -.03em
.text-heading    → --font-size-xl, --font-weight-strong, --text-strong, letter-spacing: -.02em
.text-title      → --font-size-lg, --font-weight-heading, --text-strong
.text-body       → --font-size-md, 400, --text, line-height: 1.6
.text-caption    → --font-size-sm, 400, --text-muted
.text-micro      → --font-size-xs, 400, --text-ghost
.text-label      → --font-size-xs, 700, --text-muted, uppercase, letter-spacing: .1em
.text-mono       → --font-mono, --font-size-sm, 400, --text
```

### 3.2 Buttons

Three variants. All use `--radius-sm` (6px), `--font-sans`.

| Variant     | Background     | Text     | Border                      | When to use                                          |
| ----------- | -------------- | -------- | --------------------------- | ---------------------------------------------------- |
| **Primary** | `--green`      | `#fff`   | none                        | Single main action per view (Begin Planning, Submit) |
| **Accent**  | `--copper` | `#fff`   | none                        | Secondary prominent action (Submit Review)           |
| **Ghost**   | `transparent`  | `--text` | `1px solid --border-strong` | Cancel, Back, non-committal actions                  |

Sizing: `padding: 12px 24px`, `font-size: --font-size-md`, `font-weight: 600`.

States:

- **Hover:** `opacity: 0.85` (primary/accent), `border-color: --text-muted` (ghost)
- **Disabled:** `opacity: 0.4`, `cursor: not-allowed`
- **No focus ring color** — use browser default outline.

### 3.3 Inputs

All inputs: `--radius-sm`, `padding: 12px 16px`, `border: 1px solid --border`,
`background: --bg-elevated`, `font-size: --font-size-md`, `color: --text-strong`.

- **Focus:** `border-color: --copper`
- **Placeholder:** `color: --text-ghost`, `font-style: italic`
- **Textarea:** Same as input. `min-height: 80px`, `resize: vertical`.
- **Select:** Same as input. Custom chevron via background SVG in `--text-muted`.

### 3.4 Badges

Inline status indicators. `--radius-md` (10px), `padding: 5px 14px`,
`font-size: --font-size-sm`, `font-weight: 600`.

| State   | Background        | Text           |
| ------- | ----------------- | -------------- |
| Done    | `--green-bg`      | `--green`      |
| Active  | `--copper-bg` | `--copper` |
| Failed  | `--red-bg`        | `--red`        |
| Warning | `--ochre-bg`      | `--ochre`      |
| Neutral | `--bg-inset`      | `--text-muted` |

### 3.5 Labels

Uppercase section markers. See `.text-label` style.

`font-size: --font-size-xs`, `font-weight: 700`, `color: --text-muted`,
`text-transform: uppercase`, `letter-spacing: .1em`.

Always followed by `--space-2` gap before content.

---

## 4. Components

Composed from primitives. Each component has a clear purpose and defined
states.

### 4.1 Card

The primary container. Paper on the desk.

```
background: --bg-elevated
border: 1px solid --border
border-radius: --radius-lg (14px)
padding: --space-6 (24px)
```

**Status variants** — left accent border, tinted background:

| State   | Background        | Left border              |
| ------- | ----------------- | ------------------------ |
| Default | `--bg-elevated`   | none                     |
| Running | `--copper-bg` | `3px solid --copper` |
| Done    | `--green-bg`      | `3px solid --green`      |
| Failed  | `--red-bg`        | `3px solid --red`        |

When a card has a status border, use `border-radius: 0 --radius-lg --radius-lg 0`
so the left edge is straight.

**Card anatomy:**

```
┌──────────────────────────────────┐
│ [label]          [badge]         │  ← card header (flex, space-between)
│                                  │
│ Title Text                       │  ← .text-title
│ Body description text that       │  ← .text-body
│ wraps to multiple lines.         │
│                                  │
│ [metadata]        [action btn]   │  ← card footer (flex, space-between)
└──────────────────────────────────┘
```

### 4.2 Pill Strip

Phase navigation. A row of connected segments showing workflow progress.

```
display: flex
border-radius: --radius-md (10px)
overflow: hidden
border: 1px solid --border
background: --bg
```

Individual pills: `padding: 6px 16px`, `font-size: --font-size-sm`, `font-weight: 600`.

| State    | Background     | Text           | Prefix |
| -------- | -------------- | -------------- | ------ |
| Inactive | `--bg`         | `--text-ghost` | none   |
| Active   | `--copper` | `#fff`         | `● `   |
| Done     | `--green`      | `#fff`         | `✓ `   |

Pills are separated by `border-right: 1px solid --border`. Last pill has no
right border.

### 4.3 Agent Table

Data table for subagent monitoring. Mono typography throughout.

```
Header row:  .text-label style (uppercase, xs, muted)
Data cells:  --font-mono, --font-size-sm
             padding: 8px on each cell
             border-bottom: 1px solid --border
```

Agent name is `--font-weight-heading` (600) and colored by status:

- Running: `--copper`
- Done: `--green`
- Failed: `--red`
- Queued: `--text-ghost`

Token counts and model names are always `--text-muted`.

### 4.4 Activity Card

Collapsible card in the activity feed showing a thinking block, tool call,
or scout dispatch.

```
background: --bg-surface
border: 1px solid --border
border-radius: --radius-lg
```

**Header:** flex row — tool name (left, `--text-muted` or status color) and
metadata (right, `--text-muted`, `--font-size-xs`).

**Body:** `--font-mono`, `--font-size-sm`, `--text-muted`, `white-space: pre-wrap`.
Clamped to 3 lines with "show more ▸" link in `--copper`.

**Active variant:** `border-color: --copper-border`.

**Thinking variant:** tool name in `--plum`.

### 4.5 Question Card

User-facing form for answering questions during intake.

```
background: --bg-elevated
border: 1px solid --border
border-radius: --radius-lg
padding: --space-6
```

**Structure:**

1. Header label (`.text-label`)
2. Context paragraphs (`.text-body`, `--text-muted`)
3. Question text (`--font-size-lg + 1px = 18px`, weight 500, `--text-strong`)
4. Options list (vertical stack, `--space-1` gap)

**Option items:** `padding: --space-2 --space-4`, `border: 1px solid --border`,
`border-radius: --radius-sm`, `cursor: pointer`.

- Hover: `border-color: --text-muted`
- Selected: `border-color: --copper-border`, `background: --copper-bg`

Radio dots: `14px` circle, `border: 2px solid --text-ghost`.
Selected: `border-color: --copper`, `background: --copper`.

### 4.6 Notification Toast

Transient feedback. Appears bottom-right, fades out.

```
padding: --space-2 --space-6
border-radius: --radius-md
color: #fff
animation: fade-in --duration-fast, then fade-out --duration-slow after 3s
```

| Type    | Background     |
| ------- | -------------- |
| Info    | `--copper` |
| Warning | `--ochre`      |
| Error   | `--red`        |

### 4.7 Overlay / Modal

For artifact review, settings, etc.

```
Backdrop: rgba(42, 31, 20, 0.5)   ← warm dark, not cold black
Panel:    --bg-elevated
          border: 1px solid --border
          border-radius: --radius-lg
          max-width: 860px
          max-height: 88vh
```

Header: `padding: 16px 24px`, `border-bottom: 1px solid --border`.
Body: `padding: 24px 28px`, scrollable.

---

## 5. Layout Patterns

### 5.1 App Shell

```
┌──────────────────────────────────────────────┐
│  HEADER (logo + pill strip + settings)       │  ← 56px height, border-bottom
├──────────────────────────────────────────────┤
│                                              │
│                 MAIN AREA                    │  ← flex: 1, scrollable
│                                              │
├──────────────────────────────────────────────┤
│  MONITOR (agent table)                       │  ← flex: 0 auto, border-top
└──────────────────────────────────────────────┘
```

- Max-width: `1300px`, centered.
- Background: `--bg` everywhere except monitor (`--bg-surface`).
- Header background: `--bg`.

### 5.2 Three-Column Workspace

Used during execution phase:

```
┌────────┬─────────────────────┬────────┐
│ STATUS │    ACTIVITY FEED    │ ARTI-  │
│ SIDE-  │                     │ FACTS  │
│ BAR    │                     │ SIDE-  │
│        │                     │ BAR    │
│ 240-   │     flex: 1         │ 240-   │
│ 300px  │                     │ 300px  │
└────────┴─────────────────────┴────────┘
```

- Sidebars: `background: --bg-surface`, `border-right/left: 1px solid --border`.
- Activity feed: `background: --bg`, centered content with `max-width: 960px`.

### 5.3 Centered Content

For intake, brief, planning phases — single centered column:

```
max-width: 960px
margin: 0 auto
padding: --space-8 --space-6
```

---

## 6. Decision Trees

Use these when deciding how to implement a new UI element.

### 6.1 "What container should I use?"

```
Is it a distinct content block with its own identity?
  → Card (--bg-elevated, border, --radius-lg)

Is it a list of status items (agents, scouts)?
  → Agent Table or scout-entry list (no outer card — direct on --bg-surface)

Is it a user-interactive form section?
  → Question Card

Is it above the page (blocking interaction)?
  → Overlay/Modal

Is it transient feedback?
  → Notification Toast
```

### 6.2 "What color should this text be?"

```
Is it a heading or name?           → --text-strong
Is it body copy?                   → --text
Is it a timestamp, count, model?   → --text-muted
Is it a placeholder or disabled?   → --text-ghost
Is it a status indicator?          → Use the status color (--green, --copper, --red, --ochre)
Is it an interactive link/action?  → --copper
```

### 6.3 "Should I use mono or sans?"

```
Is it a file path, command, or code?     → mono
Is it an agent/model name?               → mono
Is it a token count or numeric stat?     → mono
Is it a timestamp or duration?           → mono
Everything else                          → sans
```

### 6.4 "How should I signal state?"

```
Idle/default   → no color, --border, --bg-elevated
Running/active → left accent border (--copper), tinted bg (--copper-bg)
Complete/done  → left accent border (--green), tinted bg (--green-bg)
Error/failed   → left accent border (--red), tinted bg (--red-bg)
Warning        → left accent border (--ochre), tinted bg (--ochre-bg)
Thinking       → text color --plum, pulsing dot animation
Queued         → --text-ghost, no accent
```

### 6.5 "What spacing should I use?"

```
Between a label and its content     → --space-2 (8px)
Between items in a list             → --space-2 (8px)
Inside a card                       → --space-6 (24px) padding
Between cards                       → --space-8 (32px) gap
Between major sections              → --space-12 (48px)
Page edge padding                   → --space-8 (32px)
```

---

## 7. Anti-Patterns

Things that violate the design system. If you see these in code or are
tempted to add them, stop.

| ❌ Don't                                      | ✅ Do instead                                  |
| --------------------------------------------- | ---------------------------------------------- |
| Use `box-shadow` for elevation                | Use `border: 1px solid --border`               |
| Use blue (`#58a6ff`) for anything             | Use `--copper` for active/accent           |
| Use raw hex colors in components              | Reference `var(--token)`                       |
| Make text uppercase in body copy              | Uppercase only in `.text-label` elements       |
| Add `transform: scale()` animations           | Use `opacity` transitions only                 |
| Use `border-radius: 50%` on cards             | Cards always use `--radius-lg`                 |
| Put saturated color on `--bg` base            | Status color only on status-tinted backgrounds |
| Use `--font-mono` for descriptions            | Mono is for data/code/paths only               |
| Add padding less than `--space-2`             | Minimum meaningful spacing is 8px              |
| Use more than 2 font weights in one component | Pick from the weight scale                     |

---

## 8. Implementation Notes

### File Organization

```
src/planner/web/css/
  variables.css    ← all tokens defined here
  layout.css       ← app shell, grid, sidebar layouts
  components.css   ← card, badge, pill, table, form components
  animations.css   ← keyframes and motion utilities
```

### Token Naming Convention

- Background tokens: `--bg-*`
- Text tokens: `--text-*`
- Border tokens: `--border-*`
- Status colors: `--{color-name}`, `--{color-name}-bg`, `--{color-name}-border`
- Spacing: `--space-{multiplier}` (multiplier × 4px)
- Radii: `--radius-{sm|md|lg}`
- Motion: `--duration-{speed}`, `--ease-*`

### Scrollbar Styling

Scrollbars must blend into the warm palette. Never use browser defaults.

```css
scrollbar-width: thin;
scrollbar-color: var(--border-strong) transparent;
```

Webkit:

- Track: `transparent`
- Thumb: `var(--border-strong)` (`#B8B098`) — warm tan, not gray or black
- Thumb hover: `var(--text-muted)` (`#7A7450`) — slightly darker on interaction
- Width: `7px`
- Border-radius: `4px`

**Never use dark/black scrollbar thumbs.** They break the warm paper aesthetic.

### Global Reset

```css
*,
*::before,
*::after {
  box-sizing: border-box;
}
html,
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--font-size-md);
  line-height: 1.6;
}
```

Note: `line-height` is `1.6` (not `1.5`) for the breathing layout.
