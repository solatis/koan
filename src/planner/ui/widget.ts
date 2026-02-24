// Persistent TUI widget for koan workflow progress.
// Full-width background canvas (toolPendingBg) via component factory.
// Hash-based change detection + 1s unref'd timer for elapsed updates.
// Created by session.plan(), destroyed in onContextComplete finally block.
//
// Uses setWidget(key, factory) to get render(width) for full-width bg.
// Content stays at a fixed CONTENT width; background fills terminal edge.

import type { ExtensionUIContext } from "@mariozechner/pi-coding-agent";
import type { Theme, ThemeColor } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";

// -- Types --

export type PhaseStatus = "pending" | "running" | "completed" | "failed";

interface PhaseEntry {
  key: string;
  label: string;
  status: PhaseStatus;
}

interface WidgetState {
  planId: string;
  phases: PhaseEntry[];
  activeIndex: number; // 0-based; -1 when done
  step: string;
  activity: string;
  startedAt: number;
}

export interface WidgetUpdate {
  activeIndex?: number;
  step?: string;
  activity?: string;
  phaseStatus?: { index: number; status: PhaseStatus };
}

// -- Constants --

const WIDGET_KEY = "koan";
const PAD = 2; // horizontal padding each side

const PHASES: ReadonlyArray<{ key: string; label: string }> = [
  { key: "ctx", label: "Gathering context" },
  { key: "design", label: "Designing plan" },
  { key: "code", label: "Planning code" },
  { key: "docs", label: "Planning docs" },
  { key: "exec-c", label: "Executing code" },
  { key: "exec-d", label: "Executing docs" },
];

const STATUS_ICON: Record<PhaseStatus, string> = {
  pending: "[  ]",
  running: "[>>]",
  completed: "[OK]",
  failed: "[!!]",
};

const ICON_COLOR: Record<PhaseStatus, ThemeColor> = {
  pending: "muted",
  running: "warning",
  completed: "success",
  failed: "error",
};

// -- Canvas primitive --
// Content width adapts to terminal; background fills edge to edge.

function contentWidth(termWidth: number): number {
  return Math.max(40, termWidth - PAD * 2);
}

function canvasLine(content: string, termWidth: number, theme: Theme): string {
  const cw = contentWidth(termWidth);
  const inner = truncateToWidth(content, cw, "...", true);
  const line = " ".repeat(PAD) + inner + " ".repeat(PAD);
  return theme.bg("toolPendingBg", line);
}

// -- Helpers --

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

function rightAlign(left: string, right: string, width: number): string {
  const gap = Math.max(1, width - visibleWidth(left) - visibleWidth(right));
  return `${left}${" ".repeat(gap)}${right}`;
}

// Pure render: (state, theme, termWidth) -> 7 lines. No side effects.
function render(state: WidgetState, theme: Theme, termWidth: number): string[] {
  const c = (s: string) => canvasLine(s, termWidth, theme);
  const cw = contentWidth(termWidth);

  // Header: koan [N/6] label ... elapsed
  const idx = state.activeIndex;
  const label = idx >= 0 ? state.phases[idx].label : "done";
  const num = idx >= 0 ? idx + 1 : 6;
  const left = `${theme.bold(theme.fg("accent", "koan"))} [${num}/6] ${label}`;
  const elapsed = theme.fg("dim", formatElapsed(Date.now() - state.startedAt));
  const header = rightAlign(left, elapsed, cw);

  // Plan ID
  const planId = theme.fg("dim", state.planId);

  // Phase bar
  const phaseBar = state.phases
    .map((p) => `${theme.fg(ICON_COLOR[p.status], STATUS_ICON[p.status])} ${p.key}`)
    .join("  ");

  // Step + activity
  const step = state.step ? theme.fg("dim", state.step) : "";
  const act = state.activity ? theme.fg("muted", ` > ${state.activity}`) : "";
  const detail = truncateToWidth(step + act, cw, "...");

  return [
    c(""),       // top padding
    c(header),
    c(planId),
    c(""),       // separator
    c(phaseBar),
    c(detail),
    c(""),       // bottom padding
  ];
}

// -- WidgetController --

export class WidgetController {
  private state: WidgetState;
  private lastHash = "";
  private timer: ReturnType<typeof setInterval>;
  private ui: ExtensionUIContext;

  constructor(ui: ExtensionUIContext, planId: string) {
    this.ui = ui;
    this.state = {
      planId,
      phases: PHASES.map((p) => ({ key: p.key, label: p.label, status: "pending" as PhaseStatus })),
      activeIndex: 0,
      step: "",
      activity: "",
      startedAt: Date.now(),
    };
    this.state.phases[0].status = "running";

    this.timer = setInterval(() => this.doRender(), 1000);
    this.timer.unref();

    this.doRender();
  }

  update(patch: WidgetUpdate): void {
    if (patch.phaseStatus !== undefined) {
      const { index, status } = patch.phaseStatus;
      if (index >= 0 && index < this.state.phases.length) {
        this.state.phases[index].status = status;
      }
    }
    if (patch.activeIndex !== undefined) {
      this.state.activeIndex = patch.activeIndex;
      const ai = patch.activeIndex;
      if (ai >= 0 && ai < this.state.phases.length && this.state.phases[ai].status === "pending") {
        this.state.phases[ai].status = "running";
      }
    }
    if (patch.step !== undefined) {
      this.state.step = patch.step;
    }
    if (patch.activity !== undefined) {
      this.state.activity = patch.activity;
    }
    this.doRender();
  }

  destroy(): void {
    clearInterval(this.timer);
    this.ui.setWidget(WIDGET_KEY, undefined);
  }

  private doRender(): void {
    // Capture state snapshot for the factory closure
    const state = { ...this.state, phases: this.state.phases.map((p) => ({ ...p })) };
    const theme = this.ui.theme;

    // Hash check: skip setWidget if content unchanged (ignoring width)
    const hashLines = render(state, theme, 0);
    const hash = hashLines.join("\n");
    if (hash === this.lastHash) return;
    this.lastHash = hash;

    // Component factory: Pi calls render(width) with actual terminal width
    this.ui.setWidget(WIDGET_KEY, (_tui, th) => ({
      render: (width: number) => render(state, th, width),
      invalidate: () => {},
    }));
  }
}
