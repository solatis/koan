import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import { EventLog, readProjection, readRecentLogs, fold, summarize, extractToolEvent } from "../src/planner/lib/audit.js";
import type { Projection, AuditEvent, ToolEvent } from "../src/planner/lib/audit.js";

async function createTempDir(prefix: string): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

// -- EventLog + readProjection --

describe("EventLog", () => {
  it("persists events and projection through step transitions", async () => {
    const dir = await createTempDir("koan-audit-");

    const log = new EventLog(dir, "architect", "plan-design");
    await log.open();

    await log.emitPhaseStart(6);
    await log.emitStepTransition(1, "Task Analysis", 6);
    await log.emitStepTransition(2, "Decision Framework", 6);
    await log.emitPhaseEnd("completed");
    await log.close();

    const proj = await readProjection(dir);
    assert.ok(proj, "projection should be readable");
    assert.equal(proj.role, "architect");
    assert.equal(proj.phase, "plan-design");
    assert.equal(proj.status, "completed");
    assert.equal(proj.step, 2);
    assert.equal(proj.totalSteps, 6);
    assert.equal(proj.stepName, "Step 2/6: Decision Framework");
    assert.equal(proj.eventCount, 4);

    // Verify events.jsonl has correct number of lines
    const raw = await fs.readFile(path.join(dir, "events.jsonl"), "utf8");
    const lines = raw.trimEnd().split("\n").filter(Boolean);
    assert.equal(lines.length, 4);

    await fs.rm(dir, { recursive: true, force: true });
  });

  it("tracks lastAction from tool events", async () => {
    const dir = await createTempDir("koan-audit-");

    const log = new EventLog(dir, "architect", "plan-design");
    await log.open();

    await log.append({
      kind: "tool_file",
      tool: "read",
      path: "src/main.ts",
      lines: 50,
      chars: 1200,
      error: false,
    } as Omit<AuditEvent, "ts" | "seq">);

    const proj = log.state;
    assert.equal(proj.lastAction, "read src/main.ts (50L, 1200c)");

    await log.close();
    await fs.rm(dir, { recursive: true, force: true });
  });

  it("returns null for missing projection", async () => {
    const dir = await createTempDir("koan-audit-");
    const proj = await readProjection(dir);
    assert.equal(proj, null);
    await fs.rm(dir, { recursive: true, force: true });
  });
});

// -- readRecentLogs --

describe("readRecentLogs", () => {
  it("returns recent non-heartbeat events as structured LogLines", async () => {
    const dir = await createTempDir("koan-audit-");

    const log = new EventLog(dir, "architect", "plan-design");
    await log.open();

    await log.emitPhaseStart(3);
    await log.emitStepTransition(1, "Analysis", 3);
    await log.append({
      kind: "tool_file",
      tool: "read",
      path: "src/foo.ts",
      lines: 100,
      chars: 3000,
      error: false,
    } as Omit<AuditEvent, "ts" | "seq">);
    await log.close();

    const lines = await readRecentLogs(dir, 5);
    // 3 events (heartbeats filtered), all returned
    assert.equal(lines.length, 3);

    assert.equal(lines[0].tool, "phase");
    assert.ok(lines[0].summary.includes("plan-design"));

    assert.equal(lines[1].tool, "step 1/3");
    assert.equal(lines[1].summary, "Analysis");

    assert.equal(lines[2].tool, "read");
    assert.ok(lines[2].summary.includes("src/foo.ts"));
    assert.ok(lines[2].summary.includes("100L"));

    await fs.rm(dir, { recursive: true, force: true });
  });

  it("filters out koan_complete_step events", async () => {
    const dir = await createTempDir("koan-audit-");

    const log = new EventLog(dir, "architect", "plan-design");
    await log.open();

    await log.append({
      kind: "tool_koan",
      tool: "koan_complete_step",
      input: { thoughts: "done" },
      response: ["ok"],
      error: false,
    } as Omit<AuditEvent, "ts" | "seq">);

    await log.append({
      kind: "tool_koan",
      tool: "koan_set_overview",
      input: { problem: "test" },
      response: ["saved"],
      error: false,
    } as Omit<AuditEvent, "ts" | "seq">);

    await log.close();

    const lines = await readRecentLogs(dir, 5);
    assert.equal(lines.length, 1);
    assert.equal(lines[0].tool, "koan_set_overview");

    await fs.rm(dir, { recursive: true, force: true });
  });

  it("returns empty array for missing directory", async () => {
    const lines = await readRecentLogs("/nonexistent/path", 5);
    assert.deepEqual(lines, []);
  });
});

