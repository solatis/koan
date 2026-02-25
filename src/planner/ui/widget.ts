// Persistent TUI widget for koan workflow progress.
// Full-width background canvas (toolPendingBg) via component factory.
// Hash-based change detection + 1s unref'd timer for elapsed updates.
// Created by session.plan(), destroyed in onContextComplete finally block.
//
// Layout and styling reference: docs/planning-widget.md and the
// corresponding execution widget design deck selections (Stacked Modular
// Cards canvas + Vertical Timeline Rail).

import type { ExtensionUIContext } from "@mariozechner/pi-coding-agent";
import type { Theme, ThemeColor } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@mariozechner/pi-tui";

// -- Types --

export type PhaseStatus = "pending" | "running" | "completed" | "failed";

interface PhaseEntry {
  key: string;
  label: string;
  detail: string;
  status: PhaseStatus;
}

type WidgetMode = "planning" | "execution";

type QRMode = "initial" | "fix";
type QRPhase = "idle" | "execute" | "decompose" | "verify" | "done";

interface WidgetState {
  mode: WidgetMode;
  planId: string;
  phases: PhaseEntry[];
  activeIndex: number; // 0-based; -1 when done
  step: string;
  activity: string;
  startedAt: number;
  logLines: string[];
  qrIteration: number | null;
  qrIterationsMax: number | null;
  qrMode: QRMode | null;
  qrPhase: QRPhase;
}

export interface WidgetUpdate {
  activeIndex?: number;
  step?: string;
  activity?: string;
  phaseStatus?: { index: number; status: PhaseStatus };
  mode?: WidgetMode;
  logLines?: readonly string[];
  qrIteration?: number | null;
  qrIterationsMax?: number | null;
  qrMode?: QRMode | null;
  qrPhase?: QRPhase;
}

// -- Constants --

const WIDGET_KEY = "koan";
const PAD = 2; // horizontal canvas padding each side
const CARD_MARGIN = 2; // left margin before card borders
const LOG_LINES = 5;

const BODY_INDENT = "    ";

const PLANNING_PHASES: ReadonlyArray<{ key: string; label: string; detail: string }> = [
  { key: "ctx", label: "Context", detail: "Gathering context" },
  { key: "design", label: "Plan design", detail: "Designing plan" },
  { key: "code", label: "Plan code", detail: "Creating code plan" },
  { key: "docs", label: "Plan docs", detail: "Documenting plan" },
];

const STATUS_ICON: Record<PhaseStatus, string> = {
  pending: "○",
  running: "●",
  completed: "●",
  failed: "✖",
};

const STATUS_COLOR: Record<PhaseStatus, ThemeColor> = {
  pending: "muted",
  running: "accent",
  completed: "dim",
  failed: "error",
};

const STATUS_TAG: Record<PhaseStatus, string> = {
  pending: "upcoming",
  running: "current",
  completed: "done",
  failed: "failed",
};

const LOG_PLACEHOLDER = "No recent log entries";
const TIMELINE_MIN_WIDTH = 16;
const TIMELINE_MAX_WIDTH = 28;
const CONNECTOR = "│";

interface BorderStyle {
  topLeft: string;
  topRight: string;
  bottomLeft: string;
  bottomRight: string;
  horizontal: string;
  vertical: string;
}

const BORDER_SOLID: BorderStyle = {
  topLeft: "┌",
  topRight: "┐",
  bottomLeft: "└",
  bottomRight: "┘",
  horizontal: "─",
  vertical: "│",
};

const BORDER_SUBTLE: BorderStyle = {
  topLeft: "╭",
  topRight: "╮",
  bottomLeft: "╰",
  bottomRight: "╯",
  horizontal: "─",
  vertical: "│",
};

// -- Canvas primitive --
// Content width adapts to terminal; background fills edge to edge.

function contentWidth(termWidth: number): number {
  return Math.max(40, termWidth - PAD * 2);
}

