// Tests for audit-log-formatter.ts debug mode behavior.
//
// Verifies:
//  - debug:false  → no body on step lines (non-debug baseline unchanged)
//  - debug:true   → koanResponse attached as body to the preceding step line
//  - debug:true   → empty koanResponse does not set body
//  - debug:true   → "Phase complete." case does not attach body (last?.tool guard)
//  - non-koan output is identical regardless of debug flag

import { test } from "node:test";
import * as assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readRecentLogs } from "../src/planner/lib/audit-log-formatter.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let seqCounter = 0;

function makeEvent(partial: Record<string, unknown>): string {
  return JSON.stringify({
    ts: new Date().toISOString(),
    seq: seqCounter++,
    ...partial,
  });
}

async function writeTmpEvents(dir: string, lines: string[]): Promise<void> {
  await writeFile(join(dir, "events.jsonl"), lines.join("\n") + "\n");
}

async function withTmpDir(fn: (dir: string) => Promise<void>): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), "koan-fmt-test-"));
  try {
    await fn(dir);
  } finally {
    await rm(dir, { recursive: true });
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("readRecentLogs debug:false — no body on step line when koan_complete_step present", async () => {
  await withTmpDir(async (dir) => {
    const events = [
      makeEvent({ kind: "phase_start", phase: "intake", role: "intake", model: null, totalSteps: 3 }),
      makeEvent({ kind: "step_transition", step: 1, name: "Extract", totalSteps: 3 }),
      makeEvent({ kind: "tool_call", toolCallId: "tc1", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc1", tool: "koan_complete_step", error: false, koanResponse: ["Step 1 guidance text."] }),
    ];
    await writeTmpEvents(dir, events);

    const logs = await readRecentLogs(dir, 8, { debug: false });
    const stepLine = logs.find((l) => l.tool === "step");
    assert.ok(stepLine !== undefined, "step line should be present");
    assert.equal(stepLine.body, undefined, "no body in non-debug mode");
  });
});

test("readRecentLogs debug:true — koanResponse attached as body to step line", async () => {
  await withTmpDir(async (dir) => {
    const events = [
      makeEvent({ kind: "phase_start", phase: "intake", role: "intake", model: null, totalSteps: 3 }),
      makeEvent({ kind: "step_transition", step: 1, name: "Extract", totalSteps: 3 }),
      makeEvent({ kind: "tool_call", toolCallId: "tc1", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc1", tool: "koan_complete_step", error: false, koanResponse: ["Step 1 guidance text."] }),
    ];
    await writeTmpEvents(dir, events);

    const logs = await readRecentLogs(dir, 8, { debug: true });
    const stepLine = logs.find((l) => l.tool === "step");
    assert.ok(stepLine !== undefined, "step line should be present");
    assert.equal(stepLine.body, "Step 1 guidance text.", "body should equal koanResponse text");
  });
});

test("readRecentLogs debug:true — multi-part koanResponse joined with newline", async () => {
  await withTmpDir(async (dir) => {
    const events = [
      makeEvent({ kind: "step_transition", step: 2, name: "Scout", totalSteps: 3 }),
      makeEvent({ kind: "tool_call", toolCallId: "tc2", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc2", tool: "koan_complete_step", error: false, koanResponse: ["Line one.", "Line two."] }),
    ];
    await writeTmpEvents(dir, events);

    const logs = await readRecentLogs(dir, 8, { debug: true });
    const stepLine = logs.find((l) => l.tool === "step");
    assert.ok(stepLine !== undefined, "step line should be present");
    assert.equal(stepLine.body, "Line one.\nLine two.", "multi-part koanResponse joined with newline");
  });
});

test("readRecentLogs debug:true — empty koanResponse does not set body", async () => {
  await withTmpDir(async (dir) => {
    const events = [
      makeEvent({ kind: "step_transition", step: 1, name: "Extract", totalSteps: 3 }),
      makeEvent({ kind: "tool_call", toolCallId: "tc1", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc1", tool: "koan_complete_step", error: false, koanResponse: [] }),
    ];
    await writeTmpEvents(dir, events);

    const logs = await readRecentLogs(dir, 8, { debug: true });
    const stepLine = logs.find((l) => l.tool === "step");
    assert.ok(stepLine !== undefined, "step line should be present");
    assert.equal(stepLine.body, undefined, "empty koanResponse must not set body");
  });
});

test("readRecentLogs debug:true — phase-complete guard: 'Phase complete.' not attached to step line", async () => {
  // Models one phase-complete edge case: a bash tool is called before the
  // final koan_complete_step, so lines[lines.length - 1] is a bash result
  // (tool !== "step") when the terminal koan_complete_step result is processed.
  // Body attachment is skipped; independently, the formatter also blocks
  // terminal attachment via the `!phaseEnded` guard.
  await withTmpDir(async (dir) => {
    const events = [
      // Step 2 line (from step 1's handling — emitted immediately before step 1's tool_result)
      makeEvent({ kind: "step_transition", step: 2, name: "Write", totalSteps: 3 }),
      makeEvent({ kind: "tool_call", toolCallId: "tc1", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc1", tool: "koan_complete_step", error: false, koanResponse: ["Step 2 guidance."] }),
      // LLM does work in step 2 — bash call keeps "bash" as the last line
      makeEvent({ kind: "tool_call", toolCallId: "tc2", tool: "bash", input: { command: "echo done" } }),
      makeEvent({ kind: "tool_result", toolCallId: "tc2", tool: "bash", error: false, lines: 1, chars: 4 }),
      // Phase ends — no step_transition(3), phase_end fires instead
      makeEvent({ kind: "phase_end", outcome: "completed" }),
      // Final koan_complete_step with "Phase complete."
      makeEvent({ kind: "tool_call", toolCallId: "tc3", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc3", tool: "koan_complete_step", error: false, koanResponse: ["Phase complete."] }),
    ];
    await writeTmpEvents(dir, events);

    const logs = await readRecentLogs(dir, 20, { debug: true });

    // "Phase complete." must not be the body of any step line
    const stepLines = logs.filter((l) => l.tool === "step");
    assert.ok(!stepLines.some((l) => l.body === "Phase complete."), "'Phase complete.' must not be attached to any step line");

    // The step 2 line should have the guidance body from its own koan_complete_step result
    const writeStep = stepLines.find((l) => l.summary === "Write");
    assert.ok(writeStep !== undefined, "step 2 line should be present");
    assert.equal(writeStep.body, "Step 2 guidance.", "step 2 body should contain its own guidance");
  });
});

test("readRecentLogs debug:true — phase-complete with no intermediate tools does not overwrite step guidance", async () => {
  await withTmpDir(async (dir) => {
    const events = [
      // Step line emitted before koan_complete_step result for step 1
      makeEvent({ kind: "step_transition", step: 1, name: "Write", totalSteps: 1 }),
      makeEvent({ kind: "tool_call", toolCallId: "tc1", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc1", tool: "koan_complete_step", error: false, koanResponse: ["Actual step guidance."] }),
      // No intermediate tool calls; phase ends immediately
      makeEvent({ kind: "phase_end", outcome: "completed" }),
      makeEvent({ kind: "tool_call", toolCallId: "tc2", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc2", tool: "koan_complete_step", error: false, koanResponse: ["Phase complete."] }),
    ];
    await writeTmpEvents(dir, events);

    const logs = await readRecentLogs(dir, 20, { debug: true });
    const stepLine = logs.find((l) => l.tool === "step");
    assert.ok(stepLine !== undefined, "step line should be present");
    assert.equal(stepLine.body, "Actual step guidance.", "phase-complete result must not overwrite prior step guidance body");
  });
});

test("readRecentLogs — non-koan output identical regardless of debug flag", async () => {
  await withTmpDir(async (dir) => {
    const events = [
      makeEvent({ kind: "tool_call", toolCallId: "tc1", tool: "bash", input: { command: "ls -la" } }),
      makeEvent({ kind: "tool_result", toolCallId: "tc1", tool: "bash", error: false, lines: 3, chars: 60 }),
    ];
    await writeTmpEvents(dir, events);

    const [logsOff, logsOn] = await Promise.all([
      readRecentLogs(dir, 8, { debug: false }),
      readRecentLogs(dir, 8, { debug: true }),
    ]);
    assert.deepEqual(logsOff, logsOn, "non-koan output must be byte-identical in both modes");
  });
});

test("readRecentLogs — no opts parameter behaves like debug:false", async () => {
  await withTmpDir(async (dir) => {
    const events = [
      makeEvent({ kind: "step_transition", step: 1, name: "Extract", totalSteps: 2 }),
      makeEvent({ kind: "tool_call", toolCallId: "tc1", tool: "koan_complete_step", input: {} }),
      makeEvent({ kind: "tool_result", toolCallId: "tc1", tool: "koan_complete_step", error: false, koanResponse: ["Guidance."] }),
    ];
    await writeTmpEvents(dir, events);

    const [logsNoOpts, logsDebugFalse] = await Promise.all([
      readRecentLogs(dir, 8),
      readRecentLogs(dir, 8, { debug: false }),
    ]);
    assert.deepEqual(logsNoOpts, logsDebugFalse, "no opts must behave identically to debug:false");

    const stepLine = logsNoOpts.find((l) => l.tool === "step");
    assert.equal(stepLine?.body, undefined, "no body when opts omitted");
  });
});
