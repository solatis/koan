// Audit trail for subagent sessions: event-sourced append log (events.jsonl)
// with an eagerly materialized projection (state.json) for parent polling.
// fold() is pure so the projection can be replayed from the raw log for testing.
// Graduated tool capture: full detail for koan_* tools, paths for file ops,
// binary name for bash, name-only for everything else.

import { promises as fs } from "node:fs";
import * as path from "node:path";

// -- Types --

export interface EventBase {
  ts: string;
  seq: number;
}

export interface ToolFileEvent extends EventBase {
  kind: "tool_file";
  tool: "read" | "edit" | "write";
  path: string;
  lines?: number;
  chars?: number;
  error: boolean;
}

export interface ToolBashEvent extends EventBase {
  kind: "tool_bash";
  bin: string;
  lines?: number;
  chars?: number;
  error: boolean;
}

export interface ToolKoanEvent extends EventBase {
  kind: "tool_koan";
  tool: string;
  input: Record<string, unknown>;
  response: string[];
  error: boolean;
}

export interface ToolGenericEvent extends EventBase {
  kind: "tool_generic";
  tool: string;
  error: boolean;
}

export type ToolEvent = ToolFileEvent | ToolBashEvent | ToolKoanEvent | ToolGenericEvent;

export interface PhaseStartEvent extends EventBase {
  kind: "phase_start";
  phase: string;
  role: string;
  model?: string | null;
  totalSteps: number;
}

export interface StepTransitionEvent extends EventBase {
  kind: "step_transition";
  step: number;
  name: string;
  totalSteps: number;
}

export interface PhaseEndEvent extends EventBase {
  kind: "phase_end";
  outcome: "completed" | "failed";
  detail?: string;
}

export interface HeartbeatEvent extends EventBase {
  kind: "heartbeat";
}

export type AuditEvent =
  | ToolFileEvent
  | ToolBashEvent
  | ToolKoanEvent
  | ToolGenericEvent
  | PhaseStartEvent
  | StepTransitionEvent
  | PhaseEndEvent
  | HeartbeatEvent;

export interface Projection {
  role: string;
  phase: string;
  model: string | null;
  status: "running" | "completed" | "failed";
  step: number;
  totalSteps: number;
  stepName: string;
  lastAction: string | null;
  updatedAt: string;
  eventCount: number;
  error: string | null;
}

// Pi's ToolResultEvent shape (subset we need).
interface PiToolResultEvent {
  toolName: string;
  input: Record<string, unknown>;
  content: Array<{ type: string; text?: string }>;
  isError: boolean;
}

// -- Constants --

const FILE_TOOLS = new Set(["read", "edit", "write"]);
const HEARTBEAT_MS = 10_000;

// -- Helpers --

function now(): string {
  return new Date().toISOString();
}

// Derives a concise last-action string from a tool event for display.
export function summarize(e: ToolEvent): string {
  switch (e.kind) {
    case "tool_file": {
      const suffix = e.lines != null ? ` (${e.lines}L, ${e.chars}c)` : "";
      return `${e.tool} ${e.path}${suffix}`;
    }
    case "tool_bash": {
      const suffix = e.lines != null ? ` (${e.lines}L, ${e.chars}c)` : "";
      return `bash ${e.bin}${suffix}`;
    }
    case "tool_koan":
      return e.tool;
    case "tool_generic":
      return e.tool;
  }
}

// Pure projection update — one case per discriminated kind.
// All branches update updatedAt and increment eventCount.
export function fold(s: Projection, e: AuditEvent): Projection {
  const base = { ...s, updatedAt: e.ts, eventCount: s.eventCount + 1 };

  switch (e.kind) {
    case "phase_start":
      return {
        ...base,
        role: e.role,
        phase: e.phase,
        model: e.model ?? s.model,
        status: "running",
        step: 0,
        totalSteps: e.totalSteps,
        stepName: "",
        lastAction: null,
        error: null,
      };

    case "step_transition":
      return {
        ...base,
        step: e.step,
        totalSteps: e.totalSteps,
        stepName: `Step ${e.step}/${e.totalSteps}: ${e.name}`,
      };

    case "phase_end":
      return {
        ...base,
        status: e.outcome,
        error: e.detail ?? null,
      };

    case "tool_file":
    case "tool_bash":
    case "tool_koan":
    case "tool_generic":
      return { ...base, lastAction: summarize(e) };

    case "heartbeat":
      return base;
  }
}