// -- fold (pure) --

describe("fold", () => {
  const initial: Projection = {
    role: "",
    phase: "",
    status: "running",
    step: 0,
    totalSteps: 0,
    stepName: "",
    lastAction: null,
    updatedAt: "",
    eventCount: 0,
    error: null,
  };

  it("phase_start resets projection", () => {
    const e: AuditEvent = {
      kind: "phase_start",
      phase: "plan-design",
      role: "architect",
      totalSteps: 6,
      ts: "2026-01-01T00:00:00Z",
      seq: 0,
    };
    const s = fold(initial, e);
    assert.equal(s.role, "architect");
    assert.equal(s.phase, "plan-design");
    assert.equal(s.totalSteps, 6);
    assert.equal(s.eventCount, 1);
  });

  it("step_transition updates step name", () => {
    const e: AuditEvent = {
      kind: "step_transition",
      step: 3,
      name: "Risk Assessment",
      totalSteps: 6,
      ts: "2026-01-01T00:00:01Z",
      seq: 1,
    };
    const s = fold(initial, e);
    assert.equal(s.step, 3);
    assert.equal(s.stepName, "Step 3/6: Risk Assessment");
  });

  it("phase_end sets status and error", () => {
    const e: AuditEvent = {
      kind: "phase_end",
      outcome: "failed",
      detail: "timeout",
      ts: "2026-01-01T00:00:02Z",
      seq: 2,
    };
    const s = fold(initial, e);
    assert.equal(s.status, "failed");
    assert.equal(s.error, "timeout");
  });
});

// -- summarize --

describe("summarize", () => {
  it("file tool with size stats", () => {
    const e: ToolEvent = {
      kind: "tool_file",
      tool: "read",
      path: "src/main.ts",
      lines: 42,
      chars: 1500,
      error: false,
      ts: "",
      seq: 0,
    };
    assert.equal(summarize(e), "read src/main.ts (42L, 1500c)");
  });

  it("bash tool with size stats", () => {
    const e: ToolEvent = {
      kind: "tool_bash",
      bin: "grep",
      lines: 10,
      chars: 200,
      error: false,
      ts: "",
      seq: 0,
    };
    assert.equal(summarize(e), "bash grep (10L, 200c)");
  });

  it("file tool without size stats", () => {
    const e: ToolEvent = {
      kind: "tool_file",
      tool: "edit",
      path: "src/foo.ts",
      error: false,
      ts: "",
      seq: 0,
    };
    assert.equal(summarize(e), "edit src/foo.ts");
  });
});

// -- extractToolEvent --

describe("extractToolEvent", () => {
  it("extracts read tool with line/char counts", () => {
    const content = "line1\nline2\nline3";
    const e = extractToolEvent({
      toolName: "read",
      input: { path: "src/test.ts" },
      content: [{ type: "text", text: content }],
      isError: false,
    });
    assert.equal(e.kind, "tool_file");
    if (e.kind === "tool_file") {
      assert.equal(e.tool, "read");
      assert.equal(e.path, "src/test.ts");
      assert.equal(e.lines, 3);
      assert.equal(e.chars, content.length);
    }
  });

  it("extracts bash tool with line/char counts", () => {
    const output = "found 5 matches\n";
    const e = extractToolEvent({
      toolName: "bash",
      input: { command: "grep -r pattern ." },
      content: [{ type: "text", text: output }],
      isError: false,
    });
    assert.equal(e.kind, "tool_bash");
    if (e.kind === "tool_bash") {
      assert.equal(e.bin, "grep");
      assert.equal(e.lines, 2);
      assert.equal(e.chars, output.length);
    }
  });

  it("extracts koan tool with input and response", () => {
    const e = extractToolEvent({
      toolName: "koan_set_overview",
      input: { problem: "test problem" },
      content: [{ type: "text", text: "saved" }],
      isError: false,
    });
    assert.equal(e.kind, "tool_koan");
    if (e.kind === "tool_koan") {
      assert.equal(e.tool, "koan_set_overview");
      assert.deepEqual(e.response, ["saved"]);
    }
  });

  it("falls back to generic for unknown tools", () => {
    const e = extractToolEvent({
      toolName: "unknown_tool",
      input: {},
      content: [],
      isError: false,
    });
    assert.equal(e.kind, "tool_generic");
    if (e.kind === "tool_generic") {
      assert.equal(e.tool, "unknown_tool");
    }
  });
});
