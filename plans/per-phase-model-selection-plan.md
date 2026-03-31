## Context

### Decisions

- Koan adds a new root command parser via `/koan`, with `config` as the first subcommand.
- `/koan config` opens a settings-style menu with one section now: `Model selection`.
- `Model selection` uses a 5x4 matrix:
  - Rows: `plan-design`, `plan-code`, `plan-docs`, `exec-code`, `exec-docs`
  - Columns: `exec-debut`, `exec-fix`, `qr-decompose`, `qr-verify`
- Each matrix cell maps to one canonical key in the `phase-model` namespace (20 total keys).
- Cell picker uses an inline anchored selector and sources models from pi's model registry (`ctx.modelRegistry.getAvailable()`), matching `/model` inventory semantics.
- Quick-set controls exist at the top of model selection:
  - `Reset to active model` clears koan model overrides
  - `Set strong model` applies one chosen model to strong keys
  - `Set general-purpose model` applies one chosen model to all remaining keys
- Strong key set is fixed:
  - All `*-qr-decompose`
  - `plan-design-exec-debut`, `plan-design-exec-fix`
  - `exec-docs-exec-debut`, `exec-docs-exec-fix`
- General-purpose key set is computed as `all keys - strong keys`.
- Storage is denormalized: config persists either all 20 key/value pairs or none.
- Runtime model application happens only at subagent spawn time by passing `--model <provider/model>` when override exists.
- If koan model config is absent, all phases inherit pi's current active model by omitting `--model`.
- Quick-set writes always preserve all-or-none persistence: when no saved config exists, untouched keys are initialized from the current active model snapshot so all 20 keys are still written.
- Naming aligns precursor terminology to `exec-debut` and removes `exec-init` equivalents in koan-facing labels.

### Rationale

- Settings-style navigation matches existing pi interaction patterns and lowers learning cost.
- Matrix layout gives complete phase visibility and keeps override auditing simple.
- Quick-set controls reduce repetitive edits and enforce consistent strategy intent.
- Strong/decompose bias places more reasoning budget where planning and verification quality creates ripple effects across later work.
- `exec-docs-exec-debut/fix` are strong while `exec-code-exec-debut/fix` stay GP because code execution has a mechanical correctness backstop (build/test signals) that documentation execution does not.
- Spawn-time model resolution keeps implementation isolated to orchestration and avoids phase prompt churn.
- Denormalized persistence keeps read paths deterministic and avoids partial-state ambiguity.

### Constraints

- Current koan execution pipeline does not implement `exec-code` and `exec-docs`; plan still defines keys for forward compatibility.
- Existing workflow must remain behaviorally unchanged when config is absent.
- Model source must stay aligned with pi model availability/auth filtering.
- `/koan config` must work in TUI using ASCII/Unicode-safe rendering.
- Command parsing must use extension command behavior (`/koan` + args), not built-in command interception internals.

### Invisible knowledge

- Koan currently registers `/koan-execute` and `/koan-status`; no `/koan` root parser exists yet.
- Subagent model is currently observed for UI telemetry but never selected by koan.
- `spawnSubagent()` is the single chokepoint for all work/fix/QR subprocesses.
- `ModelSelectorComponent` is exported by pi and writes default model through settings manager on selection, so koan integration must prevent unintended global default mutation.

## Implementation

### 1) Canonical phase-key model map and preset sets

- Add `src/planner/model-phase.ts`.
- Define:
  - phase row constants
  - sub-phase column constants
  - `PhaseModelKey` union for all 20 keys
  - `ALL_PHASE_MODEL_KEYS`
  - `STRONG_PHASE_MODEL_KEYS`
  - `GENERAL_PURPOSE_PHASE_MODEL_KEYS`
- Add helpers:
  - `isPhaseModelKey(value)`
  - `buildPhaseModelKey(phaseRow, subPhase)`
  - internal `computeGeneralPurposeKeys()` used only to initialize exported constants
- Keep existing `WorkPhaseKey` definitions in `src/planner/subagent.ts` and `src/planner/session.ts` as intentionally narrower planning-only types; do not consolidate them into `PhaseModelKey` row definitions.

WHY: One canonical key map eliminates drift across UI, persistence, and spawn resolution while preserving existing planning-only type boundaries.

### 2) Config persistence (denormalized)

- Add `src/planner/model-config.ts`.
- Store at `~/.koan/config.json` under a dedicated object, e.g.:
  - `phaseModels: Record<PhaseModelKey, string>`
- Implement:
  - `loadPhaseModelConfig(): Promise<Record<PhaseModelKey, string> | null>`
  - `savePhaseModelConfig(config: Record<PhaseModelKey, string> | null): Promise<void>`
  - strict validation that accepts only all-keys or none
- On invalid partial data, treat as absent and log warning.

WHY: Denormalized all-or-none storage keeps runtime fallback rules unambiguous, and colocating this module under `src/planner/` keeps feature files cohesive.

### 3) Spawn-time model resolver

- Add `src/planner/model-resolver.ts`.
- Define and export `type SpawnContext = "work-debut" | "fix" | "qr-decompose" | "qr-verify"`.
- Implement:
  - `resolvePhaseModelOverride(key): Promise<string | undefined>`
  - `mapSpawnContextToPhaseModelKey(context: SpawnContext, phaseRow, fixPhase?): PhaseModelKey`