function canvasLine(content: string, termWidth: number, theme: Theme): string {
  const cw = contentWidth(termWidth);
  const inner = clampToWidth(content, cw);
  const line = " ".repeat(PAD) + inner + " ".repeat(PAD);
  return theme.bg("toolPendingBg", line);
}

// -- Helpers --

function clampToWidth(text: string, width: number, ellipsis = ""): string {
  const truncated = truncateToWidth(text, width, ellipsis === "" ? "" : ellipsis, false);
  const visible = visibleWidth(truncated);
  if (visible >= width) {
    return truncated;
  }
  return truncated + " ".repeat(width - visible);
}

function indentLines(lines: string[], width: number, indent = BODY_INDENT): string[] {
  if (!indent) {
    return lines.map((line) => clampToWidth(line, width));
  }
  const indentWidth = visibleWidth(indent);
  const available = Math.max(0, width - indentWidth);
  return lines.map((line) => indent + clampToWidth(line, available));
}

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

function activePhase(state: WidgetState): PhaseEntry | null {
  if (state.activeIndex < 0) return null;
  return state.phases[state.activeIndex] ?? null;
}

function normalizeLogLines(lines: readonly string[] | undefined): string[] {
  if (!lines || lines.length === 0) return [];
  const trimmed = lines.map((line) => line.replace(/\s+$/u, ""));
  return trimmed.slice(-LOG_LINES);
}

function phaseChipLabel(phase: PhaseEntry, index: number, state: WidgetState, theme: Theme): string {
  const label = `┃ ${phase.label} ┃`;
  if (index === state.activeIndex) {
    return theme.bold(theme.fg("accent", label));
  }
  if (phase.status === "completed") {
    return theme.bold(theme.fg("muted", label));
  }
  if (phase.status === "failed") {
    return theme.fg("error", label);
  }
  return theme.fg("muted", label);
}

function renderPhaseChips(state: WidgetState, theme: Theme, width: number): string {
  const chips = state.phases.map((phase, index) => phaseChipLabel(phase, index, state, theme));
  return clampToWidth(chips.join("    "), width, "…");
}

function renderTimelineLines(state: WidgetState, theme: Theme, width: number): string[] {
  const lines: string[] = [];
  const total = state.phases.length;

  state.phases.forEach((phase, index) => {
    const isActive = index === state.activeIndex;
    const color = STATUS_COLOR[phase.status];
    const iconBase = STATUS_ICON[phase.status];
    const icon = isActive
      ? theme.bold(theme.fg("accent", iconBase))
      : theme.fg(color, iconBase);

    const labelColor: ThemeColor = phase.status === "completed"
      ? "dim"
      : isActive
        ? "accent"
        : phase.status === "failed"
          ? "error"
          : "muted";

    const emphasize = isActive || phase.status === "completed";
    const label = emphasize
      ? theme.bold(theme.fg(labelColor, phase.label))
      : theme.fg(labelColor, phase.label);

    lines.push(clampToWidth(`${icon} ${label}`, width, "…"));

    const connector = index < total - 1 ? theme.fg("muted", CONNECTOR) : " ";
    lines.push(clampToWidth(`${connector}      ${theme.fg("muted", STATUS_TAG[phase.status].toUpperCase())}`, width, "…"));

    if (index < total - 1) {
      lines.push(clampToWidth(`${theme.fg("muted", CONNECTOR)}      `, width));
    }
  });

  return lines;
}

function upcomingSummary(state: WidgetState): string {
  const remaining = state.activeIndex < 0
    ? []
    : state.phases.slice(state.activeIndex + 1).filter((p) => p.status !== "failed");
  if (state.activeIndex < 0) return "Planning complete";
  if (remaining.length === 0) return "Final step in progress";
  const labels = remaining.map((p) => p.label).join(" → ");
  return `Upcoming: ${labels}`;
}

