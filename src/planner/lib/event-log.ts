// EventLog class: file I/O, heartbeat, serialization, and emit helpers.
// Extractors transform pi hook events into AuditEvent types.

import { promises as fs } from "node:fs";
import * as path from "node:path";
import type {
  AuditEvent,
  AuditEventPartial,
  HeartbeatEvent,
  PhaseStartEvent,
  StepTransitionEvent,
  PhaseEndEvent,
  Projection,
  ToolCallEvent,
  ToolResultEvent,
} from "./audit-events.js";
import { fold } from "./audit-fold.js";

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

// Tools for which a bounded debug output preview is captured when debug mode
// is active. Intentionally narrow: only bash in this iteration.
const DEBUG_CAPTURE_TOOLS = new Set(["bash"]);

const DEBUG_CAPTURE_LIMIT = 4096;

// -- Helpers --

import { now } from "./time.js";

// -- Extractors --
// Transform pi's raw hook events into our audit event types.
// ts/seq are placeholders -- EventLog.append() overwrites them.

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

export function extractToolResult(
  piEvent: PiToolResultEvent,
  opts?: { debug?: boolean },
): ToolResultEvent {
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

  // Debug mode: capture a bounded preview of tool output for designated tools.
  // Only populated when debug is active; never written in normal mode.
  // NOT folded into Projection — debug-only; never add to Projection.
  if (opts?.debug && DEBUG_CAPTURE_TOOLS.has(toolName) && !isError) {
    const text = content.find((c) => c.type === "text")?.text ?? "";
    ev.debugOutput =
      text.slice(0, DEBUG_CAPTURE_LIMIT) +
      (text.length > DEBUG_CAPTURE_LIMIT ? "\n\u2026[truncated]" : "");
  }

  void input; // suppress unused-variable warning (input is part of the public API shape)

  return ev;
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
  // both call append() concurrently -- without serialization, two
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
    };
  }

  async open(): Promise<void> {
    this.fd = await fs.open(this.eventsPath, "a");
    await this.writeState();
    // Heartbeat keeps updatedAt fresh even during long-running steps.
    // unref() so the timer doesn't prevent process exit — pi's print mode
    // relies on natural event loop drain (no process.exit()) and never
    // emits session_shutdown, so EventLog.close() may not be called.
    this.heartbeat = setInterval(() => {
      void this.append({ kind: "heartbeat" } as Omit<HeartbeatEvent, "ts" | "seq">);
    }, HEARTBEAT_MS);
    this.heartbeat.unref();
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
