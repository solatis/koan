// Audit trail for subagent sessions: event-sourced append log (events.jsonl)
// with an eagerly materialized projection (state.json) for parent polling.
// fold() is pure so the projection can be replayed from the raw log for testing.
//
// Tool invocations are captured as two events: tool_call (request) and
// tool_result (response), correlated by toolCallId. The flat event stream
// can be reduced into ToolInvocation[] via correlateTools() for paired access.

import { promises as fs } from "node:fs";
import * as path from "node:path";

// -- Types --

export interface EventBase {
  ts: string;
  seq: number;
}

// -- Tool events --
// Every tool invocation produces a (tool_call, tool_result) pair in the log.
// tool_call fires when the LLM requests the tool; tool_result fires when
// the tool returns. Both carry toolCallId for correlation.

export interface ToolCallEvent extends EventBase {
  kind: "tool_call";
  toolCallId: string;
  tool: string;
  input: Record<string, unknown>;
}

export interface ToolResultEvent extends EventBase {
  kind: "tool_result";
  toolCallId: string;
  tool: string;
  error: boolean;
  // Summarized output metrics (not the full content — too large for the log).
  lines?: number;
  chars?: number;
  // Koan tool response text preserved for projection (completionSummary, etc.).
  koanResponse?: string[];
}

// -- Lifecycle events --

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

