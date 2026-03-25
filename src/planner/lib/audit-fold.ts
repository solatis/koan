// Pure fold/correlate/summarize functions. No I/O, no Node.js or pi imports
// -- safe to unit-test directly.

import type {
  AuditEvent,
  Projection,
  ToolInvocation,
  ToolCallEvent,
  ToolResultEvent,
} from "./audit-events.js";

// -- Constants --

const FILE_TOOLS = new Set(["read", "edit", "write"]);

// -- Formatters --

export function formatChars(chars: number): string {
  if (chars < 1000) return `${chars}c`;
  const k = chars / 1000;
  if (k >= 10) return `${Math.round(k)}k`;
  return `${k.toFixed(1)}k`;
}

// -- Correlate --

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
      // Orphan result (no matching call) -- can happen if the subagent
      // started before tool_call hooking was added. Silently skip.
    }
  }

  return ordered;
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
        stepName: e.name,
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
      // `thoughts` is an escape hatch for models that can't mix text +
      // tool_call (see step.ts invariant), NOT task output. We capture a
      // 500-char prefix for UI display — this is incidental, not a contract.
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