- Return `undefined` when config is absent or no override is expected, so spawn omits `--model`.

WHY: Spawn-time resolution guarantees current active model fallback without duplicating model logic in each phase.

### 4) Integrate model option into subagent spawning

- Update `src/planner/subagent.ts`:
  - extend spawn options with optional `modelOverride?: string`
  - append `--model <modelOverride>` when provided
  - extend QR spawn option types (`SpawnQRDecomposerOptions`, `SpawnReviewerOptions`) with `modelOverride?: string`
- Update `src/planner/session.ts`:
  - extend `SpawnWorkRunOptions` and `SpawnFixRunOptions` with `modelOverride?: string`
  - update `PhaseRunConfig.spawnWork` and `PhaseRunConfig.spawnFix` lambda forwarding to include `modelOverride`
  - update QR call sites in `runQRBlock(...)` so both `spawnQRDecomposer(...)` and `spawnReviewer(...)` receive resolved `modelOverride`
  - resolve the phase-specific key before each spawn and pass through the updated option chain

WHY: A single spawn chokepoint keeps model selection simple and mechanically verifiable, and explicit option threading prevents silent override drops across work, fix, and QR paths.

### 5) Add `/koan` command parser and config entry

- Update `extensions/koan.ts`:
  - register `/koan` command
  - parse args:
    - `config` opens config menu
    - unknown args display concise usage
  - keep existing `/koan-execute` and `/koan-status` commands unchanged

WHY: `/koan config` requires extension command parsing semantics that pi already supports for slash-command arguments.

### 6) Build `/koan config` menu screen

- Add `src/planner/ui/config/menu.ts` (or equivalent UI module).
- Use settings-style list with one item now:
  - `Model selection`
- Implement via `ctx.ui.custom(...)` + `SettingsList` or equivalent selector primitives.

WHY: A section-based menu matches `/settings` mental model; new sections extend without restructuring.

### 7) Build model selection matrix UI with inline picker

- Add `src/planner/ui/config/model-selection.ts`.
- Screen behavior:
  - quick-set row
  - blank spacer row
  - 5x4 matrix
  - cell values show explicit model or inherited marker (active model fallback)
- Inline anchored model picker opens for selected cell.
- Model list source comes from `ctx.modelRegistry.getAvailable()`.
- Reuse pi `ModelSelectorComponent` for selection UX parity, and pass `SettingsManager.inMemory()` so cell selection never mutates global default model settings.

WHY: Inline editing preserves matrix context and minimizes navigation overhead during bulk tuning while preserving `/model` selector parity.

### 8) Quick-set behavior and recommendation copy

- In model selection UI logic:
  - `Reset to active model` -> clear saved overrides (persist none)
  - `Set strong model` -> apply chosen model to strong keys; initialize non-strong keys from existing saved values, or from current active model snapshot when config is absent
  - `Set general-purpose model` -> apply chosen model to GP keys; initialize non-GP keys from existing saved values, or from current active model snapshot when config is absent
  - both quick-set actions write a complete 20-key map to satisfy all-or-none persistence
- Display recommendation nudges in UI copy:
  - Strong examples: GPT-5 (Codex), Opus, Gemini 3 Pro
  - GP examples: Sonnet, GPT-5 (Mini), Gemini 3 Flash

WHY: Presets encode reasoning allocation strategy while preserving per-cell override capability.

### 9) Rename precursor wording to `exec-debut`

- Apply `exec-debut` naming to:
  - phase-model key column constants and serialized key names
  - `/koan config` user-visible matrix labels
  - docs that describe phase/sub-phase naming
- Keep widget runtime token `qrMode: "initial"` in `src/planner/session.ts` and `src/planner/ui/widget.ts` unchanged because it remains internal orchestration state (used by routing/logic), not a model phase/sub-phase identifier and not the primary runtime progress display.

WHY: Shared terminology improves comprehension and keeps planning/exec vocabulary consistent without conflating UI state tokens with phase keys.

### 10) Validation and tests

- Add tests for:
  - key-space integrity (20 keys)
  - strong/GP partition correctness
  - config validator all-or-none behavior
  - quick-set from empty config initializes untouched keys from active model snapshot and still writes full 20-key maps
  - resolver fallback when config absent
  - spawn args include/exclude `--model` correctly
  - end-to-end threading for work/fix/qr spawn contexts, including `spawnQRDecomposer` and `spawnReviewer`

WHY: Orchestration defaults require deterministic tests to prevent silent model-routing regressions.

## Quality Checklist

Code quality standards from ~/.claude/conventions/code-quality/ applicable to this change:

- [ ] 01-naming-and-types (design-mode)
- [ ] 02-structure-and-composition (design-mode)
- [ ] 06-module-and-dependencies (design-mode)
- [ ] 07-cross-file-consistency (design-mode)

## Execution Protocol

```
1. delegate @agent-developer: implement per this plan file
2. delegate @agent-quality-reviewer: verify against plan + ~/.claude/conventions/code-quality/ (code-mode)

When delegating, pass this plan file path. Supplement only with:
- rationale for decisions not captured in plan
- business constraints
- technical prerequisites the agent cannot infer
```
