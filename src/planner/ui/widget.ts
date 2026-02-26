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
import type { LogLine } from "../lib/audit.js";

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
  logLines: LogLine[];
  qrIteration: number | null;
  qrIterationsMax: number | null;
  qrMode: QRMode | null;
  qrPhase: QRPhase;
  qrDone: number | null;
  qrTotal: number | null;
  qrPass: number | null;
  qrFail: number | null;
  qrTodo: number | null;
}

export interface WidgetUpdate {
  activeIndex?: number;
  step?: string;
  activity?: string;
  phaseStatus?: { index: number; status: PhaseStatus };
  mode?: WidgetMode;
  logLines?: readonly LogLine[];
  qrIteration?: number | null;
  qrIterationsMax?: number | null;
  qrMode?: QRMode | null;
  qrPhase?: QRPhase;
  qrDone?: number | null;
  qrTotal?: number | null;
  qrPass?: number | null;
  qrFail?: number | null;
  qrTodo?: number | null;
}

// -- Constants --

const WIDGET_KEY = "koan";
const PAD = 2; // horizontal canvas padding each side
const CARD_MARGIN = 2; // left margin before card borders
const LOG_LINES = 5;

const BODY_INDENT = "    ";

const PLANNING_PHASES: ReadonlyArray<{ key: string; label: string; detail: string }> = [
  { key: "ctx", label: "Context gathering", detail: "Gathering initial context" },
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
const COLUMN_GAP = 4;

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

interface PlanningColumns {
  innerWidth: number;
  contentWidth: number;
  timelineWidth: number;
  detailWidth: number;
}

function planningColumns(width: number): PlanningColumns {
  const innerWidth = Math.max(0, width - 2);
  const indentWidth = visibleWidth(BODY_INDENT);
  const contentWidth = Math.max(0, innerWidth - indentWidth);
  const timelineWidth = Math.min(TIMELINE_MAX_WIDTH, Math.max(TIMELINE_MIN_WIDTH, Math.floor(contentWidth * 0.3)));
  const detailWidth = Math.max(14, contentWidth - timelineWidth - COLUMN_GAP);
  return { innerWidth, contentWidth, timelineWidth, detailWidth };
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;

  if (h > 0) {
    return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  }

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

function normalizeLogLines(lines: readonly LogLine[] | undefined): LogLine[] {
  if (!lines || lines.length === 0) return [];
  return [...lines].slice(-(LOG_LINES * 2));
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

function shouldShowQR(state: WidgetState): boolean {
  if (state.qrIteration === null) return false;
  const active = activePhase(state);
  if (!active) return false;
  return active.key !== "ctx";
}

type QRTier = "wide" | "medium" | "tight";

const QR_TIER_MEDIUM_WIDTH = 68;
const QR_TIER_TIGHT_WIDTH = 52;
const QR_META_MAX_CHARS = 64;

function qrTier(width: number): QRTier {
  if (width < QR_TIER_TIGHT_WIDTH) return "tight";
  if (width < QR_TIER_MEDIUM_WIDTH) return "medium";
  return "wide";
}

function qrPhaseLabel(phase: QRPhase): string {
  switch (phase) {
    case "idle":
      return "execute";
    case "execute":
      return "execute";
    case "decompose":
      return "decompose";
    case "verify":
      return "verify";
    case "done":
      return "done";
  }
}

function qrPhaseShortLabel(phase: QRPhase): string {
  switch (phase) {
    case "idle":
      return "exec";
    case "execute":
      return "exec";
    case "decompose":
      return "decomp";
    case "verify":
      return "vfy";
    case "done":
      return "done";
  }
}

function firstBudgeted(candidates: string[], budget: number): string {
  for (const c of candidates) {
    if (visibleWidth(c) <= budget) return c;
  }
  const fallback = candidates[candidates.length - 1] ?? "";
  return truncateToWidth(fallback, budget, "…", false);
}

function qrMetaText(state: WidgetState, tier: QRTier, budget: number): string {
  const phase = qrPhaseLabel(state.qrPhase);
  const short = qrPhaseShortLabel(state.qrPhase);
  const modeFull = state.qrMode === "fix" ? "fix" : "initial";
  const modeShort = state.qrMode === "fix" ? "fx" : "in";
  const iter = state.qrIteration ?? 0;
  const iterMax = state.qrIterationsMax ? `/${state.qrIterationsMax}` : "";
  const iterFull = `${iter}${iterMax}`;

  const wide = `phase:${phase} · iter ${iterFull} ${modeFull}`;
  const medium = `${phase} · iter ${iterFull} ${modeFull}`;
  const compact = `${short} · i${iterFull} ${modeFull}`;
  const tight = `${short} i${iterFull} ${modeShort}`;

  const candidates = tier === "wide"
    ? [wide, medium, compact, tight]
    : tier === "medium"
      ? [medium, compact, tight]
      : [compact, tight];

  return firstBudgeted(candidates, budget);
}

interface QRCounterValues {
  done: string;
  pass: string;
  fail: string;
  todo: string;
}

function qrCounterValues(state: WidgetState): QRCounterValues {
  const meaningful = (state.qrPhase === "verify" || state.qrPhase === "done") && state.qrTotal !== null;
  if (!meaningful || state.qrTotal === null) {
    return { done: "-/-", pass: "-", fail: "-", todo: "-" };
  }

  return {
    done: `${state.qrDone ?? 0}/${state.qrTotal}`,
    pass: String(state.qrPass ?? 0),
    fail: String(state.qrFail ?? 0),
    todo: String(state.qrTodo ?? 0),
  };
}

function renderQRCounterLine(state: WidgetState, theme: Theme, tier: QRTier, width: number, budget: number): string {
  const values = qrCounterValues(state);

  const labelSets = tier === "wide"
    ? [
      { done: "done", pass: "pass", fail: "fail", todo: "todo" },
      { done: "d", pass: "p", fail: "f", todo: "t" },
    ]
    : [{ done: "d", pass: "p", fail: "f", todo: "t" }];

  const render = (labels: { done: string; pass: string; fail: string; todo: string }) => [
    `${theme.fg("muted", `${labels.done}:`)}${theme.fg("dim", values.done)}`,
    `${theme.fg("muted", `${labels.pass}:`)}${theme.fg("accent", values.pass)}`,
    `${theme.fg("muted", `${labels.fail}:`)}${theme.bold(theme.fg("error", values.fail))}`,
    `${theme.fg("muted", `${labels.todo}:`)}${theme.fg("muted", values.todo)}`,
  ].join(" ");

  const candidates = labelSets.map(render);
  const selected = firstBudgeted(candidates, budget);
  return clampToWidth(selected, width, "…");
}

function renderQRStatusSection(state: WidgetState, theme: Theme, width: number): string[] {
  if (!shouldShowQR(state)) {
    return [];
  }

  const tier = qrTier(width);
  const budget = Math.min(width, QR_META_MAX_CHARS);

  const headerMeta = qrMetaText(state, tier, budget);
  const header = clampToWidth(
    `${theme.bold(theme.fg("accent", "QR"))} ${theme.fg("muted", "|")} ${theme.fg("dim", headerMeta)}`,
    width,
    "…",
  );

  const phaseEntries: Array<{ key: Exclude<QRPhase, "idle" | "done">; label: string }> = tier === "wide"
    ? [
      { key: "execute", label: state.qrMode === "fix" ? "Execute (fix)" : "Execute" },
      { key: "decompose", label: "QR decompose" },
      { key: "verify", label: "QR verify" },
    ]
    : tier === "medium"
      ? [
        { key: "execute", label: state.qrMode === "fix" ? "Exec(fix)" : "Exec" },
        { key: "decompose", label: "Decomp" },
        { key: "verify", label: "Verify" },
      ]
      : [
        { key: "execute", label: "X" },
        { key: "decompose", label: "D" },
        { key: "verify", label: "V" },
      ];

  const effectivePhase: Exclude<QRPhase, "idle"> = state.qrPhase === "idle" ? "execute" : state.qrPhase;
  let currentIndex = phaseEntries.findIndex((entry) => entry.key === effectivePhase);
  if (effectivePhase === "done") {
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

  const rail = clampToWidth(segments.join(theme.fg("muted", " → ")), width, "…");
  const counters = renderQRCounterLine(state, theme, tier, width, budget);
  const divider = clampToWidth(theme.fg("muted", "─".repeat(width)), width);

  return [header, rail, counters, divider];
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
  core.push(clampToWidth(theme.fg("dim", "Current step"), width));
  core.push(clampToWidth(theme.bold(theme.fg("accent", stepTitle)), width, "…"));

  if (state.activity) {
    const activityLines = wrapTextWithAnsi(theme.fg("muted", state.activity), width);
    for (const line of activityLines) {
      core.push(clampToWidth(line, width));
    }
  }

  const qrSection = renderQRStatusSection(state, theme, width);
  if (qrSection.length > 0) {
    if (core.length > 0 && core[core.length - 1].trim() !== "") {
      core.push(blank);
    }
    core.push(...qrSection.map((line) => clampToWidth(line, width)));
  }

  if (active) {
    footer.push(...wrapTextWithAnsi(theme.fg("dim", `Plan · ${state.planId}`), width).map((line) => clampToWidth(line, width, "…")));
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
  const { innerWidth, contentWidth, timelineWidth, detailWidth } = planningColumns(width);

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
    const qrCompact = formatQRCompact(state, theme, contentWidth);
    if (qrCompact.length > 0) {
      fallbackContent.push(...qrCompact);
    }
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

  const timelineLines = renderTimelineLines(state, theme, timelineWidth);
  const detailSections = buildDetailSections(state, theme, detailWidth);
  const detailLines = layoutDetailColumn(detailSections, detailWidth, timelineLines.length);
  const combined: string[] = [];
  const maxLines = Math.max(timelineLines.length, detailLines.length);

  for (let i = 0; i < maxLines; i++) {
    const left = timelineLines[i] ?? "";
    const right = detailLines[i] ?? "";
    const composed = `${clampToWidth(left, timelineWidth)}${" ".repeat(COLUMN_GAP)}${clampToWidth(right, detailWidth)}`;
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
    `${BODY_INDENT}${theme.bold(theme.fg("accent", "Planning"))}`,
    elapsed,
    body,
    width,
    theme,
  );
}

function wrapRightColumn(entry: LogLine, width: number): string[] {
  const summary = entry.summary.trim();
  if (!summary) return [""];

  if (!entry.highValue) {
    return [clampToWidth(summary, width, "…")];
  }

  const wrapped = wrapTextWithAnsi(summary, width).map((line) => clampToWidth(line, width, "…"));
  if (wrapped.length <= 1) return wrapped;
  if (wrapped.length === 2) return wrapped;

  const tail = wrapped.slice(1).join(" ").replace(/\s+/gu, " ").trim();
  return [wrapped[0], clampToWidth(truncateToWidth(tail, width, "…", false), width)];
}

function renderLogEntry(entry: LogLine, theme: Theme, leftWidth: number, rightWidth: number, gap: number): string[] {
  const rightLines = wrapRightColumn(entry, rightWidth);
  const rows: string[] = [];

  rightLines.forEach((line, index) => {
    const left = index === 0
      ? theme.bold(theme.fg("accent", entry.tool))
      : "";
    const composed = `${clampToWidth(left, leftWidth)}${" ".repeat(gap)}${clampToWidth(theme.fg("muted", line), rightWidth)}`;
    rows.push(composed);
  });

  return rows;
}

interface LogColumns {
  left: number;
  right: number;
  gap: number;
}

function logColumnWidths(availableWidth: number, entries: readonly LogLine[], gap: number): LogColumns {
  const longestTool = entries.reduce((max, entry) => Math.max(max, visibleWidth(entry.tool)), 0);
  const preferredLeft = Math.max(16, Math.min(38, longestTool + 2));

  const minRight = availableWidth < 64 ? 18 : 24;
  let left = Math.min(preferredLeft, Math.floor(availableWidth * 0.42));
  left = Math.min(left, Math.max(14, availableWidth - minRight - gap));
  left = Math.max(14, left);

  const right = Math.max(8, availableWidth - left - gap);
  return { left, right, gap };
}

function renderLogCard(state: WidgetState, theme: Theme, width: number, forcedColumns?: LogColumns): string[] {
  const innerWidth = Math.max(0, width - 2);
  const availableWidth = Math.max(0, innerWidth - visibleWidth(BODY_INDENT));
  const hasEntries = state.logLines.length > 0;
  const entries = hasEntries ? state.logLines.slice(-(LOG_LINES * 2)) : [];

  const columns = forcedColumns ?? logColumnWidths(availableWidth, entries, 2);
  const leftWidth = Math.max(8, Math.min(columns.left, Math.max(8, availableWidth - columns.gap - 8)));
  const rightWidth = Math.max(8, availableWidth - leftWidth - columns.gap);

  const visualRows: string[] = [];
  if (entries.length > 0) {
    const rendered = entries.map((entry) => renderLogEntry(entry, theme, leftWidth, rightWidth, columns.gap));
    const selected: string[][] = [];
    let remaining = LOG_LINES;

    for (let i = rendered.length - 1; i >= 0; i--) {
      if (remaining <= 0) break;
      const rowLines = rendered[i];
      if (rowLines.length <= remaining) {
        selected.push(rowLines);
        remaining -= rowLines.length;
      } else {
        selected.push(rowLines.slice(0, remaining));
        remaining = 0;
      }
    }

    selected.reverse();
    for (const lines of selected) {
      visualRows.push(...lines);
    }
  }

  if (visualRows.length === 0) {
    visualRows.push(clampToWidth(theme.fg("muted", LOG_PLACEHOLDER), innerWidth));
  }

  while (visualRows.length < LOG_LINES) {
    visualRows.push("");
  }

  const body = indentLines(visualRows, innerWidth);
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

function formatQRCompact(state: WidgetState, theme: Theme, width: number): string[] {
  if (!shouldShowQR(state)) return [];

  const tier = qrTier(width);
  const budget = Math.min(width, QR_META_MAX_CHARS);
  const meta = qrMetaText(state, tier, budget);
  const line1 = clampToWidth(`${theme.fg("muted", "QR")} ${theme.fg("muted", "|")} ${theme.fg("dim", meta)}`, width, "…");
  const line2 = renderQRCounterLine(state, theme, tier, width, budget);
  return [line1, line2];
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
function stripBoxFrame(lines: string[]): string[] {
  if (lines.length <= 2) return [];
  return lines.slice(1, -1).map((line) => (line.length >= 2 ? line.slice(1, -1) : ""));
}

function renderIntegratedWorkspaceCard(state: WidgetState, theme: Theme, width: number): string[] {
  const innerWidth = Math.max(0, width - 2);
  const elapsed = theme.fg("dim", formatElapsed(Date.now() - state.startedAt));
  const rightInset = " ".repeat(visibleWidth(BODY_INDENT));

  const { innerWidth: planningInnerWidth, contentWidth, timelineWidth, detailWidth } = planningColumns(width);
  const alignedColumns: LogColumns | undefined = planningInnerWidth >= 60 && contentWidth >= 40
    ? { left: timelineWidth, right: detailWidth, gap: COLUMN_GAP }
    : undefined;

  const planningInner = stripBoxFrame(renderPlanningCard(state, theme, width));
  const logInner = stripBoxFrame(renderLogCard(state, theme, width, alignedColumns));

  const divider = clampToWidth(theme.fg("muted", "─".repeat(innerWidth)), innerWidth);
  const spacer = clampToWidth("", innerWidth);
  const logTitle = clampToWidth(`${BODY_INDENT}${theme.bold(theme.fg("accent", "Latest log"))}`, innerWidth, "…");

  const body = [
    ...planningInner,
    divider,
    spacer,
    logTitle,
    ...logInner,
  ];

  return renderBox(
    `${BODY_INDENT}${theme.bold(theme.fg("accent", "Planning"))}`,
    `${elapsed}${rightInset}`,
    body,
    width,
    theme,
  );
}

// Pure render: (state, theme, termWidth) -> lines. No side effects.
function render(state: WidgetState, theme: Theme, termWidth: number): string[] {
  const c = (s: string) => canvasLine(s, termWidth, theme);
  const cw = contentWidth(termWidth);
  const lines: string[] = [];
  const margin = " ".repeat(CARD_MARGIN);

  lines.push(c(""));
  for (const line of renderIntegratedWorkspaceCard(state, theme, cw - CARD_MARGIN)) {
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
      qrDone: null,
      qrTotal: null,
      qrPass: null,
      qrFail: null,
      qrTodo: null,
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
    if (patch.qrDone !== undefined) {
      this.state.qrDone = patch.qrDone;
    }
    if (patch.qrTotal !== undefined) {
      this.state.qrTotal = patch.qrTotal;
    }
    if (patch.qrPass !== undefined) {
      this.state.qrPass = patch.qrPass;
    }
    if (patch.qrFail !== undefined) {
      this.state.qrFail = patch.qrFail;
    }
    if (patch.qrTodo !== undefined) {
      this.state.qrTodo = patch.qrTodo;
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
      logLines: this.state.logLines.map((l) => ({ ...l })),
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