// Transforms pi's ToolResultEvent into a graduated AuditEvent.
export function extractToolEvent(piEvent: PiToolResultEvent): ToolEvent {
  const { toolName, input, content, isError } = piEvent;
  const ts = now();
  // ts and seq are assigned by EventLog.append(); values here are
  // placeholders overridden on write.
  const seq = 0;

  if (FILE_TOOLS.has(toolName)) {
    const ev: ToolFileEvent = {
      kind: "tool_file",
      tool: toolName as "read" | "edit" | "write",
      path: (input["path"] as string | undefined) ?? "",
      error: isError,
      ts,
      seq,
    };
    if (toolName === "read" && !isError) {
      const text = content.find((c) => c.type === "text")?.text ?? "";
      ev.lines = text.split("\n").length;
      ev.chars = text.length;
    }
    return ev;
  }

  if (toolName === "bash") {
    const cmd = (input["command"] as string | undefined) ?? "";
    const bin = cmd.trim().split(/\s+/)[0] ?? "bash";
    const text = content.find((c) => c.type === "text")?.text ?? "";
    return { kind: "tool_bash", bin, lines: text.split("\n").length, chars: text.length, error: isError, ts, seq };
  }

  if (toolName.startsWith("koan_")) {
    const response = content
      .filter((c) => c.type === "text" && c.text !== undefined)
      .map((c) => c.text as string);
    return { kind: "tool_koan", tool: toolName, input, response, error: isError, ts, seq };
  }

  return { kind: "tool_generic", tool: toolName, error: isError, ts, seq };
}

// -- EventLog --

export class EventLog {
  private readonly eventsPath: string;
  private readonly statePath: string;
  private readonly stateTmpPath: string;
  private fd: fs.FileHandle | null = null;
  private seq = 0;
  private projection: Projection;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  // Serializes append() calls. Heartbeat timer and tool_result handler
  // both call append() concurrently — without serialization, two
  // writeState() calls race on the shared tmp file (ENOENT on rename).
  private pending: Promise<void> = Promise.resolve();

  constructor(dir: string, role: string, phase: string, model: string | null = null) {
    this.eventsPath = path.join(dir, "events.jsonl");
    this.statePath = path.join(dir, "state.json");
    this.stateTmpPath = path.join(dir, "state.tmp.json");
    this.projection = {
      role,
      phase,
      model,
      status: "running",
      step: 0,
      totalSteps: 0,
      stepName: "",
      lastAction: null,
      updatedAt: now(),
      eventCount: 0,
      error: null,
    };
  }

  async open(): Promise<void> {
    this.fd = await fs.open(this.eventsPath, "a");
    await this.writeState();
    // Heartbeat keeps updatedAt fresh even during long-running steps.
    this.heartbeat = setInterval(() => {
      void this.append({ kind: "heartbeat" } as Omit<HeartbeatEvent, "ts" | "seq">);
    }, HEARTBEAT_MS);
  }

  // Assigns ts + seq, appends JSON line, folds, writes state atomically.
  // Serialized: concurrent callers queue behind the in-flight write.
  async append(partial: Omit<AuditEvent, "ts" | "seq">): Promise<void> {
    const task = () => this.doAppend(partial);
    this.pending = this.pending.then(task, task);
    return this.pending;
  }

  private async doAppend(partial: Omit<AuditEvent, "ts" | "seq">): Promise<void> {
    if (!this.fd) {
      throw new Error("EventLog.append called before open()");
    }

    const e = { ...partial, ts: now(), seq: this.seq++ } as AuditEvent;
    await this.fd.write(JSON.stringify(e) + "\n");
    this.projection = fold(this.projection, e);
    await this.writeState();
  }

