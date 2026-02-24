// Directory infrastructure for subagent working directories.
// Audit state (state.json, events.jsonl) is managed by EventLog in lib/audit.ts.
// This module is retained for createSubagentDir, used by session.ts.

import { promises as fs } from "node:fs";
import * as crypto from "node:crypto";
import * as path from "node:path";

export async function createSubagentDir(planDir: string, role: string): Promise<string> {
  const hex = crypto.randomBytes(2).toString("hex");
  const dir = path.join(planDir, "subagents", `${role}-${hex}`);
  await fs.mkdir(dir, { recursive: true });
  return dir;
}