export interface UsageEvent extends EventBase {
  kind: "usage";
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

export interface ThinkingEvent extends EventBase {
  kind: "thinking";
  // Truncated thinking content (first 2000 chars for log size).
  text: string;
  // Original length before truncation.
  chars: number;
}

export interface ConfidenceChangeEvent extends EventBase {
  kind: "confidence_change";
  // The confidence level declared by the intake agent via koan_set_confidence.
  level: "exploring" | "low" | "medium" | "high" | "certain";
  // Which iteration of the Scout→Deliberate→Reflect loop this was declared in.
  iteration: number;
}

export interface IterationStartEvent extends EventBase {
  kind: "iteration_start";
  // The new iteration number (incremented from the previous Reflect step).
  iteration: number;
  // Maximum allowed iterations before the loop is forced to exit.
  maxIterations: number;
}

export type AuditEvent =
  | ToolCallEvent
  | ToolResultEvent
  | PhaseStartEvent
  | StepTransitionEvent
  | PhaseEndEvent
  | HeartbeatEvent
  | UsageEvent
  | ThinkingEvent
  | ConfidenceChangeEvent
  | IterationStartEvent;

// Distributive Omit — distributes over union members so object literals
// with fields specific to one member are accepted.
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
export type AuditEventPartial = DistributiveOmit<AuditEvent, "ts" | "seq">;

// -- Projection --
// Eagerly materialized state summary. Written atomically to state.json
// after every event so the parent (web server) can poll cheaply.

export interface Projection {
  role: string;
  phase: string;
  model: string | null;
  status: "running" | "completed" | "failed";
  step: number;
  totalSteps: number;
  stepName: string;
  lastAction: string | null;
  // toolCallId of the currently in-flight tool, null when idle.
  // Lets the UI distinguish "doing X" from "done with X".
  currentToolCallId: string | null;
  updatedAt: string;
  eventCount: number;
  error: string | null;
  completionSummary: string | null;
  tokensSent: number;
  tokensReceived: number;
  // Timestamp of the most recent tool_result event; used to track thinking gaps.
  lastToolResultAt: string | null;
  // Intake-specific: the most recent confidence level declared by koan_set_confidence.
  // Null for non-intake subagents or before any confidence is declared.
  intakeConfidence: "exploring" | "low" | "medium" | "high" | "certain" | null;
  // Intake-specific: the current loop iteration (1-based). Zero for non-intake.
  intakeIteration: number;
}

// -- Correlated tool invocations --
// Reduced view of paired (tool_call, tool_result) events.

export interface ToolInvocation {
  toolCallId: string;
  tool: string;
  input: Record<string, unknown>;
  callTs: string;
  resultTs: string | null;
  error: boolean | null;
  inFlight: boolean;
  durationMs: number | null;
  // Output metrics from the result event.
  lines?: number;
  chars?: number;
  koanResponse?: string[];
}

// Reduces a flat event stream into paired tool invocations.
// In-flight tools (call without result) have inFlight=true, resultTs=null.
export function correlateTools(events: AuditEvent[]): ToolInvocation[] {
  const byId = new Map<string, ToolInvocation>();
  const ordered: ToolInvocation[] = [];

  for (const e of events) {
    if (e.kind === "tool_call") {
      const inv: ToolInvocation = {
        toolCallId: e.toolCallId,
        tool: e.tool,
        input: e.input,
        callTs: e.ts,
        resultTs: null,
        error: null,
        inFlight: true,
        durationMs: null,
      };
      byId.set(e.toolCallId, inv);
      ordered.push(inv);
    } else if (e.kind === "tool_result") {
      const inv = byId.get(e.toolCallId);
      if (inv) {
        inv.resultTs = e.ts;
        inv.error = e.error;
        inv.inFlight = false;
        inv.durationMs = new Date(e.ts).getTime() - new Date(inv.callTs).getTime();
        inv.lines = e.lines;
        inv.chars = e.chars;
        inv.koanResponse = e.koanResponse;
      }
      // Orphan result (no matching call) — can happen if the subagent
      // started before tool_call hooking was added. Silently skip.
    }
  }

  return ordered;
}

// -- Pi event shapes (subset we consume) --

interface PiToolCallEvent {
  toolCallId: string;
  toolName: string;
  input: Record<string, unknown>;
}

interface PiToolResultEvent {
  toolCallId: string;
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

// -- Extractors --
// Transform pi's raw hook events into our audit event types.
// ts/seq are placeholders — EventLog.append() overwrites them.

export function extractToolCall(piEvent: PiToolCallEvent): ToolCallEvent {
  return {
    kind: "tool_call",
    toolCallId: piEvent.toolCallId,
    tool: piEvent.toolName,
    input: piEvent.input,
    ts: now(),
    seq: 0,
  };
}

export function extractToolResult(piEvent: PiToolResultEvent): ToolResultEvent {
  const { toolCallId, toolName, input, content, isError } = piEvent;

  const ev: ToolResultEvent = {
    kind: "tool_result",
    toolCallId,
    tool: toolName,
    error: isError,
    ts: now(),
    seq: 0,
  };

  // Capture output size for file and bash tools.
  if (FILE_TOOLS.has(toolName) && !isError) {
    const text = content.find((c) => c.type === "text")?.text ?? "";
    ev.lines = text.split("\n").length;
    ev.chars = text.length;
  } else if (toolName === "bash") {
    const text = content.find((c) => c.type === "text")?.text ?? "";
    ev.lines = text.split("\n").length;
    ev.chars = text.length;
  }

  // Preserve koan tool response text for projection use (completionSummary).
  if (toolName.startsWith("koan_")) {
    ev.koanResponse = content
      .filter((c) => c.type === "text" && c.text !== undefined)
      .map((c) => c.text as string);
  }

  return ev;
}

// -- Summarize --
// Human-readable one-liner from a tool invocation.
// Uses input (from call) + output metrics (from result) when available.

export function summarizeInvocation(inv: ToolInvocation): string {
  const { tool, input } = inv;

  // Tool name / key input identifier.
  let label: string;
  if (FILE_TOOLS.has(tool)) {
    label = `${tool} ${(input["path"] as string | undefined) ?? ""}`;
  } else if (tool === "bash") {
    const cmd = (input["command"] as string | undefined) ?? "";
    label = `bash ${cmd.trim().split(/\s+/)[0] ?? ""}`;
  } else {
    label = tool;
  }

  // Append output metrics if result has landed.
  if (!inv.inFlight && (inv.lines != null || inv.chars != null)) {
    const lines = inv.lines ?? 0;
    const chars = inv.chars ?? 0;
    label += ` · ${lines}L/${formatChars(chars)}`;
  }

  return label;
}

// Summarize from a ToolCallEvent alone (in-flight, no result yet).
function summarizeCall(e: ToolCallEvent): string {
  if (FILE_TOOLS.has(e.tool)) {
    return `${e.tool} ${(e.input["path"] as string | undefined) ?? ""}`;
  }
  if (e.tool === "bash") {
    const cmd = (e.input["command"] as string | undefined) ?? "";
    return `bash ${cmd.trim().split(/\s+/)[0] ?? ""}`;
  }
  return e.tool;
}

// Summarize from a ToolResultEvent alone (used in fold when call was missed).
function summarizeResult(e: ToolResultEvent): string {
  let label = e.tool;
  if (e.lines != null || e.chars != null) {
    label += ` · ${e.lines ?? 0}L/${formatChars(e.chars ?? 0)}`;
  }
  return label;
}

// -- Fold --
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
        currentToolCallId: null,
        error: null,
        completionSummary: null,
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
        currentToolCallId: null,
      };