  async emitPhaseStart(totalSteps: number): Promise<void> {
    await this.append({
      kind: "phase_start",
      phase: this.projection.phase,
      role: this.projection.role,
      model: this.projection.model,
      totalSteps,
    } as Omit<PhaseStartEvent, "ts" | "seq">);
  }

  async emitStepTransition(step: number, name: string, totalSteps: number): Promise<void> {
    await this.append({
      kind: "step_transition",
      step,
      name,
      totalSteps,
    } as Omit<StepTransitionEvent, "ts" | "seq">);
  }

  async emitPhaseEnd(outcome: "completed" | "failed", detail?: string): Promise<void> {
    await this.append({
      kind: "phase_end",
      outcome,
      detail,
    } as Omit<PhaseEndEvent, "ts" | "seq">);
  }

  async close(): Promise<void> {
    if (this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
    if (this.fd) {
      await this.fd.close();
      this.fd = null;
    }
  }

  get state(): Readonly<Projection> {
    return this.projection;
  }

  // Atomic write: tmp file then rename so readers never see partial JSON.
  private async writeState(): Promise<void> {
    const json = JSON.stringify(this.projection, null, 2) + "\n";
    await fs.writeFile(this.stateTmpPath, json);
    await fs.rename(this.stateTmpPath, this.statePath);
  }
}

// -- Exports --

// Reads state.json as a Projection; returns null if missing or malformed.
// Used by driver polling loop.
export async function readProjection(dir: string): Promise<Projection | null> {
  try {
    const raw = await fs.readFile(path.join(dir, "state.json"), "utf8");
    return JSON.parse(raw) as Projection;
  } catch {
    return null;
  }
}

// Structured log line for the widget log card.
// `tool` is the left-column scan anchor, `summary` is the right-column detail.
// High-value rows may wrap to two visual lines in the widget.
export interface LogLine {
  tool: string;
  summary: string;
  highValue: boolean;
}

interface ToolShape {
  keys: string[];
  arrays?: string[];
  freeform?: string[];
  getter?: boolean;
  highValue?: boolean;
}

const PREVIEW_CHARS = 40;
const KEY_PRIORITY = ["id", "story_id", "milestone", "decision_ref", "intent_ref", "file", "path", "phase"];

// Tool shapes for koan_* tools. No koan_escalate (eliminated in §11.3.1).
const KOAN_SHAPES: Record<string, ToolShape> = {
  koan_select_story: { keys: ["story_id"], highValue: true },
  koan_complete_story: { keys: ["story_id"], highValue: true },
  koan_retry_story: { keys: ["story_id", "failure_summary"], freeform: ["failure_summary"], highValue: true },
  koan_skip_story: { keys: ["story_id", "reason"], freeform: ["reason"], highValue: true },
  koan_ask_question: { keys: ["questions"], arrays: ["questions"], highValue: true },
  koan_request_scouts: { keys: ["scouts"], arrays: ["scouts"], highValue: true },
};

// Reads the tail of events.jsonl and returns structured log entries.
// Filters out heartbeats (noisy). Used by driver to feed the widget log card.
export async function readRecentLogs(dir: string, count = 8): Promise<LogLine[]> {
  try {
    const raw = await fs.readFile(path.join(dir, "events.jsonl"), "utf8");
    const events = raw
      .trimEnd()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as AuditEvent)
      .filter((e) => e.kind !== "heartbeat" && !(e.kind === "tool_koan" && e.tool === "koan_complete_step"));
    return events.slice(-count).map(formatLogLine);
  } catch {
    return [];
  }
}

function formatChars(chars: number): string {
  if (chars < 1000) return `${chars}c`;
  const k = chars / 1000;
  if (k >= 10) return `${Math.round(k)}k`;
  return `${k.toFixed(1)}k`;
}

function textStats(text: string): string {
  const lines = text.length === 0 ? 0 : text.split("\n").length;
  return `${lines}L/${formatChars(text.length)}`;
}

function responseSize(response: string[]): string {
  return textStats(response.join("\n"));
}

