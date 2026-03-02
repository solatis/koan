import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";

import { exportConversation } from "../src/planner/conversation.js";

type MockEntry = { type: string; role?: string; content?: string };

function createMockSessionManager(header: MockEntry | null, branch: MockEntry[]) {
  return {
    getHeader: () => header,
    getBranch: () => branch,
  };
}

async function withTempDir<T>(fn: (dir: string) => Promise<T>): Promise<T> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "koan-conv-test-"));
  try {
    return await fn(dir);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
}

describe("exportConversation", () => {
  it("writes valid JSONL with header and branch entries", async () => {
    await withTempDir(async (dir) => {
      const header: MockEntry = { type: "header", content: "session-metadata" };
      const branch: MockEntry[] = [
        { type: "message", role: "user", content: "Plan this task" },
        { type: "message", role: "assistant", content: "I will plan it" },
      ];

      const sessionManager = createMockSessionManager(header, branch);
      const filePath = await exportConversation(
        sessionManager as any,
        dir,
      );

      assert.equal(filePath, path.join(dir, "conversation.jsonl"));

      const raw = await fs.readFile(filePath, "utf8");
      const lines = raw.trimEnd().split("\n");

      assert.equal(lines.length, 3, "should have header + 2 branch entries");

      const parsed = lines.map((line) => JSON.parse(line) as MockEntry);
      assert.deepEqual(parsed[0], header);
      assert.deepEqual(parsed[1], branch[0]);
      assert.deepEqual(parsed[2], branch[1]);
    });
  });

  it("writes valid JSONL without header when header is null", async () => {
    await withTempDir(async (dir) => {
      const branch: MockEntry[] = [
        { type: "message", role: "user", content: "Hello" },
      ];

      const sessionManager = createMockSessionManager(null, branch);
      await exportConversation(sessionManager as any, dir);

      const raw = await fs.readFile(path.join(dir, "conversation.jsonl"), "utf8");
      const lines = raw.trimEnd().split("\n");

      assert.equal(lines.length, 1, "should have only the branch entry");
      const parsed = JSON.parse(lines[0]) as MockEntry;
      assert.deepEqual(parsed, branch[0]);
    });
  });

  it("writes empty file with trailing newline when no entries", async () => {
    await withTempDir(async (dir) => {
      const sessionManager = createMockSessionManager(null, []);
      await exportConversation(sessionManager as any, dir);

      const raw = await fs.readFile(path.join(dir, "conversation.jsonl"), "utf8");
      assert.equal(raw, "\n", "empty conversation should produce a single newline");
    });
  });

  it("each line is valid JSON", async () => {
    await withTempDir(async (dir) => {
      const header: MockEntry = { type: "header" };
      const branch: MockEntry[] = [
        { type: "message", role: "user", content: 'contains "quotes" and\nnewlines' },
        { type: "message", role: "assistant", content: "response" },
      ];

      const sessionManager = createMockSessionManager(header, branch);
      await exportConversation(sessionManager as any, dir);

      const raw = await fs.readFile(path.join(dir, "conversation.jsonl"), "utf8");
      const lines = raw.trimEnd().split("\n");

      for (const line of lines) {
        assert.doesNotThrow(() => JSON.parse(line), `line should be valid JSON: ${line}`);
      }
    });
  });
});