function renderQRStatusWidget(state: WidgetState, theme: Theme, width: number): string[] {
  if (state.qrIteration === null || state.qrPhase === "idle") {
    return [];
  }

  const innerWidth = Math.max(0, width - 2);
  const iterationTotal = state.qrIterationsMax ? ` / ${state.qrIterationsMax}` : "";
  const modeLabel = state.qrMode === "fix" ? "Fix" : "Initial";

  const headerLeft = theme.bold(theme.fg("accent", "Quality review"));
  const headerRightParts = [`Iter ${state.qrIteration}${iterationTotal}`];
  if (modeLabel) headerRightParts.push(modeLabel);
  const headerRight = theme.fg("dim", headerRightParts.join(" · "));

  const phaseEntries: Array<{ key: Exclude<QRPhase, "idle" | "done">; label: string }> = [
    { key: "execute", label: state.qrMode === "fix" ? "Execute (fix)" : "Execute" },
    { key: "decompose", label: "QR decompose" },
    { key: "verify", label: "QR verify" },
  ];

  let currentIndex = phaseEntries.findIndex((entry) => entry.key === state.qrPhase);
  if (state.qrPhase === "done") {
    currentIndex = phaseEntries.length;
  }

  const segments = phaseEntries.map((entry, index) => {
    if (index < currentIndex) {
      return theme.bold(theme.fg("dim", `${entry.label} ✓`));
    }
    if (index === currentIndex) {
      return theme.bold(theme.fg("accent", entry.label));
    }
    return theme.fg("muted", entry.label);
  });

  const separator = theme.fg("muted", " → ");
  const stageLine = clampToWidth(segments.join(separator), innerWidth, "…");

  const description = (() => {
    if (state.qrPhase === "execute") {
      return state.qrMode === "fix"
        ? "Fix-mode architect applies QR feedback."
        : "Initial execution to gather plan context.";
    }
    if (state.qrPhase === "decompose") {
      return state.qrIteration && state.qrIteration > 1
        ? "Re-decomposing updates into review items."
        : "Deriving QR checklist from the current plan.";
    }
    if (state.qrPhase === "verify") {
      return "Massively parallel reviewers scoring QR items.";
    }
    if (state.qrPhase === "done") {
      return "Quality review loop complete.";
    }
    return "";
  })();

  const body: string[] = [];
  body.push(stageLine);
  if (description) {
    body.push(clampToWidth(theme.fg("muted", description), innerWidth, "…"));
  }

  return renderBox(headerLeft, headerRight, body, width, theme, BORDER_SUBTLE);
}

interface DetailSections {
  core: string[];
  footer: string[];
}

function buildDetailSections(state: WidgetState, theme: Theme, width: number): DetailSections {
  const core: string[] = [];
  const footer: string[] = [];
  const blank = clampToWidth("", width);

  const active = activePhase(state);
  const stepTitle = state.step || active?.detail || active?.label || "Awaiting step";
  core.push(clampToWidth(theme.bold(theme.fg("accent", stepTitle)), width, "…"));

  if (state.activity) {
    const activityLines = wrapTextWithAnsi(theme.fg("muted", state.activity), width);
    for (const line of activityLines) {
      core.push(clampToWidth(line, width));
    }
  }

  const qrWidget = renderQRStatusWidget(state, theme, width);
  if (qrWidget.length > 0) {
    if (core.length > 0 && core[core.length - 1].trim() !== "") {
      core.push(blank);
    }
    core.push(...qrWidget.map((line) => clampToWidth(line, width)));
  }

  if (active) {
    footer.push(...wrapTextWithAnsi(theme.fg("dim", `Phase ${state.activeIndex + 1}/${state.phases.length}`), width).map((line) => clampToWidth(line, width, "…")));
    footer.push(...wrapTextWithAnsi(theme.fg("dim", `Plan · ${state.planId}`), width).map((line) => clampToWidth(line, width, "…")));
  }

  const summary = upcomingSummary(state);
  if (summary) {
    footer.push(...wrapTextWithAnsi(theme.fg("muted", summary), width).map((line) => clampToWidth(line, width, "…")));
  }

  return { core, footer };
}

