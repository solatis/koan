// Model selection UI for /koan config.
// Renders a 3-row tier table (strong / standard / cheap).
// Enter opens an inline ModelSelectorComponent for the selected tier.
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

import { ALL_MODEL_TIERS, type ModelTier } from "../../model-phase.js";
import { saveModelTierConfig } from "../../model-config.js";
import type { ModelTierConfig } from "../../model-config.js";

function padRight(text: string, width: number): string {
  const padding = Math.max(0, width - visibleWidth(text));
  return text + " ".repeat(padding);
}

function renderCell(theme: Theme, text: string, width: number, selected: boolean): string {
  const innerWidth = Math.max(1, width - 2);
  const clipped = truncateToWidth(text, innerWidth, "");
  const padded = padRight(clipped, innerWidth);
  const raw = ` ${padded} `;
  if (selected) return theme.inverse(raw);
  return raw;
}

function cellDisplay(modelId: string | undefined, activeModelId: string | undefined): string {
  if (modelId === undefined) {
    return activeModelId ? `inherit:${activeModelId}` : "inherit:active";
  }
  return modelId;
}

export function createModelSelectionComponent(
  tui: TUI,
  theme: Theme,
  modelRegistry: ModelRegistry,
  activeModelId: string | undefined,
  initialConfig: ModelTierConfig | null,
  onConfigChange: (newConfig: ModelTierConfig | null) => void,
  onSaveError: (error: unknown) => void,
  onClose: () => void,
): Component {
  const fallbackActive = activeModelId ?? "(active model)";
  const configRef: { value: ModelTierConfig | null } = { value: initialConfig };

  let rowIndex = 0;
  let overlay: Component | null = null;

  function requestRender(): void {
    tui.requestRender();
  }

  async function persistAndNotify(newConfig: ModelTierConfig | null): Promise<boolean> {
    const previous = configRef.value;
    try {
      await saveModelTierConfig(newConfig as ModelTierConfig);
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

  function openTierSelector(): void {
    const tier = ALL_MODEL_TIERS[rowIndex] as ModelTier;
    const currentId = configRef.value?.[tier];

    overlay = makeModelSelector(
      currentId,
      (modelId) => {
        const base: ModelTierConfig = configRef.value ?? {
          strong: fallbackActive,
          standard: fallbackActive,
          cheap: fallbackActive,
        };
        const newConfig: ModelTierConfig = { ...base, [tier]: modelId };
        void persistAndNotify(newConfig).finally(() => closeOverlay());
      },
      () => closeOverlay(),
    );
    requestRender();
  }

  function moveUp(): void {
    if (rowIndex > 0) rowIndex -= 1;
  }

  function moveDown(): void {
    if (rowIndex < ALL_MODEL_TIERS.length - 1) rowIndex += 1;
  }

  function renderMain(width: number): string[] {
    const lines: string[] = [];

    lines.push(theme.bold(theme.fg("accent", "Koan / Config / Model selection")));
    lines.push(theme.fg("muted", `Fallback active model: ${fallbackActive}`));
    lines.push("");

    const tierColWidth = 12;
    const sep = " | ";
    const sepWidth = visibleWidth(sep);
    const modelColWidth = Math.max(20, width - tierColWidth - sepWidth);

    const headerCells = [
      renderCell(theme, "tier", tierColWidth, false),
      renderCell(theme, "model", modelColWidth, false),
    ];
    lines.push(headerCells.join(sep));
    lines.push("-".repeat(Math.max(10, Math.min(width, visibleWidth(headerCells.join(sep))))));

    for (let r = 0; r < ALL_MODEL_TIERS.length; r += 1) {
      const tier = ALL_MODEL_TIERS[r] as ModelTier;
      const model = configRef.value?.[tier];
      const display = cellDisplay(model, activeModelId);
      const selected = rowIndex === r;

      const row = [
        renderCell(theme, tier, tierColWidth, false),
        renderCell(theme, display, modelColWidth, selected),
      ];
      lines.push(truncateToWidth(row.join(sep), width));
    }

    lines.push("");
    lines.push(theme.fg("dim", "↑↓ move row · Enter select model · Esc back"));

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
        openTierSelector();
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
      }
    },
    invalidate: () => {
      overlay?.invalidate?.();
    },
  };
}
