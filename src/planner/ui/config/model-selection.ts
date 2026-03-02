// Model selection matrix UI for /koan config.
// Renders quick-set actions plus a true 5×4 matrix (phase rows × sub-phase columns).
// Enter opens an inline ModelSelectorComponent for the selected quick-set/cell.
// Uses SettingsManager.inMemory() to prevent global default model mutation.

import { ModelSelectorComponent, SettingsManager } from "@mariozechner/pi-coding-agent";
import type { Theme } from "@mariozechner/pi-coding-agent";
import type { ModelRegistry } from "@mariozechner/pi-coding-agent";
import {
  type Component,
  type TUI,
  getEditorKeybindings,
  truncateToWidth,
  visibleWidth,
} from "@mariozechner/pi-tui";

import {
  ALL_PHASE_MODEL_KEYS,
  GENERAL_PURPOSE_PHASE_MODEL_KEYS,
  PHASE_ROWS,
  STRONG_PHASE_MODEL_KEYS,
  SUB_PHASES,
  buildPhaseModelKey,
  type PhaseModelKey,
  type PhaseRow,
} from "../../model-phase.js";
import { savePhaseModelConfig } from "../../model-config.js";

// -- Pure quick-set utilities (exported for testing) --

export function initConfigFromActiveModel(activeModelId: string): Record<PhaseModelKey, string> {
  const config: Partial<Record<PhaseModelKey, string>> = {};
  for (const key of ALL_PHASE_MODEL_KEYS) {
    config[key] = activeModelId;
  }
  return config as Record<PhaseModelKey, string>;
}

export function applyStrongModel(
  model: string,
  existingConfig: Record<PhaseModelKey, string> | null,
  activeModelId: string,
): Record<PhaseModelKey, string> {
  const base = existingConfig ?? initConfigFromActiveModel(activeModelId);
  const result = { ...base };
  for (const key of STRONG_PHASE_MODEL_KEYS) {
    result[key] = model;
  }
  return result;
}

export function applyGeneralPurposeModel(
  model: string,
  existingConfig: Record<PhaseModelKey, string> | null,
  activeModelId: string,
): Record<PhaseModelKey, string> {
  const base = existingConfig ?? initConfigFromActiveModel(activeModelId);
  const result = { ...base };
  for (const key of GENERAL_PURPOSE_PHASE_MODEL_KEYS) {
    result[key] = model;
  }
  return result;
}

// -- Confirmation component for reset action --

class ResetConfirmComponent implements Component {
  constructor(
    private readonly theme: Theme,
    private readonly onConfirm: () => void,
    private readonly onCancel: () => void,
  ) {}

  render(_width: number): string[] {
    return [
      this.theme.bold(this.theme.fg("accent", "Reset all model overrides to active model?")),
      "",
      this.theme.fg("muted", "  This will set all 20 phase model cells to the current active model."),
      "",
      this.theme.fg("dim", "  Enter to confirm · Escape to cancel"),
    ];
  }

  handleInput(data: string): void {
    if (data === "\r" || data === "\n") {
      this.onConfirm();
    } else if (data === "\x1b") {
      this.onCancel();
    }
  }

  invalidate(): void {}
}

function padRight(text: string, width: number): string {
  const padding = Math.max(0, width - visibleWidth(text));
  return text + " ".repeat(padding);
}

function renderCell(theme: Theme, text: string, width: number, selected: boolean, strong: boolean): string {
  const innerWidth = Math.max(1, width - 2);
  const clipped = truncateToWidth(text, innerWidth, "");
  const padded = padRight(clipped, innerWidth);
  const raw = ` ${padded} `;

  if (selected) return theme.inverse(raw);
  if (strong) return theme.fg("accent", raw);
  return raw;
}

function cellDisplay(modelId: string | undefined, activeModelId: string | undefined): string {
  if (modelId === undefined) {
    return activeModelId ? `inherit:${activeModelId}` : "inherit:active";
  }
  return modelId;
}

type SelectionZone = "quick" | "grid";

// -- Create model selection component --

