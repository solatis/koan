// Log formatters for the web UI activity feed. Reads events.jsonl and
// produces structured LogLine entries.

import { promises as fs } from "node:fs";
import * as path from "node:path";
import type {
  AuditEvent,
  ToolResultEvent,
  PhaseStartEvent,
  StepTransitionEvent,
  PhaseEndEvent,
  ToolInvocation,
} from "./audit-events.js";
import { correlateTools, formatChars } from "./audit-fold.js";

// -- Types --

export interface LogLine {
  tool: string;
  summary: string;
  highValue: boolean;
  inFlight: boolean;
  details?: string[];
  // Timestamp used by thinking entries to drive the live elapsed timer.
  ts?: string;
  // Expandable content body: thinking text, tool output, step guidance, etc.
  body?: string;
  // Structured scout data for koan_request_scouts cards.
  scouts?: Array<{ id: string; role: string }>;
}

interface ToolShape {
  keys: string[];
  arrays?: string[];
  freeform?: string[];
  getter?: boolean;
  highValue?: boolean;
}

// -- Constants --

const PREVIEW_CHARS = 40;
const KEY_PRIORITY = ["id", "story_id", "milestone", "decision_ref", "intent_ref", "file", "path", "phase"];

const KOAN_SHAPES: Record<string, ToolShape> = {
  koan_select_story: { keys: ["story_id"], highValue: true },
  koan_complete_story: { keys: ["story_id"], highValue: true },
  koan_retry_story: { keys: ["story_id", "failure_summary"], freeform: ["failure_summary"], highValue: true },
  koan_skip_story: { keys: ["story_id", "reason"], freeform: ["reason"], highValue: true },
  koan_ask_question: {
    keys: ["questions"],
    arrays: ["questions"],
    highValue: true,
  },
  koan_request_scouts: { keys: [], highValue: true },
};

const FILE_TOOLS = new Set(["read", "edit", "write"]);

// -- Public API --

// Reads events.jsonl, correlates tool pairs, and returns structured log entries.
// Filters out heartbeats, usage, and koan_complete_step (noisy in non-debug mode).
// In debug mode, koan_complete_step results are used to attach step guidance text
// as an expandable body on the preceding step line.
export async function readRecentLogs(
  dir: string,
  count = 8,
  opts?: { debug?: boolean },
): Promise<LogLine[]> {
  try {
    const raw = await fs.readFile(path.join(dir, "events.jsonl"), "utf8");
    const events = raw
      .trimEnd()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as AuditEvent);

    return buildChronologicalLog(events, count, opts?.debug ?? false);
  } catch {
    return [];
  }
}

// -- Helpers --

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
  return `${chars.slice(0, maxChars).join("")}\u2026`;
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
  if (typeof value === "object") return "{\u2026}";
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

// -- Formatters --

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

  // Structured scout data for the UI card.
  if (inv.tool === "koan_request_scouts" && Array.isArray(inv.input["scouts"])) {
    line.scouts = (inv.input["scouts"] as Array<Record<string, unknown>>).map(
      (s) => ({ id: String(s["id"] ?? "?"), role: String(s["role"] ?? "agent") }),
    );
  }

  return line;
}

// Format a tool_result event paired with its call's input.
function formatPairedResult(e: ToolResultEvent, input: Record<string, unknown>): LogLine {
  if (FILE_TOOLS.has(e.tool)) {
    const p = (input["path"] as string | undefined) ?? "";
    const suffix = e.lines != null ? ` · ${e.lines}L/${formatChars(e.chars ?? 0)}` : "";
    // Placeholder for future debug body rendering.
    // In debug mode, a per-tool formatter may populate line.body.
    // See: formatDebugBody(tool, input, e.debugOutput)
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
    // Placeholder for future debug body rendering.
    // In debug mode, a per-tool formatter may populate line.body.
    // See: formatDebugBody(tool, input, e.debugOutput)
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

function formatLifecycleEvent(e: PhaseStartEvent | StepTransitionEvent | PhaseEndEvent): LogLine | null {
  switch (e.kind) {
    case "phase_start":
      // Phase labels removed — subagent activity flows seamlessly.
      return null;
    case "step_transition":
      return { tool: "step", summary: e.name, highValue: false, inFlight: false };
    case "phase_end":
      // Phase end labels removed — subagent activity flows seamlessly.
      return null;
  }
}

// Format an in-flight tool_call (no result yet). Same structure as
// formatPairedResult but with inFlight: true and no output metrics.
function formatInFlightCall(tool: string, input: Record<string, unknown>): LogLine {
  if (FILE_TOOLS.has(tool)) {
    // Placeholder for future debug body rendering.
    // In debug mode, a per-tool formatter may populate line.body.
    // See: formatDebugBody(tool, input, debugOutput)
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
    // Placeholder for future debug body rendering.
    // In debug mode, a per-tool formatter may populate line.body.
    // See: formatDebugBody(tool, input, debugOutput)
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

// -- Chronological log builder --

// Builds a chronological log by walking events in order and emitting
// one LogLine per tool invocation (at result time, or at call time if
// still in-flight) plus lifecycle events. Inserts thinking lines to
// represent gaps between visible events where the LLM is reasoning.
//
// In debug mode, koan_complete_step results are not dropped: the
// koanResponse text is attached as an expandable body to the most
// recent step line (tool === "step"), which was emitted by the
// step_transition event immediately preceding this result.
function buildChronologicalLog(events: AuditEvent[], count: number, debug: boolean = false): LogLine[] {
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


    if (e.kind === "thinking") {
      // Retroactive: this text is from the turn that just completed.
      // Overwrite (not append) -- later message_update events have more
      // complete content, so the last one wins.
      if (lastThinkingIdx >= 0) {
        lines[lastThinkingIdx].body = e.text;
      }
      continue;
    }

    if (e.kind === "tool_call") {
      // Before a visible tool_call, insert a completed thinking line if gap >= 1s
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
        // In debug mode, attach the step guidance text to the most recent step
        // line. step_transition fires immediately before this tool_result in
        // events.jsonl (guaranteed by the serialised EventLog.append chain), so
        // lines[lines.length - 1] is the step line when it exists.
        //
        // "Phase complete." edge case: when handleStepComplete returns null,
        // phase_end has already been emitted. phaseEnded blocks attachment so
        // the terminal koan_complete_step result cannot overwrite the previous
        // step's guidance body.
        if (debug && e.koanResponse?.length && !phaseEnded) {
          const last = lines[lines.length - 1];
          if (last?.tool === "step") {
            last.body = e.koanResponse.join("\n");
          }
        }
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
      const lifecycleLine = formatLifecycleEvent(e);
      if (lifecycleLine) lines.push(lifecycleLine);
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