function layoutDetailColumn(sections: DetailSections, width: number, targetRows: number): string[] {
  const blank = clampToWidth("", width);
  const lines = [...sections.core];

  if (sections.footer.length > 0) {
    if (lines.length === 0 || lines[lines.length - 1].trim() !== "") {
      lines.push(blank);
    }
  }

  const used = lines.length + sections.footer.length;
  const goal = Math.max(targetRows, used);

  while (lines.length < goal - sections.footer.length) {
    lines.push(blank);
  }

  if (sections.footer.length === 0) {
    return lines;
  }

  return [...lines, ...sections.footer];
}

function renderBox(
  titleLeft: string,
  titleRight: string,
  body: string[],
  width: number,
  theme: Theme,
  border: BorderStyle = BORDER_SOLID,
): string[] {
  const innerWidth = Math.max(0, width - 2);
  const left = visibleWidth(titleLeft) > innerWidth ? truncateToWidth(titleLeft, innerWidth, "", false) : titleLeft;
  const right = visibleWidth(titleRight) > innerWidth ? truncateToWidth(titleRight, innerWidth, "", false) : titleRight;
  const headerContent = rightAlign(left, right, innerWidth);

  const top = `${border.topLeft}${clampToWidth(headerContent, innerWidth)}${border.topRight}`;
  const bottom = `${border.bottomLeft}${clampToWidth(border.horizontal.repeat(innerWidth), innerWidth)}${border.bottomRight}`;

  const content = body.map((line) => `${border.vertical}${clampToWidth(line, innerWidth)}${border.vertical}`);
  return [top, ...content, bottom];
}

function renderPlanningCard(state: WidgetState, theme: Theme, width: number): string[] {
  const elapsed = theme.fg("dim", formatElapsed(Date.now() - state.startedAt));
  const innerWidth = Math.max(0, width - 2);
  const indentWidth = visibleWidth(BODY_INDENT);
  const contentWidth = Math.max(0, innerWidth - indentWidth);

  if (innerWidth < 60 || contentWidth < 40) {
    const fallbackContent: string[] = [
      "",
      theme.fg("muted", `Plan · ${state.planId}`),
      "",
      formatStepLine(state, theme),
      formatPhaseTrail(state, theme, contentWidth),
    ];
    const detail = formatDetail(state, theme, contentWidth);
    if (detail) fallbackContent.push(detail);
    fallbackContent.push("");

    const body = indentLines(fallbackContent, innerWidth);
    return renderBox(
      `${BODY_INDENT}${theme.bold(theme.fg("accent", "Planning"))}`,
      elapsed,
      body,
      width,
      theme,
    );
  }

  const chipsLine = renderPhaseChips(state, theme, contentWidth);
  const timelineWidth = Math.min(TIMELINE_MAX_WIDTH, Math.max(TIMELINE_MIN_WIDTH, Math.floor(contentWidth * 0.3)));
  const detailWidth = Math.max(14, contentWidth - timelineWidth - 4);

  const timelineLines = renderTimelineLines(state, theme, timelineWidth);
  const detailSections = buildDetailSections(state, theme, detailWidth);
  const detailLines = layoutDetailColumn(detailSections, detailWidth, timelineLines.length);
  const combined: string[] = [];
  const maxLines = Math.max(timelineLines.length, detailLines.length);

  for (let i = 0; i < maxLines; i++) {
    const left = timelineLines[i] ?? "";
    const right = detailLines[i] ?? "";
    const composed = `${clampToWidth(left, timelineWidth)}    ${clampToWidth(right, detailWidth)}`;
    combined.push(clampToWidth(composed, contentWidth));
  }

  const body = indentLines(
    [
      "",
      chipsLine,
      "",
      ...combined,
      "",
    ],
    innerWidth,
  );

  return renderBox(
    `${BODY_INDENT}${theme.bold(theme.fg("accent", "Planning Workspace"))}`,
    elapsed,
    body,
    width,
    theme,
  );
}