function truncateUnicode(text: string, maxChars: number): string {
  const chars = Array.from(text);
  if (chars.length <= maxChars) return text;
  return `${chars.slice(0, maxChars).join("")}…`;
}

function inlineScalar(value: unknown): string {
  if (typeof value === "string") {
    return truncateUnicode(value.replace(/\r\n?|\n/gu, "\\n"), PREVIEW_CHARS);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null) return "null";
  if (Array.isArray(value)) return `[${value.length}]`;
  if (typeof value === "object") return "{…}";
  return String(value);
}

function arrayPreview(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) {
    return "[]";
  }
  const first = inlineScalar(value[0]);
  if (value.length === 1) {
    return `[${first}]`;
  }
  return `[${first}] +${value.length - 1}`;
}

function freeformSize(value: unknown): string {
  if (typeof value === "string") {
    return textStats(value);
  }
  const json = JSON.stringify(value);
  return textStats(json ?? String(value));
}

function hasKey(input: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(input, key);
}

function orderedShapeKeys(keys: string[]): string[] {
  const indexed = keys.map((key, index) => ({ key, index }));
  indexed.sort((a, b) => {
    const pa = KEY_PRIORITY.indexOf(a.key);
    const pb = KEY_PRIORITY.indexOf(b.key);
    const ra = pa === -1 ? Number.MAX_SAFE_INTEGER : pa;
    const rb = pb === -1 ? Number.MAX_SAFE_INTEGER : pb;
    if (ra !== rb) return ra - rb;
    return a.index - b.index;
  });
  return indexed.map((x) => x.key);
}

function formatKnownKoan(e: ToolKoanEvent, shape: ToolShape): LogLine {
  const arrayKeys = new Set(shape.arrays ?? []);
  const freeformKeys = new Set(shape.freeform ?? []);
  const chunks: string[] = [];

  for (const key of orderedShapeKeys(shape.keys)) {
    if (!hasKey(e.input, key)) continue;
    const value = e.input[key];

    if (arrayKeys.has(key)) {
      chunks.push(`${key}:${arrayPreview(value)}`);
      continue;
    }

    if (freeformKeys.has(key)) {
      chunks.push(`${key}:${freeformSize(value)}`);
      continue;
    }

    chunks.push(`${key}=${inlineScalar(value)}`);
  }

  if (shape.getter) {
    if (chunks.length === 0) {
      chunks.push("scope=plan");
    }
    chunks.push(`resp:${responseSize(e.response)}`);
  }

  return {
    tool: e.tool,
    summary: chunks.join(" · "),
    highValue: shape.highValue ?? chunks.length >= 3,
  };
}

function formatKoanLogLine(e: ToolKoanEvent): LogLine {
  const shape = KOAN_SHAPES[e.tool];
  if (!shape) {
    return { tool: e.tool, summary: "", highValue: false };
  }
  return formatKnownKoan(e, shape);
}

function formatLogLine(e: AuditEvent): LogLine {
  switch (e.kind) {
    case "phase_start":
      return { tool: "phase", summary: `${e.phase} (${e.totalSteps} steps)`, highValue: false };
    case "step_transition":
      return { tool: `step ${e.step}/${e.totalSteps}`, summary: e.name, highValue: false };
    case "phase_end":
      return { tool: "phase", summary: e.detail ? `${e.outcome} · ${e.detail}` : e.outcome, highValue: false };
    case "tool_file":
      return {
        tool: e.tool,
        summary: e.lines != null ? `${e.path} · ${e.lines}L/${formatChars(e.chars ?? 0)}` : e.path,
        highValue: e.tool === "read",
      };
    case "tool_bash":
      return {
        tool: "bash",
        summary: e.lines != null ? `${e.bin} · ${e.lines}L/${formatChars(e.chars ?? 0)}` : e.bin,
        highValue: false,
      };
    case "tool_koan":
      return formatKoanLogLine(e);
    case "tool_generic":
      return { tool: e.tool, summary: "", highValue: false };
    case "heartbeat":
      return { tool: "heartbeat", summary: "", highValue: false };
  }
}