export function createModelSelectionComponent(
  tui: TUI,
  theme: Theme,
  modelRegistry: ModelRegistry,
  activeModelId: string | undefined,
  initialConfig: Record<PhaseModelKey, string> | null,
  onConfigChange: (newConfig: Record<PhaseModelKey, string> | null) => void,
  onSaveError: (error: unknown) => void,
  onClose: () => void,
): Component {
  const fallbackActive = activeModelId ?? "(active model)";
  const configRef: { value: Record<PhaseModelKey, string> | null } = { value: initialConfig };

  const quickItems = [
    "Reset to active",
    `Set strong (${STRONG_PHASE_MODEL_KEYS.size})`,
    `Set general (${GENERAL_PURPOSE_PHASE_MODEL_KEYS.length})`,
  ] as const;

  let zone: SelectionZone = "quick";
  let quickIndex = 0;
  let rowIndex = 0;
  let colIndex = 0;
  let overlay: Component | null = null;

  function requestRender(): void {
    tui.requestRender();
  }

  async function persistAndNotify(newConfig: Record<PhaseModelKey, string> | null): Promise<boolean> {
    const previous = configRef.value;
    try {
      await savePhaseModelConfig(newConfig);
      configRef.value = newConfig;
      onConfigChange(newConfig);
      return true;
    } catch (error) {
      configRef.value = previous;
      onSaveError(error);
      return false;
    }
  }

  function makeModelSelector(
    currentModelId: string | undefined,
    onSelect: (modelId: string) => void,
    onCancel: () => void,
  ): Component {
    const available = modelRegistry.getAvailable();
    const currentModel = currentModelId
      ? available.find((m) => `${m.provider}/${m.id}` === currentModelId)
      : available.find((m) => `${m.provider}/${m.id}` === activeModelId);

    const sm = SettingsManager.inMemory();

    return new ModelSelectorComponent(
      tui,
      currentModel,
      sm,
      modelRegistry,
      [],
      (model) => onSelect(`${model.provider}/${model.id}`),
      onCancel,
    );
  }

  function closeOverlay(): void {
    overlay = null;
    requestRender();
  }

  function openResetConfirm(): void {
    overlay = new ResetConfirmComponent(
      theme,
      () => {
        const resetConfig = initConfigFromActiveModel(fallbackActive);
        void persistAndNotify(resetConfig).finally(() => closeOverlay());
      },
      () => closeOverlay(),
    );
    requestRender();
  }

  function openStrongSelector(): void {
    const strongSample = Array.from(STRONG_PHASE_MODEL_KEYS)[0];
    const currentId = configRef.value?.[strongSample];

    overlay = makeModelSelector(
      currentId,
      (modelId) => {
        const newConfig = applyStrongModel(modelId, configRef.value, fallbackActive);
        void persistAndNotify(newConfig).finally(() => closeOverlay());
      },
      () => closeOverlay(),
    );
    requestRender();
  }

  function openGeneralSelector(): void {
    const gpSample = GENERAL_PURPOSE_PHASE_MODEL_KEYS[0];
    const currentId = configRef.value?.[gpSample];

    overlay = makeModelSelector(
      currentId,
      (modelId) => {
        const newConfig = applyGeneralPurposeModel(modelId, configRef.value, fallbackActive);
        void persistAndNotify(newConfig).finally(() => closeOverlay());
      },
      () => closeOverlay(),
    );
    requestRender();
  }

  function openCellSelector(): void {
    const row = PHASE_ROWS[rowIndex] as PhaseRow;
    const subPhase = SUB_PHASES[colIndex];
    const key = buildPhaseModelKey(row, subPhase);
    const currentId = configRef.value?.[key];

    overlay = makeModelSelector(
      currentId,
      (modelId) => {
        const base = configRef.value ?? initConfigFromActiveModel(fallbackActive);
        const newConfig = { ...base, [key]: modelId };
        void persistAndNotify(newConfig).finally(() => closeOverlay());
      },
      () => closeOverlay(),
    );
    requestRender();
  }

  function activateSelection(): void {
    if (zone === "quick") {
      if (quickIndex === 0) {
        openResetConfirm();
      } else if (quickIndex === 1) {
        openStrongSelector();
      } else {
        openGeneralSelector();
      }
      return;
    }

    openCellSelector();
  }

  function moveUp(): void {
    if (zone === "quick") return;
    if (rowIndex === 0) {
      zone = "quick";
      return;
    }
    rowIndex -= 1;
  }

  function moveDown(): void {
    if (zone === "quick") {
      zone = "grid";
      rowIndex = 0;
      return;
    }

    if (rowIndex === PHASE_ROWS.length - 1) {
      rowIndex = 0;
      return;
    }

    rowIndex += 1;
  }

  function moveLeft(): void {
    if (zone === "quick") {
      quickIndex = quickIndex === 0 ? quickItems.length - 1 : quickIndex - 1;
      return;
    }

    colIndex = colIndex === 0 ? SUB_PHASES.length - 1 : colIndex - 1;
  }

  function moveRight(): void {
    if (zone === "quick") {
      quickIndex = quickIndex === quickItems.length - 1 ? 0 : quickIndex + 1;
      return;
    }

    colIndex = colIndex === SUB_PHASES.length - 1 ? 0 : colIndex + 1;
  }

  function renderMain(width: number): string[] {
    const lines: string[] = [];

    lines.push(theme.bold(theme.fg("accent", "Koan / Config / Model selection")));
    lines.push(theme.fg("muted", `Fallback active model: ${fallbackActive}`));
    lines.push("");

    const quick = quickItems
      .map((label, i) => {
        const block = ` ${label} `;
        if (zone === "quick" && quickIndex === i) return theme.inverse(block);
        return theme.fg("muted", block);
      })
      .join("  ");

    lines.push(`Quick-set: ${quick}`);
    lines.push("");

    const sep = " | ";
    const sepWidth = visibleWidth(sep);
    const phaseColWidth = 12;
    const available = Math.max(24, width - phaseColWidth - sepWidth * 4);
    const modelColWidth = Math.max(12, Math.floor(available / 4));

    const headerCells = [
      renderCell(theme, "phase", phaseColWidth, false, false),
      ...SUB_PHASES.map((sub) => renderCell(theme, sub, modelColWidth, false, false)),
    ];
    lines.push(headerCells.join(sep));
    lines.push("-".repeat(Math.max(10, Math.min(width, visibleWidth(headerCells.join(sep))))));

    for (let r = 0; r < PHASE_ROWS.length; r += 1) {
      const row = PHASE_ROWS[r] as PhaseRow;
      const rowCells: string[] = [renderCell(theme, row, phaseColWidth, false, false)];

      for (let c = 0; c < SUB_PHASES.length; c += 1) {
        const sub = SUB_PHASES[c];
        const key = buildPhaseModelKey(row, sub);
        const model = configRef.value?.[key];
        const display = cellDisplay(model, activeModelId);
        const selected = zone === "grid" && rowIndex === r && colIndex === c;
        const strong = STRONG_PHASE_MODEL_KEYS.has(key);
        rowCells.push(renderCell(theme, display, modelColWidth, selected, strong));
      }

      lines.push(truncateToWidth(rowCells.join(sep), width));
    }

    lines.push("");
    lines.push(theme.fg("dim", "★ strong cell"));
    lines.push(theme.fg("dim", "↑↓ move row/section · ←→ move column/quick-set · Enter select · Esc back"));

    return lines;
  }

  return {
    render: (width) => {
      if (overlay) return overlay.render(width);
      return renderMain(width);
    },
    handleInput: (data) => {
      if (overlay) {
        overlay.handleInput?.(data);
        return;
      }

      const kb = getEditorKeybindings();

      if (kb.matches(data, "selectCancel")) {
        onClose();
        return;
      }
      if (kb.matches(data, "selectConfirm") || data === " ") {
        activateSelection();
        return;
      }
      if (kb.matches(data, "selectUp")) {
        moveUp();
        requestRender();
        return;
      }
      if (kb.matches(data, "selectDown")) {
        moveDown();
        requestRender();
        return;
      }
      if (kb.matches(data, "cursorLeft")) {
        moveLeft();
        requestRender();
        return;
      }
      if (kb.matches(data, "cursorRight")) {
        moveRight();
        requestRender();
      }
    },
    invalidate: () => {
      overlay?.invalidate?.();
    },
  };
}