function renderLogCard(state: WidgetState, theme: Theme, width: number): string[] {
  const innerWidth = Math.max(0, width - 2);
  const raw = state.logLines.length > 0 ? state.logLines.slice(-LOG_LINES) : [LOG_PLACEHOLDER];
  const padded = [...raw];
  while (padded.length < LOG_LINES) padded.push("");

  const lines = padded.map((line) => {
    if (!line) return "";
    return theme.fg("dim", `• ${line}`);
  });

  const body = indentLines(lines, innerWidth);
  return renderBox(
    `${BODY_INDENT}${theme.bold(theme.fg("accent", "Latest log"))}`,
    "",
    body,
    width,
    theme,
  );
}

function formatPhaseTrail(state: WidgetState, theme: Theme, width: number): string {
  const parts = state.phases.map((phase, index) => {
    const icon = STATUS_ICON[phase.status];
    const color = STATUS_COLOR[phase.status];
    const label = index === state.activeIndex ? theme.bold(phase.label) : phase.label;
    return theme.fg(color, `${icon} ${label}`);
  });
  const trail = parts.join("    ");
  return clampToWidth(trail, width, "…");
}

function formatDetail(state: WidgetState, theme: Theme, width: number): string {
  const step = state.step ? theme.fg("muted", state.step) : "";
  const activity = state.activity ? theme.fg("dim", ` · ${state.activity}`) : "";
  const detail = `${step}${activity}`;
  if (!detail) return "";
  return clampToWidth(detail, width, "…");
}

function formatStepLine(state: WidgetState, theme: Theme): string {
  const total = state.phases.length;
  const active = activePhase(state);
  const stepNumber = state.activeIndex >= 0 ? state.activeIndex + 1 : total;
  const count = theme.fg("muted", `Step ${stepNumber} of ${total}`);
  const label = active
    ? theme.bold(theme.fg("accent", active.label))
    : theme.bold(theme.fg("muted", "Complete"));
  return `${count} ${theme.fg("muted", "·")} ${label}`;
}

// Pure render: (state, theme, termWidth) -> lines. No side effects.
function render(state: WidgetState, theme: Theme, termWidth: number): string[] {
  const c = (s: string) => canvasLine(s, termWidth, theme);
  const cw = contentWidth(termWidth);
  const lines: string[] = [];
  const margin = " ".repeat(CARD_MARGIN);

  lines.push(c(""));
  for (const line of renderPlanningCard(state, theme, cw - CARD_MARGIN)) {
    lines.push(c(margin + line));
  }
  lines.push(c(margin));
  for (const line of renderLogCard(state, theme, cw - CARD_MARGIN)) {
    lines.push(c(margin + line));
  }
  lines.push(c(""));

  return lines;
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
      mode: "planning",
      planId,
      phases: PLANNING_PHASES.map((p) => ({ key: p.key, label: p.label, detail: p.detail, status: "pending" as PhaseStatus })),
      activeIndex: 0,
      step: "",
      activity: "",
      startedAt: Date.now(),
      logLines: [],
      qrIteration: null,
      qrIterationsMax: null,
      qrMode: null,
      qrPhase: "idle",
    };
    this.state.phases[0].status = "running";

    this.timer = setInterval(() => this.doRender(), 1000);
    this.timer.unref();

    this.doRender();
  }

  update(patch: WidgetUpdate): void {
    if (patch.mode !== undefined) {
      this.state.mode = patch.mode;
    }
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
    if (patch.logLines !== undefined) {
      this.state.logLines = normalizeLogLines(patch.logLines);
    }
    if (patch.qrIteration !== undefined) {
      this.state.qrIteration = patch.qrIteration;
    }
    if (patch.qrIterationsMax !== undefined) {
      this.state.qrIterationsMax = patch.qrIterationsMax;
    }
    if (patch.qrMode !== undefined) {
      this.state.qrMode = patch.qrMode;
    }
    if (patch.qrPhase !== undefined) {
      this.state.qrPhase = patch.qrPhase;
    }
    this.doRender();
  }

  destroy(): void {
    clearInterval(this.timer);
    this.ui.setWidget(WIDGET_KEY, undefined);
  }

  private doRender(): void {
    // Capture state snapshot for the factory closure
    const state = {
      ...this.state,
      phases: this.state.phases.map((p) => ({ ...p })),
      logLines: [...this.state.logLines],
    };
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