    case "tool_call": {
      const updated: Projection = {
        ...base,
        lastAction: summarizeCall(e),
        currentToolCallId: e.toolCallId,
      };
      // Extract completionSummary from koan_complete_step's thoughts param.
      // The thoughts parameter is chain-of-thought, not task output (per
      // AGENTS.md invariant), but we capture a prefix for the projection
      // so the web UI can show scout summaries.
      if (e.tool === "koan_complete_step" && typeof e.input?.thoughts === "string") {
        updated.completionSummary = e.input.thoughts.slice(0, 500) || null;
      }
      return updated;
    }

    case "tool_result":
      return {
        ...base,
        lastAction: summarizeResult(e),
        currentToolCallId: null,
        lastToolResultAt: e.ts,
      };

    case "heartbeat":
      return base;

    case "usage":
      return {
        ...base,
        tokensSent: s.tokensSent + e.input,
        tokensReceived: s.tokensReceived + e.output,
      };

    case "thinking":
      return base;

    case "confidence_change":
      return {
        ...base,
        intakeConfidence: e.level,
        intakeIteration: e.iteration,
      };

    case "iteration_start":
      return {
        ...base,
        intakeIteration: e.iteration,
      };
  }
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
      currentToolCallId: null,
      updatedAt: now(),
      eventCount: 0,
      error: null,
      completionSummary: null,
      tokensSent: 0,
      tokensReceived: 0,
      lastToolResultAt: null,
      intakeConfidence: null,
      intakeIteration: 0,
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
  async append(partial: AuditEventPartial): Promise<void> {
    const task = () => this.doAppend(partial);
    this.pending = this.pending.then(task, task);
    return this.pending;
  }

  private async doAppend(partial: AuditEventPartial): Promise<void> {
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

  async emitConfidenceChange(level: ConfidenceChangeEvent["level"], iteration: number): Promise<void> {
    await this.append({
      kind: "confidence_change",
      level,
      iteration,
    } as Omit<ConfidenceChangeEvent, "ts" | "seq">);
  }

  async emitIterationStart(iteration: number, maxIterations: number): Promise<void> {
    await this.append({
      kind: "iteration_start",
      iteration,
      maxIterations,
    } as Omit<IterationStartEvent, "ts" | "seq">);
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
// Used by web server polling loop.
export async function readProjection(dir: string): Promise<Projection | null> {
  try {
    const raw = await fs.readFile(path.join(dir, "state.json"), "utf8");
    return JSON.parse(raw) as Projection;
  } catch {
    return null;
  }
}

// -- Log formatting --
// Structured log lines for the web UI activity feed.

export interface LogLine {
  tool: string;
  summary: string;
  highValue: boolean;
  inFlight: boolean;
  details?: string[];
  // Timestamp used by thinking entries to drive the live elapsed timer.
  ts?: string;
  // Expandable content body: thinking text, tool output, etc.
  body?: string;
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

const KOAN_SHAPES: Record<string, ToolShape> = {
  koan_select_story: { keys: ["story_id"], highValue: true },
  koan_complete_story: { keys: ["story_id"], highValue: true },
  koan_retry_story: { keys: ["story_id", "failure_summary"], freeform: ["failure_summary"], highValue: true },
  koan_skip_story: { keys: ["story_id", "reason"], freeform: ["reason"], highValue: true },
  koan_ask_question: { keys: ["questions"], arrays: ["questions"], highValue: true },
  koan_request_scouts: { keys: ["scouts"], arrays: ["scouts"], highValue: true },
};

// Reads events.jsonl, correlates tool pairs, and returns structured log entries.
// Filters out heartbeats, usage, and koan_complete_step (noisy).
export async function readRecentLogs(dir: string, count = 8): Promise<LogLine[]> {
  try {
    const raw = await fs.readFile(path.join(dir, "events.jsonl"), "utf8");
    const events = raw
      .trimEnd()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as AuditEvent);

    return buildChronologicalLog(events, count);
  } catch {
    return [];
  }
}

// Builds a chronological log by walking events in order and emitting
// one LogLine per tool invocation (at result time, or at call time if
// still in-flight) plus lifecycle events. Inserts thinking lines to
// represent gaps between visible events where the LLM is reasoning.
function buildChronologicalLog(events: AuditEvent[], count: number): LogLine[] {
  const pendingCalls = new Map<string, { tool: string; input: Record<string, unknown> }>();
  const lines: LogLine[] = [];
  let thinkingStartTs: string | null = null;
  // Index of the last thinking line pushed to `lines`. Thinking events fire
  // AFTER the turn's tool_result (message_update is a post-turn event), so the
  // text belongs to the PREVIOUS thinking gap, not the current one. We
  // retroactively set body on the already-emitted line.
  let lastThinkingIdx = -1;
  let phaseEnded = false;

  for (const e of events) {
    if (e.kind === "heartbeat" || e.kind === "usage") continue;
    if (e.kind === "confidence_change" || e.kind === "iteration_start") continue;

    if (e.kind === "thinking") {
      // Retroactive: this text is from the turn that just completed.
      // Overwrite (not append) — later message_update events have more
      // complete content, so the last one wins.
      if (lastThinkingIdx >= 0) {
        lines[lastThinkingIdx].body = e.text;
      }
      continue;
    }

    if (e.kind === "tool_call") {
      // Before a visible tool_call, insert a completed thinking line if gap ≥ 1s
      if (e.tool !== "koan_complete_step" && thinkingStartTs) {
        const gapMs = new Date(e.ts).getTime() - new Date(thinkingStartTs).getTime();
        if (gapMs >= 1000) {
          lines.push({
            tool: "thinking",
            summary: formatThinkingDuration(gapMs),
            highValue: false,
            inFlight: false,
          });
          lastThinkingIdx = lines.length - 1;
        }
        thinkingStartTs = null;
      }
      pendingCalls.set(e.toolCallId, { tool: e.tool, input: e.input });
      continue;
    }

    if (e.kind === "tool_result") {
      if (e.tool === "koan_complete_step") {
        pendingCalls.delete(e.toolCallId);
        continue;
      }
      const call = pendingCalls.get(e.toolCallId);
      lines.push(formatPairedResult(e, call?.input ?? {}));
      pendingCalls.delete(e.toolCallId);
      thinkingStartTs = e.ts;
      continue;
    }

    if (
      e.kind === "phase_start" ||
      e.kind === "step_transition" ||
      e.kind === "phase_end"
    ) {
      // Flush any pending thinking gap before the lifecycle line.
      if (thinkingStartTs) {
        const gapMs = new Date(e.ts).getTime() - new Date(thinkingStartTs).getTime();
        if (gapMs >= 1000) {
          lines.push({
            tool: "thinking",
            summary: formatThinkingDuration(gapMs),
            highValue: false,
            inFlight: false,
          });
          lastThinkingIdx = lines.length - 1;
        }
        thinkingStartTs = null;
      }
      if (e.kind === "phase_end") phaseEnded = true;
      lines.push(formatLifecycleEvent(e));
      thinkingStartTs = e.ts;
    }
  }

  // Currently-thinking indicator: all tools completed, phase still running
  if (thinkingStartTs && pendingCalls.size === 0 && !phaseEnded) {
    lines.push({
      tool: "thinking",
      summary: "",
      highValue: false,
      inFlight: true,
      ts: thinkingStartTs,
    });
  }

  // Emit remaining calls without results as in-flight lines.
  for (const [, call] of pendingCalls) {
    if (call.tool === "koan_complete_step") continue;
    lines.push(formatInFlightCall(call.tool, call.input));
  }

  return lines.slice(-count);
}

// Format an in-flight tool_call (no result yet). Same structure as
// formatPairedResult but with inFlight: true and no output metrics.
function formatInFlightCall(tool: string, input: Record<string, unknown>): LogLine {
  if (FILE_TOOLS.has(tool)) {
    return {
      tool,
      summary: (input["path"] as string | undefined) ?? "",
      highValue: tool === "read",
      inFlight: true,
    };
  }

  if (tool === "bash") {
    const cmd = (input["command"] as string | undefined) ?? "";
    const bin = cmd.trim().split(/\s+/)[0] ?? "bash";
    return { tool: "bash", summary: bin, highValue: false, inFlight: true };
  }

  if (tool.startsWith("koan_")) {
    const shape = KOAN_SHAPES[tool];
    if (shape) {
      const inv: ToolInvocation = {
        toolCallId: "", tool, input,
        callTs: "", resultTs: null,
        error: null, inFlight: true, durationMs: null,
      };
      return formatKoanInvocation(inv);
    }
  }

  return { tool, summary: "", highValue: false, inFlight: true };
}

// -- Formatters --

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

function formatThinkingDuration(ms: number): string {
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  return remSec > 0 ? `${min}m ${remSec}s` : `${min}m`;
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

// Format a completed tool invocation from its correlated pair.
function formatToolInvocation(inv: ToolInvocation): LogLine {
  if (inv.tool.startsWith("koan_")) {
    return formatKoanInvocation(inv);
  }

  if (FILE_TOOLS.has(inv.tool)) {
    const p = (inv.input["path"] as string | undefined) ?? "";
    const suffix = inv.lines != null ? ` · ${inv.lines}L/${formatChars(inv.chars ?? 0)}` : "";
    return {
      tool: inv.tool,
      summary: `${p}${suffix}`,
      highValue: inv.tool === "read",
      inFlight: inv.inFlight,
    };
  }

  if (inv.tool === "bash") {
    const cmd = (inv.input["command"] as string | undefined) ?? "";
    const bin = cmd.trim().split(/\s+/)[0] ?? "bash";
    const suffix = inv.lines != null ? ` · ${inv.lines}L/${formatChars(inv.chars ?? 0)}` : "";
    return {
      tool: "bash",
      summary: `${bin}${suffix}`,
      highValue: false,
      inFlight: inv.inFlight,
    };
  }

  return { tool: inv.tool, summary: "", highValue: false, inFlight: inv.inFlight };
}

function formatKoanInvocation(inv: ToolInvocation): LogLine {
  const shape = KOAN_SHAPES[inv.tool];
  if (!shape) {
    return { tool: inv.tool, summary: "", highValue: false, inFlight: inv.inFlight };
  }

  const arrayKeys = new Set(shape.arrays ?? []);
  const freeformKeys = new Set(shape.freeform ?? []);
  const chunks: string[] = [];

  for (const key of orderedShapeKeys(shape.keys)) {
    if (!hasKey(inv.input, key)) continue;
    const value = inv.input[key];

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

  if (shape.getter && inv.koanResponse) {
    if (chunks.length === 0) {
      chunks.push("scope=plan");
    }
    chunks.push(`resp:${responseSize(inv.koanResponse)}`);
  }

  const line: LogLine = {
    tool: inv.tool,
    summary: chunks.join(" · "),
    highValue: shape.highValue ?? chunks.length >= 3,
    inFlight: inv.inFlight,
  };

  // Expand koan_request_scouts with per-scout detail lines.
  if (inv.tool === "koan_request_scouts" && Array.isArray(inv.input["scouts"])) {
    line.details = (inv.input["scouts"] as Array<Record<string, unknown>>).map(
      (s) => `${s["id"] ?? "?"} (${s["role"] ?? "agent"})`,
    );
  }

  return line;
}

// Format a tool_result event paired with its call's input.
function formatPairedResult(e: ToolResultEvent, input: Record<string, unknown>): LogLine {
  if (FILE_TOOLS.has(e.tool)) {
    const p = (input["path"] as string | undefined) ?? "";
    const suffix = e.lines != null ? ` · ${e.lines}L/${formatChars(e.chars ?? 0)}` : "";
    return {
      tool: e.tool,
      summary: `${p}${suffix}`,
      highValue: e.tool === "read",
      inFlight: false,
    };
  }

  if (e.tool === "bash") {
    const cmd = (input["command"] as string | undefined) ?? "";
    const bin = cmd.trim().split(/\s+/)[0] ?? "bash";
    const suffix = e.lines != null ? ` · ${e.lines}L/${formatChars(e.chars ?? 0)}` : "";
    return {
      tool: "bash",
      summary: `${bin}${suffix}`,
      highValue: false,
      inFlight: false,
    };
  }

  if (e.tool.startsWith("koan_")) {
    const shape = KOAN_SHAPES[e.tool];
    if (shape) {
      // Rebuild invocation-like object for the koan formatter.
      const inv: ToolInvocation = {
        toolCallId: e.toolCallId,
        tool: e.tool,
        input,
        callTs: e.ts,
        resultTs: e.ts,
        error: e.error,
        inFlight: false,
        durationMs: null,
        koanResponse: e.koanResponse,
      };
      return formatKoanInvocation(inv);
    }
    return { tool: e.tool, summary: "", highValue: false, inFlight: false };
  }

  return { tool: e.tool, summary: "", highValue: false, inFlight: false };
}

function formatLifecycleEvent(e: PhaseStartEvent | StepTransitionEvent | PhaseEndEvent): LogLine {
  switch (e.kind) {
    case "phase_start":
      return { tool: "phase", summary: `${e.phase} (${e.totalSteps} steps)`, highValue: false, inFlight: false };
    case "step_transition":
      return { tool: `step ${e.step}/${e.totalSteps}`, summary: e.name, highValue: false, inFlight: false };
    case "phase_end":
      return { tool: "phase", summary: e.detail ? `${e.outcome} · ${e.detail}` : e.outcome, highValue: false, inFlight: false };
  }
}

// formatToolInvocation is kept for callers outside buildChronologicalLog.
void formatToolInvocation;
