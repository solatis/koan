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
  error: boolean;
}

export interface ToolBashEvent extends EventBase {
  kind: "tool_bash";
  bin: string;
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
    case "tool_file":
      return `${e.tool} ${e.path}`;
    case "tool_bash":
      return `bash ${e.bin}`;
    case "tool_koan":
      return e.tool;
    case "tool_generic":
      return e.tool;
  }
}

// Pure projection update -- one case per discriminated kind.
// All branches update updatedAt and increment eventCount.
export function fold(s: Projection, e: AuditEvent): Projection {
  const base = { ...s, updatedAt: e.ts, eventCount: s.eventCount + 1 };

  switch (e.kind) {
    case "phase_start":
      return {
        ...base,
        role: e.role,
        phase: e.phase,
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
    return {
      kind: "tool_file",
      tool: toolName as "read" | "edit" | "write",
      path: (input["path"] as string | undefined) ?? "",
      error: isError,
      ts,
      seq,
    };
  }

  if (toolName === "bash") {
    const cmd = (input["command"] as string | undefined) ?? "";
    const bin = cmd.trim().split(/\s+/)[0] ?? "bash";
    return { kind: "tool_bash", bin, error: isError, ts, seq };
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
  // both call append() concurrently -- without serialization, two
  // writeState() calls race on the shared tmp file (ENOENT on rename).
  private pending: Promise<void> = Promise.resolve();

  constructor(dir: string, role: string, phase: string) {
    this.eventsPath = path.join(dir, "events.jsonl");
    this.statePath = path.join(dir, "state.json");
    this.stateTmpPath = path.join(dir, "state.tmp.json");
    this.projection = {
      role,
      phase,
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
// Used by session.ts parent polling loop.
export async function readProjection(dir: string): Promise<Projection | null> {
  try {
    const raw = await fs.readFile(path.join(dir, "state.json"), "utf8");
    return JSON.parse(raw) as Projection;
  } catch {
    return null;
  }
}
