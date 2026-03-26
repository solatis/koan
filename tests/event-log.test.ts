// Tests for extractToolResult() in event-log.ts.
//
// Verifies the debugOutput extensibility seam:
//  - debug:false  → debugOutput never set
//  - debug:true   → bash output ≤ 4096 chars: full text, no truncation marker
//  - debug:true   → bash output > 4096 chars: truncated to 4096 + "\n…[truncated]"
//  - debug:true   → isError:true: debugOutput not set
//  - debug:true   → non-bash tool (e.g. read): debugOutput not set
//  - no opts      → debugOutput never set (same as debug:false)

import { test } from "node:test";
import * as assert from "node:assert/strict";
import { extractToolResult } from "../src/planner/lib/event-log.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface PiToolResultOverrides {
  toolCallId?: string;
  toolName?: string;
  input?: Record<string, unknown>;
  content?: Array<{ type: string; text?: string }>;
  isError?: boolean;
}

function makePiEvent(overrides: PiToolResultOverrides = {}) {
  return {
    toolCallId: "tc1",
    toolName: "bash",
    input: { command: "echo hi" },
    content: [{ type: "text", text: "hi" }],
    isError: false,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("extractToolResult debug:false — debugOutput not set for bash", () => {
  const ev = extractToolResult(makePiEvent(), { debug: false });
  assert.equal(ev.debugOutput, undefined, "debugOutput must not be set when debug=false");
});

test("extractToolResult no opts — debugOutput not set for bash", () => {
  const ev = extractToolResult(makePiEvent());
  assert.equal(ev.debugOutput, undefined, "debugOutput must not be set when opts omitted");
});

test("extractToolResult debug:true — bash output exactly 4096 chars: no truncation", () => {
  const text = "x".repeat(4096);
  const ev = extractToolResult(
    makePiEvent({ content: [{ type: "text", text }] }),
    { debug: true },
  );
  assert.equal(ev.debugOutput, text, "full text set when output is exactly at limit");
  assert.ok(!ev.debugOutput?.includes("[truncated]"), "no truncation marker at exact limit");
});

test("extractToolResult debug:true — bash output < 4096 chars: full text", () => {
  const text = "hello world";
  const ev = extractToolResult(
    makePiEvent({ content: [{ type: "text", text }] }),
    { debug: true },
  );
  assert.equal(ev.debugOutput, text, "full text set when output is under limit");
});

test("extractToolResult debug:true — bash output > 4096 chars: truncated with marker", () => {
  const text = "a".repeat(5000);
  const ev = extractToolResult(
    makePiEvent({ content: [{ type: "text", text }] }),
    { debug: true },
  );
  const expected = "a".repeat(4096) + "\n\u2026[truncated]";
  assert.equal(ev.debugOutput, expected, "output truncated at 4096 chars with ellipsis marker");
});

test("extractToolResult debug:true — isError:true: debugOutput not set", () => {
  const ev = extractToolResult(
    makePiEvent({ content: [{ type: "text", text: "error output" }], isError: true }),
    { debug: true },
  );
  assert.equal(ev.debugOutput, undefined, "debugOutput must not be set for error results");
});

test("extractToolResult debug:true — non-bash tool (read): debugOutput not set", () => {
  const ev = extractToolResult(
    makePiEvent({ toolName: "read", input: { path: "/tmp/foo.ts" }, content: [{ type: "text", text: "file content" }] }),
    { debug: true },
  );
  assert.equal(ev.debugOutput, undefined, "debugOutput must not be set for non-bash tools");
});

test("extractToolResult debug:true — non-bash koan tool: debugOutput not set", () => {
  const ev = extractToolResult(
    makePiEvent({ toolName: "koan_complete_step", content: [{ type: "text", text: "Phase complete." }] }),
    { debug: true },
  );
  assert.equal(ev.debugOutput, undefined, "debugOutput must not be set for koan tools");
});

test("extractToolResult debug:true — bash with no text content: debugOutput is empty string (no truncation)", () => {
  const ev = extractToolResult(
    makePiEvent({ content: [] }),
    { debug: true },
  );
  // text defaults to "" — under 4096, no truncation marker
  assert.equal(ev.debugOutput, "", "empty text results in empty debugOutput string");
});

test("extractToolResult — koanResponse still set for koan tools regardless of debug flag", () => {
  const content = [{ type: "text", text: "Phase complete." }];
  const ev = extractToolResult(
    makePiEvent({ toolName: "koan_complete_step", content }),
    { debug: true },
  );
  assert.deepEqual(ev.koanResponse, ["Phase complete."], "koanResponse always set for koan_ tools");
});

test("extractToolResult — lines and chars still set for bash regardless of debug flag", () => {
  const text = "line1\nline2\nline3";
  const ev = extractToolResult(
    makePiEvent({ content: [{ type: "text", text }] }),
    { debug: false },
  );
  assert.equal(ev.lines, 3, "lines metric set");
  assert.equal(ev.chars, text.length, "chars metric set");
});
